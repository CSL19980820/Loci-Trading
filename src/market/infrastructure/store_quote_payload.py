"""行情批量写入前的归一化。"""
from __future__ import annotations

from collections.abc import Iterable, Mapping
from typing import Any

import pandas as pd

from src.market.infrastructure.store_codes import MarketError, normalize_code
from src.market.infrastructure.store_schema import PANEL_FIELDS

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
