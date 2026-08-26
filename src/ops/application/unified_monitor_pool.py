"""统一监察池：持仓、候选与当前动作的唯一投影。"""
from __future__ import annotations

from datetime import datetime
from typing import Any
from zoneinfo import ZoneInfo

DRAGON_SLUG = "dragon-return"
DRAGON_INITIAL_CAPITAL = 200_000.0
DRAGON_MAX_LAYERS = 10.0
DRAGON_MAX_POSITIONS = 3
DRAGON_MAX_OBSERVE = 5


def is_retired_paper_cabin(slug: str) -> bool:
    """龙回头 / 龙池纸面舱已退役，禁止 GET 或启动路径隐式建舱。"""
    from src.ops.application.retire_dragon_return import (
        is_retired_paper_cabin as _retired,
    )

    return _retired(slug)

_TZ = ZoneInfo("Asia/Shanghai")
_POOL_KEY_PREFIX = "unified_monitor_pool:"
_LEGACY_POOL_KEY_PREFIX = "paper_live_pool:"
_CANDIDATE_FEED_FIELD = "candidate_feed"
_BUY_ACTIONS = frozenset({"open", "buy"})
_REBALANCE_ACTIONS = frozenset({"add", "buy_dip"})
_SELL_ACTIONS = frozenset({"close", "sell", "reduce", "take_profit", "stop_cut", "trim_high"})


def _pool_key(slug: str) -> str:
    return f"{_POOL_KEY_PREFIX}{str(slug or '').strip()}"


def _limits(slug: str, cabin: dict[str, Any]) -> dict[str, int | float]:
    cfg = cabin.get("config") if isinstance(cabin.get("config"), dict) else {}
    paper_cfg = cfg.get("paper_quant") if isinstance(cfg.get("paper_quant"), dict) else cfg
    if slug == DRAGON_SLUG:
        return {
            "initial_capital": DRAGON_INITIAL_CAPITAL,
            "max_layers": DRAGON_MAX_LAYERS,
            "max_positions": DRAGON_MAX_POSITIONS,
            "max_observe": DRAGON_MAX_OBSERVE,
            "max_total": DRAGON_MAX_POSITIONS + DRAGON_MAX_OBSERVE,
        }
    max_positions = max(1, int(paper_cfg.get("max_positions") or DRAGON_MAX_POSITIONS))
    max_observe = max(0, int(paper_cfg.get("max_observe") or DRAGON_MAX_OBSERVE))
    return {
        "initial_capital": float(paper_cfg.get("initial_capital") or DRAGON_INITIAL_CAPITAL),
        "max_layers": float(cabin.get("max_layers") or 4.0),
        "max_positions": max_positions,
        "max_observe": max_observe,
        "max_total": max_positions + max_observe,
    }


def ensure_dragon_cabin_policy(store: Any, slug: str) -> dict[str, Any]:
    """把龙王舱收敛到 20 万、100%（10 层）、3+5 容量。

    已退役的 slug **只读已有舱、绝不 INSERT**。测试仍可 ``store.ensure_paper_cabin``
    显式建舱；生产路径（盘面 GET / 启动 reconcile）不能把删掉的舱召回。
    """
    if is_retired_paper_cabin(slug):
        cabin = store.get_paper_cabin(slug)
        if not cabin:
            return {}
    else:
        cabin = store.ensure_paper_cabin(
            slug,
            max_layers=DRAGON_MAX_LAYERS if slug == DRAGON_SLUG else 4.0,
        )
    if slug != DRAGON_SLUG:
        return cabin

    if float(cabin.get("max_layers") or 0) != DRAGON_MAX_LAYERS:
        cabin = store.update_paper_cabin_limits(slug, max_layers=DRAGON_MAX_LAYERS)

    root_cfg = dict(cabin.get("config") or {})
    nested = isinstance(root_cfg.get("paper_quant"), dict)
    paper_cfg = dict(root_cfg.get("paper_quant") or {}) if nested else dict(root_cfg)
    required = {
        "initial_capital": DRAGON_INITIAL_CAPITAL,
        "max_positions": DRAGON_MAX_POSITIONS,
        "max_observe": DRAGON_MAX_OBSERVE,
        "max_total": DRAGON_MAX_POSITIONS + DRAGON_MAX_OBSERVE,
        "max_position_pct": 100.0,
    }
    if any(paper_cfg.get(key) != value for key, value in required.items()):
        paper_cfg.update(required)
        cabin = store.update_paper_cabin_config(
            slug,
            {"paper_quant": paper_cfg} if nested else paper_cfg,
        )
    return cabin


