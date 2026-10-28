"""Minimal live PG18 read/write smoke test for the cutover."""
from __future__ import annotations

import json
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.shared.postgres import database_url
import psycopg
from psycopg.rows import dict_row


def main() -> int:
    timings: dict[str, float] = {}
    with psycopg.connect(database_url(), row_factory=dict_row) as conn:
        started = time.perf_counter()
        version = conn.execute("SELECT version() AS version").fetchone()["version"]
        timings["version_ms"] = round((time.perf_counter() - started) * 1000, 3)

        started = time.perf_counter()
        row = conn.execute(
            "SELECT trade_date, code, close FROM market.quotes_daily "
            "WHERE code=%s ORDER BY trade_date DESC LIMIT 1",
            ("600000",),
        ).fetchone()
        timings["single_code_latest_ms"] = round((time.perf_counter() - started) * 1000, 3)

        started = time.perf_counter()
        history = conn.execute(
            "SELECT trade_date, close FROM market.quotes_daily "
            "WHERE code=%s AND trade_date >= %s AND trade_date <= %s "
            "ORDER BY trade_date",
            ("600000", "2023-10-27", "2026-10-27"),
        ).fetchall()
        timings["single_code_3y_ms"] = round((time.perf_counter() - started) * 1000, 3)

        started = time.perf_counter()
        panel = conn.execute(
            "SELECT trade_date, code, close FROM market.quotes_daily "
            "WHERE trade_date >= %s ORDER BY trade_date, code",
            ("2026-07-28",),
        ).fetchall()
        timings["market_60d_rows_ms"] = round((time.perf_counter() - started) * 1000, 3)

        conn.execute("BEGIN")
        conn.execute(
            "INSERT INTO ops.meta(key,value,updated_at) "
            "VALUES(%s,%s,CURRENT_TIMESTAMP) "
            "ON CONFLICT(key) DO UPDATE SET value=EXCLUDED.value",
            ("postgres_smoke", "ok"),
        )
        found = conn.execute(
            "SELECT value FROM ops.meta WHERE key=%s", ("postgres_smoke",)
        ).fetchone()
        conn.rollback()
        rolled_back = conn.execute(
            "SELECT value FROM ops.meta WHERE key=%s", ("postgres_smoke",)
        ).fetchone()

    print(
        json.dumps(
            {
                "status": "ok",
                "version": version,
                "latest": dict(row) if row else None,
                "history_rows": len(history),
                "panel_rows": len(panel),
                "write_visible_in_tx": bool(found),
                "write_absent_after_rollback": rolled_back is None,
                "timings": timings,
            },
            ensure_ascii=False,
            default=str,
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
