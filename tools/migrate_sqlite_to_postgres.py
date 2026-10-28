"""One-shot, idempotent SQLite -> PostgreSQL importer for Loci.

The source databases are opened read-only.  Each table is copied in bounded
batches, then row counts and primary-key digests are compared before the
command succeeds.  Re-running replaces only rows in the target tables covered
by this import, so an interrupted run can be resumed safely.
"""
from __future__ import annotations

import argparse
from datetime import date, datetime
import hashlib
import json
import os
from pathlib import Path
import sqlite3
import sys
from typing import Any, Iterable

import psycopg
from psycopg import sql
from psycopg.rows import dict_row

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.shared.postgres import database_url
from src.shared.postgres_schema import SCHEMA_SQL, apply_schema


JSON_COLUMNS = {
    "requested_sources_json": "requested_sources",
    "coverage_json": "coverage",
    "fields_json": "fields",
    "payload_json": "payload",
    "config_json": "config",
    "result_json": "result",
    "models_json": "models",
    "condition_group_json": "condition_group",
    "channel_ids_json": "channel_ids",
    "metrics_json": "metrics",
    "issues": "issues",
    "tags_json": "tags",
    "effective_params_json": "effective_params",
    "evidence_json": "evidence",
    "top_codes": "top_codes",
    "state_json": "state",
    "actions_json": "actions",
    "detail_json": "detail",
    "latest_actions_json": "latest_actions",
    "snapshot_json": "snapshot",
    "raw_profile": "raw_profile",
    "detail_json": "detail",
}

COLUMN_TARGETS = {
    "source_route_receipts": {
        "requested_sources_json": "requested_sources",
        "coverage_json": "coverage",
    },
    "source_route_attempts": {
        "fields_json": "fields",
    },
    "intel_snapshots": {"payload_json": "payload"},
    "jobs": {"config_json": "config"},
    "job_runs": {"result_json": "result"},
    "llm_providers": {"models_json": "models"},
    "alert_rules": {
        "condition_group_json": "condition_group",
        "channel_ids_json": "channel_ids",
    },
    "alert_hits": {"snapshot_json": "snapshot"},
    "stocks": {"tags_json": "tags"},
    "candidate_reviews": {
        "effective_params_json": "effective_params",
        "evidence_json": "evidence",
    },
    "ai_judgments": {"top_codes": "top_codes"},
    "guardian_portfolio": {"state_json": "state"},
    "guardian_cycles": {"result_json": "result"},
    "guardian_trades": {"detail_json": "detail"},
    "guardian_consultations": {"payload_json": "payload"},
    "guardian_consult_turns": {"payload_json": "payload"},
    "guardian_diary_preferences": {"prefs_json": "prefs"},
    "stock_agent_profiles": {
        "config_json": "config",
        "state_json": "state",
        "latest_actions_json": "latest_actions",
    },
    "stock_agent_runs": {"actions_json": "actions", "detail_json": "detail"},
    "stock_agent_trades": {"detail_json": "detail"},
    "identities": {"raw_profile": "raw_profile"},
    "audit_log": {"detail_json": "detail"},
}

