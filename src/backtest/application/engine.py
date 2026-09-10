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
  一字**涨停**不在此列——涨停价上有买盘，卖得掉。
- **跳空不按限价成交**：低开穿过止损位只能按开盘价出，高开越过止盈价则卖
  在更高的开盘价。按限价记账会让偏差单向堆在最差的那批交易上。
- **停牌**：成交量为 0 的交易日不可成交。
- **成本**：双边佣金 + 卖出印花税 + 滑点。个人账户单边万三、印花税千一，
  一趟下来约 0.2-0.3%，对短持有期策略足以吃掉大半利润。

## 口径

单笔信号独立评估，不做组合层面的资金约束——先回答"这个战法本身有没有
alpha"，再谈"用多少仓位去打"。诊断用顺序复利曲线见 ``performance``；
真实槽位组合见 ``research_portfolio``。
"""
from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any

import numpy as np
import pandas as pd

from src.backtest.application.metrics import compute_metrics
from src.backtest.application.performance import compute_trade_performance
from src.backtest.domain.models import EXIT_REASONS, BacktestConfig, Trade

__all__ = [
    "EXIT_REASONS",
    "BacktestConfig",
    "BacktestResult",
    "Trade",
    "compute_metrics",
    "run_backtest",
]


@dataclass
class BacktestResult:
    strategy_slug: str
    config: dict[str, Any]
    trades: list[Trade] = field(default_factory=list)
    skipped: dict[str, int] = field(default_factory=dict)
    metrics: dict[str, Any] = field(default_factory=dict)
    performance: dict[str, Any] = field(default_factory=dict)

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


def _one_word_masks(
    high_a: np.ndarray, low_a: np.ndarray, close_a: np.ndarray
) -> tuple[np.ndarray, np.ndarray]:
    """把一字板拆成涨停一字与跌停一字。

    方向由收盘与前收比较得出。一字涨停买不进但**卖得掉**（涨停价上有买盘），
    一字跌停才是卖不出——两者共用一个方向无关的掩码，会把一字涨停日的了结
    推到下一个交易日按收盘价结算，系统性低估打板类策略。

    首行没有前收，方向未知时两边都算上，保持"不确定就不撮合"的保守口径。
    """
    one_word = np.isclose(high_a, low_a) & np.isfinite(high_a)
    prev_close = np.full_like(close_a, np.nan)
    prev_close[1:] = close_a[:-1]
    unknown = ~np.isfinite(prev_close)
    return (
        one_word & (unknown | (close_a > prev_close)),
        one_word & (unknown | (close_a < prev_close)),
    )


def run_backtest(
    signals: pd.DataFrame,
    panels: dict[str, pd.DataFrame],
    *,
    entry_timing: str,
    entry_price_panel: pd.DataFrame | None = None,
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

    open_a = open_.to_numpy(dtype=float)
    high_a = high.to_numpy(dtype=float)
    low_a = low.to_numpy(dtype=float)
    close_a = close.to_numpy(dtype=float)
    volume_a = volume.to_numpy(dtype=float) if volume is not None else None

    # 一字板：全天最高等于最低。涨停一字买不进、跌停一字卖不出。
    one_word_up, one_word_down = _one_word_masks(high_a, low_a, close_a)

    # 三种入场时点对应两个自由度：哪一天、用哪个价。
    #   open      当日开盘（9:25 竞价筛出来的，开盘就能买）
    #   close     当日收盘（14:50 左右筛，收盘价成交）
    #   next_open 次日开盘（盘后筛，只能等下一个交易日）
    #   next_dip 次日低吸（T 日生成目标价，T+1 触价才成交）
    # 把 close 拿 next_open 凑是错的：少等一天的同时还按错的价成交，
    # 回测收益会系统性偏离，且偏离方向不固定，事后无法校正。
    entry_price_a: np.ndarray | None = None
    if entry_timing == "next_dip":
        if entry_price_panel is None:
            raise ValueError("entry_timing=next_dip 必须提供 entry_price_panel")
        entry_price_a = entry_price_panel.reindex(
            index=signals.index, columns=signals.columns
        ).to_numpy(dtype=float)

    if entry_timing in {"next_open", "next_dip"}:
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
    cost = cfg.round_trip_cost_pct()

    for row, col in zip(signal_rows.tolist(), signal_cols.tolist()):
        entry_idx = row + entry_offset
        if entry_idx >= len(dates):
            skip("入场日超出数据范围")
            continue

        if volume_a is not None and not volume_a[entry_idx, col] > 0:
            skip("入场日停牌")
            continue
        if one_word_up[entry_idx, col] and not cfg.allow_limit_up_entry:
            skip("入场日一字板买不进")
            continue

        if entry_timing == "next_dip":
            assert entry_price_a is not None
            target_price = entry_price_a[row, col]
            next_low = low_a[entry_idx, col]
            next_open = open_a[entry_idx, col]
            if not np.isfinite(target_price) or target_price <= 0:
                skip("次日低吸价无效")
                continue
            if np.isfinite(next_open) and next_open <= target_price:
                entry_price = next_open
            elif np.isfinite(next_low) and next_low <= target_price:
                entry_price = target_price
            else:
                skip("次日低吸未触价")
                continue
        else:
            entry_price = entry_prices[entry_idx, col]
            if not np.isfinite(entry_price) or entry_price <= 0:
                skip("入场日无行情（停牌或缺数据）")
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
            open_a=open_a,
            one_word_down=one_word_down,
            volume_a=volume_a,
            last_index=len(dates) - 1,
        )
        if exit_idx is None or not np.isfinite(exit_price) or exit_price <= 0:
            skip("持有期内始终无法卖出")
            continue

        window = slice(entry_idx, exit_idx + 1)
        highs = high_a[window, col]
        lows = low_a[window, col]
        mfe = (np.nanmax(highs) / entry_price - 1) * 100 if highs.size else 0.0
        mae = (np.nanmin(lows) / entry_price - 1) * 100 if lows.size else 0.0

        gross = (exit_price / entry_price - 1) * 100
        net = gross - cost

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
    result.performance = compute_trade_performance(trades)
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
    open_a: np.ndarray,
    one_word_down: np.ndarray,
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
    # 没有触价规则时直接到期撮合，避免逐日执行空判断。
    scan_end = min(planned_exit, last_index) if stop_price is not None or target_price is not None else entry_idx
    for idx in range(entry_idx + 1, scan_end + 1):
        if stop_price is not None and low_a[idx, col] <= stop_price:
            price, resolved = _tradable_exit(
                col, idx, stop_price, cfg, close_a, one_word_down, volume_a, last_index,
                open_a=open_a, limit_kind="stop",
            )
            if resolved is not None:
                return resolved, price, "stop_loss"
        if target_price is not None and high_a[idx, col] >= target_price:
            price, resolved = _tradable_exit(
                col, idx, target_price, cfg, close_a, one_word_down, volume_a, last_index,
                open_a=open_a, limit_kind="take",
            )
            if resolved is not None:
                return resolved, price, "take_profit"

    if planned_exit > last_index:
        # 数据到头了：按最后一根收盘结算，并标记原因，避免混进"到期了结"。
        return last_index, float(close_a[last_index, col]), "data_end"

    price, resolved = _tradable_exit(
        col, planned_exit, None, cfg, close_a, one_word_down, volume_a, last_index
    )
    if resolved is None:
        return None, 0.0, "hold_expired"
    return resolved, price, "hold_expired"


def _limit_fill_price(
    limit_price: float,
    open_a: np.ndarray | None,
    idx: int,
    col: int,
    kind: str | None,
) -> float:
    """触发日的真实成交价。

    "当日最低跌破止损价"只说明能成交，不代表能成交在止损价上——跳空低开
    穿过止损位时只能按开盘价出，按止损价记账等于给回测注水，而且偏差全落在
    最差的那批交易上，最大回撤与盈亏比会一起失真。止盈反向同理。
    """
    if open_a is None or kind is None:
        return limit_price
    open_price = float(open_a[idx, col])
    if not np.isfinite(open_price) or open_price <= 0:
        return limit_price
    return min(limit_price, open_price) if kind == "stop" else max(limit_price, open_price)


def _tradable_exit(
    col: int,
    idx: int,
    limit_price: float | None,
    cfg: BacktestConfig,
    close_a: np.ndarray,
    one_word_down: np.ndarray,
    volume_a: np.ndarray | None,
    last_index: int,
    *,
    open_a: np.ndarray | None = None,
    limit_kind: str | None = None,
) -> tuple[float, int | None]:
    """从 idx 起找第一个真的能成交的日子。一字跌停/停牌顺延。"""
    for candidate in range(idx, last_index + 1):
        suspended = volume_a is not None and not volume_a[candidate, col] > 0
        if suspended or one_word_down[candidate, col]:
            continue
        if candidate == idx and limit_price is not None:
            price = _limit_fill_price(limit_price, open_a, candidate, col, limit_kind)
        else:
            price = close_a[candidate, col]
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
