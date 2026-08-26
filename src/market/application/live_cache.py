"""进程内实时行情 / 分时 TTL 缓存。

仅服务监测、提醒、纸面量化；不写 market.db，不进 research run card。
"""
from __future__ import annotations

from src.shared.clock import utc_now

from dataclasses import dataclass
import threading
import time
from typing import Any

from src.market import fetch_live_quotes_routed, fetch_minute_routed
from src.market.infrastructure.store import normalize_code

_LOCK = threading.Lock()
_QUOTE_TTL_SEC = 5.0
_MINUTE_TTL_SEC = 45.0

_quote_cache: dict[str, tuple[float, dict[str, Any], str]] = {}
_minute_cache: dict[str, tuple[float, list[dict[str, Any]], str]] = {}


@dataclass(frozen=True)
class LiveSnapshot:
    """一次监测用的 ephemeral 快照。"""

    quotes: dict[str, dict[str, Any]]
    minutes: dict[str, list[dict[str, Any]]]
    fetched_at: str
    adapter_ids: dict[str, str]
    cache_hits: dict[str, bool]


def get_cached_quotes(
    codes: list[str],
    *,
    force_refresh: bool = False,
) -> tuple[dict[str, dict[str, Any]], dict[str, str], dict[str, bool]]:
    """批量取现价；返回 (by_code, adapter_by_code, cache_hit_by_code)。"""
    normalized: list[str] = []
    for raw in codes:
        try:
            normalized.append(normalize_code(str(raw)))
        except Exception:
            continue
    normalized = list(dict.fromkeys(normalized))
    now = time.monotonic()
    out: dict[str, dict[str, Any]] = {}
    adapters: dict[str, str] = {}
    hits: dict[str, bool] = {}
    missing: list[str] = []

    with _LOCK:
        for code in normalized:
            cached = _quote_cache.get(code)
            if (
                not force_refresh
                and cached is not None
                and now - cached[0] < _QUOTE_TTL_SEC
            ):
                out[code] = cached[1]
                adapters[code] = cached[2]
                hits[code] = True
            else:
                missing.append(code)
                hits[code] = False

    if missing:
        rows, adapter_id = fetch_live_quotes_routed(missing)
        adapter = str(adapter_id or "")
        by_code: dict[str, dict[str, Any]] = {}
        for row in rows or []:
            if not isinstance(row, dict):
                continue
            try:
                code = normalize_code(str(row.get("code") or ""))
            except Exception:
                continue
            by_code[code] = row
        stamp = time.monotonic()
        with _LOCK:
            for code in missing:
                row = by_code.get(code)
                if row is None:
                    continue
                _quote_cache[code] = (stamp, row, adapter)
                out[code] = row
                adapters[code] = adapter
    return out, adapters, hits


def get_cached_minute(
    code: str,
    *,
    force_refresh: bool = False,
) -> tuple[list[dict[str, Any]], str, bool]:
    try:
        code = normalize_code(code)
    except Exception:
        return [], "", False
    now = time.monotonic()
    with _LOCK:
        cached = _minute_cache.get(code)
        if (
            not force_refresh
            and cached is not None
            and now - cached[0] < _MINUTE_TTL_SEC
        ):
            return list(cached[1]), cached[2], True

    try:
        bars, adapter_id = fetch_minute_routed(code)
    except Exception:
        return [], "", False
    rows: list[dict[str, Any]] = []
    if bars is None:
        rows = []
    elif hasattr(bars, "to_dict"):
        try:
            rows = list(bars.to_dict(orient="records"))  # type: ignore[arg-type]
        except Exception:
            rows = []
    elif isinstance(bars, list):
        rows = [b for b in bars if isinstance(b, dict)]
    adapter = str(adapter_id or "")
    with _LOCK:
        _minute_cache[code] = (time.monotonic(), rows, adapter)
    return rows, adapter, False


def build_monitor_snapshot(
    codes: list[str],
    *,
    include_minute: bool = True,
    force_refresh: bool = False,
) -> LiveSnapshot:
    from datetime import datetime, timezone

    quotes, adapters, hits = get_cached_quotes(codes, force_refresh=force_refresh)
    minutes: dict[str, list[dict[str, Any]]] = {}
    if include_minute:
        for code in quotes:
            bars, adapter, hit = get_cached_minute(code, force_refresh=force_refresh)
            minutes[code] = bars
            if adapter:
                adapters[f"minute:{code}"] = adapter
            hits[f"minute:{code}"] = hit
    return LiveSnapshot(
        quotes=quotes,
        minutes=minutes,
        fetched_at=utc_now(),
        adapter_ids=adapters,
        cache_hits=hits,
    )
