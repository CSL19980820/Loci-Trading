"""账本共享类型、校验与序列化助手。"""
from __future__ import annotations

from datetime import date, datetime
import json
from typing import Any

#: v10：持仓/成交/账户七张表下线，已有库靠 schema.py 的 DROP 迁移清掉。
#: 加删 DDL 必须同步 bump，否则已建库跳过 init_schema 的 DDL 段，迁移跑不到。
SCHEMA_VERSION = 10

#: 候选裁决唯一合法值（界面筛选与入库口径）。
CANONICAL_DECISIONS = frozenset({"精选", "落选", "观察"})
DEFAULT_RULE_VERSION = "潜龙"

#: 战法 slug → 中文入库名（潜龙 / 涨停战法系列）。
_RULE_VERSION_ALIASES: dict[str, str] = {
    "qianlong": "潜龙",
    "qianlong-v1": "潜龙",
    "qianlong-close": "潜龙",
    "qianlong-close-v2": "潜龙",
    "qianlong-close-v3": "潜龙",
    "qianlong-tail-v1": "潜龙(已下线)",
    "qianlong-auction": "潜龙",
    "潜龙": "潜龙",
    "潜龙出海": "潜龙",
    "潜龙出海·原版": "潜龙",
    "潜龙出海·竞价版": "潜龙",
    "sanyuan-tail-v1": "三源尾盘共振",
    "sanyuan-tail-1450": "三源尾盘(已下线)",
    "sanyuan": "三源尾盘共振",
    "yangshi-tail-v1": "杨氏尾盘选股",
    "yangshi-tail-1450": "杨氏尾盘(已下线)",
    "yangshi": "杨氏尾盘选股",
    "rsi30-dip": "RSI低吸(已下线)",
    "qianfu-close": "潜伏(已下线)",
    "qianfu-1450": "潜伏(已下线)",
    "lugw-sanwai": "三外有三",
    "lugw-tianyi": "天衣无缝",
    "lugw-daoba": "倒拔杨柳",
    "lugw-haidi": "海底捞月(已下线)",
    "lugw-fenshou": "分手快乐",
    "lugw-chouma": "筹码峰突破",
    "卢高文·三外有三": "三外有三",
    "卢高文·天衣无缝": "天衣无缝",
    "卢高文·倒拔杨柳": "倒拔杨柳",
    "卢高文·海底捞月": "海底捞月",
    "卢高文·分手快乐": "分手快乐",
    "卢高文·筹码峰突破": "筹码峰突破",
}

#: 候选时点常见别名 → 中文（入库与展示共用）。
_TIMING_ALIASES: dict[str, str] = {
    "open": "当日开盘",
    "close": "当日收盘",
    "next_open": "次日开盘",
    "next_dip": "次日低吸",
    "next_op": "次日开盘",
    "w": "尾盘",
    "禁w": "禁尾盘",
    "ban_w": "禁尾盘",
    "d-flat": "平开",
    "d_flat": "平开",
    "flat": "平开",
    "d-low": "低吸",
    "d_low": "低吸",
    "low": "低吸",
    "d-high": "高开回踩",
    "d_high": "高开回踩",
    "high": "高开回踩",
    "hold": "持有",
    "watch": "观望",
    "auction": "竞价",
}


def _normalize_timing(value: str | None) -> str:
    """候选时点归一为中文；已是中文则原样保留。"""
    stripped = str(value or "").strip()
    if not stripped:
        return ""
    key = stripped.lower().replace(" ", "")
    if key in _TIMING_ALIASES:
        return _TIMING_ALIASES[key]
    compact = stripped.replace(" ", "")
    mapped = _TIMING_ALIASES.get(compact.lower())
    if mapped:
        return mapped
    return stripped


#: 理由里常见英文/代码因子键 → 中文。
_REASON_FACTOR_LABELS: dict[str, str] = {
    "vol_ratio_5d": "5日量比",
    "vol_ratio": "量比",
    "turnover": "换手率",
    "ma20": "MA20",
    "ma5": "MA5",
    "ma10": "MA10",
    "score": "评分",
    "hsl": "换手%",
    "zt": "涨停",
    "one_word": "一字板",
    "auction_ratio": "竞价比",
    "open_pct": "开盘涨幅%",
    "close_pct": "收盘涨幅%",
    "COST15": "筹码15%",
    "COST50": "筹码50%",
    "COST85": "筹码85%",
    "concentration": "集中度",
}


