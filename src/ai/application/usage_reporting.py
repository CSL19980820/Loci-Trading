"""Read-only platform reporting over the existing per-tenant daily model counters."""
from __future__ import annotations

from contextlib import closing
from datetime import date
from pathlib import Path
import sqlite3
from typing import Any

from src.shared.tenancy import PRIMARY_TENANT, list_tenant_ids, tenant_paths


def platform_model_usage(data_root: Path, *, start: date, end: date) -> dict[str, Any]:
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
