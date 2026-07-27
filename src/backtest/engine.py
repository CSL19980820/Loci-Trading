"""信号级回测引擎。

## 前视偏差的两面

回测里有两类"看未来"，一类是致命错误，一类是必需的：

- **信号计算看未来 = 作弊。** 用今天收盘后才知道的数据去决定今天买什么，
  回测曲线会很漂亮但一分钱赚不到。由 ``tests/test_strategies.py`` 的
  信号截断一致性测试把守。
- **结果计算看未来 = 天经地义。** 想知道这笔交易赚没赚，当然要看之后
  发生了什么。本模块做的就是这件事。

两者必须在代码上物理分开：策略只吐信号，本模块只吃信号吐结果，中间不
交换任何信息。这样"作弊"就无处发生——策略拿不到未来数据，回测器不参与
选股决策。

## A 股规则

不实现这些，回测收益会系统性虚高：

- **T+1**：当日买入当日不可卖，最短持有一个交易日。
- **涨停买不进**：开盘即涨停且全天一字（high == low）时无法成交，跳过
  该信号而不是假装买到了。
- **跌停卖不出**：触发退出条件当天若是一字跌停，顺延到下一个能成交的日子。
- **停牌**：成交量为 0 的交易日不可成交。
- **成本**：双边佣金 + 卖出印花税 + 滑点。个人账户单边万三、印花税千一，
  一趟下来约 0.2-0.3%，对短持有期策略足以吃掉大半利润。

## 口径

单笔信号独立评估，不做组合层面的资金约束——先回答"这个战法本身有没有
alpha"，再谈"用多少仓位去打"。组合级资金曲线由 equity 模块另做。
"""
from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any

import numpy as np
import pandas as pd

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


@dataclass
class BacktestResult:
    strategy_slug: str
    config: dict[str, Any]
    trades: list[Trade] = field(default_factory=list)
    skipped: dict[str, int] = field(default_factory=dict)
    metrics: dict[str, Any] = field(default_factory=dict)

    def to_frame(self) -> pd.DataFrame:
        if not self.trades:
            return pd.DataFrame()
        frame = pd.DataFrame([asdict(trade) for trade in self.trades])
        frame["alpha_pct"] = [trade.alpha_pct for trade in self.trades]
        return frame

    def summary(self) -> str:
        if not self.trades:
            reason = "，".join(f"{k}={v}" for k, v in self.skipped.items()) or "无信号"
            return f"[{self.strategy_slug}] 没有可评估的交易（{reason}）"
        m = self.metrics
        return (
            f"[{self.strategy_slug}] {m['trades']} 笔  "
            f"胜率 {m['win_rate']:.1f}%  "
            f"净收益均值 {m['avg_net_return']:+.2f}%  "
            f"期望 {m['expectancy']:+.2f}%  "
            f"盈亏比 {m['profit_factor']}  "
            f"MFE均值 {m['avg_mfe']:+.2f}%  MAE均值 {m['avg_mae']:+.2f}%"
        )


def _forward_extreme(panel: pd.DataFrame, window: int, *, highest: bool) -> pd.DataFrame:
    """未来 window 根（含当根）的最高/最低。

    这是**故意向前看**的——用于计算已发生交易的 MFE/MAE，不参与任何信号
    判断。实现上是把 rolling 的结果整体前移，等价于 [t, t+window-1] 的极值。
    """
    rolled = panel.rolling(window, min_periods=1).max() if highest else panel.rolling(
        window, min_periods=1
    ).min()
    return rolled.shift(-(window - 1))


