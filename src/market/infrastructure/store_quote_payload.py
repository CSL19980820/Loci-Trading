"""行情批量写入前的归一化。"""
from __future__ import annotations

from collections.abc import Iterable, Mapping
from typing import Any
import sqlite3

import pandas as pd

from src.market.infrastructure.history_floor import MIN_TRADE_DATE
from src.market.infrastructure.store_codes import MarketError, normalize_code
from src.market.infrastructure.store_schema import PANEL_FIELDS
from src.market.infrastructure.store_row_count import track_quote_upsert

#: 参数行里数值列的排列，**与 quotes_daily 的 INSERT 语句一致**。
#: 刻意不复用 ``PANEL_FIELDS``：那份常量里 ``turnover`` 排在 ``outstanding_share``
#: 之前，照它拼参数会把股本和换手率对调，且两列都是 REAL、写进去不会报错。
QUOTE_VALUE_FIELDS = (
    "open", "high", "low", "close",
    "volume", "amount", "outstanding_share", "turnover",
)


def partition_valid_ohlc_rows(frame: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame]:
    """按日 K 最小价格约束拆分可落盘与拒绝的行，保留原始列供回执记录。

    全市场同步一天要跑五千多次，所以这里不搭 pandas 中间帧：四个价格列直接取
    numpy 数组比较，且全部合法时原样返回入参、不做防御性 copy（250 行帧实测
    1.69 ms → 0.12 ms）。合法帧的三个调用方（store_rw / sync / sync_spot）都只
    读它，新增调用方若要就地改列请自己 copy。
    """
    if frame is None:
        return pd.DataFrame(), pd.DataFrame()
    if frame.empty:
        return frame.copy(), frame.copy()

    columns = {str(column).strip().lower(): column for column in frame.columns}
    required = ("open", "high", "low", "close")
    if any(field not in columns for field in required):
        return frame.iloc[0:0].copy(), frame.copy()

    open_, high, low, close = (
        pd.to_numeric(frame[columns[field]], errors="coerce").to_numpy(dtype="float64")
        for field in required
    )
    # NaN 与任何值比较都是 False，缺价行因此自动落进拒绝侧，不必再单独 notna。
    valid = (
        (open_ > 0) & (high > 0) & (low > 0) & (close > 0)
        & (high >= open_) & (high >= low) & (high >= close)
        & (low <= open_) & (low <= close)
    )
    if valid.all():
        return frame, frame.iloc[0:0]
    return frame.loc[valid].copy(), frame.loc[~valid].copy()


def quote_payload_from_bars(
    bars: Iterable[dict[str, Any]],
    *,
    source: str,
    receipt_ids: Mapping[str, str] | None = None,
) -> list[tuple[Any, ...]]:
    records: list[dict[str, Any]] = []
    for raw in bars:
        try:
            code = normalize_code(str(raw.get("code") or ""))
        except MarketError:
            continue
        trade_date = raw.get("date") if raw.get("date") is not None else raw.get("trade_date")
        if trade_date is not None and trade_date != "":
            records.append(
                {"code": code, "trade_date": trade_date, **{
                    column: raw.get(column) for column in PANEL_FIELDS
                }}
            )
    if not records:
        return []
    frame = pd.DataFrame(records)
    # 上游 bar 的日期是 ``date`` / ``Timestamp`` 对象或 ``YYYY-MM-DD`` 文本（见
    # sync_spot 的 bar 组装与各 adapter 的 date 列），全是 year-first。显式给
    # format 省掉 pandas 的逐值格式推断；更要紧的是推断只按首个非空值定格式，
    # 混进一个宽度不同的值会被静默判成 NaT。
    frame["trade_date"] = pd.to_datetime(
        frame["trade_date"], format="ISO8601"
    ).dt.strftime("%Y-%m-%d")
    # 防回填地板：早于 MIN_TRADE_DATE 的 bar 一律不落库（与 market.db 的
    # quotes_daily_floor 触发器同口径，代码侧再兜一层）。YYYY-MM-DD 字典序即时间序。
    frame = frame[frame["trade_date"] >= MIN_TRADE_DATE]
    if frame.empty:
        return []
    frame = frame[["code", "trade_date", *PANEL_FIELDS]].drop_duplicates(
        subset=["code", "trade_date"], keep="last"
    )
    frame, _rejected = partition_valid_ohlc_rows(frame)
    if frame.empty:
        return []
    ids = receipt_ids or {}
    return [
        (trade_date, code, *values, source, ids.get(code))
        for trade_date, code, values in zip(
            frame["trade_date"].tolist(),
            frame["code"].tolist(),
            zip(*quote_value_columns(frame), strict=True),
            strict=True,
        )
    ]