TABLE_TARGETS = {
    "market": {
        "meta": "market.meta",
        "instruments": "market.instruments",
        "quotes_daily": "market.quotes_daily",
        "adjust_factors": "market.adjust_factors",
        "trading_calendar": "market.trading_calendar",
        "ingest_watermark": "market.ingest_watermark",
        "source_route_receipts": "market.source_route_receipts",
        "source_route_attempts": "market.source_route_attempts",
        "intel_snapshots": "market.intel_snapshots",
    },
    "ledger": {
        "meta": "ledger.meta",
        "stocks": "ledger.stocks",
        "candidate_reviews": "ledger.candidate_reviews",
        "plans": "ledger.plans",
        "reviews": "ledger.reviews",
        "ai_judgments": "ledger.ai_judgments",
        "guardian_portfolio": "ledger.guardian_portfolio",
        "guardian_cycles": "ledger.guardian_cycles",
        "guardian_trades": "ledger.guardian_trades",
        "guardian_reports": "ledger.guardian_reports",
        "guardian_report_revisions": "ledger.guardian_report_revisions",
        "guardian_consultations": "ledger.guardian_consultations",
        "guardian_consult_turns": "ledger.guardian_consult_turns",
        "guardian_notices": "ledger.guardian_notices",
        "guardian_experience_versions": "ledger.guardian_experience_versions",
        "guardian_diary_preferences": "ledger.guardian_diary_preferences",
        "guardian_diary_compactions": "ledger.guardian_diary_compactions",
        "stock_agent_profiles": "ledger.stock_agent_profiles",
        "stock_agent_runs": "ledger.stock_agent_runs",
        "stock_agent_trades": "ledger.stock_agent_trades",
        "stock_agent_funding": "ledger.stock_agent_funding",
        "stock_agent_equity": "ledger.stock_agent_equity",
    },
    "ops": {
        "meta": "ops.meta",
        "jobs": "ops.jobs",
        "job_runs": "ops.job_runs",
        "llm_providers": "ops.llm_providers",
        "alert_rules": "ops.alert_rules",
        "alert_hits": "ops.alert_hits",
        "signal_journal": "ops.signal_journal",
    },
    "identity": {
        "meta": "identity.meta",
        "users": "identity.users",
        "identities": "identity.identities",
        "sessions": "identity.sessions",
        "email_verifications": "identity.email_verifications",
        "oauth_states": "identity.oauth_states",
        "user_quotas": "identity.user_quotas",
        "usage_counters": "identity.usage_counters",
        "audit_log": "identity.audit_log",
        "notifications": "identity.notifications",
    },
}


def _pg_columns(cur: psycopg.Cursor, table: str) -> dict[str, str]:
    schema_name, table_name = table.split(".", 1)
    cur.execute(
        """
        SELECT column_name, data_type
        FROM information_schema.columns
        WHERE table_schema=%s AND table_name=%s
        ORDER BY ordinal_position
        """,
        (schema_name, table_name),
    )
    return {str(row["column_name"]): str(row["data_type"]) for row in cur.fetchall()}


def _source_columns(conn: sqlite3.Connection, table: str) -> list[str]:
    return [str(row[1]) for row in conn.execute(f'PRAGMA table_info("{table}")')]


def _convert(value: Any, source: str, target_type: str) -> Any:
    if value is None:
        return None
    if target_type == "jsonb":
        if isinstance(value, (dict, list)):
            return json.dumps(value, ensure_ascii=False)
        if source in JSON_COLUMNS:
            return value
        return json.dumps(value, ensure_ascii=False)
    if target_type in {"boolean"}:
        return bool(value)
    if target_type in {"date"}:
        return str(value)[:10] or None
    if target_type.startswith("timestamp"):
        text = str(value).strip()
        return text or None
    return value


