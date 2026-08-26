"""观察池生命周期：结构化盘中预警、日终复核与角色回填。"""
from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any

from src.ops.application.skill_watch.observe_format import (
    format_observe_alert_line,
    observe_alert_records,
    role_bad,
)

ALERT_SETTING_PREFIX = "observe_alerts:"
ROLE_REFRESH_MARKER = "_observe_role_refresh"

_SEVERE_ALERT_KINDS = frozenset({"role_weak", "structure_failed", "score_below_min"})
_KNOWN_ALERT_KINDS = _SEVERE_ALERT_KINDS | {"drop_pct"}
_ALERT_PRIORITY = {
    "drop_pct": 1,
    "score_below_min": 2,
    "role_weak": 3,
    "structure_failed": 4,
}


def alert_setting_key(slug: str) -> str:
    """按战法 slug 隔离盘中预警状态。"""
    return f"{ALERT_SETTING_PREFIX}{str(slug or '').strip()}"


def _normalize_alert(
    raw: Mapping[str, Any],
    *,
    default_trade_date: str = "",
) -> dict[str, Any] | None:
    code = str(raw.get("code") or "").strip()
    if not code:
        return None
    reason = str(raw.get("reason") or "").strip()
    trade_date = str(raw.get("trade_date") or default_trade_date).strip()
    kind = str(raw.get("kind") or raw.get("alert_kind") or "").strip()
    if kind not in _KNOWN_ALERT_KINDS:
        return None
    return {
        "code": code,
        "name": str(raw.get("name") or code).strip(),
        "reason": reason,
        "trade_date": trade_date,
        "kind": kind,
        "alert_kind": kind,
    }


def collect_observe_alerts(
    items: list[dict[str, Any]],
    quotes: dict[str, Any] | None,
    *,
    trade_date: str,
    min_score: float = 50.0,
    drop_pct: float = -5.0,
) -> tuple[list[dict[str, Any]], list[str]]:
    """直接消费结构化预警记录，禁止再解析中文文案行。"""
    by_key: dict[tuple[str, str], dict[str, Any]] = {}
    lines: list[str] = []
    for raw in observe_alert_records(
        items,
        quotes,
        min_score=min_score,
        drop_pct=drop_pct,
    ):
        record = _normalize_alert(
            {**raw, "trade_date": trade_date},
            default_trade_date=trade_date,
        )
        if record is None:
            continue
        by_key[(record["code"], record["kind"])] = record
        lines.append(format_observe_alert_line(record))
    return list(by_key.values()), lines


def _stored_alerts(store: Any, slug: str) -> tuple[str, list[dict[str, Any]]]:
    getter = getattr(store, "get_setting", None)
    if not callable(getter):
        return "", []
    raw = getter(alert_setting_key(slug), None)
    if not isinstance(raw, Mapping):
        return "", []
    trade_date = str(raw.get("trade_date") or "").strip()
    alerts = [
        normalized
        for item in (raw.get("alerts") or [])
        if isinstance(item, Mapping)
        for normalized in [_normalize_alert(item, default_trade_date=trade_date)]
        if normalized is not None
    ]
    return trade_date, alerts


def save_observe_alerts(
    store: Any,
    *,
    slug: str,
    trade_date: str,
    alerts: Sequence[Mapping[str, Any]],
) -> list[dict[str, Any]]:
    """合并当天预警，覆盖旧交易日状态，避免跨 slug 串扰。"""
    day = str(trade_date or "").strip()
    saved_day, previous = _stored_alerts(store, slug)
    merged: dict[tuple[str, str], dict[str, Any]] = {}
    if saved_day == day:
        for item in previous:
            merged[(item["code"], item["kind"])] = item
    for raw in alerts:
        normalized = _normalize_alert(raw, default_trade_date=day)
        if normalized is not None and normalized["trade_date"] == day:
            merged[(normalized["code"], normalized["kind"])] = normalized
    result = list(merged.values())
    store.set_setting(
        alert_setting_key(slug),
        {"trade_date": day, "alerts": result},
    )
    return result


def clear_observe_alerts(store: Any, *, slug: str) -> bool:
    """清理已被日终消费的预警；不触碰账本或观察池事实。"""
    deleter = getattr(store, "delete_setting", None)
    if not callable(deleter):
        return False
    return bool(deleter(alert_setting_key(slug)))


