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


def _grid_from_bounds(
    low: np.ndarray, high: np.ndarray, bins: int
) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """按截至当前日的每只票价格区间划分档位。"""
    if bins <= 0:
        raise ValueError("筹码档位数必须为正")
    raw_lo = np.asarray(low, dtype=float)
    raw_hi = np.asarray(high, dtype=float)
    finite = np.isfinite(raw_lo) & np.isfinite(raw_hi)
    lo = np.where(finite, raw_lo, 0.0)
    hi = np.where(finite, raw_hi, 0.0)
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


def _rebin_chips(
    chips: np.ndarray,
    centers: np.ndarray,
    new_lo: np.ndarray,
    new_width: np.ndarray,
    changed: np.ndarray,
) -> None:
    """价格范围扩展时，把存量筹码映射到新的价格档位。"""
    if not changed.any():
        return
    old_centers = centers[:, changed]
    old_chips = chips[:, changed]
    target = np.floor(
        (old_centers - new_lo[changed][None, :]) / new_width[changed][None, :]
    ).astype(int)
    target = np.clip(target, 0, chips.shape[0] - 1)
    remapped = np.zeros_like(old_chips)
    column_index = np.broadcast_to(np.arange(target.shape[1]), target.shape)
    np.add.at(remapped, (target.ravel(), column_index.ravel()), old_chips.ravel())
    chips[:, changed] = remapped


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
    chips = np.zeros((bins, cols), dtype=float)
    started = np.zeros(cols, dtype=bool)
    trusted = np.zeros(cols, dtype=bool)
    initialized = np.zeros(cols, dtype=bool)
    seen_low = np.full(cols, np.inf, dtype=float)
    seen_high = np.full(cols, -np.inf, dtype=float)
    lo = np.zeros(cols, dtype=float)
    width = np.ones(cols, dtype=float)
    centers = np.zeros((bins, cols), dtype=float)

    for t in range(rows):
        close_t = close[t]
        finite_low = np.isfinite(low[t])
        finite_high = np.isfinite(high[t])
        seen_low = np.minimum(seen_low, np.where(finite_low, low[t], np.inf))
        seen_high = np.maximum(seen_high, np.where(finite_high, high[t], -np.inf))
        grid_ready = np.isfinite(seen_low) & np.isfinite(seen_high)
        next_lo, next_width, next_centers = _grid_from_bounds(
            seen_low, seen_high, bins
        )
        changed = grid_ready & (
            ~initialized
            | ~np.isclose(lo, next_lo, rtol=1e-12, atol=1e-12)
            | ~np.isclose(width, next_width, rtol=1e-12, atol=1e-12)
        )
        _rebin_chips(chips, centers, next_lo, next_width, changed)
        if changed.any():
            lo[changed] = next_lo[changed]
            width[changed] = next_width[changed]
            centers[:, changed] = next_centers[:, changed]
            initialized[changed] = True

        observed = np.isfinite(close_t)
        complete = (
            observed
            & finite_high
            & finite_low
            & np.isfinite(turnover[t])
            & (turnover[t] >= 0)
        )
        if observed.any():
            safe_close = np.nan_to_num(close_t, nan=0.0)
            high_t = np.where(finite_high, high[t], safe_close)
            low_t = np.where(finite_low, low[t], safe_close)
            high_t = np.maximum(high_t, low_t)
            weights = _today_weights(centers, low_t, high_t, safe_close)
            weights = np.nan_to_num(weights, nan=0.0)
            weights[:, ~observed] = 0.0

            rate = np.nan_to_num(turnover[t], nan=0.0)
            rate = np.clip(rate * decay, 0.0, 1.0)
            # 首个有效交易日：还没有存量筹码，全部按当日分布建立。
            fresh = complete & ~started
            effective = np.where(fresh, 1.0, rate)
            effective = np.where(complete, effective, 0.0)

            chips = chips * (1.0 - effective)[None, :] + weights * effective[None, :]
            trusted |= fresh
            started |= fresh

        # 任何一天的 OHLC/换手率不完整，都不能把上一日的成本继续冒充当前值；
        # 一旦中断，后续即使恢复数据也不重建旧状态，避免跨缺口产生伪精确结果。
        trusted &= complete
        yield t, chips, centers, started, trusted


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

    for t, chips, centers, started, trusted in _accumulate(
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
            # 面板与单票路径的浮点归约顺序可能让恰好 50% 变成
            # 0.4999999999999998；允许极小误差，避免两条路径选不同档位。
            reached_mask = cumulative >= (target - 1e-12)
            index = np.argmax(reached_mask, axis=0)
            reached = reached_mask[index, np.arange(cols)]
            values = centers[index, np.arange(cols)]
            out[percent][t] = np.where(
                usable & reached & usable_column & trusted, values, np.nan
            )

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

    for t, chips, centers, started, trusted in _accumulate(
        high_a, low_a, close_a, turnover_a, bins=bins, decay=decay
    ):
        if not started.any():
            continue
        total = chips.sum(axis=0)
        usable = total > 1e-12
        below = np.where(centers <= reference[t][None, :], chips, 0.0).sum(axis=0)
        out[t] = np.where(
            usable & usable_column & trusted & np.isfinite(reference[t]),
            below / np.where(usable, total, 1.0) * 100.0,
            np.nan,
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
