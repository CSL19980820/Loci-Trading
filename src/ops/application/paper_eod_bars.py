"""日终回看的日 K 取数与数值小工具。

从 ``paper_eod_review.py`` 拆出来是体量原因。这里最要紧的一条是
``_lookback_panels``：回看池逐票 ``history`` 在 2000 条候选上是 2000 次查询，
换成一次 ``load_panel`` 宽表后恒为 1 次；缺票/停牌在面板里是 NaN，
``_bars_from_panel`` 负责把它还原成「那天没有这根 K 线」而不是 0。
"""
from __future__ import annotations

import logging
from typing import Any

logger = logging.getLogger(__name__)


def _safe_float(value: Any) -> float | None:
    try:
        if value is None or value == "":
            return None
        return float(value)
    except (TypeError, ValueError):
        return None


def _pct(prev: float | None, cur: float | None) -> float | None:
    if prev is None or cur is None or prev == 0:
        return None
    return round((cur / prev - 1.0) * 100.0, 3)


def _bars_from_history(frame: Any) -> list[dict[str, Any]]:
    if frame is None or getattr(frame, "empty", True):
        return []
    bars: list[dict[str, Any]] = []
    prev_close: float | None = None
    for row in frame.itertuples(index=False):
        close = _safe_float(getattr(row, "close", None))
        bar = {
            "trade_date": str(getattr(row, "trade_date", "")),
            "open": _safe_float(getattr(row, "open", None)),
            "high": _safe_float(getattr(row, "high", None)),
            "low": _safe_float(getattr(row, "low", None)),
            "close": close,
            "volume": _safe_float(getattr(row, "volume", None)),
            "amount": _safe_float(getattr(row, "amount", None)),
            "turnover": _safe_float(getattr(row, "turnover", None)),
            "pct": _pct(prev_close, close),
        }
        bars.append(bar)
        if close is not None:
            prev_close = close
    return bars


#: 面板一次取回的日 K 字段。含 turnover：回看文案会打印「换手」，少一列就改了输出。
_PANEL_BAR_FIELDS = ("open", "high", "low", "close", "volume", "amount", "turnover")


def _lookback_panels(
    market: Any, codes: list[str], *, start: str, end: str
) -> dict[str, Any] | None:
    """一次面板查询取回整个回看池的日 K；没有批量接口或查询失败返回 None。

    为什么批量：回看池有 N 只票，原来就是 N 次 ``history`` = N 次 SQLite 往返
    （战法池上百只、候选场景两千只即两千次）；面板一条 ``IN (...)`` 全取回。
    """
    loader = getattr(market, "load_panel", None)
    if not callable(loader) or not codes:
        return None
    try:
        return loader(
            fields=_PANEL_BAR_FIELDS,
            codes=codes,
            start=start,
            end=end,
            adjust="qfq",
        )
    except Exception as exc:  # noqa: BLE001
        logger.warning("eod lookback load_panel failed: %s", exc)
        return None


def _bars_from_panel(panels: dict[str, Any], code: str) -> list[dict[str, Any]]:
    """把宽表面板里某一票的列切成与 ``_bars_from_history`` 同构的日 K 列表。

    缺票/停牌在面板里是 NaN：整行 NaN 等价于原来 ``history`` 没有这根 K 线，
    直接跳过（**不能当 0 用**）；单字段 NaN 映射成原来的 None。
    """
    columns: dict[str, Any] = {}
    index: Any = None
    for field in _PANEL_BAR_FIELDS:
        panel = panels.get(field)
        if panel is None or getattr(panel, "empty", True):
            continue
        if code not in panel.columns:
            continue
        column = panel[code]
        columns[field] = column
        if index is None:
            index = column.index
    if index is None:
        return []
    bars: list[dict[str, Any]] = []
    prev_close: float | None = None
    for day in index:
        values: dict[str, float | None] = {}
        for field in _PANEL_BAR_FIELDS:
            column = columns.get(field)
            raw = None if column is None else column.get(day)
            # raw != raw 即 NaN：该字段本来就没数，按 None 处理
            values[field] = None if raw is None or raw != raw else float(raw)
        if all(value is None for value in values.values()):
            continue
        close = values["close"]
        bars.append(
            {
                "trade_date": str(day),
                "open": values["open"],
                "high": values["high"],
                "low": values["low"],
                "close": close,
                "volume": values["volume"],
                "amount": values["amount"],
                "turnover": values["turnover"],
                "pct": _pct(prev_close, close),
            }
        )
        if close is not None:
            prev_close = close
    return bars
