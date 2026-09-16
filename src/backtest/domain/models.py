"""回测领域值对象：成交配置与单笔交易。"""
from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import date
import re

#: 退出原因。用于归因："赚的钱是止盈拿到的还是到期拿到的"含义完全不同。
EXIT_REASONS = ("hold_expired", "stop_loss", "take_profit", "data_end")


@dataclass
class BacktestConfig:
    """回测参数。默认值面向短持有期的突破型战法。"""

    hold_days: int = 3
    """入场后经过的市场交易日数；9表示入场日计第1日、第10日收盘退出。"""

    stop_loss_pct: float | None = -6.0
    """止损线（相对开仓价的百分比，负数）。None 表示不设。"""

    take_profit_pct: float | None = None
    """止盈线。None 表示只靠持有期到期了结。"""

    commission_bps: float = 3.0
    """单边佣金，基点。万三 = 3bps。"""

    stamp_duty_bps: float = 10.0
    """实验中的卖出税费基点；默认值为历史兼容参数，不代表现行法定税率。"""

    slippage_bps: float = 5.0
    """单边滑点，基点。开盘成交的实际价格通常比看到的差一点。"""

    allow_limit_up_entry: bool = False
    """是否允许在一字涨停日入场。默认否——那天根本买不到。"""

    benchmark: str | None = "000300"
    """基准指数代码，用于算超额收益。None 表示不比。"""

    strict_limit_prices: bool = False
    """拒绝涨停开盘买入；收盘跌停时延期退出。优先于允许一字板入场。"""

    economic_returns: bool = False
    """保留原始成交价，使用显式复权因子计算经济收益与价格触发条件。"""

    valuation_end: str | None = None
    """执行与估值截止日；未完成交易以data_end记录，不能当作已平仓。"""

    signal_dataset: str | None = None
    """由runner解析的租户内信号数据集ID，不是文件路径。"""

    def __post_init__(self) -> None:
        for name in ("strict_limit_prices", "economic_returns"):
            if not isinstance(getattr(self, name), bool):
                raise ValueError(f"{name} 必须为布尔值")
        if self.valuation_end is not None:
            if not isinstance(self.valuation_end, str) or not re.fullmatch(r"\d{4}-\d{2}-\d{2}", self.valuation_end):
                raise ValueError("valuation_end 必须为 YYYY-MM-DD")
            date.fromisoformat(self.valuation_end)
        if self.signal_dataset is not None and (
            not isinstance(self.signal_dataset, str)
            or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_-]{0,95}", self.signal_dataset)
        ):
            raise ValueError("signal_dataset 必须为安全的数据集ID")

    def round_trip_cost_pct(self) -> float:
        """一趟买卖的总成本（百分比）。"""
        return (
            self.commission_bps * 2 + self.stamp_duty_bps + self.slippage_bps * 2
        ) / 100.0

    def to_dict(self) -> dict[str, object]:
        """默认输出保持旧冻结契约；只附加实际启用的新配置。"""
        body = asdict(self)
        for key in ("strict_limit_prices", "economic_returns", "valuation_end", "signal_dataset"):
            if body[key] is False or body[key] is None:
                body.pop(key)
        return body


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
    entry_factor: float = 1.0
    exit_factor: float = 1.0

    def to_dict(self, *, include_factors: bool = False) -> dict[str, object]:
        """旧交易字段默认不变；经济价格回放显式携带因子。"""
        body = asdict(self)
        if not include_factors:
            body.pop("entry_factor")
            body.pop("exit_factor")
        return body

    @property
    def alpha_pct(self) -> float | None:
        """相对基准的超额。绝对收益会被大盘涨跌掩盖真实水平。"""
        if self.benchmark_return_pct is None:
            return None
        return round(self.net_return_pct - self.benchmark_return_pct, 4)
