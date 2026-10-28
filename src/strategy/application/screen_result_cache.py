"""Versioned task result cache for finalized, reproducible screen days."""
from __future__ import annotations

from dataclasses import asdict
from hashlib import sha256
import json
import os
from pathlib import Path
import time
from typing import Any, Mapping

from src.shared.tenancy import current_tenant
from src.strategy.application.screener import ScreenResult

SCREEN_RESULT_CACHE_SCHEMA = 1
_MAX_CACHE_FILES = 500


def _cache_root(store: Any) -> Path:
    raw = getattr(store, "db_path", "")
    base = Path(str(raw or paths_fallback())).expanduser()
    if str(base) in {"", ":memory:"}:
        return Path(paths_fallback()).parent / "cache" / "screen-results"
    return base.parent / "cache" / "screen-results"


def paths_fallback() -> str:
    from src.shared.paths import market_db

    return str(market_db())


def _canonical(value: Any) -> Any:
    if isinstance(value, Mapping):
        return {
            str(key): _canonical(item)
            for key, item in sorted(value.items(), key=lambda pair: str(pair[0]))
        }
    if isinstance(value, (list, tuple)):
        return [_canonical(item) for item in value]
    if isinstance(value, set | frozenset):
        return sorted(_canonical(item) for item in value)
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    return str(value)


def _key_payload(
    store: Any,
    engine: Any,
    trade_date: str,
    *,
    params: Mapping[str, Any] | None,
    codes: list[str] | None,
    universe: Mapping[str, Any] | None,
    adjust: str,
    extra_bars: int,
    health_check: bool,
    skip_universe_safety: bool,
) -> dict[str, Any]:
    return {
        "schema": SCREEN_RESULT_CACHE_SCHEMA,
        "tenant": current_tenant(),
        "strategy": str(getattr(engine, "slug", "")),
        "strategy_revision": str(getattr(engine, "strategy_revision", "")),
        "trade_date": str(trade_date),
        "market_revision": str(store.market_revision()),
        "params": _canonical(params or {}),
        "codes": _canonical(codes),
        "universe": _canonical(universe),
        "adjust": str(adjust),
        "extra_bars": int(extra_bars),
        "skip_universe_safety": bool(skip_universe_safety),
    }


def _cache_path(store: Any, payload: Mapping[str, Any]) -> Path:
    encoded = json.dumps(
        payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")
    return _cache_root(store) / f"{sha256(encoded).hexdigest()}.json"


def load_screen_result(
    store: Any,
    engine: Any,
    trade_date: str,
    *,
    params: Mapping[str, Any] | None,
    codes: list[str] | None,
    universe: Mapping[str, Any] | None,
    adjust: str,
    extra_bars: int,
    health_check: bool,
    skip_universe_safety: bool,
) -> ScreenResult | None:
    """Load only an exact revision/input match; any parse failure is a miss."""
    payload = _key_payload(
        store, engine, trade_date, params=params, codes=codes, universe=universe,
        adjust=adjust, extra_bars=extra_bars, health_check=health_check,
        skip_universe_safety=skip_universe_safety,
    )
    path = _cache_path(store, payload)
    started = time.monotonic()
    try:
        document = json.loads(path.read_text(encoding="utf-8"))
        cached_key = document.get("key")
        result_payload = document.get("result")
        if cached_key != payload or not isinstance(result_payload, dict):
            return None
        result = ScreenResult(**result_payload)
    except (OSError, ValueError, TypeError, json.JSONDecodeError):
        return None
    if (
        result.strategy_slug != payload["strategy"]
        or result.strategy_revision != payload["strategy_revision"]
        or result.trade_date != payload["trade_date"]
        or str(result.data_snapshot.get("market_revision") or "")
        != payload["market_revision"]
    ):
        return None
    result.cache_hit = True
    result.elapsed_seconds = round(time.monotonic() - started, 6)
    return result


def save_screen_result(
    store: Any,
    engine: Any,
    result: ScreenResult,
    *,
    params: Mapping[str, Any] | None,
    codes: list[str] | None,
    universe: Mapping[str, Any] | None,
    adjust: str,
    extra_bars: int,
    health_check: bool,
    skip_universe_safety: bool,
) -> None:
    """Atomically persist a finalized result; cache failures never break screening."""
    payload = _key_payload(
        store, engine, result.trade_date, params=params, codes=codes, universe=universe,
        adjust=adjust, extra_bars=extra_bars, health_check=health_check,
        skip_universe_safety=skip_universe_safety,
    )
    path = _cache_path(store, payload)
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        body = {
            "schema": SCREEN_RESULT_CACHE_SCHEMA,
            "key": payload,
            "result": asdict(result),
            "saved_at": time.time(),
        }
        temporary = path.with_name(
            f".{path.name}.{os.getpid()}.{abs(hash((threading_id(), time.time_ns())))}.tmp"
        )
        temporary.write_text(
            json.dumps(
                body, ensure_ascii=False, sort_keys=True, separators=(",", ":"),
                allow_nan=False,
            ),
            encoding="utf-8",
        )
        os.replace(temporary, path)
        cached = sorted(
            path.parent.glob("*.json"),
            key=lambda item: item.stat().st_mtime_ns,
            reverse=True,
        )
        for stale in cached[_MAX_CACHE_FILES:]:
            stale.unlink(missing_ok=True)
    except (OSError, TypeError, ValueError):
        try:
            temporary.unlink(missing_ok=True)
        except (OSError, UnboundLocalError):
            pass


def threading_id() -> int:
    # Kept behind a helper so the cache module has no import-time threading cost.
    import threading

    return threading.get_ident()
