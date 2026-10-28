"""Rebuild the online PostgreSQL schemas from the frozen SQLite source.

This is the cutover command, not a long-lived dual-write path.  It preserves
the existing table/column contract, copies data through PostgreSQL ``COPY`` in
one transaction per table, and builds indexes only after loading.
"""
from __future__ import annotations

import argparse
from datetime import date, timedelta
import json
from pathlib import Path
import re
import sqlite3
import sys
from typing import Any

import psycopg
from psycopg import sql

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.shared.postgres import database_url, translate_sql


DOMAIN_FILES = {
    "market": "market.db",
    "ledger": "palace.db",
    "ops": "ops.db",
    "identity": "identity.db",
}

TABLE_ORDER = {
    "market": [
        "meta",
        "instruments",
        "quotes_daily",
        "adjust_factors",
        "trading_calendar",
        "ingest_watermark",
        "source_route_receipts",
        "source_route_attempts",
        "intel_snapshots",
    ],
    "ledger": [
        "meta",
        "stocks",
        "candidate_reviews",
        "plans",
        "reviews",
        "ai_judgments",
        "guardian_portfolio",
        "guardian_cycles",
        "guardian_trades",
        "guardian_reports",
        "guardian_report_revisions",
        "guardian_consultations",
        "guardian_consult_turns",
        "guardian_notices",
        "guardian_experience_versions",
        "guardian_diary_preferences",
        "guardian_diary_compactions",
        "stock_agent_profiles",
        "stock_agent_runs",
        "stock_agent_trades",
        "stock_agent_funding",
        "stock_agent_equity",
    ],
    "ops": [
        "meta",
        "jobs",
        "job_runs",
        "llm_providers",
        "alert_rules",
        "alert_hits",
        "ai_sessions",
        "ai_messages",
        "ai_agent_runs",
        "ai_agent_events",
        "ai_assistant_profile",
        "ai_decisions",
        "ai_execution_grants",
        "ai_memories",
        "ai_usage_daily",
        "leader_role_snapshots",
        "mcp_quota",
        "signal_journal",
        "signal_rule_config",
        "strategy_backtests",
        "strategy_docs",
        "strategy_versions",
    ],
    "identity": [
        "meta",
        "users",
        "identities",
        "sessions",
        "email_verifications",
        "oauth_states",
        "user_quotas",
        "usage_counters",
        "audit_log",
        "notifications",
    ],
}


def _translate_ddl(raw: str) -> str:
    ddl = str(raw)
    ddl = re.sub(r"\bWITHOUT\s+ROWID\b", "", ddl, flags=re.I)
    ddl = re.sub(
        r"\bINTEGER\s+PRIMARY\s+KEY\s+AUTOINCREMENT\b",
        "BIGSERIAL PRIMARY KEY",
        ddl,
        flags=re.I,
    )
    ddl = re.sub(r"\bAUTOINCREMENT\b", "", ddl, flags=re.I)
    ddl = re.sub(r"\bBLOB\b", "BYTEA", ddl, flags=re.I)
    ddl = re.sub(r"\bREAL\b", "DOUBLE PRECISION", ddl, flags=re.I)
    return ddl.strip()


def _objects(
    source: sqlite3.Connection, kind: str
) -> list[tuple[str, str]]:
    return [
        (str(name), _translate_ddl(str(ddl)))
        for name, ddl in source.execute(
            "SELECT name, sql FROM sqlite_master "
            "WHERE type=? AND sql IS NOT NULL ORDER BY name",
            (kind,),
        )
        # SQLite's internal sequence table is represented by PostgreSQL identity
        # columns and must not be copied as a business table.
        if not str(name).startswith("sqlite_")
    ]


def _columns(source: sqlite3.Connection, table: str) -> list[str]:
    return [str(row[1]) for row in source.execute(f'PRAGMA table_info("{table}")')]


def _where_for(
    domain: str,
    table: str,
    *,
    trade_date_floor: str,
    evidence_floor: str,
    ops_floor: str,
) -> str:
    if domain == "market":
        if table in {"quotes_daily", "trading_calendar", "intel_snapshots"}:
            return f"trade_date >= '{trade_date_floor}'"
        if table == "adjust_factors":
            return (
                f"trade_date >= '{trade_date_floor}' OR "
                "(code, trade_date) IN ("
                "SELECT code, MAX(trade_date) FROM adjust_factors "
                f"WHERE trade_date < '{trade_date_floor}' GROUP BY code)"
            )
        if table == "source_route_receipts":
            return f"generated_at >= '{evidence_floor}'"
        if table == "source_route_attempts":
            return (
                "receipt_id IN (SELECT receipt_id FROM source_route_receipts "
                f"WHERE generated_at >= '{evidence_floor}')"
            )
    if domain == "ops" and table == "job_runs":
        return f"started_at >= '{ops_floor}'"
    return ""


