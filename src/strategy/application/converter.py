"""AI 策略转换器：通达信公式 / 文字描述 → 可注册的 Python 策略文件。

## 工作流

1. 把输入（TDX 公式或文字描述）+ 上下文（formula 函数签名、现有策略示例）
   拼成一条 prompt，发给配置的 LLM。
2. LLM 返回纯 Python 代码（一个继承了 StrategyEngine 协议的类 + register 调用）。
3. 用 ast.parse 做语法检查，提取 slug/name/min_bars 等元数据做完整性检查。
4. 保存到 src/strategies/custom/{slug}.py，用 importlib 热加载，自动注册进全局注册表。
5. 任何步骤失败都带具体原因返回，不静默降级。

## 安全约束

- 生成的文件只写入 CUSTOM_DIR（src/strategies/custom/），拒绝路径穿越。
- ast.parse 确保代码可以被 Python 解析（但不做语义安全审计——这是内部工具，
  不对公网开放代码生成）。
- 加载失败（如 import 错误）会回滚文件并告知原因。
"""
from __future__ import annotations

import ast
import importlib.util
import logging
import re
import sys
import traceback
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

from src.shared.paths import ops_db as _default_ops_db

# 自定义策略的落地目录。固定在这里，不接受外部传入路径。
CUSTOM_DIR = Path(__file__).resolve().parent.parent / "infrastructure" / "custom"
# OpsStore 路径，用于保存版本历史。
#: 兼容保留。**不要用**：import 期求值，多租户下会把版本历史写进别人的库。
DEFAULT_OPS_DB = _default_ops_db()

# prompt 里注入的函数速查表，帮 LLM 选正确的 formula 函数
_FORMULA_CHEATSHEET = """
## src.formula 可用函数（全部对 Series/DataFrame 都有效）

位移/均线: REF(x,n), MA(x,n), EMA(x,n), SMA(x,n,m), WMA(x,n), DMA(x,alpha)
累计/统计: SUM(x,n), HHV(x,n), LLV(x,n), STD(x,n), AVEDEV(x,n)
时间计数: BARSLAST(cond), BARSSINCE(cond), BARSCOUNT(x), HHVBARS(x,n), LLVBARS(x,n)
条件统计: COUNT(cond,n), EVERY(cond,n), EXIST(cond,n), FILTER(cond,n)
逻辑/数学: IF(cond,a,b), ABS(x), MAX(a,b), MIN(a,b), CROSS(fast,slow)
A股专用: ZTPRICE(prev_close, ratio=0.1)  # 涨停价
芯片: COST(panels, pct), WINNER(panels, price)  # 需要 chips.py 额外字段
特殊: weighted_ref_sum(x, weights_dict, divisor)  # 辰星线等加权均线

panels 字典键名: 'open','high','low','close','volume','turnover','amount'
换手率: panels['turnover'] 是小数(0.05=5%)，通达信 HSL 是百分数 → 要×100
"""

# 参考策略示例（从真实代码截取关键片段）
_STRATEGY_TEMPLATE = '''
## Python 策略文件结构（严格遵守，不要改接口）

```python
"""一句话说明策略。"""
from __future__ import annotations
from typing import Any
import pandas as pd
from src.formula import MA, REF, COUNT  # 按需 import
from src.strategy.domain.base import SignalResult, merge_params, register


class MyStrategyPicker:
    slug = "my-strategy"           # 全小写+连字符，唯一
    name = "我的策略"
    description = "策略描述"
    entry_timing = "next_open"     # "open"、"next_open" 或 "next_dip"

    def default_params(self) -> dict[str, Any]:
        return {"ma_period": 5}    # 可调参数及默认值

    def required_fields(self) -> tuple[str, ...]:
        return ("close", "volume") # 只声明用到的字段

    def min_bars(self) -> int:
        return 30                  # 指标窗口所需最少K线数

    def compute(self, panels: dict[str, pd.DataFrame],
                params: dict[str, Any] | None = None) -> SignalResult:
        p = merge_params(self, params)
        close = panels["close"]
        # ... 计算信号 ...
        signals = close > MA(close, p["ma_period"])
        return SignalResult(
            signals=signals.fillna(False),
            factors={"均线": MA(close, p["ma_period"])},
        )

register(MyStrategyPicker())
```

重要：
- signals 必须是 bool 型 DataFrame，True=选中，fillna(False)
- factors 里放中间指标，供复盘归因用，不能省略
- 文件最后必须 register(实例)
- 只写 Python 代码，不要 markdown 代码块，不要解释
'''


