"""筹码分布：通达信 ``COST()`` / ``WINNER()`` 的向量化实现。

## 与现有 calc_chip_distribution 的区别

``src/indicators.py`` 里那个只是"最近 30 日成交量按价格等宽分箱"的直方图：
不衰减、不递推、窗口外的历史直接丢掉。它能画个示意图，但语义和通达信的
``COST()`` 相差很远，不能拿来复刻依赖筹码的公式。

真正的筹码分布是**逐日递推的换手衰减模型**：

    chips(t) = chips(t-1) × (1 − 换手率) + 换手率 × 今日成交价格分布

含义是"每天有换手率那么大比例的筹码换了手，新持有者的成本落在今日价格
区间内"。历史成本因此被逐日稀释而不是被窗口一刀切掉——这才是"低位单峰
密集"这类判断成立的基础。

``COST(p)`` 是从低价往高价累加筹码、达到 p% 时的价格。

## 向量化

递推有状态，只能沿时间轴推进；但每一步对**全部股票 × 全部价格档位**是
一次矩阵运算。循环次数等于交易日数（几百次），不是股票数（几千只）。

内存：状态是 (股票数 × 档位数)，5509 × 100 × 8B ≈ 4.4 MB；输出是每个
分位一张 (交易日 × 股票) 面板。都很小。
"""
from __future__ import annotations

import numpy as np
import pandas as pd

#: 价格档位数。通达信内部用的是逐分价位，那对全市场面板来说太重；
#: 100 档在个股价格区间上通常已细于 1%，足够支撑分位判断。
DEFAULT_BINS = 100

#: 衰减系数。1.0 表示"换手多少就换掉多少筹码"，是通达信默认口径。
DEFAULT_DECAY = 1.0

__all__ = ["COST", "WINNER", "chip_cost_series", "chip_winner_series"]


def _prepare(
    high: pd.DataFrame | pd.Series,
    low: pd.DataFrame | pd.Series,
    close: pd.DataFrame | pd.Series,
    turnover: pd.DataFrame | pd.Series,
) -> tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray, bool]:
    arrays = [np.asarray(item, dtype=float) for item in (high, low, close, turnover)]
    single = arrays[0].ndim == 1
    if single:
        arrays = [item[:, None] for item in arrays]
    shapes = {item.shape for item in arrays}
    if len(shapes) != 1:
        raise ValueError(f"高开低收与换手率的形状必须一致，实际 {shapes}")
    return (*arrays, single)


def _bin_grid(
    high: np.ndarray, low: np.ndarray, bins: int
) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """按每只票自己的历史价格区间划分档位。

    统一用一个全市场价格网格是不行的：2 元的票和 2000 元的票放在同一套
    档位上，前者会全部挤进第一个档位，分位数完全失去意义。
    """
    lo = np.nanmin(low, axis=0)
    hi = np.nanmax(high, axis=0)
    # 上下各留一点余量，避免最高价恰好落在最后一档边界上被丢掉。
    span = np.where(hi > lo, hi - lo, np.maximum(np.abs(hi), 1.0) * 0.01)
    lo = lo - span * 0.01
    hi = hi + span * 0.01
    width = (hi - lo) / bins
    width = np.where(width > 0, width, 1e-9)
    centers = lo[None, :] + (np.arange(bins)[:, None] + 0.5) * width[None, :]
    return lo, width, centers  # centers: (bins, codes)


