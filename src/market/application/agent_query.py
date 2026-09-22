"""供独立研究使用的原始行情只读查询，不含战法、候选池或账户数据。"""
from __future__ import annotations

import sqlite3
import time
from contextlib import closing
from datetime import date
from pathlib import Path
from typing import Callable

from src.shared.paths import market_db

VIEWS = {
    "daily_prices": ("quotes_daily", "trade_date"),
    "securities": ("instruments", None),
    "calendar": ("trading_calendar", "trade_date"),
    "adjustments": ("adjust_factors", "trade_date"),
}
SAFE_FUNCTIONS = frozenset("abs avg ceil ceiling coalesce concat concat_ws count cume_dist date datetime dense_rank exp first_value floor format glob group_concat hex ifnull iif instr json json_array json_array_length json_extract json_group_array json_group_object json_object json_quote json_type json_valid julianday lag last_value lead length like ln log log10 log2 lower ltrim max min mod nth_value ntile nullif percent_rank pi pow power printf rank replace round row_number rtrim sign sqrt strftime substr substring sum time total trim trunc typeof unicode unixepoch upper".split())


def query_agent_market(*, sql: str = "", cutoff: str, limit: int = 200, offset: int = 0,
                       path: str | Path | None = None, checkpoint: Callable[[], None] | None = None,
                       deadline: float | None = None) -> dict:
    """SQL可自由比较、聚合和窗口计算；分页不限制研究总量，历史视图不能越过截止日。"""
    cutoff = date.fromisoformat(cutoff).isoformat()
    if not 1 <= limit <= 1000 or offset < 0:
        raise ValueError("每页1—1000行，offset不能为负；通过next_offset继续查询")
    target = Path(path or market_db()).resolve()
    if not target.is_file():
        raise ValueError("本地原始行情库尚未就绪，请使用公开行情工具")

    def check() -> None:
        if checkpoint:
            checkpoint()
        if deadline is not None and time.monotonic() >= deadline:
            raise TimeoutError("行情查询已超过本轮时间预算")

    check()
    with closing(sqlite3.connect(target.as_uri() + "?mode=ro", uri=True, timeout=5)) as conn:
        conn.row_factory = sqlite3.Row
        schemas = {}
        for view, (table, day_field) in VIEWS.items():
            fields = conn.execute(f'PRAGMA table_info("{table}")').fetchall()
            if not fields:
                continue
            condition = f" WHERE {day_field} <= '{cutoff}'" if day_field else ""
            conn.execute(f'CREATE TEMP VIEW "{view}" AS SELECT * FROM main."{table}"{condition}')
            schemas[view] = {row["name"]: row["type"] for row in fields}
        conn.execute("PRAGMA query_only=ON")
        meta = {"source": "market.db / 原始未复权行情", "cutoff": cutoff,
                "note": "日线/复权因子按截止日隔离。证券名称、行业与状态为最新元数据，非历史时点快照；不推定复盘当时已知。", "schemas": schemas}
        if not sql.strip():
            return meta
        if len(sql) > 100000:
            raise ValueError("SQL过长，请拆分查询")

        def authorize(action, arg1, arg2, database, origin):
            if action in (sqlite3.SQLITE_SELECT, sqlite3.SQLITE_RECURSIVE):
                return sqlite3.SQLITE_OK
            if action == sqlite3.SQLITE_FUNCTION:
                return sqlite3.SQLITE_OK if str(arg2 or "").lower() in SAFE_FUNCTIONS else sqlite3.SQLITE_DENY
            if action == sqlite3.SQLITE_READ:
                if database == "temp" and arg1 in schemas:
                    return sqlite3.SQLITE_OK
                if origin in schemas and database == "main" and arg1 == VIEWS[origin][0]:
                    return sqlite3.SQLITE_OK
            return sqlite3.SQLITE_DENY

        stopped = []
        def progress():
            try:
                check()
                return 0
            except Exception as exc:
                stopped.append(exc)
                return 1

        conn.set_authorizer(authorize)
        conn.set_progress_handler(progress, 5000)
        statement = sql.strip().removesuffix(";")
        try:
            cursor = conn.execute(f"SELECT * FROM ({statement}) LIMIT ? OFFSET ?", (limit + 1, offset))
            rows = [dict(row) for row in cursor.fetchall()]
        except sqlite3.Error as exc:
            if stopped:
                raise stopped[0] from exc
            raise ValueError(f"只读行情查询失败：{exc}。仅可查询公开的视图，不能直接访问原表或其他数据库。") from exc
        check()
        return {**meta, "rows": rows[:limit], "offset": offset,
                "next_offset": offset + limit if len(rows) > limit else None}