def build_convert_prompt(source: str, source_type: str, slug: str, name: str,
                          entry_timing: str) -> str:
    type_hint = "通达信选股公式（.txt 格式）" if source_type == "tdx" else "策略文字描述"
    return f"""你是 A 股量化策略翻译专家。把下面的{type_hint}翻译成符合项目规范的 Python 策略文件。

## 目标策略信息
- slug: {slug}
- name: {name}
- entry_timing: {entry_timing}（open=当日开盘，next_open=次日开盘，next_dip=次日低吸）

{_FORMULA_CHEATSHEET}

{_STRATEGY_TEMPLATE}

## 输入（需要翻译的{type_hint}）

{source}

## 输出要求

1. 只输出 Python 代码，不要任何 markdown 标记、不要解释文字
2. 代码第一行必须是 docstring，说明策略逻辑
3. slug 必须是 {slug}，name 必须是 {name}
4. entry_timing 必须是 {entry_timing}
5. 把通达信的条件逐一翻译成向量化表达式，不能省略任何条件
6. 如果公式里有 HSL（换手率），记住要乘以 100（行情仓是小数口径）
7. min_bars 设为指标窗口最大值 + 10 的保守值
8. factors 里放关键中间变量（至少 3 个），名字用中文，方便归因

直接输出 Python 代码："""


def build_skill_prompt(description: str, slug: str, name: str,
                        context_hints: list[str]) -> str:
    context_str = "、".join(context_hints) if context_hints else "无特定数据需求"
    return f"""你是潜龙记忆宫殿系统的技能包作者。根据描述生成一个 SKILL.md 文件。

## 技能元信息
- slug: {slug}
- name: {name}
- 数据上下文需求: {context_str}

## SKILL.md 格式

```markdown
---
slug: {slug}
name: {name}
version: "1.0"
description: 一句话描述
instructions: |
  （这里写给 AI 执行的完整指令，包括分析目标、输出格式、风险提示要求等）
allowed_tools: []
---

（正文可以补充背景说明，供人类阅读）
```

## 用途描述

{description}

## 输出要求

1. 只输出 SKILL.md 的文本内容，不要额外解释
2. instructions 字段里的指令要具体，告诉 AI 该用什么数据、输出什么格式
3. 必须在 instructions 末尾加上：「结论末尾必须附上：本分析仅供参考，不构成投资建议。」
4. 如果需要 screen/positions/market_coverage 数据，在 instructions 里写明要用这些数据
5. 不要生成 cron、schedule、default_cron 或任何运行时间配置；调度由系统负责

直接输出 SKILL.md 内容："""


def _extract_code(raw: str) -> str:
    """从 LLM 响应里提取纯 Python 代码，去掉 markdown 代码块标记。"""
    raw = raw.strip()
    # 去掉 ```python ... ``` 或 ``` ... ```
    match = re.search(r"```(?:python)?\n(.*?)```", raw, re.DOTALL)
    if match:
        return match.group(1).strip()
    return raw


def _syntax_check(code: str) -> str | None:
    """返回语法错误描述，无错误返回 None。"""
    try:
        ast.parse(code)
        return None
    except SyntaxError as exc:
        return f"SyntaxError at line {exc.lineno}: {exc.msg}"


def _validate_strategy_code(code: str, expected_slug: str) -> list[str]:
    """做完整性检查，返回问题列表（空=通过）。"""
    issues = []
    tree = ast.parse(code)

    # 找到 register() 调用
    has_register = any(
        isinstance(node, ast.Expr)
        and isinstance(node.value, ast.Call)
        and isinstance(node.value.func, ast.Name)
        and node.value.func.id == "register"
        for node in ast.walk(tree)
    )
    if not has_register:
        issues.append("缺少 register(...) 调用，策略不会被自动注册")

    # 检查 slug 是否在代码里出现
    if f'"{expected_slug}"' not in code and f"'{expected_slug}'" not in code:
        issues.append(f"代码里找不到 slug='{expected_slug}'，LLM 可能改了 slug")

    # 检查 SignalResult 是否被返回
    if "SignalResult" not in code:
        issues.append("compute() 没有返回 SignalResult")

    # 检查 fillna(False) 防止 None 值混进信号
    if "fillna(False)" not in code:
        issues.append("signals 没有 fillna(False)，可能有 NaN 混入选股结果")

    return issues


def save_and_load(
    code: str, slug: str, *, ops_db: str | Path | None = None
) -> dict[str, Any]:
    """把代码写入文件并热加载，返回结果。

    加载失败会删掉文件（避免留下损坏状态），并返回详细错误。
    """
    CUSTOM_DIR.mkdir(parents=True, exist_ok=True)

    # 写入 __init__.py（确保包可被识别）
    init_file = CUSTOM_DIR / "__init__.py"
    if not init_file.exists():
        init_file.write_text("# 自定义策略包\n", encoding="utf-8")

    target = CUSTOM_DIR / f"{slug}.py"

    # 防路径穿越：slug 已经在路由层用 regex 校验了，这里再 double-check
    resolved = target.resolve()
    if not resolved.is_relative_to(CUSTOM_DIR.resolve()):
        raise ValueError(f"路径穿越：{slug}")

    previous_code = target.read_text(encoding="utf-8") if target.exists() else None
    _replace_and_load_custom_strategy(target, slug, code)

    logger.info("自定义策略 %s 加载注册成功", slug)
    rel_path = str(target.relative_to(Path(__file__).parents[2]))

    # 版本历史（失败不影响主流程）
    try:
        from src.ops import OpsStore
        with OpsStore(ops_db or _default_ops_db()) as ops:
            version = ops.save_strategy_version(slug, code, file_path=rel_path)
        logger.info("策略版本 v%s 已保存", version)
    except Exception as exc:
        logger.exception("策略已加载，但版本历史保存失败（slug=%s）", slug)
        if previous_code is None:
            target.unlink(missing_ok=True)
        else:
            _replace_and_load_custom_strategy(target, slug, previous_code)
        raise RuntimeError(f"策略版本历史保存失败：{exc}") from exc

    from src.strategy.domain.base import _REGISTRY
    engine = _REGISTRY[slug]
    engine.source_kind = "custom"
    engine.version = str(version)
    engine.strategy_revision = f"custom:{slug}:v{version}"
    return {
        "slug": slug,
        "file": rel_path,
        "registered": True,
        "version": str(version),
    }