def _code(row: dict[str, Any]) -> str:
    return str(row.get("code") or "").strip()


def _candidate_action(row: dict[str, Any]) -> str:
    raw = str(row.get("action") or row.get("intent") or "observe").strip().lower()
    if raw in _BUY_ACTIONS:
        return "buy"
    if raw in _REBALANCE_ACTIONS:
        return "rebalance"
    if raw in _SELL_ACTIONS:
        return "sell"
    if raw in {"holding", "hold"}:
        return "holding"
    return "observe"


def _action_rows(actions: list[Any] | None) -> dict[str, dict[str, Any]]:
    out: dict[str, dict[str, Any]] = {}
    for raw in actions or []:
        if isinstance(raw, dict):
            row = dict(raw)
        elif hasattr(raw, "as_dict"):
            row = dict(raw.as_dict())
        else:
            continue
        code = _code(row)
        if code:
            out[code] = row
    return out


def _stored_watch_items(store: Any, slug: str, trade_date: str) -> list[dict[str, Any]]:
    raw = store.get_setting(_pool_key(slug), None)
    if isinstance(raw, dict) and str(raw.get("trade_date") or "") == trade_date:
        return [
            dict(row)
            for row in raw.get("items") or []
            if isinstance(row, dict) and row.get("bucket") != "position" and _code(row)
        ]

    legacy = store.get_setting(f"{_LEGACY_POOL_KEY_PREFIX}{slug}", None)
    if not isinstance(legacy, dict) or str(legacy.get("trade_date") or "") != trade_date:
        return []
    return [dict(row) for row in legacy.get("picks") or [] if isinstance(row, dict) and _code(row)]


def _latest_stored_watch_items(store: Any, slug: str) -> list[dict[str, Any]]:
    raw = store.get_setting(_pool_key(slug), None)
    if isinstance(raw, dict):
        return [
            dict(row)
            for row in raw.get("items") or []
            if isinstance(row, dict) and row.get("bucket") != "position" and _code(row)
        ]
    return []