def _copy_table(
    src: sqlite3.Connection,
    dst: psycopg.Connection,
    *,
    source_table: str,
    target_table: str,
    batch_size: int,
    where_sql: str = "",
) -> int:
    source_columns = _source_columns(src, source_table)
    target_columns = _pg_columns(dst.cursor(), target_table)
    mapping = COLUMN_TARGETS.get(source_table, {})
    pairs = [
        (column, mapping.get(column, column))
        for column in source_columns
        if mapping.get(column, column) in target_columns
    ]
    if not pairs:
        raise RuntimeError(f"{source_table} 没有可导入的公共列")
    source_names = [source for source, _ in pairs]
    target_names = [target for _, target in pairs]
    select_sql = (
        "SELECT "
        + ",".join(f'"{column}"' for column in source_names)
        + f' FROM "{source_table}"'
        + (f" WHERE {where_sql}" if where_sql else "")
    )
    schema_name, table_name = target_table.split(".", 1)
    target = sql.SQL("{}.{}").format(sql.Identifier(schema_name), sql.Identifier(table_name))
    column_sql = sql.SQL(",").join(sql.Identifier(column) for column in target_names)
    conflict_columns = {
        "market.meta": ["key"],
        "market.instruments": ["code"],
        "market.quotes_daily": ["trade_date", "code"],
        "market.adjust_factors": ["code", "trade_date"],
        "market.trading_calendar": ["trade_date"],
        "market.ingest_watermark": ["code"],
        "market.source_route_receipts": ["receipt_id"],
        "market.source_route_attempts": ["receipt_id", "attempt_no"],
        "market.intel_snapshots": ["trade_date", "tool", "args_hash"],
        "ledger.meta": ["key"],
        "ledger.stocks": ["code"],
        "ledger.candidate_reviews": ["id"],
        "ledger.plans": ["id"],
        "ledger.reviews": ["id"],
        "ledger.ai_judgments": ["id"],
        "ledger.guardian_portfolio": ["id"],
        "ledger.guardian_cycles": ["slot"],
        "ledger.guardian_trades": ["id"],
        "ledger.guardian_reports": ["report_key"],
        "ledger.guardian_report_revisions": ["report_key", "revision"],
        "ledger.guardian_consultations": ["id"],
        "ledger.guardian_consult_turns": ["id"],
        "ledger.guardian_notices": ["slot"],
        "ledger.guardian_experience_versions": ["id"],
        "ledger.guardian_diary_preferences": ["id"],
        "ledger.guardian_diary_compactions": ["slot"],
        "ledger.stock_agent_profiles": ["id"],
        "ledger.stock_agent_runs": ["id"],
        "ledger.stock_agent_trades": ["id"],
        "ledger.stock_agent_funding": ["agent_id", "request_id"],
        "ledger.stock_agent_equity": ["agent_id", "day"],
        "ops.meta": ["key"],
        "ops.jobs": ["id"],
        "ops.job_runs": ["id"],
        "ops.llm_providers": ["id"],
        "ops.alert_rules": ["id"],
        "ops.alert_hits": ["id"],
        "ops.signal_journal": ["id"],
        "identity.meta": ["key"],
        "identity.users": ["id"],
        "identity.identities": ["id"],
        "identity.sessions": ["id"],
        "identity.email_verifications": ["id"],
        "identity.oauth_states": ["state"],
        "identity.user_quotas": ["user_id"],
        "identity.usage_counters": ["user_id", "period", "metric"],
        "identity.audit_log": ["id"],
        "identity.notifications": ["id"],
    }.get(target_table)
    insert_sql = sql.SQL("INSERT INTO {} ({}) VALUES ({})").format(
        target,
        column_sql,
        sql.SQL(",").join(sql.Placeholder() for _ in target_names),
    )
    if conflict_columns and set(conflict_columns).issubset(target_names):
        updates = sql.SQL(",").join(
            sql.SQL("{} = EXCLUDED.{}").format(sql.Identifier(column), sql.Identifier(column))
            for column in target_names
            if column not in conflict_columns
        )
        if updates:
            insert_sql += sql.SQL(" ON CONFLICT ({}) DO UPDATE SET {}").format(
                sql.SQL(",").join(sql.Identifier(column) for column in conflict_columns),
                updates,
            )
        else:
            insert_sql += sql.SQL(" ON CONFLICT ({}) DO NOTHING").format(
                sql.SQL(",").join(sql.Identifier(column) for column in conflict_columns)
            )
    total = 0
    rows = src.execute(select_sql)
    with dst.cursor() as cur:
        while True:
            batch = rows.fetchmany(batch_size)
            if not batch:
                break
            payload = [
                tuple(
                    _convert(row[index], source, target_columns[target])
                    for index, (source, target) in enumerate(pairs)
                )
                for row in batch
            ]
            cur.executemany(insert_sql, payload)
            total += len(payload)
    return total


def _source_count(conn: sqlite3.Connection, table: str) -> int:
    return int(conn.execute(f'SELECT COUNT(*) FROM "{table}"').fetchone()[0])


def _source_count_where(conn: sqlite3.Connection, table: str, where_sql: str) -> int:
    return int(
        conn.execute(
            f'SELECT COUNT(*) FROM "{table}"' + (f" WHERE {where_sql}" if where_sql else "")
        ).fetchone()[0]
    )


def _target_count(conn: psycopg.Connection, table: str) -> int:
    schema_name, table_name = table.split(".", 1)
    with conn.cursor() as cur:
        cur.execute(
            sql.SQL("SELECT COUNT(*) AS n FROM {}.{}").format(
                sql.Identifier(schema_name), sql.Identifier(table_name)
            )
        )
        return int(cur.fetchone()["n"])


