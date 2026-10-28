"""quotes_daily 行数缓存：冻结基数 + 活动尾巴，由写入路径增量维护。

为什么不能每次 COUNT(*)：生产库 1,664 万行，COUNT 走 400 MB 的覆盖索引，
冷读一次 26～30 s（2026-09-04 线上实测）。上一版把缓存绑在 ``quotes_revision``
上，盘中每 5 分钟一次同步就让它失效——设置页、数据目录接口随之卡 30 s。

方案（``meta['quotes_daily_rows_v2'] = "{base_date}|{base_rows}"``）：

- ``base_rows`` = ``COUNT(*) WHERE trade_date < base_date``，**冻结**；
- 总行数 = ``base_rows`` + ``COUNT(*) WHERE trade_date >= base_date``：主键
  ``(trade_date, code)`` 前缀范围，尾巴只有最近一两个交易日（≈5k 行/日）；
    - 写入路径维护基数：落在基数区（``< base_date``）的行按主键探测写入前后是否存在，
  只有真正新增的才计入；热库裁窗按实际删掉的行数递减；批内出现更新的交易日就把
  冻结线推进到它（区间计数，便宜）；
- 只有没有缓存（首次 / 旧格式）时才全表 COUNT 一次。

所有函数只吃 sqlite3 连接或游标；写路径都跑在调用方的写事务里，这里不开事务。
"""
from __future__ import annotations

from collections.abc import Iterable, Iterator
from contextlib import contextmanager
import sqlite3
from typing import Any

ROW_COUNT_KEY = "quotes_daily_rows_v2"
_LEGACY_KEYS = ("quotes_daily_rows_v1",)
#: 热库重灌区间深入基数区超过这么多交易日（全量重建）就直接作废缓存：
#: 前后各扫一遍区间要读掉大半张表，不如让下一次 coverage 走覆盖索引重建一次。
REBUILD_INVALIDATE_DAYS = 30

Conn = sqlite3.Connection | sqlite3.Cursor


def _row_value(row: Any) -> Any:
    """Read the first selected value from sqlite3.Row or dict rows."""
    if row is None:
        return None
    if hasattr(row, "values"):
        return next(iter(row.values()))
    return row[0]


def read_base(conn: Conn) -> tuple[str, int] | None:
    """读冻结基数 ``(base_date, base_rows)``；缺失或格式不对视为无缓存。"""
    row = conn.execute("SELECT value FROM meta WHERE key = ?", (ROW_COUNT_KEY,)).fetchone()
    value = row["value"] if row and hasattr(row, "keys") else (row[0] if row else None)
    if not value:
        return None
    parts = str(value).split("|")
    if len(parts) != 2 or not parts[0]:
        return None
    try:
        return parts[0], int(parts[1])
    except ValueError:
        return None


def write_base(cursor: Conn, base_date: str, base_rows: int) -> None:
    cursor.execute(
        "INSERT INTO meta(key, value, updated_at) VALUES(?, ?, datetime('now'))"
        " ON CONFLICT(key) DO UPDATE SET value = excluded.value, updated_at = excluded.updated_at",
        (ROW_COUNT_KEY, f"{base_date}|{max(0, int(base_rows))}"),
    )


def invalidate(cursor: Conn) -> None:
    """作废缓存；下一次 ``quote_row_count`` 会全表 COUNT 重建。"""
    cursor.execute("DELETE FROM meta WHERE key = ?", (ROW_COUNT_KEY,))


def count_range(conn: Conn, start: str, end: str | None = None) -> int:
    """``[start, end)`` 区间行数；``end`` 为空即到末尾。走主键前缀，不碰覆盖索引。"""
    if end is None:
        row = conn.execute(
            "SELECT COUNT(*) FROM quotes_daily WHERE trade_date >= ?", (start,)
        ).fetchone()
    else:
        row = conn.execute(
            "SELECT COUNT(*) FROM quotes_daily WHERE trade_date >= ? AND trade_date < ?",
            (start, end),
        ).fetchone()
    value = _row_value(row)
    return int(value or 0)


def rebuild_quote_row_count(cursor: Conn, last_date: str | None = None) -> dict[str, int | str]:
    """用一次精确 COUNT 重建行数缓存，并返回可审计的前缀/尾巴计数。

    这是显式维护动作，不放进稳态读取路径：生产库执行它会完整扫描一次
    ``quotes_daily``。``last_date`` 为空时取库内最大交易日，避免调用方把
    非交易日写进冻结线。
    """
    date = str(last_date or "").strip()
    if not date:
        row = cursor.execute("SELECT MAX(trade_date) FROM quotes_daily").fetchone()
        date = str(_row_value(row) or "") if row else ""
    if not date:
        write_base(cursor, "1970-01-01", 0)
        return {"base_date": "1970-01-01", "base_rows": 0, "tail_rows": 0, "total_rows": 0}
    total_row = cursor.execute("SELECT COUNT(*) AS count FROM quotes_daily").fetchone()
    total = int(
        total_row["count"] if total_row and hasattr(total_row, "keys") else _row_value(total_row) or 0
    )
    tail = count_range(cursor, date)
    base_rows = total - tail
    if base_rows < 0:
        raise RuntimeError(f"quotes_daily 行数缓存重建得到负前缀：total={total}, tail={tail}")
    write_base(cursor, date, base_rows)
    return {
        "base_date": date,
        "base_rows": base_rows,
        "tail_rows": tail,
        "total_rows": total,
    }