def _build_snapshot(
    *,
    slug: str,
    trade_date: str,
    cabin: dict[str, Any],
    positions: list[dict[str, Any]],
    candidates: list[dict[str, Any]],
    actions: list[Any] | None,
    source: str,
    updated_at: str | None = None,
) -> dict[str, Any]:
    limits = _limits(slug, cabin)
    action_by_code = _action_rows(actions)
    candidate_by_code: dict[str, dict[str, Any]] = {}
    candidate_order: list[str] = []
    for raw in candidates:
        if not isinstance(raw, dict):
            continue
        code = _code(raw)
        if not code:
            continue
        if code not in candidate_by_code:
            candidate_order.append(code)
        candidate_by_code[code] = dict(raw)

    position_items: list[dict[str, Any]] = []
    held_codes: set[str] = set()
    for raw in positions:
        if not isinstance(raw, dict):
            continue
        code = _code(raw)
        if not code or code in held_codes:
            continue
        held_codes.add(code)
        item = {**candidate_by_code.get(code, {}), **dict(raw)}
        action = _candidate_action(action_by_code.get(code, {"action": "holding"}))
        item.update(
            {
                "code": code,
                "name": str(item.get("name") or code),
                "bucket": "position",
                "action": action,
                "intent": action,
            }
        )
        if code in action_by_code and action_by_code[code].get("reason"):
            item["action_reason"] = str(action_by_code[code]["reason"])
        position_items.append(item)

    watch_items: list[dict[str, Any]] = []
    watch_seen: set[str] = set()
    for code in [*candidate_order, *action_by_code]:
        if code in held_codes or code in watch_seen:
            continue
        base = candidate_by_code.get(code) or action_by_code.get(code) or {}
        item = dict(base)
        action = _candidate_action(action_by_code.get(code, item))
        item.update(
            {
                "code": code,
                "name": str(item.get("name") or code),
                "bucket": "observe",
                "action": action,
                "intent": action,
            }
        )
        if code in action_by_code and action_by_code[code].get("reason"):
            item["action_reason"] = str(action_by_code[code]["reason"])
        watch_items.append(item)
        watch_seen.add(code)
        if len(watch_items) >= int(limits["max_observe"]):
            break

    items = [*position_items, *watch_items]
    return {
        "slug": slug,
        "trade_date": trade_date,
        "updated_at": updated_at or datetime.now(_TZ).isoformat(timespec="seconds"),
        "source": source,
        "limits": limits,
        "counts": {
            "positions": len(position_items),
            "observe": len(watch_items),
            "total": len(items),
        },
        "over_capacity": len(position_items) > int(limits["max_positions"]),
        "items": items,
    }


def reconcile_unified_monitor_pool(
    store: Any,
    *,
    slug: str,
    trade_date: str,
    candidates: list[dict[str, Any]] | None = None,
    actions: list[Any] | None = None,
    source: str = "reconcile",
    preserve_existing: bool = False,
) -> dict[str, Any]:
    """用当前持仓、候选和动作幂等重建并保存唯一监察池。"""
    key = str(slug or "").strip()
    day = str(trade_date or "").strip()
    cabin = ensure_dragon_cabin_policy(store, key)
    if not cabin:
        return {
            "slug": key,
            "trade_date": day,
            "updated_at": datetime.now(_TZ).isoformat(timespec="seconds"),
            "source": source,
            "limits": _limits(key, {}),
            "counts": {"positions": 0, "observe": 0, "total": 0},
            "over_capacity": False,
            "items": [],
            "changes": {"kept": [], "added": [], "dropped": [], "changed": False},
        }
    previous_watch = _latest_stored_watch_items(store, key)
    watch = _stored_watch_items(store, key, day) if candidates is None else candidates
    if preserve_existing and candidates is not None:
        by_code = {_code(row): dict(row) for row in previous_watch if _code(row)}
        by_code.update({_code(row): dict(row) for row in candidates if _code(row)})
        watch = list(by_code.values())
    snapshot = _build_snapshot(
        slug=key,
        trade_date=day,
        cabin=cabin,
        positions=store.list_paper_positions(cabin["id"]),
        candidates=watch,
        actions=actions,
        source=source,
    )
    old_by_code = {
        _code(row): row
        for row in previous_watch
        if _code(row) and _candidate_action(row) == "observe"
    }
    new_by_code = {
        _code(row): row
        for row in snapshot.get("items") or []
        if isinstance(row, dict)
        and row.get("bucket") != "position"
        and _candidate_action(row) == "observe"
        and _code(row)
    }
    snapshot["changes"] = {
        "kept": [new_by_code[code] for code in new_by_code if code in old_by_code],
        "added": [new_by_code[code] for code in new_by_code if code not in old_by_code],
        "dropped": [old_by_code[code] for code in old_by_code if code not in new_by_code],
        "changed": set(old_by_code) != set(new_by_code),
    }
    store.set_setting(_pool_key(key), snapshot)
    return snapshot


