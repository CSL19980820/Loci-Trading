"""悟道盘口载荷到 tape DTO 的兼容解析层。

现有 skill_watch 解析器仍是历史兼容入口；这里先复用它的字段别名、日期和
质量语义，给 market provider 一个稳定 façade。Step 3+ 再把调用方完全迁到
market 公共解析器，本轮不改 skill_watch 的调用链。
"""
from __future__ import annotations

from importlib import import_module
from typing import Any

from src.market.domain.tape import (
    AuctionSnapshot,
    BrokenLimitUp,
    LimitUpLadder,
    MarketEmotion,
    TapeValue,
    ThemeBoard,
    ThemeMembers,
    ThemeRank,
)


def _legacy() -> Any:
    """延迟取旧解析器，避免 market 与 ops 在 import 期互相成环。"""
    return import_module("src.ops.application.skill_watch.payload")


def normal_key(value: Any) -> str:
    return _legacy().normal_key(value)


def number(value: Any) -> float | None:
    return _legacy().number(value)


def clean_code(value: Any) -> str:
    return _legacy().clean_code(value)


def structured(payload: Any) -> dict[str, Any]:
    return _legacy().structured(payload)


def walk_maps(value: Any, *, depth: int = 0) -> list[dict[str, Any]]:
    return _legacy().walk_maps(value, depth=depth)


def field(row: dict[str, Any], name: str) -> float | None:
    return _legacy().field(row, name)


def metric(payload: Any, name: str) -> float | None:
    return _legacy().metric(payload, name)


def max_metric(payload: Any, name: str) -> float | None:
    return _legacy().max_metric(payload, name)


def text_field(row: dict[str, Any], *names: str) -> str:
    return _legacy().text_field(row, *names)


def rows_by_code(
    payload: Any,
    *,
    limit: int = 24,
    inherit_keys: tuple[str, ...] | None = None,
) -> dict[str, dict[str, Any]]:
    parser = _legacy()
    kwargs: dict[str, Any] = {"limit": limit}
    if inherit_keys is not None:
        kwargs["inherit_keys"] = inherit_keys
    return parser.rows_by_code(payload, **kwargs)


def row_count(payload: Any) -> int:
    return _legacy().row_count(payload)


def quality_warnings(payload: Any, label: str) -> list[str]:
    return _legacy().quality_warnings(payload, label)


def normalize_trade_date(value: Any) -> str:
    return _legacy().normalize_trade_date(value)


def extract_freshness(payload: Any, *, requested: str = "") -> dict[str, Any]:
    return _legacy().extract_freshness(payload, requested=requested)


def merge_freshness(*parts: dict[str, Any], requested: str = "") -> dict[str, Any]:
    return _legacy().merge_freshness(*parts, requested=requested)


def tool_failed(payload: Any) -> bool:
    return _legacy().tool_failed(payload)


def _trade_date(payload: Any, requested: str | None) -> str | None:
    actual = extract_freshness(payload, requested=requested or "").get("actual_trade_date")
    return str(actual or requested or "") or None


def _rows(payload: Any, *, limit: int = 200) -> tuple[dict[str, Any], ...] | None:
    rows = tuple(rows_by_code(payload, limit=limit, inherit_keys=()).values())
    return rows or None


def _raw_rows(payload: Any, *, limit: int = 200) -> tuple[dict[str, Any], ...] | None:
    found: list[dict[str, Any]] = []
    for mapping in walk_maps(structured(payload)):
        for key in ("rows", "items", "levels", "ladder"):
            values = mapping.get(key)
            if not isinstance(values, list):
                continue
            found.extend(item for item in values if isinstance(item, dict))
            if len(found) >= limit:
                return tuple(found[:limit])
    return tuple(found) or None


def parse_lane_payload(
    lane: str,
    payload: Any,
    *,
    requested_date: str | None = None,
) -> TapeValue | None:
    """把常用 lane 解析为领域 DTO；未知 lane 保留原始结构化数据。"""
    root = structured(payload)
    day = _trade_date(payload, requested_date)
    if lane == "market_emotion":
        return MarketEmotion(
            trade_date=day,
            temperature=metric(payload, "temperature"),
            breadth=metric(payload, "breadth"),
            promotion_rate=metric(payload, "promotion_rate"),
            broken_rate=metric(payload, "broken_rate"),
            limit_up_count=metric(payload, "limit_up_count"),
            limit_down_count=metric(payload, "limit_down_count"),
            payload=root,
        )
    if lane == "limit_up_pool":
        return LimitUpLadder(
            trade_date=day,
            height=metric(payload, "height"),
            rows=_rows(payload),
            payload=root,
        )
    if lane == "broken_limit_up":
        return BrokenLimitUp(trade_date=day, rows=_rows(payload), payload=root)
    if lane == "theme_board":
        ranks = tuple(
            ThemeRank(
                theme_code=text_field(row, "themeCode", "theme_code", "板块代码") or None,
                theme_name=text_field(row, "themeName", "theme_name", "板块名称", "name")
                or None,
                strength=field(row, "theme_strength"),
                pct_chg=field(row, "pct_chg"),
                main_net_amount=field(row, "main_net_amount"),
                payload=row,
            )
            for row in _raw_rows(payload, limit=200) or ()
        )
        return ThemeBoard(
            trade_date=day,
            strength=max_metric(payload, "theme_strength"),
            ranks=ranks or None,
            payload=root,
        )
    if lane == "theme_members":
        return ThemeMembers(
            trade_date=day,
            theme_code=text_field(root, "themeCode", "theme_code", "板块代码") or None,
            theme_name=text_field(root, "themeName", "theme_name", "板块名称", "name")
            or None,
            members=_rows(payload),
            payload=root,
        )
    if lane == "auction_snapshot":
        active = root.get("active")
        return AuctionSnapshot(
            trade_date=day,
            active=bool(active) if active is not None else None,
            rows=_rows(payload),
            payload=root,
        )
    return root or None


__all__ = [
    "clean_code",
    "extract_freshness",
    "field",
    "max_metric",
    "merge_freshness",
    "metric",
    "normal_key",
    "normalize_trade_date",
    "number",
    "parse_lane_payload",
    "quality_warnings",
    "row_count",
    "rows_by_code",
    "structured",
    "text_field",
    "tool_failed",
    "walk_maps",
]