def quote_value_columns(frame: pd.DataFrame) -> list[list[Any]]:
    """按 ``QUOTE_VALUE_FIELDS`` 逐列取出 sqlite 能收的 Python 值。

    sqlite3 不认 NaN，会存成一个不等于自身的浮点毒值，所以缺值必须显式变 NULL。
    原先靠整帧 ``astype(object).where(pd.notna(frame), None)`` 做这件事：250 行帧
    上那一步本身要 0.44 ms，还把整张表变成 object dtype，让随后 OHLC 校验的
    ``to_numeric`` 再多花 0.27 ms。现在校验跑在原始数值帧上，只有真要落库的列
    才逐列换 NULL。
    """
    # ``value != value`` 是 NaN/NaT 判定：两者都不等于自身，None 与字符串则相等。
    return [
        [None if value != value else value for value in frame[field].tolist()]
        for field in QUOTE_VALUE_FIELDS
    ]


def write_quote_payload(cursor: sqlite3.Cursor, payload: list[tuple[Any, ...]]) -> int:
    """在调用方事务中写日 K 与日历，保护已定稿权威行并返回实际写入数。"""
    with track_quote_upsert(cursor, payload):
        cursor.executemany(
            """
            INSERT INTO quotes_daily(trade_date, code, open, high, low, close,
                                     volume, amount, outstanding_share, turnover,
                                     source, receipt_id, fetched_at)
            VALUES(?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, datetime('now'))
            ON CONFLICT(trade_date, code) DO UPDATE SET
                open=excluded.open, high=excluded.high, low=excluded.low,
                close=excluded.close,
                -- 缺列的源经 _prepare_quote_frame 会补成 NULL；量额与股本
                -- 换手一样禁止被空值抹掉（0 是停牌日的真值，仍照常覆盖）。
                volume=COALESCE(excluded.volume, quotes_daily.volume),
                amount=COALESCE(excluded.amount, quotes_daily.amount),
                outstanding_share=COALESCE(
                    excluded.outstanding_share, quotes_daily.outstanding_share
                ),
                turnover=COALESCE(excluded.turnover, quotes_daily.turnover),
                source=excluded.source,
                receipt_id=COALESCE(excluded.receipt_id, quotes_daily.receipt_id),
                fetched_at=excluded.fetched_at
            WHERE quotes_daily.source <> 'tdx' OR excluded.source = 'tdx'
               OR (quotes_daily.trade_date = date('now', 'localtime')
                   AND time('now', 'localtime') < '15:00:00')
            """,
            payload,
        )
        written = cursor.rowcount
    # 一批里同一交易日会重复上千次（全市场 spot 是 5500 行同一天）。日历表只关心
    # 有哪些交易日，去重后再喂：5500 条 DO NOTHING 降到 1 条（实测 4.83 → 0.25 ms）。
    cursor.executemany(
        "INSERT INTO trading_calendar(trade_date, updated_at)"
        " VALUES(?, datetime('now')) ON CONFLICT(trade_date) DO NOTHING",
        [(trade_date,) for trade_date in dict.fromkeys(row[0] for row in payload)],
    )
    return written