def run_backtest(
    signals: pd.DataFrame,
    panels: dict[str, pd.DataFrame],
    *,
    entry_timing: str,
    config: BacktestConfig | None = None,
    strategy_slug: str = "",
    benchmark_close: pd.Series | None = None,
) -> BacktestResult:
    """对信号面板跑回测。

    signals 与 panels 必须同形（同一批交易日与股票）。entry_timing 由策略
    声明，不由调用方随意指定——见 src/strategies/base.py 的说明。
    """
    cfg = config or BacktestConfig()
    result = BacktestResult(strategy_slug=strategy_slug, config=asdict(cfg))

    if signals.empty:
        result.skipped["无信号"] = 0
        return result

    open_ = panels["open"]
    high = panels["high"]
    low = panels["low"]
    close = panels["close"]
    volume = panels.get("volume")

    dates = list(signals.index)
    codes = list(signals.columns)
    date_pos = {date: i for i, date in enumerate(dates)}

    open_a = open_.to_numpy(dtype=float)
    high_a = high.to_numpy(dtype=float)
    low_a = low.to_numpy(dtype=float)
    close_a = close.to_numpy(dtype=float)
    volume_a = volume.to_numpy(dtype=float) if volume is not None else None

    # 一字板：全天最高等于最低。涨停一字买不进、跌停一字卖不出。
    one_word = np.isclose(high_a, low_a) & np.isfinite(high_a)

    # 三种入场时点对应两个自由度：哪一天、用哪个价。
    #   open      当日开盘（9:25 竞价筛出来的，开盘就能买）
    #   close     当日收盘（14:50 左右筛，收盘价成交）
    #   next_open 次日开盘（盘后筛，只能等下一个交易日）
    # 把 close 拿 next_open 凑是错的：少等一天的同时还按错的价成交，
    # 回测收益会系统性偏离，且偏离方向不固定，事后无法校正。
    if entry_timing == "next_open":
        entry_offset, entry_at_close = 1, False
    elif entry_timing == "close":
        entry_offset, entry_at_close = 0, True
    else:
        entry_offset, entry_at_close = 0, False
    entry_prices = close_a if entry_at_close else open_a
    skipped: dict[str, int] = {}

    def skip(reason: str) -> None:
        skipped[reason] = skipped.get(reason, 0) + 1

    signal_rows, signal_cols = np.nonzero(signals.fillna(False).to_numpy(dtype=bool))
    trades: list[Trade] = []

    for row, col in zip(signal_rows, signal_cols):
        entry_idx = row + entry_offset
        if entry_idx >= len(dates):
            skip("入场日超出数据范围")
            continue

        entry_price = entry_prices[entry_idx, col]
        if not np.isfinite(entry_price) or entry_price <= 0:
            skip("入场日无行情（停牌或缺数据）")
            continue
        if volume_a is not None and not volume_a[entry_idx, col] > 0:
            skip("入场日停牌")
            continue
        if one_word[entry_idx, col] and not cfg.allow_limit_up_entry:
            skip("入场日一字板买不进")
            continue

        # T+1：最早在入场次日才能卖出。
        first_exit = entry_idx + max(1, cfg.hold_days)
        exit_idx, exit_price, reason = _resolve_exit(
            col=col,
            entry_idx=entry_idx,
            entry_price=entry_price,
            planned_exit=first_exit,
            cfg=cfg,
            high_a=high_a,
            low_a=low_a,
            close_a=close_a,
            one_word=one_word,
            volume_a=volume_a,
            last_index=len(dates) - 1,
        )
        if exit_idx is None:
            skip("持有期内始终无法卖出")
            continue

        window = slice(entry_idx, exit_idx + 1)
        highs = high_a[window, col]
        lows = low_a[window, col]
        mfe = (np.nanmax(highs) / entry_price - 1) * 100 if highs.size else 0.0
        mae = (np.nanmin(lows) / entry_price - 1) * 100 if lows.size else 0.0

        gross = (exit_price / entry_price - 1) * 100
        net = gross - cfg.round_trip_cost_pct()

        bench = None
        if benchmark_close is not None:
            bench = _benchmark_return(
                benchmark_close, dates[entry_idx], dates[exit_idx]
            )

        trades.append(
            Trade(
                code=codes[col],
                signal_date=dates[row],
                entry_date=dates[entry_idx],
                entry_price=round(float(entry_price), 4),
                exit_date=dates[exit_idx],
                exit_price=round(float(exit_price), 4),
                hold_days=int(exit_idx - entry_idx),
                gross_return_pct=round(float(gross), 4),
                net_return_pct=round(float(net), 4),
                mae_pct=round(float(mae), 4),
                mfe_pct=round(float(mfe), 4),
                exit_reason=reason,
                benchmark_return_pct=bench,
            )
        )

    result.trades = trades
    result.skipped = skipped
    result.metrics = compute_metrics(trades)
    return result


def _resolve_exit(
    *,
    col: int,
    entry_idx: int,
    entry_price: float,
    planned_exit: int,
    cfg: BacktestConfig,
    high_a: np.ndarray,
    low_a: np.ndarray,
    close_a: np.ndarray,
    one_word: np.ndarray,
    volume_a: np.ndarray | None,
    last_index: int,
) -> tuple[int | None, float, str]:
    """决定退出日与退出价。

    优先级：先看持有期内有没有触发止损/止盈，没有就到期按收盘了结。
    触发日若是一字跌停或停牌则顺延——那天挂单也卖不掉，假装卖掉就是
    在给回测注水。
    """
    stop_price = (
        entry_price * (1 + cfg.stop_loss_pct / 100.0) if cfg.stop_loss_pct is not None else None
    )
    target_price = (
        entry_price * (1 + cfg.take_profit_pct / 100.0)
        if cfg.take_profit_pct is not None
        else None
    )

    # T+1：入场次日起才可能卖出。
    for idx in range(entry_idx + 1, min(planned_exit, last_index) + 1):
        if stop_price is not None and low_a[idx, col] <= stop_price:
            price, resolved = _tradable_exit(
                col, idx, stop_price, cfg, close_a, one_word, volume_a, last_index
            )
            if resolved is not None:
                return resolved, price, "stop_loss"
        if target_price is not None and high_a[idx, col] >= target_price:
            price, resolved = _tradable_exit(
                col, idx, target_price, cfg, close_a, one_word, volume_a, last_index
            )
            if resolved is not None:
                return resolved, price, "take_profit"

    if planned_exit > last_index:
        # 数据到头了：按最后一根收盘结算，并标记原因，避免混进"到期了结"。
        return last_index, float(close_a[last_index, col]), "data_end"

    price, resolved = _tradable_exit(
        col, planned_exit, None, cfg, close_a, one_word, volume_a, last_index
    )
    if resolved is None:
        return None, 0.0, "hold_expired"
    return resolved, price, "hold_expired"