def advance_base(cursor: Conn, new_date: str) -> None:
    """出现更新的交易日时把冻结线推到 ``new_date``：基数加上 ``[旧线, 新线)`` 的行数。"""
    base = read_base(cursor)
    if base is None or not new_date or new_date <= base[0]:
        return
    write_base(cursor, new_date, base[1] + count_range(cursor, base[0], new_date))


def quote_row_count(store: Any, last_date: str) -> int:
    """quotes_daily 总行数。无缓存时全表 COUNT 一次，并把冻结线放在 ``last_date``。

    ``store`` 需有 ``conn`` 与 ``_transaction()``（即 ``MarketStore``）。稳态下
    只读：基数一行 meta + 尾巴一次主键范围计数，不开写事务。
    """
    base = read_base(store.conn)
    if base is None:
        with store._transaction() as cursor:
            base = read_base(cursor)
            if base is None:
                for key in _LEGACY_KEYS:
                    cursor.execute("DELETE FROM meta WHERE key = ?", (key,))
                rebuilt = rebuild_quote_row_count(cursor, last_date)
                return int(rebuilt["total_rows"])
    base_date, base_rows = base
    return base_rows + count_range(store.conn, base_date)


#: 一条探测 SQL 里最多塞几对 (trade_date, code)。SQLite 变量上限 32766，每对占
#: 两个；留足余量的同时避免超长 SQL 反复重编译。
_PROBE_CHUNK = 400


def _count_existing(cursor: Conn, pairs: list[tuple[str, str]]) -> int:
    """这批主键里已经在库的行数。

    原来是逐对 ``SELECT 1``：一票 250 个交易日的历史回填就是 250 次往返，实测
    每票 0.56 ms，全市场 5500 票 3 s 全花在 sqlite 调用开销上。改成把这批主键当
    ``VALUES`` 临时表 JOIN 主键索引，往返数降到 ``对数 / 400``。
    """
    total = 0
    for start in range(0, len(pairs), _PROBE_CHUNK):
        chunk = pairs[start : start + _PROBE_CHUNK]
        row = cursor.execute(
            "WITH probe(trade_date, code) AS (VALUES "
            + ",".join("(?,?)" for _ in chunk)
            + ") SELECT COUNT(*) FROM probe JOIN quotes_daily USING (trade_date, code)",
            [value for pair in chunk for value in pair],
        ).fetchone()
        total += int(_row_value(row) or 0)
    return total


@contextmanager
def track_quote_upsert(
    cursor: sqlite3.Cursor, payload: Iterable[tuple[Any, ...]]
) -> Iterator[None]:
    """包住 ``INSERT ... ON CONFLICT DO UPDATE``（行首两列为 trade_date, code）。

    同一批内去重；基数区有尚不存在的键时，在写入前后各探测一次，按实际新增数
    记入基数。这样 SQLite 触发器忽略的插入不会被误记。没有缓存时什么都不做。
    """
    base = read_base(cursor)
    if base is None:
        yield
        return
    base_date, base_rows = base
    pairs = {(str(row[0]), str(row[1])) for row in payload}
    if not pairs:
        yield
        return
    below = [pair for pair in pairs if pair[0] < base_date]
    existing_before = _count_existing(cursor, below) if below else 0
    yield
    added = (_count_existing(cursor, below) - existing_before
             if existing_before < len(below) else 0)
    if added:
        write_base(cursor, base_date, base_rows + added)
    advance_base(cursor, max(pair[0] for pair in pairs))


def note_trim_below(cursor: Conn, keep_from: str) -> None:
    """热库裁窗（``DELETE ... WHERE trade_date < keep_from``）**之前**调用。

    即将删掉的行里落在基数区的那部分先从基数扣掉；落在尾巴里的不用管（尾巴活算）。
    """
    base = read_base(cursor)
    if base is None or not keep_from:
        return
    cut = min(keep_from, base[0])
    doomed = cursor.execute(
        "SELECT COUNT(*) AS count FROM quotes_daily WHERE trade_date < ?", (cut,)
    ).fetchone()
    doomed = doomed["count"] if doomed and hasattr(doomed, "keys") else _row_value(doomed)
    if doomed:
        write_base(cursor, base[0], base[1] - int(doomed))


@contextmanager
def track_hot_window_rewrite(cursor: sqlite3.Cursor, start_date: str) -> Iterator[None]:
    """包住热库「删 ``[start_date, ∞)`` 再从全量库重灌」。

    只动尾巴：基数不变。深入基数区不多（增量镜像）：按区间前后差修正基数。
    深入太多（全量重建）：直接作废，下一次 coverage 重建。退出时把冻结线推到
    热库新末日。
    """
    base = read_base(cursor)
    if base is None:
        yield
        return
    base_date, base_rows = base
    if start_date >= base_date:
        yield
    else:
        days_row = cursor.execute(
            "SELECT COUNT(*) AS count FROM trading_calendar WHERE trade_date >= ? AND trade_date < ?",
            (start_date, base_date),
        ).fetchone()
        days = days_row["count"] if days_row and hasattr(days_row, "keys") else _row_value(days_row)
        if int(days or 0) > REBUILD_INVALIDATE_DAYS:
            invalidate(cursor)
            yield
            return
        before = count_range(cursor, start_date, base_date)
        yield
        after = count_range(cursor, start_date, base_date)
        write_base(cursor, base_date, base_rows + after - before)
    row = cursor.execute("SELECT MAX(trade_date) FROM quotes_daily").fetchone()
    value = _row_value(row) if row else ""
    advance_base(cursor, str(value or ""))
