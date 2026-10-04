"""监测候选池：按交易日隔离各扫描器的候选，不创建或读取模拟账户。"""
from __future__ import annotations

from copy import deepcopy
from datetime import datetime
import threading
from typing import Any
from zoneinfo import ZoneInfo

_TZ = ZoneInfo("Asia/Shanghai")
_POOL_KEY_PREFIX = "unified_monitor_pool:"
_CANDIDATE_FEED_FIELD = "candidate_feed"
_MAX_OBSERVE = 5
_lock = threading.RLock()


def _pool_key(slug: str) -> str:
    key = str(slug or "").strip()
    if not key:
        raise ValueError("监测策略标识不能为空")
    return _POOL_KEY_PREFIX + key


def _candidate_action(row: dict[str, Any]) -> str:
    raw = str(row.get("action") or row.get("intent") or "observe").strip().lower()
    if raw in {"open", "buy"}:
        return "buy"
    if raw in {"add", "buy_dip", "rebalance"}:
        return "rebalance"
    if raw in {"close", "sell", "reduce", "take_profit", "stop_cut", "trim_high"}:
        return "sell"
    return "observe"


def get_unified_monitor_pool(store: Any, *, slug: str, trade_date: str) -> dict[str, Any]:
    """纯读同一交易日的候选；跨日不把旧候选盖上今日时间。"""
    raw = store.get_setting(_pool_key(slug), None)
    if isinstance(raw, dict) and str(raw.get("trade_date") or "") == trade_date:
        result = deepcopy(raw)
        result["items"] = [row for row in result.get("items", [])
                           if isinstance(row, dict) and row.get("bucket") != "position"]
        result["counts"] = {"positions": 0, "observe": len(result["items"]), "total": len(result["items"])}
        return result
    return {"slug": slug, "trade_date": trade_date, "updated_at": "", "source": "no_current_snapshot",
            "items": [], "counts": {"positions": 0, "observe": 0, "total": 0},
            "limits": {"max_observe": _MAX_OBSERVE}, "over_capacity": False}


def replace_candidate_feed(store: Any, *, slug: str, trade_date: str, feed: str,
                           candidates: list[dict[str, Any]] | None) -> dict[str, Any]:
    """替换单个扫描来源，其余来源保留；返回原有观察池变化契约。"""
    key, day, feed_key = str(slug).strip(), str(trade_date).strip(), str(feed).strip()
    if not day or not feed_key:
        raise ValueError("交易日与候选来源不能为空")
    with _lock:
        previous = get_unified_monitor_pool(store, slug=key, trade_date=day)
        old_items = previous["items"]
        primary_feed = f"skill_watch:{key}"
        combined = [dict(row) for row in old_items
                    if str(row.get(_CANDIDATE_FEED_FIELD) or primary_feed) != feed_key]
        combined.extend({**dict(row), _CANDIDATE_FEED_FIELD: feed_key} for row in candidates or []
                        if isinstance(row, dict) and str(row.get("code") or "").strip())
        rank = {"ready": 0, "setup": 1, "near": 2}
        combined.sort(key=lambda row: rank.get(str(row.get("state") or ""),
                                             0 if _candidate_action(row) in {"buy", "rebalance"} else 3))
        picked: dict[str, dict[str, Any]] = {}
        for row in combined:
            code = str(row.get("code") or "").strip()
            if not code or code in picked:
                continue
            action = _candidate_action(row)
            picked[code] = {**row, "code": code, "name": str(row.get("name") or code),
                            "bucket": "observe", "action": action, "intent": action}
            if len(picked) >= _MAX_OBSERVE:
                break
        old = {str(row.get("code")): row for row in old_items if _candidate_action(row) == "observe"}
        new = {code: row for code, row in picked.items() if _candidate_action(row) == "observe"}
        items = list(picked.values())
        result = {"slug": key, "trade_date": day, "updated_at": datetime.now(_TZ).isoformat(timespec="seconds"),
                  "source": f"candidate_feed:{feed_key}", "items": items,
                  "limits": {"max_observe": _MAX_OBSERVE}, "over_capacity": False,
                  "counts": {"positions": 0, "observe": len(items), "total": len(items)},
                  "changes": {"kept": [new[c] for c in new if c in old],
                              "added": [new[c] for c in new if c not in old],
                              "dropped": [old[c] for c in old if c not in new], "changed": old.keys() != new.keys()}}
        store.set_setting(_pool_key(key), result)
        return deepcopy(result)


def drop_candidate_feed(store: Any, *, slug: str, feed: str) -> int:
    """只移除指定扫描来源，不改其他候选的交易日期和证据。"""
    with _lock:
        raw = store.get_setting(_pool_key(slug), None)
        if not isinstance(raw, dict):
            return 0
        items = [row for row in raw.get("items", []) if isinstance(row, dict)]
        kept = [row for row in items if str(row.get(_CANDIDATE_FEED_FIELD) or "") != feed]
        if len(kept) != len(items):
            store.set_setting(_pool_key(slug), {**raw, "items": kept,
                              "counts": {"positions": 0, "observe": len(kept), "total": len(kept)}})
        return len(items) - len(kept)
