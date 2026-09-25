"""Read-only platform reporting over the existing per-tenant daily model counters."""
from __future__ import annotations

from contextlib import closing
from datetime import date
from pathlib import Path
import sqlite3
from typing import Any
from copy import deepcopy
from threading import Event, Lock
from time import monotonic
from datetime import datetime, timezone

from src.shared.tenancy import PRIMARY_TENANT, list_tenant_ids, tenant_paths


_CACHE: dict[tuple[str, date, date], tuple[float, dict[str, Any]]] = {}
_CACHE_LOCK = Lock()
_INFLIGHT: dict[tuple[str, date, date], Event] = {}


def platform_model_usage(data_root: Path, *, start: date, end: date) -> dict[str, Any]:
    key = (str(data_root.resolve()), start, end)
    while True:
        with _CACHE_LOCK:
            cached = _CACHE.get(key)
            if cached and monotonic() - cached[0] < 15:
                result = deepcopy(cached[1])
                result['cache_age_seconds'] = round(monotonic() - cached[0], 3)
                return result
            event = _INFLIGHT.get(key)
            owner = event is None
            if owner:
                event = _INFLIGHT[key] = Event()
        if owner:
            break
        event.wait()
    try:
        result = _read_platform_model_usage(data_root, start=start, end=end)
        result.update(generated_at=datetime.now(timezone.utc).isoformat(), cache_age_seconds=0,
                      partial=bool(result['unavailable_tenants']))
        with _CACHE_LOCK:
            if len(_CACHE) >= 64:
                _CACHE.pop(next(iter(_CACHE)))
            _CACHE[key] = (monotonic(), deepcopy(result))
        return result
    finally:
        with _CACHE_LOCK:
            _INFLIGHT.pop(key).set()


def _read_platform_model_usage(data_root: Path, *, start: date, end: date) -> dict[str, Any]:
    totals: dict[tuple[str, str, str], dict[str, Any]] = {}
    unavailable: list[str] = []
    for tenant in [PRIMARY_TENANT, *list_tenant_ids(data_root)]:
        path = tenant_paths(data_root, tenant).ops_db
        if not path.is_file():
            continue
        try:
            # Reporting must not create databases or run store schema migrations.
            with closing(sqlite3.connect(f"{path.resolve().as_uri()}?mode=ro", uri=True, timeout=3)) as conn:
                if not conn.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='ai_usage_daily'").fetchone():
                    continue
                rows = conn.execute(
                    "SELECT day,provider,model,input_tokens,output_tokens,calls FROM ai_usage_daily "
                    "WHERE day >= ? AND day <= ?", (start.isoformat(), end.isoformat()),
                ).fetchall()
            for day, provider, model, inputs, outputs, calls in rows:
                key = (day, provider, model)
                item = totals.setdefault(key, dict(day=day, provider=provider, model=model,
                                                  input_tokens=0, output_tokens=0, calls=0))
                item["input_tokens"] += int(inputs or 0)
                item["output_tokens"] += int(outputs or 0)
                item["calls"] += int(calls or 0)
        except sqlite3.Error:
            unavailable.append(tenant)
    return {"items": sorted(totals.values(), key=lambda row: (row["day"], row["model"]), reverse=True),
            "unavailable_tenants": unavailable}
