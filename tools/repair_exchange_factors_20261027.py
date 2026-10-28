"""Apply or roll back the reviewed exchange-derived 689009 factor rows."""
from __future__ import annotations

import argparse
import json
import math
import os
from pathlib import Path
import sys

import psycopg
from psycopg.rows import dict_row

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.market.infrastructure.write_lock import market_write_lock
from src.shared.paths import market_db


def _rows(path: Path) -> list[dict]:
    plan = json.loads(path.read_text(encoding="utf-8"))
    if plan.get("version") != "market-repair-20261027-v2":
        raise ValueError("unsupported plan version")
    rows = plan.get("factors") or []
    expected = {
        "2023-10-27": 1.0,
        "2024-05-24": 1.0070440251572328,
        "2025-06-13": 1.0260224755724456,
        "2025-10-31": 1.0332516223555428,
        "2026-08-07": 1.063714816634754,
    }
    if len(rows) != 5:
        raise ValueError("expected five reviewed factor rows")
    for row in rows:
        day = str(row.get("trade_date") or "")
        if (
            row.get("code") != "689009"
            or day not in expected
            or row.get("source") != "exchange_reference_derived"
            or not math.isclose(
                float(row.get("hfq_factor")),
                expected[day],
                rel_tol=1e-14,
                abs_tol=0.0,
            )
        ):
            raise ValueError(f"invalid reviewed factor row: {row}")
    return rows


def _state(rows: list[dict], current: list[dict]) -> str:
    wanted = sorted(rows, key=lambda row: row["trade_date"])
    observed = sorted(current, key=lambda row: row["trade_date"])
    if not observed:
        return "empty"
    columns = ("code", "trade_date", "hfq_factor", "source")
    if len(observed) == len(wanted) and all(
        all(left.get(key) == right.get(key) for key in columns)
        for left, right in zip(observed, wanted, strict=True)
    ):
        return "applied"
    return "conflict"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("operation", choices=("verify", "apply", "rollback"))
    parser.add_argument(
        "--plan",
        type=Path,
        default=Path("/app/data/repair-20261027/repair-plan-v2.json"),
    )
    args = parser.parse_args()
    rows = _rows(args.plan)
    dsn = os.environ.get("PALACE_POSTGRES_URL") or os.environ.get("LOCI_POSTGRES_URL")
    if not dsn:
        raise RuntimeError("PALACE_POSTGRES_URL or LOCI_POSTGRES_URL must be set")
    with psycopg.connect(dsn, connect_timeout=5, autocommit=True, row_factory=dict_row) as conn:
        if args.operation == "verify":
            with conn.transaction():
                conn.execute("SET TRANSACTION READ ONLY")
                current = conn.execute(
                    "SELECT code, trade_date, hfq_factor, source, fetched_at "
                    "FROM market.adjust_factors WHERE code='689009' "
                    "ORDER BY trade_date"
                ).fetchall()
            state = _state(rows, current)
            print(f"state={state}; rows={len(current)}")
            return 0 if state == "empty" else 2
        with market_write_lock(
            market_db(), label=f"exchange-factors-20261027:{args.operation}"
        ):
            with conn.transaction():
                current = conn.execute(
                    "SELECT code, trade_date, hfq_factor, source, fetched_at "
                    "FROM market.adjust_factors WHERE code='689009' "
                    "ORDER BY trade_date FOR UPDATE"
                ).fetchall()
                state = _state(rows, current)
                if args.operation == "apply":
                    if state != "empty":
                        raise RuntimeError(f"expected empty state, found {state}")
                    for row in rows:
                        conn.execute(
                            "INSERT INTO market.adjust_factors"
                            "(code,trade_date,hfq_factor,source,fetched_at) "
                            "VALUES(%s,%s,%s,%s,%s)",
                            (
                                row["code"],
                                row["trade_date"],
                                row["hfq_factor"],
                                row["source"],
                                row["fetched_at"],
                            ),
                        )
                else:
                    if state != "applied":
                        raise RuntimeError(f"expected applied state, found {state}")
                    conn.execute(
                        "DELETE FROM market.adjust_factors "
                        "WHERE code='689009' AND source='exchange_reference_derived'"
                    )
                conn.execute(
                    "UPDATE market.meta "
                    "SET value=(value::bigint+1)::text, updated_at=CURRENT_TIMESTAMP::text "
                    "WHERE key IN ('market_revision','adjust_factors_revision')"
                )
                if conn.execute(
                    "SELECT count(*) AS count FROM market.meta "
                    "WHERE key IN ('market_revision','adjust_factors_revision')"
                ).fetchone()["count"] != 2:
                    raise RuntimeError("market revision keys are missing")
            print(f"{args.operation}=committed; rows={len(rows)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