def _normalize_reason_text(value: str | None) -> str:
    """理由尽量中文：战法 slug、因子键、时点片段一并替换。"""
    import re

    text = str(value or "").strip()
    if not text:
        return ""
    # 战法 slug 前缀（含「选中：」）
    for slug, label in sorted(_RULE_VERSION_ALIASES.items(), key=lambda x: -len(x[0])):
        text = text.replace(f"{slug} 选中：", f"{label}选中：")
        text = text.replace(f"{slug}选中：", f"{label}选中：")
        text = text.replace(slug, label)
    for eng, zh in _REASON_FACTOR_LABELS.items():
        text = text.replace(f"{eng}=", f"{zh}=")
        text = text.replace(f"{eng}:", f"{zh}：")
    for eng, zh in (
        ("禁W", "禁尾盘"),
        ("禁止W", "禁止尾盘"),
        ("错过W", "错过尾盘"),
        ("D-flat", "平开"),
        ("D-low", "低吸"),
        ("D-high", "高开回踩"),
        ("next_open", "次日开盘"),
        ("next_dip", "次日低吸"),
        ("首选W", "首选尾盘"),
        ("禁止W追", "禁止尾盘追"),
    ):
        text = text.replace(eng, zh)
    # 2.3x / 11x → 2.3倍 / 11倍（量比倍数口径）
    text = re.sub(r"(?<![A-Za-z0-9.])(\d+(?:\.\d+)?)x(?![A-Za-z])", r"\1倍", text)
    return text[:500]


class PalaceError(ValueError):
    """用户输入或账本状态不满足约束时抛出。"""


def normalize_code(value: str) -> str:
    """规范为六位 A 股代码，避免不同写法产生两份账本。"""
    digits = "".join(char for char in str(value) if char.isdigit())
    if len(digits) > 6:
        digits = digits[-6:]
    if len(digits) != 6:
        raise PalaceError("股票代码必须为 6 位数字")
    return digits


def normalize_date(value: str | None) -> str:
    """校验日期并统一输出 ISO 日期；未传时使用当天。"""
    if not value:
        return date.today().isoformat()
    try:
        return date.fromisoformat(value).isoformat()
    except ValueError as exc:
        raise PalaceError("日期必须为 YYYY-MM-DD") from exc


def _now() -> str:
    # 同一秒内的快照与成交必须可排序，否则现金滚动会漏算刚写入的成交。
    return datetime.now().astimezone().isoformat(timespec="microseconds")


def _dumps(value: Any) -> str:
    return json.dumps(value or {}, ensure_ascii=False, sort_keys=True)


def normalize_decision(value: str) -> str:
    """裁决只保留 精选 / 落选 / 观察；历史别名（含值得做、持仓等）一律映射。"""
    stripped = str(value or "").strip()
    if stripped in CANONICAL_DECISIONS:
        return stripped
    mapping = {
        # 精选
        "select": "精选",
        "selected": "精选",
        "core": "精选",
        "buy": "精选",
        "买入": "精选",
        "高确定性": "精选",
        "值得做": "精选",
        "入选": "精选",
        "重点": "精选",
        "建仓": "精选",
        "参与": "精选",
        # 落选
        "reject": "落选",
        "rejected": "落选",
        "drop": "落选",
        "exclude": "落选",
        "剔除": "落选",
        "排除": "落选",
        "放弃": "落选",
        "否决": "落选",
        "过滤": "落选",
        "空仓": "落选",
        # 观察（禁止用「持仓/持有」当裁决语义，一律归观察）
        "watch": "观察",
        "hold": "观察",
        "hold_cash": "观察",
        "partial": "观察",
        "持仓": "观察",
        "持有": "观察",
        "观望": "观察",
        "空仓观望": "观察",
        "部分参与": "观察",
    }
    key = stripped.lower()
    if key in mapping:
        return mapping[key]
    if stripped in mapping:
        return mapping[stripped]
    return stripped


def _normalize_decision(value: str) -> str:
    """Backward-compatible internal alias for ``normalize_decision``."""
    return normalize_decision(value)


def _normalize_rule_version(value: str | None) -> str:
    """战法 slug / 旧名 → 中文入库名；未知战法原样保留。"""
    stripped = str(value or "").strip() or DEFAULT_RULE_VERSION
    if stripped == DEFAULT_RULE_VERSION:
        return DEFAULT_RULE_VERSION
    key = stripped.lower()
    if key in _RULE_VERSION_ALIASES:
        return _RULE_VERSION_ALIASES[key]
    if stripped in _RULE_VERSION_ALIASES:
        return _RULE_VERSION_ALIASES[stripped]
    if key.startswith("qianlong"):
        return DEFAULT_RULE_VERSION
    if key.startswith("lugw-") and key in _RULE_VERSION_ALIASES:
        return _RULE_VERSION_ALIASES[key]
    return stripped


def _loads(value: str | None) -> dict[str, Any]:
    if not value:
        return {}
    try:
        result = json.loads(value)
    except json.JSONDecodeError:
        return {}
    return result if isinstance(result, dict) else {}


# 进程内已完成 schema 初始化的库路径，避免每个请求都写 meta 表抢锁。
_SCHEMA_READY: set[str] = set()
