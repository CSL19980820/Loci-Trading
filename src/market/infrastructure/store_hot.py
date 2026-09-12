"""滚动热读库：近 N 交易日的行情窗口镜像，供选股/行情面板只读。

设计动机（治本，而非治标）：
- 全量库被同步写锁 + 千万行扫描 → 尾盘选股 disk I/O error。
- 热库与全量库物理隔离：选股只读热库，同步只写全量库，两者永不同文件，
  锁竞争从结构上消失；热库体量 ≈ 全量 1/10，即使全量扫描也快得多。
- 热库是「可重建派生缓存」：日 K 历史不可变，损坏时删掉重建即可，零双真相。

约定：
- 热库 schema = 完整 schema（MarketStore 复用），数据只保留近 N 交易日窗口。
- 增量镜像（mirror_recent_to_hot）：同步任务完成后把最近若干交易日补进热库。
- 全量重建（mirror_to_hot）：启动/热库损坏/手动时清空热库并重灌窗口。
- 回执表只保留与窗口内日 K 关联的行，孤儿回执随清理删除（热库不做失败取证）。
"""
from __future__ import annotations

from collections.abc import Iterator
from contextlib import ExitStack, contextmanager
import logging
from pathlib import Path
import sqlite3

from src.market.infrastructure.store import MarketStore
from src.market.infrastructure.store_row_count import note_trim_below, track_hot_window_rewrite
from src.shared.paths import market_hot_db as _default_hot_db

logger = logging.getLogger(__name__)

#: 热库保留的交易日窗口（≈2.8 年）。覆盖 MA250 与常规选股/面板/复盘窗口。
HOT_WINDOW_TRADING_DAYS = 700

#: 增量镜像的缓冲交易日数：热库当前末日往后再回补几天，防止
#: 热库末日对应非交易日时漏掉缺口。
MIRROR_BUFFER_TRADING_DAYS = 6

#: SQLite IN 分片（同 store_provenance）
_SQL_IN_CHUNK = 900


def open_market_hot(hot_db: str | None = None) -> MarketStore:
    """打开热库；路径默认 ``data_dir()/market_hot.db``。"""
    # 热库必须留 idx_quotes_receipt：_purge_orphan_receipts 的 NOT EXISTS 靠它逐行探测。
    return MarketStore(Path(hot_db) if hot_db else _default_hot_db(), keep_receipt_index=True)


def _window_start(full: MarketStore, window_trading_days: int) -> str:
    days = full.trading_days()
    if not days:
        return ""
    if window_trading_days >= len(days):
        return days[0]
    return days[len(days) - window_trading_days]


def _hot_cutoff(full: MarketStore, hot: MarketStore, buffer_days: int) -> str:
    """增量起点：热库当前末日回退 buffer 交易日；热库空则从窗口起点开始。"""
    hot_max = hot.conn.execute("SELECT MAX(trade_date) FROM quotes_daily").fetchone()[0]
    if not hot_max:
        return _window_start(full, HOT_WINDOW_TRADING_DAYS)
    days = full.trading_days(end=hot_max)
    if not days:
        return hot_max
    if len(days) <= buffer_days:
        return days[0]
    return days[len(days) - buffer_days - 1]


def _meta_value(store: MarketStore, key: str) -> str:
    row = store.conn.execute("SELECT value FROM meta WHERE key = ?", (key,)).fetchone()
    return str(row["value"]) if row and row["value"] is not None else ""


