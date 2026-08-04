"""DuckDB 只读面板加速旁路（可关；失败回退 pandas/SQLite）。

权威数据仍在 market.db 的 quotes_daily；本模块不写 palace，也不改 SQLite DDL。
开关：环境变量 ``LOCI_MARKET_DUCKDB=1``（或 true/yes/on）。
"""
from __future__ import annotations

import os
import sqlite3
from collections.abc import Sequence
from typing import Any

import pandas as pd


def duckdb_panel_enabled() -> bool:
    raw = (os.environ.get("LOCI_MARKET_DUCKDB") or "").strip().lower()
    return raw in {"1", "true", "yes", "on"}


def read_quotes_flat_duckdb(
    conn: sqlite3.Connection,
    *,
    columns_sql: str,
    where_sql: str,
    params: Sequence[Any],
) -> pd.DataFrame | None:
    """用 DuckDB 经 sqlite_scanner 只读查询 quotes_daily。

    返回 DataFrame；不可用时返回 None（调用方回退 ``pd.read_sql_query``）。
    """
    try:
        import duckdb
    except ImportError:
        return None

    db_path = _sqlite_file_path(conn)
    if not db_path:
        return None

    try:
        duck = duckdb.connect(database=":memory:")
        try:
            # DuckDB sqlite 扩展：只读挂载用户 market.db
            duck.execute(f"ATTACH '{_escape_path(db_path)}' AS m (TYPE SQLITE, READ_ONLY)")
            sql = f"SELECT {columns_sql} FROM m.quotes_daily WHERE 1=1{where_sql}"
            return duck.execute(sql, list(params)).df()
        finally:
            duck.close()
    except Exception:
        return None


def _sqlite_file_path(conn: sqlite3.Connection) -> str | None:
    try:
        rows = conn.execute("PRAGMA database_list").fetchall()
    except sqlite3.Error:
        return None
    for row in rows:
        # row: (seq, name, file)
        name = str(row[1] if not isinstance(row, sqlite3.Row) else row["name"])
        path = str(row[2] if not isinstance(row, sqlite3.Row) else row["file"])
        if name == "main" and path:
            return path
    return None


def _escape_path(path: str) -> str:
    return path.replace("'", "''")