def _copy_table(
    source: sqlite3.Connection,
    target: psycopg.Connection,
    *,
    domain: str,
    table: str,
    where_sql: str,
) -> dict[str, Any]:
    columns = _columns(source, table)
    select_sql = (
        "SELECT "
        + ",".join(f'"{column}"' for column in columns)
        + f' FROM "{table}"'
        + (f" WHERE {where_sql}" if where_sql else "")
    )
    rows = source.execute(select_sql)
    table_name = sql.Identifier(domain, table)
    column_list = sql.SQL(",").join(sql.Identifier(column) for column in columns)
    seen = 0
    with target.cursor() as cur:
        with cur.copy(
            sql.SQL("COPY {} ({}) FROM STDIN").format(table_name, column_list)
        ) as copy:
            while batch := rows.fetchmany(20_000):
                for row in batch:
                    copy.write_row(tuple(row))
                    seen += 1
        cur.execute(sql.SQL("SELECT COUNT(*) AS n FROM {}").format(table_name))
        actual = int(cur.fetchone()[0])
    expected = int(
        source.execute(
            f'SELECT COUNT(*) FROM "{table}"'
            + (f" WHERE {where_sql}" if where_sql else "")
        ).fetchone()[0]
    )
    if seen != expected or actual != expected:
        raise RuntimeError(
            f"{domain}.{table} 行数不符：source={expected}, copied={seen}, target={actual}"
        )
    return {"rows": actual}


def bootstrap(
    data_root: Path,
    *,
    reset: bool,
    trade_date_floor: str,
    evidence_keep_days: int,
    ops_keep_days: int,
) -> dict[str, Any]:
    today = date.today()
    evidence_floor = str(today - timedelta(days=max(1, evidence_keep_days)))
    ops_floor = str(today - timedelta(days=max(1, ops_keep_days)))
    report: dict[str, Any] = {
        "status": "ok",
        "postgresql": None,
        "trade_date_floor": trade_date_floor,
        "evidence_floor": evidence_floor,
        "ops_floor": ops_floor,
        "domains": {},
    }
    connections: dict[str, sqlite3.Connection] = {}
    for domain, filename in DOMAIN_FILES.items():
        path = data_root / filename
        if not path.is_file():
            raise FileNotFoundError(path)
        connections[domain] = sqlite3.connect(
            f"file:{path.as_posix()}?mode=ro",
            uri=True,
        )
    try:
        with psycopg.connect(database_url(), autocommit=False) as target:
            with target.cursor() as cur:
                cur.execute("SELECT version() AS version")
                report["postgresql"] = str(cur.fetchone()[0])
            for domain, source in connections.items():
                with target.cursor() as cur:
                    if reset:
                        cur.execute(sql.SQL("DROP SCHEMA IF EXISTS {} CASCADE").format(sql.Identifier(domain)))
                    cur.execute(sql.SQL("CREATE SCHEMA IF NOT EXISTS {}").format(sql.Identifier(domain)))
                target.commit()
                tables = _objects(source, "table")
                indexes = _objects(source, "index")
                priority = {
                    name: index for index, name in enumerate(TABLE_ORDER.get(domain, []))
                }
                tables.sort(key=lambda item: (priority.get(item[0], 10_000), item[0]))
                with target.cursor() as cur:
                    cur.execute(sql.SQL("SET LOCAL search_path TO {}, public").format(sql.Identifier(domain)))
                    for _, ddl in tables:
                        cur.execute(translate_sql(ddl))
                target.commit()
                table_report: dict[str, Any] = {}
                for table, _ in tables:
                    where_sql = _where_for(
                        domain,
                        table,
                        trade_date_floor=trade_date_floor,
                        evidence_floor=evidence_floor,
                        ops_floor=ops_floor,
                    )
                    table_report[table] = _copy_table(
                        source,
                        target,
                        domain=domain,
                        table=table,
                        where_sql=where_sql,
                    )
                    target.commit()
                with target.cursor() as cur:
                    cur.execute(sql.SQL("SET LOCAL search_path TO {}, public").format(sql.Identifier(domain)))
                    for _, ddl in indexes:
                        try:
                            cur.execute(translate_sql(ddl))
                        except psycopg.errors.DuplicateTable:
                            target.rollback()
                            cur.execute(sql.SQL("SET LOCAL search_path TO {}, public").format(sql.Identifier(domain)))
                target.commit()
                with target.cursor() as cur:
                    cur.execute("ANALYZE")
                target.commit()
                report["domains"][domain] = {
                    "tables": len(tables),
                    "indexes": len(indexes),
                    "copied": table_report,
                }
    finally:
        for source in connections.values():
            source.close()
    return report


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data-root", type=Path, default=Path("/srv/qianlong-loci/data"))
    parser.add_argument("--reset", action="store_true")
    parser.add_argument("--trade-date-floor", default="2023-10-27")
    parser.add_argument("--evidence-keep-days", type=int, default=30)
    parser.add_argument("--ops-keep-days", type=int, default=30)
    args = parser.parse_args()
    result = bootstrap(
        args.data_root,
        reset=args.reset,
        trade_date_floor=args.trade_date_floor,
        evidence_keep_days=args.evidence_keep_days,
        ops_keep_days=args.ops_keep_days,
    )
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