def _copy_small_tables(full: MarketStore, hot: MarketStore, *, force: bool = False) -> None:
    """全量复制 instruments / adjust_factors（均为小表；adjust_factors 只含除权日）。

    增量镜像每次选股都会调到这里，而这两张表绝大多数时候没变——无条件
    ``DELETE`` + 整表重灌会把一次写事务压进交互路径。用 ``*_revision``
    （由 ``store_rw._bump_revisions`` 维护）做脏检查：与上次镜像时相同就跳过。
    源库没有 revision（老库从未 bump 过）时保守地照旧复制。

    ``force=True`` 供 ``mirror_to_hot`` 的全量重建使用：那是文档承诺的「热库损坏
    时重跑即可」修复路径，不能因为标记还在就跳过复制。
    """
    for table in ("instruments", "adjust_factors"):
        revision = _meta_value(full, f"{table}_revision")
        mirrored_key = f"mirrored_{table}_revision"
        if not force and revision and revision == _meta_value(hot, mirrored_key):
            continue
        cols = [str(row[1]) for row in full.conn.execute(f"PRAGMA table_info({table})")]
        rows = full.conn.execute(f"SELECT * FROM {table}").fetchall()
        with hot._transaction() as cursor:
            cursor.execute(f"DELETE FROM {table}")
            if rows:
                placeholders = ",".join("?" for _ in cols)
                cursor.executemany(
                    f"INSERT INTO {table}({','.join(cols)}) VALUES({placeholders})",
                    [tuple(row) for row in rows],
                )
            cursor.execute(
                "INSERT INTO meta(key, value, updated_at)"
                " VALUES(?, ?, datetime('now'))"
                " ON CONFLICT(key) DO UPDATE SET value = excluded.value,"
                " updated_at = excluded.updated_at",
                (mirrored_key, revision),
            )


def _purge_orphan_receipts(cursor: sqlite3.Cursor) -> None:
    """删掉热库里已经没有日 K 指向的回执及其 attempts。

    用 NOT EXISTS 而不是 NOT IN：后者每次都要把 quotes_daily 的 receipt_id
    整列去重物化一遍（热库约 700 交易日 × 5500 只 ≈ 385 万行），而且这段跑在
    写事务里；NOT EXISTS 是逐行走 idx_quotes_receipt 探测。
    """
    cursor.execute(
        "DELETE FROM source_route_receipts WHERE NOT EXISTS ("
        " SELECT 1 FROM quotes_daily q"
        " WHERE q.receipt_id = source_route_receipts.receipt_id)"
    )
    cursor.execute(
        "DELETE FROM source_route_attempts WHERE NOT EXISTS ("
        " SELECT 1 FROM source_route_receipts r"
        " WHERE r.receipt_id = source_route_attempts.receipt_id)"
    )


def _trim_hot_before(hot: MarketStore, keep_from: str) -> None:
    """删除热库中 ``trade_date < keep_from`` 的日 K / 日历，并清理孤儿回执。"""
    if not keep_from:
        return
    with hot._transaction() as cursor:
        note_trim_below(cursor, keep_from)
        cursor.execute("DELETE FROM quotes_daily WHERE trade_date < ?", (keep_from,))
        cursor.execute("DELETE FROM trading_calendar WHERE trade_date < ?", (keep_from,))
        _purge_orphan_receipts(cursor)


#: 搬运批大小：一次从全量库 ``fetchmany`` 这么多行，再一次 ``executemany`` 写进热库。
#: 5000 行 × 13 列 ≈ 数 MB 的 Python 对象，既摊平峰值内存，又不会让 executemany
#: 退化成逐行往返（批太小反而是纯开销）。
_COPY_BATCH_ROWS = 5000

_QUOTES_SELECT_SQL = (
    "SELECT trade_date, code, open, high, low, close, volume, amount, "
    "outstanding_share, turnover, source, receipt_id, fetched_at "
    "FROM quotes_daily WHERE trade_date >= ? ORDER BY trade_date, code"
)

_QUOTES_UPSERT_SQL = (
    "INSERT INTO quotes_daily(trade_date, code, open, high, low, close, "
    "volume, amount, outstanding_share, turnover, source, receipt_id, fetched_at) "
    "VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?) "
    "ON CONFLICT(trade_date, code) DO UPDATE SET "
    "open=excluded.open, high=excluded.high, low=excluded.low, "
    "close=excluded.close, volume=excluded.volume, amount=excluded.amount, "
    "outstanding_share=COALESCE(excluded.outstanding_share, quotes_daily.outstanding_share), "
    "turnover=COALESCE(excluded.turnover, quotes_daily.turnover), "
    "source=excluded.source, "
    "receipt_id=COALESCE(excluded.receipt_id, quotes_daily.receipt_id), "
    "fetched_at=excluded.fetched_at"
)


