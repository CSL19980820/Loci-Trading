"""纸面成交 decided_by 分组观测（纯函数，不改决策语义）。"""
from __future__ import annotations

from collections import Counter
from typing import Any, Mapping


def normalize_decided_by(value: Any) -> str:
    """空/缺字段计为 unknown。"""
    key = str(value or "").strip()
    return key if key else "unknown"


def count_fills_by_decided_by(fills: list[Mapping[str, Any]] | None) -> dict[str, int]:
    """按 decided_by 聚合成交笔数；只读 fills，不改决策。"""
    return dict(
        Counter(normalize_decided_by(f.get("decided_by")) for f in (fills or []))
    )
