"""Copy selected SQLite tables into existing PostgreSQL tables atomically.

Usage: run on the production host after both databases are quiescent.  The
entire destination table is replaced in one PostgreSQL transaction; a failed
copy leaves the previous table contents intact.  Column names must match; JSON
text is cast to jsonb where the destination type requires it.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import sqlite3
import sys

import psycopg
from psycopg import sql

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.shared.postgres import database_url


def _columns(conn: sqlite3.Connection, table: str) -> list[str]:
    return [str(row[1]) for row in conn.execute(f'PRAGMA table_info("{table}")')]


def copy_table(
    src: sqlite3.Connection,
    dst: psycopg.Connection,
    *,
    source_table: str,
    schema: str,
    target_table: str,
    where_sql: str = "",
) -> dict[str, object]:
    columns = _columns(src, source_table)
    with dst.cursor() as cur:
        cur.execute(
            """
            SELECT column_name, data_type, udt_name
            FROM information_schema.columns
            WHERE table_schema=%s AND table_name=%s
            """,
            (schema, target_table),
        )
        target = {str(row[0]): row for row in cur.fetchall()}
    missing = [column for column in columns if column not in target]
    if missing:
        raise RuntimeError(
            f"{schema}.{target_table} 缺少 SQLite 列：{missing[:8]}"
        )
    select_sql = (
        "SELECT "
        + ",".join(f'"{column}"' for column in columns)
        + f' FROM "{source_table}"'
        + (f" WHERE {where_sql}" if where_sql else "")
    )
    rows = src.execute(select_sql)
    target_ident = sql.Identifier(schema, target_table)
    column_ident = sql.SQL(",").join(sql.Identifier(column) for column in columns)
    with dst.cursor() as cur:
        cur.execute(sql.SQL("TRUNCATE {} CASCADE").format(target_ident))
        with cur.copy(
            sql.SQL("COPY {} ({}) FROM STDIN").format(target_ident, column_ident)
        ) as copy:
            while batch := rows.fetchmany(20_000):
                for row in batch:
                    copy.write_row(
                        tuple(
                            None
                            if value == ""
                            and (
                                str(target[column][1]).startswith("timestamp")
                                or target[column][1] == "date"
                            )
                            else (
                                json.dumps(value, ensure_ascii=False)
                                if target[column][2] == "jsonb"
                                and not isinstance(value, (str, bytes, type(None)))
                                else value
                            )
                            for column, value in zip(columns, row, strict=True)
                        )
                    )
        cur.execute(
            sql.SQL("SELECT COUNT(*) AS n FROM {}").format(target_ident)
        )
        count = int(cur.fetchone()[0])
    expected = int(
        src.execute(
            f'SELECT COUNT(*) FROM "{source_table}"'
            + (f" WHERE {where_sql}" if where_sql else "")
        ).fetchone()[0]
    )
    if count != expected:
        raise RuntimeError(
            f"{source_table} 原子拷贝行数不符：SQLite={expected}, PostgreSQL={count}"
        )
    return {"source_rows": expected, "target_rows": count}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data-root", type=Path, default=Path("/srv/qianlong-loci/data"))
    parser.add_argument("--domain", choices=("market", "ledger", "ops", "identity"), required=True)
    parser.add_argument("--table", action="append", required=True)
    parser.add_argument("--trade-date-floor", default="2023-10-27")
    args = parser.parse_args()
    source_name = {
        "market": "market.db",
        "ledger": "palace.db",
        "ops": "ops.db",
        "identity": "identity.db",
    }[args.domain]
    src = sqlite3.connect(
        f"file:{(args.data_root / source_name).as_posix()}?mode=ro",
        uri=True,
    )
    reports = {}
    with psycopg.connect(database_url()) as dst:
        for table in args.table:
            where_sql = ""
            if args.domain == "market" and table in {"quotes_daily", "trading_calendar"}:
                where_sql = f"trade_date >= '{args.trade_date_floor}'"
            reports[table] = copy_table(
                src,
                dst,
                source_table=table,
                schema=args.domain,
                target_table=table,
                where_sql=where_sql,
            )
            dst.commit()
    print(json.dumps({"status": "ok", "domain": args.domain, "tables": reports}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
