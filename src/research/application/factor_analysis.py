"""Pure cross-sectional factor statistics for research-only experiments.

This module accepts already-loaded panels.  It deliberately has no store,
strategy, execution, or persistence dependency.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Collection, Literal

import numpy as np
import pandas as pd


ReferenceField = Literal["high", "close"]


@dataclass(frozen=True, slots=True)
class QuantileSignals:
    """Stable daily quantile assignments and one-shot top/bottom selections."""

    groups: pd.DataFrame
    top: pd.DataFrame
    bottom: pd.DataFrame
    status: pd.Series
    group_count: int

    def to_dict(self) -> dict[str, Any]:
        return {
            "group_count": self.group_count,
            "groups": self.groups.to_dict(orient="split"),
            "top": self.top.to_dict(orient="split"),
            "bottom": self.bottom.to_dict(orient="split"),
            "status": self.status.to_dict(),
        }


@dataclass(frozen=True, slots=True)
class CrossSectionAnalysis:
    """Daily cross-sectional IC and equal-count portfolio diagnostics."""

    daily: pd.DataFrame
    group_returns: pd.DataFrame
    summary: dict[str, Any]

    def to_dict(self) -> dict[str, Any]:
        return {
            "daily": self.daily.to_dict(orient="split"),
            "group_returns": self.group_returns.to_dict(orient="split"),
            "summary": self.summary,
        }


def compute_pth252_scores(
    close: pd.DataFrame,
    high: pd.DataFrame | None = None,
    *,
    reference: ReferenceField = "high",
    window: int = 252,
) -> pd.DataFrame:
    """Return ``close / rolling_max(reference, window)`` without future data.

    A score is present only when the current close and every reference value in
    its trailing window are finite and positive.  ``reference='close'`` does
    not require a ``high`` panel.
    """
    close_values = _numeric_panel(close, "close")
    if not close_values.index.is_monotonic_increasing:
        raise ValueError("close index must be sorted ascending")
    if reference not in {"high", "close"}:
        raise ValueError("reference must be 'high' or 'close'")
    if not isinstance(window, int) or isinstance(window, bool) or window <= 0:
        raise ValueError("window must be a positive integer")

    if reference == "close":
        reference_values = close_values
    else:
        if high is None:
            raise ValueError("high panel is required when reference='high'")
        reference_values = _numeric_panel(high, "high")
        _require_aligned(close_values, reference_values, "close", "high")

    valid_close = close_values.where(_finite_positive(close_values))
    valid_reference = reference_values.where(_finite_positive(reference_values))
    trailing_high = valid_reference.rolling(window=window, min_periods=window).max()
    scores = valid_close / trailing_high
    return scores.where(_finite_positive(scores))


def build_quantile_signals(
    scores: pd.DataFrame,
    *,
    group_count: int = 10,
    rebalance_dates: Collection[object] | None = None,
    min_samples: int | None = None,
) -> QuantileSignals:
    """Assign stable equal-count groups and fixed top/bottom selections.

    Scores are sorted ascending by score then code, so group 1 is the bottom
    group and ``group_count`` is the top group.  A date outside
    ``rebalance_dates`` emits no new selections.  This function has no
    execution feedback, therefore it cannot refill a failed top selection.
    """
    score_values = _numeric_panel(scores, "scores")
    _require_group_count(group_count)
    required = group_count if min_samples is None else min_samples
    _require_min_samples(required, group_count)

    index, columns = score_values.index, score_values.columns
    values = score_values.to_numpy(dtype=float, copy=False)
    valid = _finite_positive_array(values)
    counts = valid.sum(axis=1)
    rebalance_keys = _rebalance_keys(rebalance_dates)
    if rebalance_keys is None:
        on_rebalance = np.ones(values.shape[0], dtype=bool)
    else:
        on_rebalance = np.fromiter(
            (_date_key(day) in rebalance_keys for day in index),
            dtype=bool,
            count=values.shape[0],
        )
    enough = counts >= required

    group_values = np.full(values.shape, np.nan, dtype=float)
    top_values = np.zeros(values.shape, dtype=bool)
    bottom_values = np.zeros(values.shape, dtype=bool)

    # 只对真正调仓且样本够的交易日排序：PTH252 每 20 天调一次，这一步就
    # 把排序量砍掉一个数量级。
    active = np.flatnonzero(on_rebalance & enough)
    if active.size:
        assigned = _quantile_group_matrix(
            values[active], valid[active], counts[active], columns, group_count
        )
        group_values[active] = np.where(valid[active], assigned, np.nan)
        top_values[active] = valid[active] & (assigned == group_count)
        bottom_values[active] = valid[active] & (assigned == 1)

    status = np.full(values.shape[0], "selected", dtype=object)
    status[on_rebalance & ~enough] = "insufficient_valid_scores"
    status[~on_rebalance] = "not_rebalance"

    return QuantileSignals(
        groups=pd.DataFrame(group_values, index=index, columns=columns),
        top=pd.DataFrame(top_values, index=index, columns=columns),
        bottom=pd.DataFrame(bottom_values, index=index, columns=columns),
        status=pd.Series(status, index=index, dtype="object"),
        group_count=group_count,
    )


def analyze_cross_section(
    scores: pd.DataFrame,
    labels: pd.DataFrame,
    *,
    group_count: int = 10,
    min_samples: int | None = None,
) -> CrossSectionAnalysis:
    """Evaluate aligned factor and forward-label panels by trading-day slice.

    IC and RankIC are each computed inside one date's stock cross section.
    They never correlate an individual code across time.  Labels must already
    embody the caller's point-in-time forward-return convention.
    """
    score_values = _numeric_panel(scores, "scores")
    label_values = _numeric_panel(labels, "labels")
    _require_aligned(score_values, label_values, "scores", "labels")
    _require_group_count(group_count)
    required = group_count if min_samples is None else min_samples
    _require_min_samples(required, group_count)

    daily_rows: list[dict[str, Any]] = []
    group_rows: list[pd.Series] = []
    group_index: list[object] = []

    for day in score_values.index:
        score_row = score_values.loc[day]
        label_row = label_values.loc[day]
        valid = _finite_positive(score_row) & _finite(label_row)
        pair_scores = score_row[valid]
        pair_labels = label_row[valid]
        sample_count = len(pair_scores)
        coverage = sample_count / len(score_values.columns) if len(score_values.columns) else 0.0
        row: dict[str, Any] = {
            "valid_samples": sample_count,
            "coverage": coverage,
            "pearson_ic": np.nan,
            "rank_ic": np.nan,
            "long_short": np.nan,
            "skip_reason": None,
        }

        reason = _skip_reason(pair_scores, pair_labels, required)
        if reason is not None:
            row["skip_reason"] = reason
            daily_rows.append(row)
            continue

        pearson_ic = float(pair_scores.corr(pair_labels, method="pearson"))
        score_ranks = pair_scores.rank(method="average")
        label_ranks = pair_labels.rank(method="average")
        rank_ic = float(score_ranks.corr(label_ranks, method="pearson"))
        assignments = _quantile_groups(pair_scores, group_count)
        returns = pair_labels.groupby(assignments, sort=True).mean()
        returns = returns.reindex(range(1, group_count + 1), fill_value=np.nan)
        row["pearson_ic"] = pearson_ic
        row["rank_ic"] = rank_ic
        row["long_short"] = float(returns.iloc[-1] - returns.iloc[0])
        daily_rows.append(row)
        group_rows.append(returns)
        group_index.append(day)

    daily = pd.DataFrame(daily_rows, index=score_values.index)
    daily.index.name = score_values.index.name
    group_returns = pd.DataFrame(group_rows, index=group_index, columns=range(1, group_count + 1))
    group_returns.index.name = score_values.index.name
    summary = _summary(daily, group_returns)
    return CrossSectionAnalysis(daily=daily, group_returns=group_returns, summary=summary)


def _numeric_panel(panel: pd.DataFrame, name: str) -> pd.DataFrame:
    if not isinstance(panel, pd.DataFrame):
        raise TypeError(f"{name} must be a pandas DataFrame")
    if panel.index.has_duplicates or panel.columns.has_duplicates:
        raise ValueError(f"{name} index and columns must be unique")
    try:
        return panel.astype(float)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{name} must contain numeric values") from exc


def _require_aligned(
    left: pd.DataFrame, right: pd.DataFrame, left_name: str, right_name: str
) -> None:
    if not left.index.equals(right.index) or not left.columns.equals(right.columns):
        raise ValueError(f"{left_name} and {right_name} must have identical index and columns")


def _finite(panel: pd.DataFrame | pd.Series) -> pd.DataFrame | pd.Series:
    return panel.notna() & np.isfinite(panel)


def _finite_positive(panel: pd.DataFrame | pd.Series) -> pd.DataFrame | pd.Series:
    return _finite(panel) & panel.gt(0)


def _require_group_count(group_count: int) -> None:
    if not isinstance(group_count, int) or isinstance(group_count, bool) or group_count < 2:
        raise ValueError("group_count must be an integer of at least 2")


def _require_min_samples(min_samples: int, group_count: int) -> None:
    if not isinstance(min_samples, int) or isinstance(min_samples, bool) or min_samples < group_count:
        raise ValueError("min_samples must be an integer no smaller than group_count")


def _finite_positive_array(values: np.ndarray) -> np.ndarray:
    """``_finite_positive`` 的 numpy 版：有限且为正。

    分组只在整块矩阵上做，走 pandas 的逐日 mask 会把向量化的收益全吐回去。
    NaN 与 ±inf 都不是有限值，直接落到 False。
    """
    return np.isfinite(values) & (values > 0)


def _code_ranks(columns: pd.Index) -> np.ndarray:
    """把股票代码换成按 ``str(code)`` 升序的名次，用作排序的次关键字。

    原实现的次关键字是 ``str(code)``；名次与字符串同序，于是可以塞进
    ``np.lexsort`` 而不必在排序过程中反复做字符串比较。这里用 object 数组
    排序，保证比较语义就是 Python 的 ``str.__lt__``。
    """
    codes = np.empty(len(columns), dtype=object)
    codes[:] = [str(code) for code in columns]
    ranks = np.empty(len(columns), dtype=np.int64)
    ranks[np.argsort(codes, kind="stable")] = np.arange(len(columns), dtype=np.int64)
    return ranks


def _quantile_group_matrix(
    values: np.ndarray,
    valid: np.ndarray,
    counts: np.ndarray,
    columns: pd.Index,
    group_count: int,
) -> np.ndarray:
    """逐行（逐交易日）按 (分数, 代码) 升序切等量组，返回 1..group_count。

    与 ``_quantile_groups`` 同口径，只是一次算完整块面板：无效格子先顶到
    行尾不参与计数，名次由 ``lexsort`` + ``put_along_axis`` 反解，全程不碰
    标签索引。无效格子的返回值没有意义，由调用方用 ``valid`` 掩掉。
    """
    keys = np.where(valid, values, np.inf)
    code_ranks = np.broadcast_to(_code_ranks(columns), keys.shape)
    order = np.lexsort((code_ranks, keys), axis=1)
    ranks = np.empty(order.shape, dtype=np.int64)
    positions = np.broadcast_to(np.arange(order.shape[1], dtype=np.int64), order.shape)
    np.put_along_axis(ranks, order, positions, axis=1)
    sizes = np.asarray(counts, dtype=np.int64).reshape(-1, 1)
    return np.minimum(group_count, (ranks * group_count) // sizes + 1)


def _quantile_groups(scores: pd.Series, group_count: int) -> pd.Series:
    """单个横截面的等量分组，返回值按 (分数, 代码) 升序排列。

    调用方保证传进来的分数已经过滤成有限正数。
    """
    values = scores.to_numpy(dtype=float, copy=False)
    count = values.shape[0]
    if count == 0:
        return pd.Series([], index=scores.index[:0], dtype="int64")
    order = np.lexsort((_code_ranks(scores.index), values))
    positions = np.arange(count, dtype=np.int64)
    assignments = np.minimum(group_count, (positions * group_count) // count + 1)
    return pd.Series(assignments, index=scores.index[order], dtype="int64")


def _rebalance_keys(rebalance_dates: Collection[object] | None) -> set[str] | None:
    if rebalance_dates is None:
        return None
    return {_date_key(day) for day in rebalance_dates}


def _date_key(value: object) -> str:
    if isinstance(value, pd.Timestamp):
        return value.date().isoformat()
    return str(value)


def _skip_reason(scores: pd.Series, labels: pd.Series, min_samples: int) -> str | None:
    if scores.empty:
        return "no_valid_pairs"
    if len(scores) < min_samples:
        return "insufficient_valid_samples"
    if scores.nunique(dropna=True) < 2:
        return "constant_scores"
    if labels.nunique(dropna=True) < 2:
        return "constant_labels"
    return None


def _summary(daily: pd.DataFrame, group_returns: pd.DataFrame) -> dict[str, Any]:
    pearson = daily["pearson_ic"].dropna()
    rank = daily["rank_ic"].dropna()
    long_short = daily["long_short"].dropna()
    group_means = group_returns.mean(axis=0).to_dict()
    values = [float(group_means[group]) for group in sorted(group_means) if pd.notna(group_means[group])]
    positions = list(range(1, len(values) + 1))
    monotonicity = {
        "valid_groups": len(values),
        "adjacent_violations": sum(right < left for left, right in zip(values, values[1:])),
        "non_decreasing": all(right >= left for left, right in zip(values, values[1:])) if values else None,
        "group_return_rank_ic": _correlation(positions, values),
    }
    return {
        "days": len(daily),
        "evaluated_days": len(rank),
        "pearson_ic_mean": _mean(pearson),
        "pearson_ic_std": _std(pearson),
        "pearson_icir": _icir(pearson),
        "rank_ic_mean": _mean(rank),
        "rank_ic_std": _std(rank),
        "rank_icir": _icir(rank),
        "positive_rank_ic_ratio": float((rank > 0).mean()) if not rank.empty else None,
        "group_return_mean": group_means,
        "long_short_mean": _mean(long_short),
        "monotonicity": monotonicity,
    }


def _mean(values: pd.Series) -> float | None:
    return float(values.mean()) if not values.empty else None


def _std(values: pd.Series) -> float | None:
    return float(values.std(ddof=1)) if len(values) > 1 else None


def _icir(values: pd.Series) -> float | None:
    deviation = _std(values)
    mean = _mean(values)
    if deviation is None or deviation == 0 or mean is None:
        return None
    return mean / deviation


def _correlation(left: list[int], right: list[float]) -> float | None:
    if len(left) < 2 or len(set(right)) < 2:
        return None
    return float(pd.Series(left, dtype=float).corr(pd.Series(right, dtype=float)))


__all__ = [
    "CrossSectionAnalysis",
    "QuantileSignals",
    "analyze_cross_section",
    "build_quantile_signals",
    "compute_pth252_scores",
]