def _today_weights(
    centers: np.ndarray, low_t: np.ndarray, high_t: np.ndarray, close_t: np.ndarray
) -> np.ndarray:
    """今日成交量在各档位上的分布权重，形状 (bins, codes)，每列和为 1。

    用三角分布而不是均匀分布：通达信的口径是成交越集中在均价附近权重越高。
    一字板（最高=最低）退化为全部落在一个档位。
    """
    peak = (high_t + low_t + close_t) / 3.0
    peak = np.clip(peak, low_t, high_t)

    left = centers - low_t[None, :]
    right = high_t[None, :] - centers
    inside = (left >= 0) & (right >= 0)

    up_span = np.maximum(peak - low_t, 1e-12)
    down_span = np.maximum(high_t - peak, 1e-12)
    rising = np.clip(left / up_span[None, :], 0.0, None)
    falling = np.clip(right / down_span[None, :], 0.0, None)
    weights = np.where(centers <= peak[None, :], rising, falling)
    weights = np.where(inside, weights, 0.0)

    total = weights.sum(axis=0)
    # 一字板或价格区间落在网格外：退化为最接近当日收盘的那一档。
    degenerate = ~(total > 0)
    if degenerate.any():
        nearest = np.argmin(np.abs(centers - close_t[None, :]), axis=0)
        fix = np.zeros_like(weights)
        fix[nearest, np.arange(weights.shape[1])] = 1.0
        weights = np.where(degenerate[None, :], fix, weights)
        total = weights.sum(axis=0)
    return weights / np.where(total > 0, total, 1.0)[None, :]


def _accumulate(
    high: np.ndarray,
    low: np.ndarray,
    close: np.ndarray,
    turnover: np.ndarray,
    *,
    bins: int,
    decay: float,
):
    """逐日推进筹码分布，把每一天的状态交给回调处理。

    不保留全部历史状态：(交易日 × 股票 × 档位) 在全市场规模下是 GB 级
    （250 × 5509 × 100 × 8B ≈ 1.1 GB）。只留当前一层，需要什么当场算完。
    """
    rows, cols = close.shape
    lo, width, centers = _bin_grid(high, low, bins)
    chips = np.zeros((bins, cols), dtype=float)
    started = np.zeros(cols, dtype=bool)

    for t in range(rows):
        close_t = close[t]
        valid = np.isfinite(close_t)
        if valid.any():
            high_t = np.where(np.isfinite(high[t]), high[t], close_t)
            low_t = np.where(np.isfinite(low[t]), low[t], close_t)
            high_t = np.maximum(high_t, low_t)
            weights = _today_weights(centers, low_t, high_t, close_t)

            rate = np.nan_to_num(turnover[t], nan=0.0)
            rate = np.clip(rate * decay, 0.0, 1.0)
            # 首个有效交易日：还没有存量筹码，全部按当日分布建立。
            fresh = valid & ~started
            effective = np.where(fresh, 1.0, rate)
            effective = np.where(valid, effective, 0.0)

            chips = chips * (1.0 - effective)[None, :] + weights * effective[None, :]
            started |= valid

        yield t, chips, centers, started


def chip_cost_series(
    high: pd.DataFrame | pd.Series,
    low: pd.DataFrame | pd.Series,
    close: pd.DataFrame | pd.Series,
    turnover: pd.DataFrame | pd.Series,
    percents: tuple[float, ...] = (15.0, 50.0, 85.0),
    *,
    bins: int = DEFAULT_BINS,
    decay: float = DEFAULT_DECAY,
) -> dict[float, pd.DataFrame]:
    """一次递推同时算出多个分位，避免为 COST(15)/COST(50)/COST(85) 跑三遍。"""
    high_a, low_a, close_a, turnover_a, single = _prepare(high, low, close, turnover)
    rows, cols = close_a.shape
    targets = np.asarray(percents, dtype=float) / 100.0
    out = {percent: np.full((rows, cols), np.nan) for percent in percents}

    # 完全没有换手率数据的标的必须整列作废。
    # 缺失换手率会让衰减率变成 0，筹码分布永远停在第一天的价格分布上——
    # 算出来是个看着正常、实则毫无意义的数字。这种静默的错误答案
    # 比直接报错危险得多，因为它会一路流进选股结果。
    usable_column = np.isfinite(turnover_a).any(axis=0) & (
        np.nan_to_num(turnover_a, nan=0.0) > 0
    ).any(axis=0)

    for t, chips, centers, started in _accumulate(
        high_a, low_a, close_a, turnover_a, bins=bins, decay=decay
    ):
        if not started.any():
            continue
        total = chips.sum(axis=0)
        usable = total > 1e-12
        if not usable.any():
            continue
        cumulative = np.cumsum(chips, axis=0) / np.where(usable, total, 1.0)[None, :]
        for percent, target in zip(percents, targets):
            # 第一个累计占比达到目标的档位价格。
            index = np.argmax(cumulative >= target, axis=0)
            reached = cumulative[index, np.arange(cols)] >= target
            values = centers[index, np.arange(cols)]
            out[percent][t] = np.where(usable & reached & usable_column, values, np.nan)

    template = close if isinstance(close, pd.DataFrame) else None
    return {
        percent: _restore(values, close, template, single) for percent, values in out.items()
    }


