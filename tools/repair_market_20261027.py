"""Apply or revert the reviewed 2026-10-27 PostgreSQL market repair plan.

The default operation is read-only verification. Apply/rollback require explicit
subcommands, an unchanged before/after image and the application's market lock.
The plan and its evidence are prepared separately; this tool never fetches data.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
from contextlib import nullcontext
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import psycopg
from psycopg.rows import dict_row


QUOTE_COLUMNS = (
    "trade_date", "code", "open", "high", "low", "close", "volume", "amount",
    "outstanding_share", "turnover", "source", "receipt_id", "fetched_at",
)
MUTABLE_COLUMNS = ("volume", "amount", "turnover")
FACTOR_COLUMNS = ("code", "trade_date", "hfq_factor", "source", "fetched_at")
SELECT_QUOTE = (
    "SELECT " + ", ".join(QUOTE_COLUMNS)
    + " FROM market.quotes_daily WHERE trade_date=%s AND code=%s"
)
SELECT_FACTORS = (
    "SELECT " + ", ".join(FACTOR_COLUMNS)
    + " FROM market.adjust_factors WHERE code=%s ORDER BY trade_date"
)
UPDATE_QUOTE = (
    "UPDATE market.quotes_daily SET volume=%s, amount=%s, turnover=%s "
    "WHERE trade_date=%s AND code=%s"
)
INSERT_FACTOR = (
    "INSERT INTO market.adjust_factors(code,trade_date,hfq_factor,source,fetched_at) "
    "VALUES(%s,%s,%s,%s,%s)"
)
DELETE_FACTOR = "DELETE FROM market.adjust_factors WHERE code=%s AND trade_date=%s"
BUMP_REVISION = (
    "UPDATE market.meta SET value=(value::bigint+1)::text, "
    "updated_at=CURRENT_TIMESTAMP::text WHERE key=%s"
)


def validate_plan(plan: dict[str, Any]) -> None:
    """Reject changes outside the reviewed securities, fields and dates."""
    if plan.get("version") != "market-repair-20261027-v2":
        raise ValueError("unsupported plan version")
    quotes = plan.get("quotes", [])
    factors = plan.get("factors", [])
    if len(quotes) != 346 or len(factors) not in (0, 5):
        raise ValueError("expected 346 quotes and either zero or five factor rows")
    seen: set[tuple[str, str]] = set()
    expected_turnover = {"2026-10-26": 0.0158, "2026-10-27": 0.0344}
    sentinel = 2.0 ** -127
    sentinel_count = 0
    turnover_dates: set[str] = set()
    for item in quotes:
        before, after = item["before"], item["after"]
        if set(before) != set(QUOTE_COLUMNS) or set(after) != set(MUTABLE_COLUMNS):
            raise ValueError("invalid quote fields")
        key = (before["code"], before["trade_date"])
        if key in seen:
            raise ValueError("duplicate quote key")
        seen.add(key)
        if (before["source"] == "tdx" and before["volume"] == sentinel * 100
                and before["amount"] == sentinel):
            if before["turnover"] is not None and not 0 <= before["turnover"] < 1e-35:
                raise ValueError(f"unexpected sentinel turnover: {key}")
            if after != {"volume": 0.0, "amount": 0.0, "turnover": 0.0}:
                raise ValueError(f"unexpected sentinel quote after-image: {key}")
            sentinel_count += 1
        elif key[0] == "689009" and key[1] in expected_turnover:
            if (before["turnover"] is not None
                    or after["volume"] != before["volume"] or after["amount"] != before["amount"]
                    or after["turnover"] != expected_turnover[key[1]]):
                raise ValueError(f"unexpected turnover after-image: {key}")
            turnover_dates.add(key[1])
        else:
            raise ValueError(f"quote outside authorized scope: {key}")
    if sentinel_count != 344 or turnover_dates != set(expected_turnover):
        raise ValueError("quote keys differ from reviewed scope")
    expected_dates = {"2023-10-27", "2024-05-24", "2025-06-13", "2025-10-31", "2026-08-07"}
    if factors and {x["trade_date"] for x in factors} != expected_dates:
        raise ValueError("factor dates differ from reviewed scope")
    expected_factors = {
        "2023-10-27": 1.0,
        "2024-05-24": 1.0070440251572328,
        "2025-06-13": 1.0260224755724456,
        "2025-10-31": 1.0332516223555428,
        "2026-08-07": 1.063714816634754,
    }
    for row in factors:
        if (set(row) != set(FACTOR_COLUMNS) or row["code"] != "689009"
                or row["source"] != "exchange_reference_derived"
                or not math.isfinite(row["hfq_factor"])
                or not math.isclose(row["hfq_factor"], expected_factors[row["trade_date"]],
                                    rel_tol=1e-14, abs_tol=0)):
            raise ValueError("invalid factor row")


def quote_after(item: dict[str, Any]) -> dict[str, Any]:
    return {**item["before"], **item["after"]}


def read_state(cursor: Any, plan: dict[str, Any], *, lock: bool = False) -> tuple[list[dict], list[dict]]:
    rows = []
    for item in plan["quotes"]:
        before = item["before"]
        cursor.execute(SELECT_QUOTE + (" FOR UPDATE" if lock else ""),
                       (before["trade_date"], before["code"]))
        row = cursor.fetchone()
        rows.append(dict(row) if row is not None else {})
    if plan["factors"]:
        cursor.execute(SELECT_FACTORS + (" FOR UPDATE" if lock else ""), ("689009",))
        return rows, [dict(row) for row in cursor.fetchall()]
    return rows, []


def state_label(rows: list[dict], factors: list[dict], plan: dict[str, Any]) -> str:
    expected_before = [item["before"] for item in plan["quotes"]]
    expected_after = [quote_after(item) for item in plan["quotes"]]
    expected_factors = sorted(plan["factors"], key=lambda row: row["trade_date"])
    if rows == expected_before and not factors:
        return "before"
    if rows == expected_after and factors == expected_factors:
        return "after"
    return "conflict"


def save_backup(path: Path, plan: dict[str, Any], plan_sha256: str) -> None:
    """Persist a non-overwritable before/after record before the first UPDATE."""
    backup = {
        "version": "market-repair-backup-v1",
        "created_at": datetime.now(timezone.utc).isoformat(),
        "plan_sha256": plan_sha256,
        "plan": plan,
    }
    payload = (json.dumps(backup, ensure_ascii=False, indent=2, allow_nan=False) + "\n").encode("utf-8")
    descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(descriptor, "wb") as output:
        output.write(payload)
        output.flush()
        os.fsync(output.fileno())


def change(conn: Any, plan: dict[str, Any], *, apply: bool,
           backup_path: Path | None = None, plan_sha256: str = "") -> None:
    """All target rows and revision marks change in one PostgreSQL transaction."""
    validate_plan(plan)
    with conn.transaction():
        with conn.cursor(row_factory=dict_row) as cursor:
            rows, factors = read_state(cursor, plan, lock=True)
            required = "before" if apply else "after"
            observed = state_label(rows, factors, plan)
            if observed != required:
                raise RuntimeError(f"expected {required} state, found {observed}; no changes made")
            if apply:
                if backup_path is None:
                    raise ValueError("apply requires an exclusive backup path")
                save_backup(backup_path, plan, plan_sha256)
            for item in plan["quotes"]:
                before = item["before"]
                values = item["after"] if apply else before
                cursor.execute(UPDATE_QUOTE, (
                    *(values[key] for key in MUTABLE_COLUMNS),
                    before["trade_date"], before["code"],
                ))
                if cursor.rowcount != 1:
                    raise RuntimeError("quote update did not affect exactly one row")
            for row in plan["factors"]:
                if apply:
                    cursor.execute(INSERT_FACTOR, tuple(row[key] for key in FACTOR_COLUMNS))
                else:
                    cursor.execute(DELETE_FACTOR, (row["code"], row["trade_date"]))
                if cursor.rowcount != 1:
                    raise RuntimeError("factor change did not affect exactly one row")
            revisions = ["market_revision", "quotes_revision"]
            if plan["factors"]:
                revisions.append("adjust_factors_revision")
            for key in revisions:
                cursor.execute(BUMP_REVISION, (key,))
                if cursor.rowcount != 1:
                    raise RuntimeError(f"missing market revision: {key}")
            after_rows, after_factors = read_state(cursor, plan)
            wanted = "after" if apply else "before"
            if state_label(after_rows, after_factors, plan) != wanted:
                raise RuntimeError("post-change verification failed")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("operation", choices=("verify", "apply", "rollback"), nargs="?", default="verify")
    parser.add_argument("--plan", type=Path)
    parser.add_argument("--backup", type=Path)
    args = parser.parse_args()
    if args.operation == "rollback":
        if not args.backup or args.plan:
            parser.error("rollback requires --backup and does not accept --plan")
        backup = json.loads(args.backup.read_text(encoding="utf-8"))
        if backup.get("version") != "market-repair-backup-v1":
            raise ValueError("invalid backup version")
        plan = backup["plan"]
        digest = backup["plan_sha256"]
    else:
        if not args.plan or (args.operation == "apply" and not args.backup):
            parser.error("verify requires --plan; apply requires --plan and --backup")
        contents = args.plan.read_bytes()
        plan = json.loads(contents)
        digest = hashlib.sha256(contents).hexdigest()
    validate_plan(plan)
    dsn = os.environ.get("PALACE_POSTGRES_URL") or os.environ.get("LOCI_POSTGRES_URL")
    if not dsn:
        raise RuntimeError("PALACE_POSTGRES_URL or LOCI_POSTGRES_URL must be set")
    print(f"plan_sha256={digest}; quotes={len(plan['quotes'])}; factors={len(plan['factors'])}")
    lock = nullcontext()
    if args.operation != "verify":
        from src.market.infrastructure.write_lock import market_write_lock
        from src.shared.paths import market_db

        lock = market_write_lock(market_db(), label="reviewed-market-repair-20261027")
    with lock, psycopg.connect(dsn, connect_timeout=5, autocommit=True) as conn:
        if args.operation == "verify":
            with conn.transaction():
                with conn.cursor(row_factory=dict_row) as cursor:
                    cursor.execute("SET TRANSACTION READ ONLY")
                    rows, factors = read_state(cursor, plan)
                    label = state_label(rows, factors, plan)
            print(f"state={label}")
            if label == "conflict":
                raise SystemExit(2)
        else:
            change(conn, plan, apply=args.operation == "apply", backup_path=args.backup,
                   plan_sha256=digest)
            print(f"{args.operation}=committed")


if __name__ == "__main__":
    main()
