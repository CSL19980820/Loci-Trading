"""多源日 K 互补合并：等齐后再按优先序落成一张表。"""
from __future__ import annotations

from typing import Mapping, Sequence

import pandas as pd

_DATE_CANDIDATES = ("date", "trade_date")
_VALUE_PRIORITY = (
    "open",
    "high",
    "low",
    "close",
    "volume",
    "amount",
    "turnover",
    "outstanding_share",
)
#: 日线这几列都是非负量，源侧「没取到」时常被填成 0（如悟道 kline 的
#: ``float(row.get("amount") or 0)``）。0 不含任何真值，不能压过别的源的实数。
_ZERO_IS_MISSING = frozenset(_VALUE_PRIORITY)


def _date_column(frame: pd.DataFrame) -> str:
    for name in _DATE_CANDIDATES:
        if name in frame.columns:
            return name
    raise ValueError("日线缺少日期列")


def _normalize_frame(frame: pd.DataFrame) -> pd.DataFrame:
    out = frame.copy()
    date_col = _date_column(out)
    # 入参是各日线源的原始帧：sina/tencent 的 date 是 ``datetime.date``，
    # tdx/baostock/eastmoney kline 是 ``YYYY-MM-DD`` 文本——都是 year-first。
    # 这里带 ``errors=coerce``，格式推断一旦按首值定错格式，其余行会静默变 NaT
    # 并被下一行 dropna 丢掉；显式 ISO8601 既省掉逐值推断也堵掉这条静默丢数路径。
    out["_trade_date"] = pd.to_datetime(
        out[date_col], format="ISO8601", errors="coerce"
    ).dt.strftime("%Y-%m-%d")
    out = out.dropna(subset=["_trade_date"])
    if out.empty:
        return out
    return out.sort_values("_trade_date").drop_duplicates("_trade_date", keep="last")


def _missing(column: str, value: object) -> bool:
    """该列的这个取值能不能算「源真的给了数」。"""
    if value is None:
        return True
    try:
        if bool(pd.isna(value)):
            return True
    except (TypeError, ValueError):  # 数组/列表等非标量
        return False
    if column not in _ZERO_IS_MISSING:
        return False
    try:
        return float(value) <= 0  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return True


def merge_daily_frames(
    frames: Sequence[tuple[str, pd.DataFrame]],
    *,
    preferred_order: Sequence[str],
    estimated_fields: Mapping[str, Sequence[str]] | None = None,
) -> tuple[pd.DataFrame, str, dict[str, int]]:
    """按日期互补合并多源日 K。

    - 冲突日：``preferred_order`` 靠前的源优先（校验口径：信任优先序）
    - 缺失日 / 空字段：用后方源补齐（互补）
    - 优先源那一行**没有可用收盘价**（0 / NaN）时不算数据，让位给真有行情的源
    - ``estimated_fields``：源自报的推算列（如腾讯 amount=close×volume），
      真实值一到就顶掉，避免估算数悄悄盖过源生成交额
    - 返回 ``(合并表, 主源 id, 各源贡献行数)``；主源取优先序中首个有贡献者
    """
    by_id = {source_id: frame for source_id, frame in frames if frame is not None and not frame.empty}
    if not by_id:
        raise ValueError("没有可合并的日线")

    order = [aid for aid in preferred_order if aid in by_id]
    order.extend(aid for aid in by_id if aid not in order)
    guessed = {aid: frozenset((estimated_fields or {}).get(aid, ())) for aid in order}

    merged_rows: dict[str, dict[str, object]] = {}
    owner: dict[str, str] = {}
    #: 已落行但收盘价不可用的日期，可被后方真有行情的源整行替换。
    unusable: set[str] = set()
    #: 日期 → 当前行里仍是估算值的列。
    guessed_cells: dict[str, set[str]] = {}
    filled_from: dict[str, int] = {aid: 0 for aid in order}

    for source_id in order:
        normalized = _normalize_frame(by_id[source_id])
        if normalized.empty:
            continue
        value_cols = [col for col in _VALUE_PRIORITY if col in normalized.columns]
        guessed_here = guessed[source_id]
        for record in normalized.to_dict("records"):
            trade_date = str(record["_trade_date"])
            current = merged_rows.get(trade_date)
            has_quote = not _missing("close", record.get("close"))
            if current is None or (trade_date in unusable and has_quote):
                row: dict[str, object] = {col: record.get(col) for col in value_cols}
                if current is not None:
                    previous_owner = owner[trade_date]
                    filled_from[previous_owner] = max(
                        0, filled_from.get(previous_owner, 0) - 1
                    )
                    # 被顶掉的坏行里可能仍有可信的量/额，别跟着一起丢。
                    for col, value in current.items():
                        if col == "date" or not _missing(col, row.get(col)):
                            continue
                        if not _missing(col, value):
                            row[col] = value
                # 只输出 date：store 归一会把 date→trade_date；两者并存会撞列。
                row["date"] = trade_date
                merged_rows[trade_date] = row
                owner[trade_date] = source_id
                filled_from[source_id] = filled_from.get(source_id, 0) + 1
                guessed_cells[trade_date] = {col for col in guessed_here if col in row}
                if has_quote:
                    unusable.discard(trade_date)
                else:
                    unusable.add(trade_date)
                continue
            # 互补：补空字段，不覆盖优先源已有 OHLC；估算列可被真实值顶掉
            still_guessed = guessed_cells.setdefault(trade_date, set())
            for col in value_cols:
                incoming = record.get(col)
                if _missing(col, incoming):
                    continue
                fillable = _missing(col, current.get(col)) or (
                    col in still_guessed and col not in guessed_here
                )
                if not fillable:
                    continue
                current[col] = incoming
                if col in guessed_here:
                    still_guessed.add(col)
                else:
                    still_guessed.discard(col)

    if not merged_rows:
        raise ValueError("合并后日线为空")

    primary = next((aid for aid in order if filled_from.get(aid, 0) > 0), order[0])
    merged = pd.DataFrame([merged_rows[key] for key in sorted(merged_rows)])
    return merged, primary, filled_from
