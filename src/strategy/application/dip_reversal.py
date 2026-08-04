"""RSI 超卖后的次日低吸反转策略。"""
from __future__ import annotations

from typing import Any

import pandas as pd

from src.formula import RSI
from src.strategy.domain.base import SignalResult, merge_params, register


class Rsi30DipPicker:
    """RSI 超卖且强势收盘后的次日低吸。"""

    slug = "rsi30-dip"
    name = "RSI22 次日低吸"
    description = (
        "RSI14<22 + 收阳 + 收盘位于当日区间上方 20%，默认主板+创业板，"
        "T+1 回撤 2% 预挂低吸，"
        "成交后持有至 T+2 收盘"
    )
    entry_instructions = (
        "T 日收盘后 15:30 选出：RSI14<22、收阳、收盘位于日内振幅上方 20%、股价不低于 5 元。"
        "T+1 以 T 日收盘价的 98% 预挂低吸：低开低于挂价按开盘价成交，"
        "否则最低价触及挂价才买，未触价不买。"
    )
    entry_timing = "next_dip"
    strategy_revision = "builtin:rsi30-dip-v2"
    version = "v2"
    version_history = [
        {"version": "v2", "status": "active", "source": "builtin"},
    ]
    backtest_metrics = {
        "trades": 64,
        "win_rate": 67.19,
        "avg_net_return": 2.8626,
        "profit_factor": 2.649,
    }
    backtest_config = {
        "start": "2026-02-01",
        "end": "2026-07-31",
        "adjust": "qfq",
        "hold_days": 3,
        "stop_loss_pct": -6.0,
        "take_profit_pct": None,
        "benchmark": None,
    }
    default_universe = {"preset": "default_a_share", "boards": ["main", "chi_next"]}
    # RSI 的 SMA 是递推值；短窗口会让同一交易日的信号随加载起点漂移。
    warmup_bars = 100

    def default_params(self) -> dict[str, Any]:
        return {
            "rsi_max": 22.0,
            "close_position_min": 0.80,
            "price_min": 5.0,
            "dip_pct": 0.02,
        }

    def required_fields(self) -> tuple[str, ...]:
        return ("open", "high", "low", "close")

    def min_bars(self) -> int:
        return 20

    def compute(
        self, panels: dict[str, pd.DataFrame], params: dict[str, Any] | None = None
    ) -> SignalResult:
        p = merge_params(self, params)
        open_, high, low, close = (
            panels["open"],
            panels["high"],
            panels["low"],
            panels["close"],
        )

        rsi14 = RSI(close, 14)
        day_range = high - low
        close_position = ((close - low) / day_range).where(day_range > 0)
        bullish = close > open_
        oversold = rsi14 < float(p["rsi_max"])
        price_ok = close >= float(p["price_min"])
        position_ok = close_position > float(p["close_position_min"])
        dip_price = close * (1.0 - float(p["dip_pct"]))
        signals = (oversold & bullish & position_ok & price_ok).fillna(False)

        return SignalResult(
            signals=signals,
            factors={
                "RSI14": rsi14,
                "收阳": bullish,
                "收盘位置": close_position,
                "价格门槛": price_ok,
                "次日挂价": dip_price,
            },
        )


register(Rsi30DipPicker())
