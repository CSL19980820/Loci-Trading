"""信号级成交绩效指标（无组合资金假设）。

从 ``Trade`` 明细即时推导，不落库。``data_end`` 仅披露笔数，不混入收益口径。
"""
from __future__ import annotations

from typing import Any, Callable, Sequence

import numpy as np

from src.backtest.domain.models import Trade

#: 样本可信度阈值（可评估笔数）。
SAMPLE_LOW = 30
SAMPLE_MEDIUM = 100


def compute_metrics(trades: list[Trade]) -> dict[str, Any]:
    """把交易列表压成一组可比较的绩效指标。

    刻意同时给出绝对收益与市场调整后的超额：项目此前那份手工回测就
    发现过"观察档绝对 +0.3% 看着很差，市场调整后其实是 +1.9% 正超额"
    ——只看绝对收益会把择时问题误判成选股问题。

    ``data_end`` 交易保留在结果明细中供审计，但未覆盖完整持有期，不能
    混入收益、胜率或 MFE/MAE；数量通过 ``data_end_trades`` 单独披露。
    """
    evaluable = [trade for trade in trades if trade.exit_reason != "data_end"]
    data_end_trades = len(trades) - len(evaluable)
    if not evaluable:
        if not data_end_trades:
            return {"trades": 0}
        return {"trades": 0, "data_end_trades": data_end_trades}

    net = np.array([t.net_return_pct for t in evaluable], dtype=float)
    gross = np.array([t.gross_return_pct for t in evaluable], dtype=float)
    mae = np.array([t.mae_pct for t in evaluable], dtype=float)
    mfe = np.array([t.mfe_pct for t in evaluable], dtype=float)
    hold = np.array([t.hold_days for t in evaluable], dtype=float)

    wins = net[net > 0]
    losses = net[net <= 0]
    win_rate = len(wins) / len(net) * 100

    profit_factor = None
    if losses.size and abs(losses.sum()) > 1e-9:
        profit_factor = round(float(wins.sum() / abs(losses.sum())), 3)
    elif wins.size:
        profit_factor = float("inf")

    payoff_ratio = None
    if wins.size and losses.size and abs(float(losses.mean())) > 1e-9:
        payoff_ratio = round(float(wins.mean() / abs(losses.mean())), 3)

    alphas = [t.alpha_pct for t in evaluable if t.alpha_pct is not None]
    max_win_streak, max_loss_streak = _streak_extremes(net)

    metrics: dict[str, Any] = {
        "trades": len(evaluable),
        "win_rate": round(float(win_rate), 2),
        "wins": int(len(wins)),
        "losses": int(len(losses)),
        "avg_gross_return": round(float(gross.mean()), 4),
        "avg_net_return": round(float(net.mean()), 4),
        "median_net_return": round(float(np.median(net)), 4),
        "std_net_return": round(float(net.std(ddof=1)), 4) if net.size > 1 else 0.0,
        "total_net_return": round(float(net.sum()), 4),
        "best": round(float(net.max()), 4),
        "worst": round(float(net.min()), 4),
        "expectancy": round(float(net.mean()), 4),
        "profit_factor": profit_factor,
        "payoff_ratio": payoff_ratio,
        "avg_win": round(float(wins.mean()), 4) if wins.size else None,
        "avg_loss": round(float(losses.mean()), 4) if losses.size else None,
        "avg_mfe": round(float(mfe.mean()), 4),
        "avg_mae": round(float(mae.mean()), 4),
        "avg_hold_days": round(float(hold.mean()), 2),
        "max_consecutive_wins": max_win_streak,
        "max_consecutive_losses": max_loss_streak,
        "exit_reasons": _count_by(evaluable, lambda t: t.exit_reason),
        "data_end_trades": data_end_trades,
        "percentiles": _percentiles(net),
        "return_distribution": _histogram_bins(net),
        "by_month": _group_returns_by_month(evaluable),
        "by_year": _group_returns_by_year(evaluable),
        "sample_confidence": _sample_confidence(len(evaluable)),
    }

    if alphas:
        alpha_array = np.array(alphas, dtype=float)
        metrics["avg_alpha"] = round(float(alpha_array.mean()), 4)
        metrics["alpha_win_rate"] = round(float((alpha_array > 0).mean() * 100), 2)

    if len(evaluable) < SAMPLE_LOW:
        metrics["caution"] = (
            f"样本仅 {len(evaluable)} 笔，统计量不稳定，不宜据此外推"
        )
    return metrics