def _stream_copy(
    source: sqlite3.Cursor,
    cursor: sqlite3.Cursor,
    insert_sql: str,
    batch_rows: int | None = None,
) -> int:
    """把 ``source`` 游标按固定批大小搬进 ``cursor``，返回搬运行数。

    读侧 **不用 fetchall**：rebuild 窗口是 700 交易日 × 5500 只 ≈ 390 万行，
    ``fetchall()`` 先把整份结果集物化成 Python list（每行一个 ``sqlite3.Row``），
    随后 ``[tuple(row) for row in rows]`` 又整体复制第二份——峰值是两份全量。
    改成 ``fetchmany`` 后同一时刻只有一批活着，峰值与窗口大小解耦。
    """
    # 默认在**调用时**读模块常量，而不是绑在函数默认值上：
    # 绑死了就没法在测试/排障时临时调批大小。
    rows_per_batch = batch_rows or _COPY_BATCH_ROWS
    copied = 0
    while True:
        batch = source.fetchmany(rows_per_batch)
        if not batch:
            return copied
        # map 而不是列表推导：executemany 直接吃迭代器，不再多留一份批级列表。
        cursor.executemany(insert_sql, map(tuple, batch))
        copied += len(batch)


def _copy_quotes_window(full: MarketStore, hot: MarketStore, start_date: str, *, force: bool = False) -> int:
    """把全量库 [start_date, ∞) 的日 K、日历与关联回执复制进热库（先删同区间）。

    **删 + 灌仍在同一个写事务里，这一点不能拆。** 热库是选股的在线只读库：
    `open_screen_store` 随时可能在 rebuild 进行中打开它，而可用性判据
    （`hot_unusable_reason` / `hot_window_shallow`）只看窗口起点、天数与末日，
    看不出「窗口中间少了 300 万行」。若按批各自提交，删除会先落地，中间态就是
    一个**行数残缺却自称可用**的热库——选股在它上面跑出来的是静默少票、少日的
    错结果，比直接失败坏得多。分批只发生在事务内部（读侧 fetchmany + 写侧
    executemany 分批），降的是峰值内存，不动原子性：整段要么全落，要么回滚。

    持锁时长因此不会缩短（本来就要写完这么多行），但少了两次全量物化，
    GC 压力与 RSS 峰值都随批大小封顶。
    """
    with hot._transaction() as cursor:
        unchanged = not force and _same_window_rows(full, cursor, _QUOTES_SELECT_SQL, start_date)
        calendar_sql = (
            "SELECT trade_date, updated_at FROM trading_calendar "
            "WHERE trade_date >= ? ORDER BY trade_date"
        )
        unchanged = unchanged and _same_window_rows(full, cursor, calendar_sql, start_date)
        written = 0
        if not unchanged:
            with track_hot_window_rewrite(cursor, start_date):
                cursor.execute("DELETE FROM quotes_daily WHERE trade_date >= ?", (start_date,))
                cursor.execute("DELETE FROM trading_calendar WHERE trade_date >= ?", (start_date,))
                written = _stream_copy(
                    full.conn.execute(_QUOTES_SELECT_SQL, (start_date,)), cursor, _QUOTES_UPSERT_SQL,
                )
                _stream_copy(
                    full.conn.execute(calendar_sql, (start_date,)), cursor,
                    "INSERT OR REPLACE INTO trading_calendar VALUES(?,?)",
                )
    # 回执：删除热库孤儿后，重灌窗口内日 K 关联的回执（含 attempts）。
    _replace_linked_receipts(full, hot, start_date)
    return written


def _same_window_rows(full: MarketStore, target: sqlite3.Cursor, sql: str, start: str) -> bool:
    """热库写事务内比对完整值，不依赖可能漏记旁路修订的版本号。"""
    source = full.conn.execute(sql, (start,))
    target.execute(sql, (start,))
    try:
        while True:
            left = source.fetchmany(_COPY_BATCH_ROWS)
            right = target.fetchmany(_COPY_BATCH_ROWS)
            if [tuple(row) for row in left] != [tuple(row) for row in right]:
                return False
            if not left:
                return True
    finally:
        source.close()


