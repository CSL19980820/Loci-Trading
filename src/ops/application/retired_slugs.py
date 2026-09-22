"""已退役的策略标识。

退役不是把一个任务开关改成 false：只要技能包还在，启动自愈就可能重新发现它。
这里放一个无依赖的单一判据，供目录、安装、任务和自主交易员研究入口共同使用。
"""
from __future__ import annotations

from typing import Any


RETIRED_STRATEGY_SLUGS = frozenset({"yixian-auction"})
# 历史报告可能保存展示名称而不是 slug；生成新报告时两种标识都视为退役引用。
RETIRED_STRATEGY_MARKERS = frozenset({"yixian-auction", "一线定乾坤"})


def canonical_strategy_slug(value: Any) -> str:
    key = str(value or "").strip().lower()
    for prefix in ("screen:", "skill:"):
        if key.startswith(prefix):
            return key[len(prefix) :].strip()
    return key


def is_retired_strategy_slug(value: Any) -> bool:
    return canonical_strategy_slug(value) in RETIRED_STRATEGY_SLUGS


__all__ = [
    "RETIRED_STRATEGY_MARKERS",
    "RETIRED_STRATEGY_SLUGS",
    "canonical_strategy_slug",
    "is_retired_strategy_slug",
]
