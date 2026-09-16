"""Daily-close inputs: normalize dates and carry whole observed economic marks."""

from __future__ import annotations

from dataclasses import dataclass
from math import isfinite
from numbers import Number
from typing import Any

import pandas as pd

from .research_portfolio import PortfolioResearchError


@dataclass(frozen=True, slots=True)
class EconomicMark:
    date: str
    raw_close: float
    factor: float

    @property
    def price(self) -> float:
        return self.raw_close * self.factor


def _day(value: Any) -> str:
    try:
        if isinstance(value, Number):
            raise ValueError("numeric date")
        if isinstance(value, str):
            value = str(value)
        stamp = pd.Timestamp(value)
        if pd.isna(stamp):
            raise ValueError("missing date")
        return stamp.date().isoformat()
    except (TypeError, ValueError, OverflowError) as exc:
        raise PortfolioResearchError(f"日期无效：{value}") from exc


def _panel(frame: pd.DataFrame, label: str) -> pd.DataFrame:
    if not isinstance(frame, pd.DataFrame):
        raise PortfolioResearchError(f"{label} 必须是日期×股票的DataFrame")
    result = frame.copy(deep=False)
    dates = [_day(value) for value in frame.index]
    result.index = dates
    result.columns = frame.columns.map(str)
    if not result.index.is_unique or not result.columns.is_unique:
        raise PortfolioResearchError(f"{label} 日期或股票索引重复")
    return result.sort_index() if not result.index.is_monotonic_increasing else result


class DailyPrices:
    """Per-call state only; no shared cache or forward-looking backfill."""

    def __init__(
        self,
        closing_prices: pd.DataFrame | None,
        adjustment_factors: pd.DataFrame | None,
    ) -> None:
        if closing_prices is None:
            raise PortfolioResearchError("daily_close 需要 closing_prices")
        self.close = _panel(closing_prices, "closing_prices")
        self.factors = (
            _panel(adjustment_factors, "adjustment_factors")
            if adjustment_factors is not None
            else None
        )
        self._factor_columns: dict[str, pd.Series] = {}

    def factor(self, code: str, day: str) -> float:
        if self.factors is None:
            return 1.0
        if code not in self.factors.columns:
            raise PortfolioResearchError(f"{code} 缺少复权因子列")
        if code not in self._factor_columns:
            self._factor_columns[code] = self.factors[code].ffill()
        series = self._factor_columns[code]
        index = int(series.index.searchsorted(day, side="right")) - 1
        try:
            value = float(series.iloc[index]) if index >= 0 else float("nan")
        except (TypeError, ValueError) as exc:
            raise PortfolioResearchError(f"{code} 在{day}的复权因子不是数值") from exc
        if not isfinite(value) or value <= 0:
            raise PortfolioResearchError(f"{code} 在{day}没有已知有效复权因子")
        return value

    def mark(self, code: str, day: str, previous: EconomicMark | None) -> EconomicMark:
        raw: Any = (
            self.close.at[day, code]
            if code in self.close.columns and day in self.close.index
            else None
        )
        if raw is None or pd.isna(raw):
            if previous is None:
                raise PortfolioResearchError(f"{code} 开仓日{day}缺少有效收盘价")
            # A factor change without a new trade must not multiply an old raw
            # quote: carry the previously observed (close, factor) pair intact.
            return previous
        try:
            value = float(raw)
        except (TypeError, ValueError) as exc:
            raise PortfolioResearchError(f"{code} 在{day}的收盘价不是数值") from exc
        if not isfinite(value) or value <= 0:
            raise PortfolioResearchError(f"{code} 在{day}的收盘价无效")
        factor = self.factor(code, day)
        if not isfinite(value * factor):
            raise PortfolioResearchError(f"{code} 在{day}的经济标记价无效")
        return EconomicMark(day, value, factor)