def _changed_receipt_rows(
    cursor: sqlite3.Cursor, table: str, cols: list[str], rows: list[sqlite3.Row],
    chunk: list[str], placeholders: str,
) -> list[tuple]:
    keys = [cols.index("receipt_id")]
    if table == "source_route_attempts":
        keys.append(cols.index("attempt_no"))
    current = {
        tuple(row[i] for i in keys): tuple(row)
        for row in cursor.execute(
            f"SELECT {','.join(cols)} FROM {table} WHERE receipt_id IN ({placeholders})", chunk,
        )
    }
    return [tuple(row) for row in rows if tuple(row) != current.get(tuple(row[i] for i in keys))]


def _replace_linked_receipts(full: MarketStore, hot: MarketStore, start_date: str) -> None:
    with hot._transaction() as cursor:
        _purge_orphan_receipts(cursor)
        ids = [
            str(row[0])
            for row in full.conn.execute(
                "SELECT DISTINCT receipt_id FROM quotes_daily "
                "WHERE trade_date >= ? AND receipt_id IS NOT NULL",
                (start_date,),
            ).fetchall()
        ]
        for offset in range(0, len(ids), _SQL_IN_CHUNK):
            chunk = ids[offset : offset + _SQL_IN_CHUNK]
            placeholders = ",".join("?" for _ in chunk)
            _copy_receipts_chunk(full, hot, cursor, chunk, placeholders)
            _copy_attempts_chunk(full, hot, cursor, chunk, placeholders)


def _copy_receipts_chunk(
    full: MarketStore,
    hot: MarketStore,
    cursor: object,
    chunk: list[str],
    placeholders: str,
) -> None:
    rows = full.conn.execute(
        "SELECT * FROM source_route_receipts WHERE receipt_id IN (" + placeholders + ")",
        chunk,
    ).fetchall()
    if not rows:
        return
    cols = [str(row[1]) for row in full.conn.execute("PRAGMA table_info(source_route_receipts)")]
    cursor.executemany(
        "INSERT OR REPLACE INTO source_route_receipts(" + ",".join(cols) + ") VALUES("
        + ",".join("?" for _ in cols) + ")",
        _changed_receipt_rows(cursor, "source_route_receipts", cols, rows, chunk, placeholders),
    )


def _copy_attempts_chunk(
    full: MarketStore,
    hot: MarketStore,
    cursor: object,
    chunk: list[str],
    placeholders: str,
) -> None:
    rows = full.conn.execute(
        "SELECT * FROM source_route_attempts WHERE receipt_id IN (" + placeholders + ")",
        chunk,
    ).fetchall()
    if not rows:
        return
    cols = [str(row[1]) for row in full.conn.execute("PRAGMA table_info(source_route_attempts)")]
    cursor.executemany(
        "INSERT OR REPLACE INTO source_route_attempts(" + ",".join(cols) + ") VALUES("
        + ",".join("?" for _ in cols) + ")",
        _changed_receipt_rows(cursor, "source_route_attempts", cols, rows, chunk, placeholders),
    )


def mirror_to_hot(
    full: MarketStore,
    hot: MarketStore | None = None,
    *,
    window_trading_days: int = HOT_WINDOW_TRADING_DAYS,
) -> dict[str, int]:
    """全量重建热库：清空行情窗口并重灌近 N 交易日（幂等，可随时重跑）。"""
    hot = hot or open_market_hot()
    start_date = _window_start(full, window_trading_days)
    if not start_date:
        return {"quotes": 0, "start": "", "end": "", "mode": "empty"}
    _copy_small_tables(full, hot, force=True)
    written = _copy_quotes_window(full, hot, start_date, force=True)
    # 裁掉窗外旧行（rebuild 的 copy start 即窗口起点；仍显式 trim 保证幂等）。
    _trim_hot_before(hot, start_date)
    end_date = hot.conn.execute("SELECT MAX(trade_date) FROM quotes_daily").fetchone()[0] or ""
    return {
        "quotes": written,
        "start": start_date,
        "end": str(end_date),
        "mode": "rebuild",
    }