def load_observe_alerts(
    store: Any,
    *,
    slug: str,
    trade_date: str,
) -> list[dict[str, Any]]:
    """只读取指定交易日预警；读取到旧日状态时顺手过期。"""
    day = str(trade_date or "").strip()
    saved_day, alerts = _stored_alerts(store, slug)
    if saved_day == day:
        return alerts
    if saved_day and saved_day < day:
        clear_observe_alerts(store, slug=slug)
    return []


def backfill_observe_rows(
    result: Mapping[str, Any],
    *,
    previous_codes: set[str],
) -> list[dict[str, Any]]:
    """从当日龙头地图/排名回填旧观察票，保留当前角色与真实分数。"""
    picks = {
        str(row.get("code") or "").strip()
        for row in (result.get("picks") or [])
        if isinstance(row, Mapping) and row.get("code")
    }
    raw_entries = result.get("entries")
    if not isinstance(raw_entries, list):
        leader_map = result.get("leader_map")
        raw_entries = leader_map.get("entries") if isinstance(leader_map, Mapping) else []
    entries = {
        str(row.get("code") or "").strip(): dict(row)
        for row in raw_entries
        if isinstance(row, Mapping) and str(row.get("code") or "").strip()
    }
    ranked = {
        str(row.get("code") or "").strip(): dict(row)
        for row in (result.get("ranked") or [])
        if isinstance(row, Mapping) and str(row.get("code") or "").strip()
    }

    rows: list[dict[str, Any]] = []
    for code in sorted(previous_codes):
        if not code or code in picks:
            continue
        entry = entries.get(code)
        if entry is None:
            continue
        is_bad = role_bad(entry)
        role = str(entry.get("role") or "").strip().lower()
        if role not in {"leader", "secondary"} and not is_bad:
            continue
        current = dict(entry)
        ranked_row = ranked.get(code)
        if not is_bad:
            if ranked_row is None or ranked_row.get("score") is None:
                # 没有当天真实形态分时不回填，避免把旧分数冒充新分数。
                continue
            current = {**ranked_row, **current}
            current["score"] = ranked_row["score"]
        current["intent"] = "observe"
        current[ROLE_REFRESH_MARKER] = True
        rows.append(current)
    return rows


def apply_observe_alert_review(
    report: dict[str, Any],
    *,
    alerts: Sequence[Mapping[str, Any]],
    observe_pool: Sequence[Mapping[str, Any]],
) -> dict[str, Any]:
    """把日终复核结果写入变更报告，不改变观察池合并规则。"""
    out = dict(report)
    by_code: dict[str, dict[str, Any]] = {}
    for raw in alerts:
        normalized = _normalize_alert(raw)
        if normalized is not None:
            previous = by_code.get(normalized["code"])
            if previous is None or _ALERT_PRIORITY[normalized["kind"]] >= _ALERT_PRIORITY[
                previous["kind"]
            ]:
                by_code[normalized["code"]] = normalized

    for dropped in out.get("dropped") or []:
        if not isinstance(dropped, dict):
            continue
        alert = by_code.get(str(dropped.get("code") or "").strip())
        if alert is None or alert["kind"] not in _SEVERE_ALERT_KINDS:
            continue
        dropped["reason"] = f"日终预警复核：{alert['reason'] or alert['kind']}"

    pool_codes = {
        str(row.get("code") or "").strip()
        for row in observe_pool
        if isinstance(row, Mapping) and row.get("code")
    }
    follow_up = [
        dict(alert)
        for alert in by_code.values()
        if alert["kind"] == "drop_pct" and alert["code"] in pool_codes
    ]
    if follow_up:
        out["alert_follow_up"] = follow_up
    return out


def format_observe_alert_follow_up(rows: Sequence[Mapping[str, Any]] | None) -> str:
    """日终正文里的轻度跌幅预警提示。"""
    items = [
        f"{row.get('name') or row.get('code')} {row.get('code')}（{row.get('reason') or '跌幅预警'}）"
        for row in (rows or [])
        if isinstance(row, Mapping) and row.get("code")
    ]
    if not items:
        return ""
    return "⚠️预警复核后续盯：" + "；".join(items)


__all__ = [
    "ALERT_SETTING_PREFIX",
    "ROLE_REFRESH_MARKER",
    "alert_setting_key",
    "apply_observe_alert_review",
    "backfill_observe_rows",
    "clear_observe_alerts",
    "collect_observe_alerts",
    "format_observe_alert_follow_up",
    "load_observe_alerts",
    "save_observe_alerts",
]
