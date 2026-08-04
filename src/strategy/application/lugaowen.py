"""海底捞月：活动目录中的卢高文系战法实现。

三外有三及其他卢高文公式已归档到 ``application/backup/lugaowen-legacy.py``，
不随 ``src.strategy`` 导入，也不会进入活动选股和托管任务目录。
"""
from __future__ import annotations

from typing import Any

import pandas as pd

from src.formula import BARSLAST, HHV, MA, REF, limit_ratio_panel, limit_up_flags
from src.strategy.domain.base import SignalResult, merge_params, register


class _LugaowenBase:
    """活动卢高文战法共享的涨停识别。"""

    entry_timing = "next_open"
    requires_instrument_names = True
    names: dict[str, str] | None = None

    def required_fields(self) -> tuple[str, ...]:
        return ("open", "high", "low", "close", "volume")

    def min_bars(self) -> int:
        return 70

    def _limit_up(self, panels: dict[str, pd.DataFrame]) -> tuple[pd.DataFrame, pd.DataFrame]:
        names = panels.get("__instrument_names__")
        if not isinstance(names, dict):
            names = self.names
        ratios = limit_ratio_panel(panels["close"], names)
        return limit_up_flags(panels["close"], panels["high"], ratios), ratios


class HaidiLaoyue(_LugaowenBase):
    """长期下跌后出现涨停，回踩不破启动涨停价。"""

    slug = "lugw-haidi"
    name = "海底捞月"
    description = "长期下跌途中突然涨停，随后 1-10 个交易日回踩不破启动涨停价并在其附近形成买点"
    entry_instructions = (
        "买入条件：先确认启动日 S 的前一交易日收盘低于 MA20、MA20 低于 MA60，"
        "且该收盘价低于 60 日高点的 75%；S 日收盘必须封住涨停。"
        "信号日 T 为 S 后第 1-10 个交易日，T 日收盘价位于 S 日涨停收盘价的 99%-108%，"
        "并且从 S 日到 T 日的期间最低价不低于 S 日涨停收盘价的 98%。"
        "满足后在 T+1 开盘买入；涨停启动当天不买，买入时点固定为次日开盘。"
        "活动策略不按 T+1 高开、平开或低开再做二次筛选；缺口差异需另做回测情景。"
    )
    strategy_revision = "builtin:lugw-haidi"
    version = "v1"
    version_history = [{"version": "v1", "status": "active", "source": "builtin"}]

    def default_params(self) -> dict[str, Any]:
        return {
            "high_ratio": 0.75,
            "window_max": 10,
            "near_low": 0.99,
            "near_high": 1.08,
            "hold_ratio": 0.98,
        }

    def compute(
        self, panels: dict[str, pd.DataFrame], params: dict[str, Any] | None = None
    ) -> SignalResult:
        p = merge_params(self, params)
        close, high, low = panels["close"], panels["high"], panels["low"]
        zt, _ = self._limit_up(panels)

        ma20, ma60 = MA(close, 20), MA(close, 60)
        downtrend = (
            (REF(close, 1) < REF(ma20, 1))
            & (REF(ma20, 1) < REF(ma60, 1))
            & (REF(close, 1) < HHV(high, 60) * p["high_ratio"])
        )
        start = zt & downtrend
        bars = BARSLAST(start)
        base = _shift_by(close, bars)
        window_low = _rolling_min_by(low, bars.clip(lower=1))

        in_window = (bars >= 1) & (bars <= p["window_max"])
        near = (close >= base * p["near_low"]) & (close <= base * p["near_high"])
        holds = window_low >= base * p["hold_ratio"]
        signals = (in_window & near & holds).fillna(False)
        return SignalResult(
            signals=signals,
            factors={
                "长期下跌": downtrend,
                "启动涨停": start,
                "距启动": bars,
                "涨停价": base,
                "期间最低": window_low,
            },
        )


def _shift_by(frame: pd.DataFrame, offsets: pd.DataFrame) -> pd.DataFrame:
    """按逐元素偏移量取历史值，等价于变量参数的 ``REF(X, N)``。"""
    import numpy as np

    values = frame.to_numpy(dtype=float)
    steps = offsets.to_numpy(dtype=float)
    rows, cols = values.shape
    row_index = np.arange(rows)[:, None] - steps
    valid = np.isfinite(row_index) & (row_index >= 0)
    safe = np.where(valid, row_index, 0).astype(int)
    gathered = values[safe, np.arange(cols)[None, :]]
    return pd.DataFrame(
        np.where(valid, gathered, np.nan), index=frame.index, columns=frame.columns
    )


def _rolling_min_by(frame: pd.DataFrame, windows: pd.DataFrame) -> pd.DataFrame:
    """按逐元素窗口长度取最小值，等价于变量窗口的 ``LLV(X, M)``。"""
    import numpy as np

    steps = windows.to_numpy(dtype=float)
    finite = steps[np.isfinite(steps)]
    max_step = int(np.nanmax(finite)) if finite.size else 0
    max_step = max(0, min(max_step, 250))
    result = frame.copy()
    for step in range(1, max_step + 1):
        shifted = frame.shift(step)
        applies = steps >= step
        result = pd.DataFrame(
            np.where(
                applies,
                np.fmin(result.to_numpy(dtype=float), shifted.to_numpy(dtype=float)),
                result.to_numpy(dtype=float),
            ),
            index=frame.index,
            columns=frame.columns,
        )
    return result


register(HaidiLaoyue())