def hot_window_shallow(
    full: MarketStore,
    hot: MarketStore,
    *,
    window_trading_days: int = HOT_WINDOW_TRADING_DAYS,
) -> bool:
    """热库是否缺窗外沿：有数据但起点晚于应有窗口，或天数明显不足。

    增量镜像只补近端，不会回填历史；浅热库会导致选股 ``min_bars`` 滤空面板
    （universe 漏斗仍显示几千，但 ``panel_columns=0``）。
    """
    keep_from = _window_start(full, window_trading_days)
    if not keep_from:
        return False
    hot_min = hot.conn.execute("SELECT MIN(trade_date) FROM quotes_daily").fetchone()[0]
    if not hot_min:
        return True
    if str(hot_min) > keep_from:
        return True
    hot_days = int(
        # 按日期主键跳到下一日，避免 DISTINCT 扫数百万条 code/date 索引。
        # 仍数真实日 K，不能用日历表掩盖热库有日历但缺行情的情况。
        hot.conn.execute(
            "WITH RECURSIVE days(d) AS ("
            " SELECT MIN(trade_date) FROM quotes_daily"
            " UNION ALL SELECT (SELECT MIN(q.trade_date) FROM quotes_daily q"
            " WHERE q.trade_date > days.d) FROM days WHERE d IS NOT NULL"
            ") SELECT COUNT(d) FROM days"
        ).fetchone()[0]
        or 0
    )
    expected = full.trading_days(start=keep_from)
    need = min(window_trading_days, len(expected)) if expected else window_trading_days
    # 允许少量日历缺口；低于 90% 视为未灌满，升级全量重建。
    return hot_days < max(1, int(need * 0.9))


def hot_unusable_reason(
    full: MarketStore,
    hot: MarketStore,
    *,
    window_trading_days: int = HOT_WINDOW_TRADING_DAYS,
) -> str:
    """热库不适合用于选股的原因；空字符串表示可用。

    ``hot_window_shallow`` 只看窗口起点与天数，而增量镜像允许日历缺口，
    因此「窗口够深」不等于「跟上了最新交易日」：热库灌满 700 天但缺当日时
    它仍判为不浅。两项都过才允许读热库，否则会静默用落后一天的面板选股。
    """
    if hot_window_shallow(full, hot, window_trading_days=window_trading_days):
        return "热库窗口偏浅"
    full_max = full.conn.execute("SELECT MAX(trade_date) FROM quotes_daily").fetchone()[0]
    hot_max = hot.conn.execute("SELECT MAX(trade_date) FROM quotes_daily").fetchone()[0]
    if full_max and (not hot_max or str(hot_max) < str(full_max)):
        return f"热库行情落后于全量库（full={full_max} hot={hot_max}）"
    return ""