def summarize_return_array(values: Sequence[float]) -> dict[str, Any]:
    """对任意收益序列做无假设聚合（horizon / 诊断共用）。"""
    if not values:
        return {"n": 0}
    arr = np.asarray(values, dtype=float)
    arr = arr[np.isfinite(arr)]
    if arr.size == 0:
        return {"n": 0}
    wins = arr[arr > 0]
    losses = arr[arr <= 0]
    win_rate = float(wins.size / arr.size * 100.0)
    payoff_ratio = None
    if wins.size and losses.size and abs(float(losses.mean())) > 1e-9:
        payoff_ratio = round(float(wins.mean() / abs(losses.mean())), 3)
    body: dict[str, Any] = {
        "n": int(arr.size),
        "win_rate": round(win_rate, 2),
        "avg": round(float(arr.mean()), 4),
        "median": round(float(np.median(arr)), 4),
        "std": round(float(arr.std(ddof=1)), 4) if arr.size > 1 else 0.0,
        "best": round(float(arr.max()), 4),
        "worst": round(float(arr.min()), 4),
        "avg_win": round(float(wins.mean()), 4) if wins.size else None,
        "avg_loss": round(float(losses.mean()), 4) if losses.size else None,
        "payoff_ratio": payoff_ratio,
        "percentiles": _percentiles(arr),
        "distribution": _histogram_bins(arr),
        "sample_confidence": _sample_confidence(int(arr.size)),
    }
    if arr.size < SAMPLE_LOW:
        body["caution"] = f"样本仅 {arr.size} 笔，统计量不稳定，不宜据此外推"
    return body


def _sample_confidence(n: int) -> str:
    if n < SAMPLE_LOW:
        return "low"
    if n < SAMPLE_MEDIUM:
        return "medium"
    return "high"


def _percentiles(arr: np.ndarray) -> dict[str, float]:
    if arr.size == 0:
        return {}
    qs = (10, 25, 50, 75, 90)
    values = np.percentile(arr, qs)
    return {f"p{q}": round(float(v), 4) for q, v in zip(qs, values)}


def _histogram_bins(arr: np.ndarray, *, bin_width: float = 2.0) -> list[dict[str, Any]]:
    """等宽分箱；宽度默认 2 个百分点，便于前端画直方。"""
    if arr.size == 0:
        return []
    lo = float(np.floor(arr.min() / bin_width) * bin_width)
    hi = float(np.ceil(arr.max() / bin_width) * bin_width)
    if hi <= lo:
        hi = lo + bin_width
    edges = np.arange(lo, hi + bin_width * 0.5, bin_width)
    counts, edges = np.histogram(arr, bins=edges)
    out: list[dict[str, Any]] = []
    for i, count in enumerate(counts):
        out.append(
            {
                "lo": round(float(edges[i]), 4),
                "hi": round(float(edges[i + 1]), 4),
                "n": int(count),
            }
        )
    return out


def _streak_extremes(net: np.ndarray) -> tuple[int, int]:
    max_win = max_loss = cur_win = cur_loss = 0
    for value in net:
        if value > 0:
            cur_win += 1
            cur_loss = 0
            max_win = max(max_win, cur_win)
        else:
            cur_loss += 1
            cur_win = 0
            max_loss = max(max_loss, cur_loss)
    return max_win, max_loss


def _group_returns_by_month(trades: Sequence[Trade]) -> list[dict[str, Any]]:
    buckets: dict[str, list[float]] = {}
    for trade in trades:
        key = str(trade.exit_date)[:7]
        buckets.setdefault(key, []).append(float(trade.net_return_pct))
    return _finalize_period_buckets(buckets)


def _group_returns_by_year(trades: Sequence[Trade]) -> list[dict[str, Any]]:
    buckets: dict[str, list[float]] = {}
    for trade in trades:
        key = str(trade.exit_date)[:4]
        buckets.setdefault(key, []).append(float(trade.net_return_pct))
    return _finalize_period_buckets(buckets)


def _finalize_period_buckets(buckets: dict[str, list[float]]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for period in sorted(buckets):
        arr = np.asarray(buckets[period], dtype=float)
        wins = int(np.sum(arr > 0))
        rows.append(
            {
                "period": period,
                "n": int(arr.size),
                "win_rate": round(float(wins / arr.size * 100.0), 2),
                "avg": round(float(arr.mean()), 4),
                "total": round(float(arr.sum()), 4),
            }
        )
    return rows


def _count_by(trades: Sequence[Trade], key: Callable[[Trade], str]) -> dict[str, int]:
    out: dict[str, int] = {}
    for trade in trades:
        value = key(trade)
        out[value] = out.get(value, 0) + 1
    return out
