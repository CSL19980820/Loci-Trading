"""Polars 只读面板旁路。

这是性能 POC，不改变 ``market.db`` schema、权威 DTO 或 palace.db。
只有 ``LOCI_MARKET_POLARS=1`` 时尝试启用；Polars 未安装、版本不兼容或
查询失败时返回 ``None``，调用方继续使用 pandas/DuckDB。
"""
from __future__ import annotations

import os
import sqlite3
from collections.abc import Sequence
from typing import Any

import pandas as pd


def _to_pandas(frame: Any) -> pd.DataFrame:
    """转回既有边界类型，不要求额外的 pyarrow 可选依赖。"""
    return pd.DataFrame(frame.to_dicts())


def polars_panel_enabled() -> bool:
    raw = (os.environ.get("LOCI_MARKET_POLARS") or "").strip().lower()
    return raw in {"1", "true", "yes", "on"}


def polars_available() -> bool:
    try:
        import polars  # noqa: F401
    except (ImportError, OSError):
        return False
    return True


def read_quotes_flat_polars(
    conn: sqlite3.Connection,
    *,
    columns_sql: str,
    where_sql: str,
    params: Sequence[Any],
) -> pd.DataFrame | None:
    """用 Polars 只读读取 ``quotes_daily``，返回现有 pandas 边界类型。

    ``read_database`` 在不同 Polars 版本的参数名略有差异，因此 POC 只在
    当前调用成功时采用；任何可预期兼容性错误都交给 store_panel 回退。
    """
    try:
        import polars as pl
    except (ImportError, OSError):
        return None

    sql = f"SELECT {columns_sql} FROM quotes_daily WHERE 1=1{where_sql}"
    try:
        frame = pl.read_database(
            query=sql,
            connection=conn,
            execute_options={"parameters": list(params)},
        )
        return _to_pandas(frame)
    except (
        AttributeError,
        ImportError,
        OSError,
        RuntimeError,
        TypeError,
        ValueError,
        sqlite3.Error,
    ):
        # 老版本 Polars 对 sqlite3 参数绑定支持不一致；仍用同一只读查询
        # 构造 Polars frame，避免把可选 POC 变成安装版本的硬门槛。
        try:
            cursor = conn.execute(sql, tuple(params))
            rows = [tuple(row) for row in cursor.fetchall()]
            names = [str(item[0]) for item in (cursor.description or ())]
            frame = pl.DataFrame(rows, schema=names, orient="row")
            return _to_pandas(frame)
        except (
            AttributeError,
            ImportError,
            OSError,
            RuntimeError,
            TypeError,
            ValueError,
            sqlite3.Error,
        ):
            return None


__all__ = [
    "polars_available",
    "polars_panel_enabled",
    "read_quotes_flat_polars",
]
