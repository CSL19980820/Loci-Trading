"""回测领域值对象：成交配置与单笔交易。"""
from __future__ import annotations

from dataclasses import dataclass

#: 退出原因。用于归因："赚的钱是止盈拿到的还是到期拿到的"含义完全不同。
EXIT_REASONS = ("hold_expired", "stop_loss", "take_profit", "data_end")


@dataclass
class BacktestConfig:
    """回测参数。默认值面向短持有期的突破型战法。"""

    hold_days: int = 3
    """固定持有交易日数。到期按收盘价了结。"""

    stop_loss_pct: float | None = -6.0
    """止损线（相对开仓价的百分比，负数）。None 表示不设。"""

    take_profit_pct: float | None = None
    """止盈线。None 表示只靠持有期到期了结。"""

    commission_bps: float = 3.0
    """单边佣金，基点。万三 = 3bps。"""

    stamp_duty_bps: float = 10.0
    """卖出印花税，基点。千一 = 10bps，只在卖出收取。"""

    slippage_bps: float = 5.0
    """单边滑点，基点。开盘成交的实际价格通常比看到的差一点。"""

    allow_limit_up_entry: bool = False
    """是否允许在一字涨停日入场。默认否——那天根本买不到。"""

    benchmark: str | None = "000300"
    """基准指数代码，用于算超额收益。None 表示不比。"""

    def round_trip_cost_pct(self) -> float:
        """一趟买卖的总成本（百分比）。"""
        return (
            self.commission_bps * 2 + self.stamp_duty_bps + self.slippage_bps * 2
        ) / 100.0


@dataclass
class Trade:
    """一笔完整的信号→入场→退出记录。"""

    code: str
    signal_date: str
    entry_date: str
    entry_price: float
    exit_date: str
    exit_price: float
    hold_days: int
    gross_return_pct: float
    net_return_pct: float
    mae_pct: float
    mfe_pct: float
    exit_reason: str
    benchmark_return_pct: float | None = None

    @property
    def alpha_pct(self) -> float | None:
        """相对基准的超额。绝对收益会被大盘涨跌掩盖真实水平。"""
        if self.benchmark_return_pct is None:
            return None
        return round(self.net_return_pct - self.benchmark_return_pct, 4)