def replace_candidate_feed(
    store: Any,
    *,
    slug: str,
    trade_date: str,
    feed: str,
    candidates: list[dict[str, Any]] | None,
) -> dict[str, Any]:
    """只替换一个候选来源，不让并行扫描器互相覆盖。

    多个扫描器可各自维护一份 feed。某一轮空结果只清掉自己的旧候选，不能把另一来源
    刚写入的 ready 一并抹掉。无 feed 的存量行按主扫描来源兼容迁移。
    """
    key = str(slug or "").strip()
    day = str(trade_date or "").strip()
    feed_key = str(feed or "").strip()
    primary_feed = f"skill_watch:{key}"
    previous = _stored_watch_items(store, key, day)
    kept: list[dict[str, Any]] = []
    for raw in previous:
        row = dict(raw)
        row_feed = str(row.get(_CANDIDATE_FEED_FIELD) or primary_feed)
        if row_feed == feed_key:
            continue
        row[_CANDIDATE_FEED_FIELD] = row_feed
        kept.append(row)

    incoming: list[dict[str, Any]] = []
    for raw in candidates or []:
        if not isinstance(raw, dict) or not _code(raw):
            continue
        row = dict(raw)
        row[_CANDIDATE_FEED_FIELD] = feed_key
        incoming.append(row)
    combined = [*kept, *incoming]
    state_rank = {"ready": 0, "setup": 1, "near": 2}
    combined.sort(
        key=lambda row: (
            state_rank.get(
                str(row.get("state") or ""),
                0 if _candidate_action(row) in {"buy", "rebalance"} else 3,
            ),
        )
    )
    seen_codes: set[str] = set()
    combined = [
        row
        for row in combined
        if not (_code(row) in seen_codes or seen_codes.add(_code(row)))
    ]
    return reconcile_unified_monitor_pool(
        store,
        slug=key,
        trade_date=day,
        candidates=combined,
        source=f"candidate_feed:{feed_key}",
    )


def drop_candidate_feed(store: Any, *, slug: str, feed: str) -> int:
    """摘掉某个候选来源的行（战法退役时用），保留其余来源与快照日期。

    不能走 ``replace_candidate_feed``：它按传入的 ``trade_date`` 读旧快照，日期对不上
    就会把整池当成空的重建，连别的来源一起抹掉。
    """
    key = str(slug or "").strip()
    raw = store.get_setting(_pool_key(key), None)
    if not isinstance(raw, dict):
        return 0
    items = [row for row in raw.get("items") or [] if isinstance(row, dict)]
    kept = [
        row
        for row in items
        if str(row.get(_CANDIDATE_FEED_FIELD) or "") != str(feed or "")
    ]
    if len(kept) == len(items):
        return 0
    store.set_setting(_pool_key(key), {**raw, "items": kept})
    return len(items) - len(kept)


def get_unified_monitor_pool(
    store: Any,
    *,
    slug: str,
    trade_date: str,
) -> dict[str, Any]:
    """读取统一池，并实时用纸面持仓账本刷新持仓投影。"""
    key = str(slug or "").strip()
    day = str(trade_date or "").strip()
    cabin = ensure_dragon_cabin_policy(store, key)
    if not cabin:
        return {
            "slug": key,
            "trade_date": day,
            "updated_at": datetime.now(_TZ).isoformat(timespec="seconds"),
            "source": "retired",
            "limits": _limits(key, {}),
            "counts": {"positions": 0, "observe": 0, "total": 0},
            "over_capacity": False,
            "items": [],
        }
    raw = store.get_setting(_pool_key(key), None)
    source = str(raw.get("source") or "read") if isinstance(raw, dict) else "legacy_migration"
    updated_at = str(raw.get("updated_at") or "") if isinstance(raw, dict) else None
    if isinstance(raw, dict) and str(raw.get("trade_date") or "") == day:
        candidates = [dict(row) for row in raw.get("items") or [] if isinstance(row, dict)]
    else:
        candidates = _stored_watch_items(store, key, day)
    return _build_snapshot(
        slug=key,
        trade_date=day,
        cabin=cabin,
        positions=store.list_paper_positions(cabin["id"]),
        candidates=candidates,
        actions=None,
        source=source,
        updated_at=updated_at or None,
    )