def restore_custom_strategy_version(
    slug: str, version: int, *, ops_db: str | Path | None = None
) -> dict[str, Any]:
    """恢复指定代码版本；运行时加载成功后才原子切换 active 标记。"""
    from src.ops import OpsError, OpsStore

    with OpsStore(ops_db or _default_ops_db()) as ops:
        target_version = ops.get_strategy_version(slug, version)
    if target_version is None:
        raise OpsError(f"策略 {slug} 不存在版本 {version}")
    code = str(target_version.get("code") or "")
    if not code:
        raise OpsError(f"策略 {slug} 版本 {version} 不包含可恢复代码")
    target = CUSTOM_DIR / f"{slug}.py"
    previous_code = target.read_text(encoding="utf-8") if target.exists() else None
    _replace_and_load_custom_strategy(target, slug, code)
    try:
        with OpsStore(ops_db or _default_ops_db()) as ops:
            restored = ops.rollback_strategy_version(slug, version)
    except Exception:
        logger.exception("策略 %s 运行时已恢复，但 active 标记切换失败", slug)
        if previous_code is None:
            target.unlink(missing_ok=True)
        else:
            _replace_and_load_custom_strategy(target, slug, previous_code)
        raise
    from src.strategy.domain.base import _REGISTRY
    engine = _REGISTRY[slug]
    engine.source_kind = "custom"
    engine.version = str(restored["version"])
    engine.strategy_revision = f"custom:{slug}:v{restored['version']}"
    return {
        "slug": slug,
        "version": str(restored["version"]),
        "file": str(target.relative_to(Path(__file__).parents[2])),
        "registered": True,
    }


def _replace_and_load_custom_strategy(target: Path, slug: str, code: str) -> None:
    """先保留旧运行时引用；新代码不能注册时恢复原注册表与文件。"""
    from src.strategy.domain.base import _REGISTRY

    old_code = target.read_text(encoding="utf-8") if target.exists() else None
    old_engine = _REGISTRY.pop(slug, None)
    module_name = f"src.strategy.infrastructure.custom.{slug.replace('-', '_')}"
    sys.modules.pop(module_name, None)
    target.write_text(code, encoding="utf-8")
    try:
        spec = importlib.util.spec_from_file_location(module_name, target)
        if spec is None or spec.loader is None:
            raise ImportError("无法创建 module spec")
        module = importlib.util.module_from_spec(spec)
        sys.modules[module_name] = module
        spec.loader.exec_module(module)  # type: ignore[union-attr]
        if slug not in _REGISTRY:
            raise RuntimeError(f"文件加载成功但策略 '{slug}' 未在注册表中")
    except Exception as exc:
        sys.modules.pop(module_name, None)
        if old_code is None:
            target.unlink(missing_ok=True)
        else:
            target.write_text(old_code, encoding="utf-8")
        if old_engine is not None:
            _REGISTRY[slug] = old_engine
        detail = traceback.format_exc(limit=5)
        raise RuntimeError(f"策略加载失败：{exc}\n{detail}") from exc


def list_custom_strategies() -> list[dict[str, Any]]:
    """列出已保存的自定义策略文件（不依赖注册表，文件即真相）。"""
    if not CUSTOM_DIR.exists():
        return []
    result = []
    for path in sorted(CUSTOM_DIR.glob("*.py")):
        if path.name == "__init__.py":
            continue
        slug = path.stem
        # 读前几行提取 slug/name
        try:
            first_lines = path.read_text(encoding="utf-8")[:2000]
            name_match = re.search(r'name\s*=\s*["\'](.+?)["\']', first_lines)
            name = name_match.group(1) if name_match else slug
        except Exception:
            name = slug
        result.append({
            "slug": slug,
            "name": name,
            "file": str(path.relative_to(Path(__file__).parents[2])),
        })
    return result


def delete_custom_strategy(slug: str) -> bool:
    """删除自定义策略文件，并从注册表移除（如果在）。"""
    target = CUSTOM_DIR / f"{slug}.py"
    if not target.exists():
        return False
    target.unlink()
    module_name = f"src.strategy.infrastructure.custom.{slug.replace('-', '_')}"
    sys.modules.pop(module_name, None)
    # 从全局注册表移除
    from src.strategy.domain.base import _REGISTRY
    _REGISTRY.pop(slug, None)
    return True