def chip_winner_series(
    high: pd.DataFrame | pd.Series,
    low: pd.DataFrame | pd.Series,
    close: pd.DataFrame | pd.Series,
    turnover: pd.DataFrame | pd.Series,
    price: pd.DataFrame | pd.Series | None = None,
    *,
    bins: int = DEFAULT_BINS,
    decay: float = DEFAULT_DECAY,
) -> pd.DataFrame | pd.Series:
    """WINNER(price)：成本低于给定价格的筹码占比，即获利盘比例。

    price 为空时用当日收盘——那正是"当前有多少人是赚的"。
    """
    high_a, low_a, close_a, turnover_a, single = _prepare(high, low, close, turnover)
    reference = close_a if price is None else _prepare(price, price, price, price)[0]
    rows, cols = close_a.shape
    out = np.full((rows, cols), np.nan)
    # 与 chip_cost_series 同理：没有换手率就没有筹码分布，不能给数字。
    usable_column = np.isfinite(turnover_a).any(axis=0) & (
        np.nan_to_num(turnover_a, nan=0.0) > 0
    ).any(axis=0)

    for t, chips, centers, started in _accumulate(
        high_a, low_a, close_a, turnover_a, bins=bins, decay=decay
    ):
        if not started.any():
            continue
        total = chips.sum(axis=0)
        usable = total > 1e-12
        below = np.where(centers <= reference[t][None, :], chips, 0.0).sum(axis=0)
        out[t] = np.where(
            usable & usable_column, below / np.where(usable, total, 1.0) * 100.0, np.nan
        )

    return _restore(out, close, close if isinstance(close, pd.DataFrame) else None, single)


def _restore(values: np.ndarray, source, template, single: bool):
    if single or template is None:
        series = pd.Series(values[:, 0], index=source.index)
        series.name = getattr(source, "name", None)
        return series
    return pd.DataFrame(values, index=template.index, columns=template.columns)


def COST(
    high: pd.DataFrame | pd.Series,
    low: pd.DataFrame | pd.Series,
    close: pd.DataFrame | pd.Series,
    turnover: pd.DataFrame | pd.Series,
    percent: float,
    *,
    bins: int = DEFAULT_BINS,
    decay: float = DEFAULT_DECAY,
) -> pd.DataFrame | pd.Series:
    """COST(p)：从低到高累计 p% 筹码时对应的价格。

    需要同时取多个分位时用 ``chip_cost_series``，一次递推算完，
    别对同一段行情跑三遍。
    """
    return chip_cost_series(
        high, low, close, turnover, (percent,), bins=bins, decay=decay
    )[percent]


def WINNER(
    high: pd.DataFrame | pd.Series,
    low: pd.DataFrame | pd.Series,
    close: pd.DataFrame | pd.Series,
    turnover: pd.DataFrame | pd.Series,
    price: pd.DataFrame | pd.Series | None = None,
    *,
    bins: int = DEFAULT_BINS,
    decay: float = DEFAULT_DECAY,
) -> pd.DataFrame | pd.Series:
    """WINNER(price)：获利盘比例（百分数）。"""
    return chip_winner_series(high, low, close, turnover, price, bins=bins, decay=decay)