def hot_fallback_reason(
    full: MarketStore,
    hot: MarketStore,
    *,
    trade_date: str,
    warmup_bars: int,
    end: str | None = None,
    live_overlay: bool = False,
    window_trading_days: int = HOT_WINDOW_TRADING_DAYS,
) -> str:
    """选股该不该回退全量库的**唯一**判据；空字符串 = 可以读热库。

    三条判据缺一不可：窗口深度（``hot_window_shallow``）、末日是否落后于全量库
    （``live_overlay`` 时跳过，盘中今日价走独立实时 overlay），以及目标日的指标
    **预热日历**是否完整落在热库内。

    第三条不能省：前两条都是相对**今天**的判据，看不出「用户要选的是 2020 年，
    而热库只有近 700 个交易日」。缺了它，``screener._resolve_start`` 的
    ``max(0, len(days) - bars)`` 会把不足的预热窗口无声钳位到热库首日，随后
    ``load_panel(min_bars=...)`` 把历史不够的票静默丢掉——跑出一份少票的
    「成功」结果并照常入库，比直接失败坏得多。

    ``warmup_bars`` 收整数而**不是** engine 对象：market 不得反向依赖 strategy，
    预热长度由调用方 ``signal_history_bars(engine)`` 算好再传。
    ``end`` 供区间选股传区间末日；默认与 ``trade_date`` 同日。
    """
    if live_overlay:
        if hot_window_shallow(full, hot, window_trading_days=window_trading_days):
            return "热库窗口偏浅"
    else:
        reason = hot_unusable_reason(full, hot, window_trading_days=window_trading_days)
        if reason:
            return reason
    start = str(trade_date or "")
    if not start:
        all_days = full.trading_days()
        start = all_days[-1] if all_days else ""
    last = str(end or start)
    # bars<=0 会让切片退化成 [-0:]=全历史，把「几乎不需要预热」误判成
    # 「热库必须装下全部历史」，恒回退全量库。
    warmup = full.trading_days(end=start)[-max(1, int(warmup_bars)):]
    if not warmup:
        return "目标交易日前没有可用历史"
    required = full.trading_days(start=warmup[0], end=last)
    available = set(hot.trading_days(start=warmup[0], end=last))
    if not set(required).issubset(available):
        return f"热库未覆盖目标日预热窗口（{warmup[0]}→{last}）"
    return ""


@contextmanager
def open_screen_store(
    market_db: str | None = None,
    hot_db: str | None = None,
    *,
    trade_date: str,
    warmup_bars: int,
) -> Iterator[MarketStore]:
    """选股**只读**入口：热库可用就给热库，否则回退全量库。

    与选股任务路径的区别是不镜像——镜像是同步 / 选股任务的写职责，只读路径
    （助手战法、技能试跑）不该顺手改热库，但仍必须过 ``hot_fallback_reason``：
    浅热库、落后一天、**目标日的预热日历不在热库窗口内**，三者都要回退全量库。

    两个关键字参数故意**不给默认值**：留默认就等于把「历史日静默少票」的缺口
    原地保留给下一个调用方。
    """
    with ExitStack() as stack:
        full = stack.enter_context(MarketStore(market_db))
        try:
            hot = stack.enter_context(open_market_hot(hot_db))
            reason = hot_fallback_reason(
                full, hot, trade_date=trade_date, warmup_bars=warmup_bars
            )
        except sqlite3.Error as exc:
            hot = None
            reason = f"热库打开失败（{exc}）"
        if hot is None or reason:
            logger.warning("%s，回退全量库选股", reason)
            yield full
        else:
            yield hot


def mirror_recent_to_hot(
    full: MarketStore,
    hot: MarketStore | None = None,
    *,
    buffer_trading_days: int = MIRROR_BUFFER_TRADING_DAYS,
    window_trading_days: int = HOT_WINDOW_TRADING_DAYS,
) -> dict[str, int]:
    """增量镜像：把全量库最近若干交易日补进热库（同步任务完成后调用）。

    若热库为空或窗口明显偏浅，升级为 ``mirror_to_hot`` 全量重灌，避免
    「只有近两周」却一直增量补齐、选股面板被 min_bars 滤空。
    """
    hot = hot or open_market_hot()
    if hot_window_shallow(full, hot, window_trading_days=window_trading_days):
        return mirror_to_hot(full, hot, window_trading_days=window_trading_days)
    start_date = _hot_cutoff(full, hot, buffer_trading_days)
    if not start_date:
        return {"quotes": 0, "start": "", "end": "", "mode": "empty"}
    _copy_small_tables(full, hot)
    written = _copy_quotes_window(full, hot, start_date)
    # 增量 copy 起点可能是近几天；裁窗外必须按全量库当前 700 日窗口起点。
    keep_from = _window_start(full, window_trading_days)
    _trim_hot_before(hot, keep_from)
    end_date = hot.conn.execute("SELECT MAX(trade_date) FROM quotes_daily").fetchone()[0] or ""
    return {
        "quotes": written,
        "start": start_date,
        "end": str(end_date),
        "mode": "incremental",
    }