def _tradable_exit(
    col: int,
    idx: int,
    limit_price: float | None,
    cfg: BacktestConfig,
    close_a: np.ndarray,
    one_word: np.ndarray,
    volume_a: np.ndarray | None,
    last_index: int,
) -> tuple[float, int | None]:
    """从 idx 起找第一个真的能成交的日子。一字跌停/停牌顺延。"""
    for candidate in range(idx, last_index + 1):
        suspended = volume_a is not None and not volume_a[candidate, col] > 0
        if suspended or one_word[candidate, col]:
            continue
        price = limit_price if candidate == idx and limit_price is not None else close_a[
            candidate, col
        ]
        if not np.isfinite(price):
            continue
        return float(price), candidate
    return 0.0, None


def _benchmark_return(
    benchmark_close: pd.Series, entry_date: str, exit_date: str
) -> float | None:
    if entry_date not in benchmark_close.index or exit_date not in benchmark_close.index:
        return None
    start = float(benchmark_close.loc[entry_date])
    end = float(benchmark_close.loc[exit_date])
    if not np.isfinite(start) or start <= 0 or not np.isfinite(end):
        return None
    return round((end / start - 1) * 100, 4)


def compute_metrics(trades: list[Trade]) -> dict[str, Any]:
    """把交易列表压成一组可比较的绩效指标。

    刻意同时给出绝对收益与市场调整后的超额：项目此前那份手工回测就
    发现过"观察档绝对 +0.3% 看着很差，市场调整后其实是 +1.9% 正超额"
    ——只看绝对收益会把择时问题误判成选股问题。
    """
    if not trades:
        return {"trades": 0}

    net = np.array([t.net_return_pct for t in trades], dtype=float)
    gross = np.array([t.gross_return_pct for t in trades], dtype=float)
    mae = np.array([t.mae_pct for t in trades], dtype=float)
    mfe = np.array([t.mfe_pct for t in trades], dtype=float)
    hold = np.array([t.hold_days for t in trades], dtype=float)

    wins = net[net > 0]
    losses = net[net <= 0]
    win_rate = len(wins) / len(net) * 100

    profit_factor = None
    if losses.size and abs(losses.sum()) > 1e-9:
        profit_factor = round(float(wins.sum() / abs(losses.sum())), 3)
    elif wins.size:
        profit_factor = float("inf")

    alphas = [t.alpha_pct for t in trades if t.alpha_pct is not None]

    metrics: dict[str, Any] = {
        "trades": len(trades),
        "win_rate": round(float(win_rate), 2),
        "wins": int(len(wins)),
        "losses": int(len(losses)),
        "avg_gross_return": round(float(gross.mean()), 4),
        "avg_net_return": round(float(net.mean()), 4),
        "median_net_return": round(float(np.median(net)), 4),
        "best": round(float(net.max()), 4),
        "worst": round(float(net.min()), 4),
        "expectancy": round(float(net.mean()), 4),
        "profit_factor": profit_factor,
        "avg_win": round(float(wins.mean()), 4) if wins.size else None,
        "avg_loss": round(float(losses.mean()), 4) if losses.size else None,
        "avg_mfe": round(float(mfe.mean()), 4),
        "avg_mae": round(float(mae.mean()), 4),
        "avg_hold_days": round(float(hold.mean()), 2),
        "exit_reasons": _count_by(trades, lambda t: t.exit_reason),
    }

    if alphas:
        alpha_array = np.array(alphas, dtype=float)
        metrics["avg_alpha"] = round(float(alpha_array.mean()), 4)
        metrics["alpha_win_rate"] = round(float((alpha_array > 0).mean() * 100), 2)

    # 小样本时给出提示，避免把 7 笔交易的均值当成结论。
    if len(trades) < 30:
        metrics["caution"] = (
            f"样本仅 {len(trades)} 笔，统计量不稳定，不宜据此外推"
        )
    return metrics


def _count_by(trades: list[Trade], key) -> dict[str, int]:
    out: dict[str, int] = {}
    for trade in trades:
        value = key(trade)
        out[value] = out.get(value, 0) + 1
    return out