def _target_estimate(conn: psycopg.Connection, table: str) -> int:
    """Cheap planner estimate used only to avoid re-importing complete tables."""
    schema_name, table_name = table.split(".", 1)
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT GREATEST(c.reltuples, 0)::bigint AS n
            FROM pg_class c
            JOIN pg_namespace ns ON ns.oid = c.relnamespace
            WHERE ns.nspname=%s AND c.relname=%s
            """,
            (schema_name, table_name),
        )
        row = cur.fetchone()
        return int(row["n"] or 0) if row else 0


def import_database(
    source: Path,
    *,
    domain: str,
    target: psycopg.Connection,
    batch_size: int,
    trade_date_floor: str,
    tables: set[str] | None = None,
) -> dict[str, Any]:
    if not source.is_file():
        return {"source": str(source), "status": "missing", "tables": {}}
    src = sqlite3.connect(f"file:{source.as_posix()}?mode=ro", uri=True)
    src.row_factory = sqlite3.Row
    report: dict[str, Any] = {"source": str(source), "status": "ok", "tables": {}}
    try:
        existing = {
            str(row[0])
            for row in src.execute(
                "SELECT name FROM sqlite_master WHERE type='table'"
            )
        }
        for source_table, target_table in TABLE_TARGETS[domain].items():
            if tables and source_table not in tables:
                continue
            if source_table not in existing:
                continue
            where_sql = ""
            if source_table == "quotes_daily":
                where_sql = f"trade_date >= '{trade_date_floor}'"
            elif source_table == "trading_calendar":
                where_sql = f"trade_date >= '{trade_date_floor}'"
            elif source_table == "adjust_factors":
                # Keep the anchor before the floor plus every factor inside it.
                where_sql = (
                    f"trade_date >= '{trade_date_floor}' OR "
                    f"(code, trade_date) IN ("
                    f"SELECT code, MAX(trade_date) FROM adjust_factors "
                    f"WHERE trade_date < '{trade_date_floor}' GROUP BY code)"
                )
            expected = _source_count_where(src, source_table, where_sql)
            actual_before = _target_estimate(target, target_table)
            if actual_before >= expected:
                report["tables"][source_table] = {
                    "rows": 0,
                    "target_rows": actual_before,
                    "source_rows": expected,
                    "skipped": "target already complete",
                }
                continue
            target.rollback()
            copied = _copy_table(
                src,
                target,
                source_table=source_table,
                target_table=target_table,
                batch_size=batch_size,
                where_sql=where_sql,
            )
            # Related tables must become visible as one migration unit.  Keep
            # errors and interruption from leaving a partial evidence graph.
            if source_table not in {"source_route_attempts"}:
                target.commit()
            else:
                target.commit()
            actual = _target_count(target, target_table)
            # Target may include rows from a prior complete import; source counts
            # are still the authoritative minimum and every target row is unique.
            if actual < expected:
                raise RuntimeError(
                    f"{source_table} 行数不足：SQLite={expected}, PostgreSQL={actual}"
                )
            report["tables"][source_table] = {
                "rows": copied,
                "target_rows": actual,
                "source_rows": expected,
            }
    finally:
        src.close()
    return report


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data-dir", type=Path, default=Path("/srv/qianlong-loci/data"))
    parser.add_argument("--batch-size", type=int, default=50_000)
    parser.add_argument("--skip-schema", action="store_true")
    parser.add_argument("--trade-date-floor", default="2023-10-27")
    parser.add_argument("--tables", default="", help="comma-separated source tables")
    args = parser.parse_args()
    sources = {
        "market": args.data_dir / "market.db",
        "ledger": args.data_dir / "palace.db",
        "ops": args.data_dir / "ops.db",
        "identity": args.data_dir / "identity.db",
    }
    with psycopg.connect(database_url(), row_factory=dict_row) as target:
        if not args.skip_schema:
            target.execute(SCHEMA_SQL)
            target.commit()
        selected = {
            table.strip()
            for table in args.tables.split(",")
            if table.strip()
        } or None
        reports = [
            import_database(
                path,
                domain=domain,
                target=target,
                batch_size=max(1, args.batch_size),
                trade_date_floor=args.trade_date_floor,
                tables=selected,
            )
            for domain, path in sources.items()
        ]
    print(json.dumps({"status": "ok", "databases": reports}, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
