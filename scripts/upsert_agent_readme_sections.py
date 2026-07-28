"""Ensure each context README has Agent 用法 + README 维护 sections."""
from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent / "src"

AGENT_BLURBS: dict[str, str] = {
    "ledger": """## 给 Agent 的用法
- 读写账本：`from src.ledger import PalaceStore, PalaceError`
- 路径：`from src.shared.paths import palace_db`
- 典型任务：记成交、候选、预案；不要在此算资金曲线（去 review）
- 禁忌：不要让 market/ai 写入 palace.db

## README 维护
改表结构、写入语义、公开导出符号时必须更新本文。""",
    "market": """## 给 Agent 的用法
- 仓：`from src.market import MarketStore, sync_quotes`
- 新源：在 `infrastructure/adapters` 实现并注册 lane
- HTTP 前缀见 `api/README.md`（现多由 `app.legacy.quant_router` 挂载）
- 禁忌：写 palace.db；在 adapter 外写死厂商 if-else

## README 维护
改同步语义、适配器契约、公开导出时必须更新本文。""",
    "review": """## 给 Agent 的用法
- 曲线/归因：`from src.review import build_equity_curve, round_trips, evaluate_candidates`
- 输入只能是真实账本 + 真实行情
- 禁忌：用 LLM 结果冒充复盘数字

## README 维护
改指标口径、缓存表、公开函数签名时必须更新本文。""",
    "strategy": """## 给 Agent 的用法
- 注册战法：实现 `StrategyEngine`，放 `application/`，在包 init 侧效 import
- 选股：`from src.strategy import screen, get`
- 必须声明 `entry_timing`；补前视审计测试
- 自定义策略目录：`infrastructure/custom/`

## README 维护
新增/下线战法、改 Protocol 或选股入口时必须更新本文。""",
    "backtest": """## 给 Agent 的用法
- `from src.backtest import backtest_strategy, run_backtest`
- 入场时点以策略声明为准，禁止调用方随意覆盖成前视口径

## README 维护
改成交假设、退出规则、公开 API 时必须更新本文。""",
    "ops": """## 给 Agent 的用法
- 任务：`from src.ops import run_job, OpsStore`
- 技能：`discover_skills` / `install_skill`；根目录每次运行时解析
- 新 Job kind：注册到 `application/jobs.EXECUTORS`

## README 维护
改 Job 种类、技能约定、ops.db 语义时必须更新本文。""",
    "ai": """## 给 Agent 的用法
- 对话：`from src.ai import chat, resolve_config`
- Agent/工具：`application/agent.py`、`application/toolbus.py`
- 禁忌：生成权威行情/盈亏数字

## README 维护
改协议、工具清单、密钥处理时必须更新本文。""",
    "intel": """## 给 Agent 的用法
- MCP：`from src.intel import McpClient`
- 配置：`data/mcp.json`；内置行情工具见 `builtin_market_mcp`
- 大批量量价仍走 market，不走 MCP 扫全市场

## README 维护
改 MCP 契约、限流、内置工具时必须更新本文。""",
    "formula": """## 给 Agent 的用法
- `from src.formula import MA, REF, COST, ...`
- 潜龙指标：`from src.formula.domain.qianlong import ...`
- 面板 DataFrame 与单票 Series 同构实现

## README 维护
新增公式函数或改通达信语义对齐时必须更新本文。""",
    "shared": """## 给 Agent 的用法
- 路径唯一入口：`from src.shared.paths import data_dir, palace_db, market_db, ops_db`
- 禁止在业务里硬编码 `data/palace.db`

## README 维护
改路径解析优先级或布局约定时必须更新本文。""",
    "app": """## 给 Agent 的用法
- 应用工厂：`from src.app.main import create_app, app`
- 量化聚合路由：`src.app.legacy.quant_router.build_quant_router`
- 新路由优先下沉到各上下文 `api/`，再在此挂载

## README 维护
改鉴权、挂载方式、静态资源策略时必须更新本文。""",
}


def upsert(text: str, section: str) -> str:
    markers = ("## 给 Agent 的用法", "## README 维护")
    if all(m in text for m in markers):
        # replace from first marker to end of 相关测试 or EOF — simpler: if present skip
        return text
    # insert before ## 相关测试 if present
    needle = "## 相关测试"
    block = "\n" + section.strip() + "\n\n"
    if needle in text:
        return text.replace(needle, block + needle, 1)
    return text.rstrip() + "\n\n" + section.strip() + "\n"


def main() -> None:
    for name, blurb in AGENT_BLURBS.items():
        path = ROOT / name / "README.md"
        if not path.is_file():
            print("skip missing", path)
            continue
        original = path.read_text(encoding="utf-8")
        updated = upsert(original, blurb)
        if updated != original:
            path.write_text(updated, encoding="utf-8")
            print("updated", path.relative_to(ROOT.parent))
        else:
            print("ok", path.relative_to(ROOT.parent))


if __name__ == "__main__":
    main()
