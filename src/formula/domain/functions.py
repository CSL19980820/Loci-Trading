"""通达信内建函数的向量化实现。

每个函数都同时接受 ``pd.Series``（单票）与 ``pd.DataFrame``（全市场面板，
index=交易日 / columns=股票代码）。绝大多数直接落在 pandas 的同名算子上，
天然对两种形状都成立；少数需要沿时间轴做位置运算的（BARSLAST / HHVBARS）
用 numpy 手写，同样一次覆盖所有列。

约定：时间轴永远是 axis=0（行=交易日，由旧到新）。
"""
from __future__ import annotations

from typing import Callable, TypeVar, Union

import numpy as np
import pandas as pd
from numpy.lib.stride_tricks import sliding_window_view

try:
    from pandas._libs.window.aggregations import roll_max as _roll_max
    from pandas._libs.window.aggregations import roll_mean as _roll_mean
    from pandas._libs.window.aggregations import roll_min as _roll_min
    from pandas.core.indexers.objects import FixedWindowIndexer as _FixedWindowIndexer
except ImportError:  # pandas 内部入口变更时退回公开 rolling API。
    _roll_mean = _roll_min = _roll_max = _FixedWindowIndexer = None

#: 面板或单票。两者在本模块里走完全相同的代码路径。
Frame = Union[pd.Series, pd.DataFrame]
F = TypeVar("F", pd.Series, pd.DataFrame)

__all__ = [
    "ABS", "AVEDEV", "BARSCOUNT", "BARSLAST", "BARSSINCE", "COUNT", "CROSS",
    "DMA", "EMA", "EVERY", "EXIST", "FILTER", "HHV", "HHVBARS", "IF", "LLV",
    "LLVBARS", "MA", "MAX", "MIN", "REF", "SMA", "STD", "SUM", "WMA",
    "ZTPRICE", "weighted_ref_sum",
]


# --------------------------------------------------------------------------
# 位移与均线
# --------------------------------------------------------------------------

def REF(series: F, periods: int) -> F:
    """REF(X, N)：N 个周期前的值。N=0 返回自身，不允许负偏移。"""
    if isinstance(periods, bool) or not isinstance(periods, int) or periods < 0:
        raise ValueError("REF 的周期必须是非负整数")
    if periods == 0:
        return series
    return series.shift(periods)


def MA(series: F, periods: int) -> F:
    """MA(X, N)：N 周期简单均线。不足 N 根返回空值，与通达信一致。"""
    if periods <= 0:
        raise ValueError("MA 的周期必须为正")
    result = _rolling_float64(series, periods, _roll_mean)
    return result if result is not None else series.rolling(periods).mean()


def _rolling_float64(series: F, periods: int, kernel: Callable | None) -> F | None:
    """MA/HHV/LLV 复用 pandas 原内核，合并逐列准备；不适用时回落公开 API。"""
    if (
        kernel is None or _FixedWindowIndexer is None
        or not isinstance(periods, (int, np.integer))
        or isinstance(periods, (bool, np.bool_)) or periods <= 0
        or type(series) not in (pd.Series, pd.DataFrame)
        or pd.get_option("compute.use_numba")
    ):
        return None
    dtypes = series.dtypes
    plain_float = (
        dtypes.eq(np.dtype(float)).all()
        if isinstance(dtypes, pd.Series) else dtypes == np.dtype(float)
    )
    if not plain_float:
        return None
    try:
        values, single = _as_matrix(series)
        inf = np.isinf(values)
        if inf.any():
            values = np.where(inf, np.nan, values)
        start, end = _FixedWindowIndexer(window_size=periods).get_window_bounds(len(values))
        out = np.empty(values.shape, dtype=float, order="F")
        # 保留原内核的 Kahan 累加、重复值及符号修正，不替换数值算法。
        with np.errstate(all="ignore"):
            for column in range(values.shape[1]):
                out[:, column] = kernel(values[:, column], start, end, periods)
        return _like(series, out[:, 0] if single else out)
    except (AttributeError, TypeError, ValueError):
        # 私有内核/索引器签名变更不能破坏公式公开接口。
        return None


def EMA(series: F, periods: int) -> F:
    """EMA(X, N)：指数移动平均，alpha = 2/(N+1)。"""
    if periods <= 0:
        raise ValueError("EMA 的周期必须为正")
    return series.ewm(span=periods, adjust=False).mean()


def SMA(series: F, periods: int, weight: float = 1.0) -> F:
    """SMA(X, N, M)：通达信的递推均值 Y = (M*X + (N-M)*Y') / N。

    注意它不是"简单移动平均"——那是 MA。这里等价于 alpha = M/N 的 EMA，
    KDJ、RSI 等指标依赖这个口径。
    """
    if periods <= 0:
        raise ValueError("SMA 的周期必须为正")
    return series.ewm(alpha=weight / periods, adjust=False).mean()


def WMA(series: F, periods: int) -> F:
    """WMA(X, N)：线性加权均线，当期权重最大（N, N-1, ..., 1）。

    权重方向是这个函数最容易写反的地方——通达信里越近的周期权重越大。
    """
    if periods <= 0:
        raise ValueError("WMA 的周期必须为正")
    # 滑动窗口的内存顺序是"最旧在前、当期在末"，所以权重要递增排列。
    # 写成 arange(periods, 0, -1) 会把最大权重压在最旧那根上——这正是
    # src/qianlong.py 辰星线曾经踩过的坑，别再踩第二次。
    weights = np.arange(1, periods + 1, dtype=float)
    weights /= weights.sum()

    # 线性加权和就是一次卷积，没必要为每个窗口回调一次 Python。这里按
    # 权重逐位累加平移后的整块矩阵：额外内存只有一份 (rows, cols)，
    # 也不需要物化 sliding_window_view（见 _rolling_column_chunks 的说明）。
    # NaN 会顺着加法自然传播，与 rolling 的 min_periods=N 语义一致：
    # 窗口内只要有一个缺失值，结果就是 NaN。
    matrix, single = _as_matrix(series)
    rows, cols = matrix.shape
    out = np.full((rows, cols), np.nan, dtype=float)
    if rows >= periods:
        span = rows - periods + 1
        total = np.zeros((span, cols), dtype=float)
        for offset, weight in enumerate(weights):
            total += weight * matrix[offset : offset + span]
        out[periods - 1 :] = total
    return _like(series, out[:, 0] if single else out)


def weighted_ref_sum(series: F, weights: dict[int, float], divisor: float) -> F:
    """按 {REF 偏移: 权重} 直接展开的加权和，再除以指定分母。

    专为翻译"手写展开成一长串 REF"的通达信公式而设（潜龙出海的辰星线
    就是这种写法）。这类公式经常出现跳过某个偏移、或者分母与权重和不等
    的构造，硬套 WMA 会悄悄改掉原意，所以给它一个可以照抄的入口。
    """
    if divisor == 0:
        raise ValueError("分母不能为 0")
    total = None
    for offset, weight in weights.items():
        term = REF(series, offset) * weight
        total = term if total is None else total + term
    if total is None:
        raise ValueError("权重表为空")
    return total / divisor


def DMA(series: F, alpha: F | float) -> F:
    """DMA(X, A)：动态权重移动平均 Y = A*X + (1-A)*Y'，A 可以是序列。"""
    if isinstance(alpha, (int, float)):
        return series.ewm(alpha=float(alpha), adjust=False).mean()
    values = np.asarray(series, dtype=float)
    weights = np.clip(np.asarray(alpha, dtype=float), 0.0, 1.0)
    out = np.full_like(values, np.nan, dtype=float)
    prev = None
    for i in range(values.shape[0]):
        current, weight = values[i], weights[i]
        if prev is None:
            prev = np.where(np.isnan(current), np.nan, current)
        else:
            step = weight * current + (1 - weight) * prev
            prev = np.where(np.isnan(current), prev, step)
        out[i] = prev
    return _like(series, out)


# --------------------------------------------------------------------------
# 区间统计
# --------------------------------------------------------------------------

def SUM(series: F, periods: int) -> F:
    """SUM(X, N)：N 周期求和。N=0 表示从上市首日累计到当前。"""
    if periods == 0:
        return series.cumsum()
    return series.rolling(periods).sum()


def HHV(series: F, periods: int) -> F:
    """HHV(X, N)：N 周期最高。N=0 表示历史最高。"""
    if periods == 0:
        return series.cummax()
    result = _rolling_float64(series, periods, _roll_max)
    return result if result is not None else series.rolling(periods).max()


def LLV(series: F, periods: int) -> F:
    """LLV(X, N)：N 周期最低。N=0 表示历史最低。"""
    if periods == 0:
        return series.cummin()
    result = _rolling_float64(series, periods, _roll_min)
    return result if result is not None else series.rolling(periods).min()


def STD(series: F, periods: int) -> F:
    """STD(X, N)：N 周期标准差。通达信用样本标准差（分母 N-1）。"""
    return series.rolling(periods).std(ddof=1)


def AVEDEV(series: F, periods: int) -> F:
    """AVEDEV(X, N)：N 周期平均绝对偏差，BOLL 的变体与 CCI 会用到。

    平均绝对偏差没有可递推的分离形式（不像 MA/STD 能靠前缀和），只能真的
    看整个窗口，所以这里按列分块取滑动窗口再整块规约，替掉原来"每个窗口
    回调一次 Python"的 ``rolling.apply``。CCI 建在它上面，全市场扫描时
    这一个函数就能吃掉大半时间。

    周期语义沿用 ``rolling`` 原样：N=0 全为空值，N<0 报错。
    """
    _require_rolling_periods(periods, "AVEDEV")
    matrix, single = _as_matrix(series)

    def _kernel(windows: np.ndarray) -> np.ndarray:
        deviations = windows - windows.mean(axis=2, keepdims=True)
        np.abs(deviations, out=deviations)
        return deviations.mean(axis=2)

    out = _rolling_column_chunks(matrix, periods, _kernel)
    return _like(series, out[:, 0] if single else out)


def COUNT(condition: F, periods: int) -> F:
    """COUNT(COND, N)：N 周期内条件成立的次数。N=0 表示自上市累计。"""
    values = np.asarray(condition)
    if (
        values.dtype == np.dtype(bool)
        and isinstance(periods, (int, np.integer))
        and not isinstance(periods, (bool, np.bool_))
        and periods > 0
    ):
        # 比较条件只有 0/1；整数前缀相减精确，且不必让 rolling 逐股票调度。
        # 数值输入仍保留原来的浮点求和语义（包括 NaN），不能强转成条件。
        counts = np.cumsum(values, axis=0, dtype=np.int64)
        counts[periods:] -= counts[:-periods]
        out = counts.astype(float)
        out[:periods - 1] = np.nan
        return _like(condition, out)
    flags = _to_float_flags(condition)
    if periods == 0:
        return flags.cumsum()
    return flags.rolling(periods).sum()


def EVERY(condition: F, periods: int) -> F:
    """EVERY(COND, N)：N 周期内条件是否始终成立。"""
    return COUNT(condition, periods) >= periods


def EXIST(condition: F, periods: int) -> F:
    """EXIST(COND, N)：N 周期内条件是否出现过。"""
    return COUNT(condition, periods) >= 1


def FILTER(condition: F, periods: int) -> F:
    """FILTER(COND, N)：条件成立后 N 周期内不再重复成立。

    用于把连续信号压成"第一根"，避免同一波行情被反复计入。
    """
    raw = np.asarray(_to_float_flags(condition).fillna(0.0), dtype=float) > 0
    single = raw.ndim == 1
    flags = raw[:, None] if single else raw
    out = np.zeros_like(flags, dtype=bool)
    # 有状态（要记住"还封着几根"），只能沿时间轴推进；但每一步对全部
    # 股票是向量运算，循环次数等于交易日数而不是股票数。
    blocked = np.zeros(flags.shape[1], dtype=int)
    for i in range(flags.shape[0]):
        fire = flags[i] & (blocked <= 0)
        out[i] = fire
        blocked = np.where(fire, periods, np.maximum(blocked - 1, 0))
    return _like(condition, out[:, 0] if single else out)


# --------------------------------------------------------------------------
# 位置类：距离上一次成立 / 距离最值
# --------------------------------------------------------------------------

def BARSLAST(condition: F) -> F:
    """BARSLAST(COND)：距上一次条件成立的周期数，当日成立为 0。

    从未成立过则为空值。实现是"把成立位置写进数组再前向填充"，
    整段没有 Python 循环，全市场一次算完。
    """
    flags = np.asarray(_to_float_flags(condition), dtype=float) > 0
    positions = np.arange(flags.shape[0], dtype=float)
    if flags.ndim == 1:
        marks = np.where(flags, positions, np.nan)
    else:
        marks = np.where(flags, positions[:, None], np.nan)
    filled = pd.DataFrame(marks) if marks.ndim == 2 else pd.Series(marks)
    filled = filled.ffill().to_numpy(dtype=float)
    if marks.ndim == 1:
        return _like(condition, positions - filled)
    return _like(condition, positions[:, None] - filled)


def BARSSINCE(condition: F) -> F:
    """BARSSINCE(COND)：距**第一次**条件成立的周期数。"""
    flags = np.asarray(_to_float_flags(condition), dtype=float) > 0
    single = flags.ndim == 1
    matrix = flags[:, None] if single else flags
    positions = np.arange(matrix.shape[0], dtype=float)
    result = np.full(matrix.shape, np.nan, dtype=float)
    # 每列只需定位首次成立的位置，之后是等差数列，不必逐行推进。
    for column in range(matrix.shape[1]):
        hits = np.flatnonzero(matrix[:, column])
        if hits.size:
            first = hits[0]
            result[first:, column] = positions[first:] - first
    return _like(condition, result[:, 0] if single else result)


def BARSCOUNT(series: F) -> F:
    """BARSCOUNT(X)：从首个有效值起算的有效周期数（含当前）。

    次新股用它来排除"上市不久、指标窗口还没填满"的票。
    """
    valid = series.notna()
    counter = valid.cumsum()
    started = valid.cummax()
    result = counter.where(started)
    return result


def HHVBARS(series: F, periods: int) -> F:
    """HHVBARS(X, N)：N 周期内最高价距今的周期数，当日最高为 0。

    同一窗口内出现相同最高值时，取离当前最近的一根；这样当前值等于
    窗口最高值时始终返回 0，与“距今”的定义一致。
    """
    return _extreme_bars(series, periods, highest=True)


def LLVBARS(series: F, periods: int) -> F:
    """LLVBARS(X, N)：N 周期内最低价距今的周期数，当日最低为 0。

    同一窗口内出现相同最低值时，取离当前最近的一根。
    """
    return _extreme_bars(series, periods, highest=False)


def _extreme_bars(series: F, periods: int, *, highest: bool) -> F:
    if periods <= 0:
        raise ValueError("HHVBARS/LLVBARS 的周期必须为正")
    matrix, single = _as_matrix(series)
    fill = -np.inf if highest else np.inf
    pick = np.argmax if highest else np.argmin

    def _kernel(windows: np.ndarray) -> np.ndarray:
        # 先反转时间方向：argmax/argmin 取到的下标就是"距当前"的周期数，
        # 也自然选中相同最值里最近的一根（两者都返回首个命中位置）。
        reversed_windows = windows[..., ::-1]
        missing = np.isnan(reversed_windows)
        # 缺失位填成 ±inf 后数组里已无 NaN，用 argmax/argmin 即可；
        # nanargmax 会在内部再复制一份同样大小的数组。
        safe = np.where(missing, fill, reversed_windows)
        distance = pick(safe, axis=2).astype(float)
        distance[missing.all(axis=2)] = np.nan
        return distance

    out = _rolling_column_chunks(matrix, periods, _kernel)
    return _like(series, out[:, 0] if single else out)


# --------------------------------------------------------------------------
# 逻辑与算术
# --------------------------------------------------------------------------

def CROSS(fast: Frame, slow: Frame) -> Frame:
    """CROSS(A, B)：A 上穿 B。今日 A>B 且昨日 A<=B。"""
    return (fast > slow) & (REF(fast, 1) <= REF(slow, 1))


def IF(
    condition: Frame | float | bool,
    when_true: Frame | float | bool,
    when_false: Frame | float | bool,
) -> Frame | float | bool:
    """IF(COND, A, B)：逐元素三元选择，支持标量条件与标量分支。"""
    if not isinstance(condition, (pd.Series, pd.DataFrame)):
        return when_true if not pd.isna(condition) and bool(condition) else when_false

    mask = _to_float_flags(condition) > 0
    if isinstance(when_true, (pd.Series, pd.DataFrame)):
        return when_true.where(mask, when_false)
    if isinstance(when_false, (pd.Series, pd.DataFrame)):
        return when_false.where(~mask, when_true)
    return _like(condition, np.where(mask, when_true, when_false))


def ABS(series: Frame) -> Frame:
    """ABS(X)：绝对值。"""
    return series.abs()


def MAX(left: Frame | float, right: Frame | float) -> Frame:
    """MAX(A, B)：逐元素取大。"""
    if isinstance(left, (pd.Series, pd.DataFrame)):
        return left.clip(lower=right) if not isinstance(right, (pd.Series, pd.DataFrame)) else left.where(left >= right, right)
    if isinstance(right, (pd.Series, pd.DataFrame)):
        return right.clip(lower=left)
    return max(left, right)


def MIN(left: Frame | float, right: Frame | float) -> Frame:
    """MIN(A, B)：逐元素取小。"""
    if isinstance(left, (pd.Series, pd.DataFrame)):
        return left.clip(upper=right) if not isinstance(right, (pd.Series, pd.DataFrame)) else left.where(left <= right, right)
    if isinstance(right, (pd.Series, pd.DataFrame)):
        return right.clip(upper=left)
    return min(left, right)


def ZTPRICE(prev_close: Frame, ratio: float = 0.1) -> Frame:
    """ZTPRICE(REF(CLOSE,1), R)：涨停价。

    交易所对涨跌停价取"四舍五入到分"，且是逢五进一；Python 内建 round()
    是银行家舍入（0.5 取偶），直接用会让一批票的涨停价差一分钱，进而
    让"是否涨停"判错。这里显式做逢五进一。
    """
    raw = prev_close * (1.0 + ratio)
    return _round_half_up(raw, 2)


def _round_half_up(series: Frame, digits: int) -> Frame:
    scale = 10.0**digits
    values = np.asarray(series, dtype=float)
    # 加一个极小量抵消二进制表示误差（如 10.045 实际存成 10.04499...）。
    rounded = np.floor(values * scale + 0.5 + 1e-9) / scale
    return _like(series, np.where(np.isnan(values), np.nan, rounded))


# --------------------------------------------------------------------------
# 内部工具
# --------------------------------------------------------------------------

#: 滑动窗口按列分块的宽度（只影响峰值内存与缓存命中，不影响结果）。
#:
#: ``sliding_window_view`` 本身零拷贝，但只要对它做一次 ``isnan`` / ``where``
#: / 减法，(rows-N+1, cols, N) 就会被整块物化：250 天 × 5500 只 × N=60 是
#: 约 1.5 GB，700 天更是 4.3 GB——而服务器可用内存只有 1.1 G
#: （见 ``src/strategy/application/screener.py`` 的开头说明），这是 OOM 不是慢。
#: 切成 256 列一批后峰值降到几十 MB 且与股票数无关；因为每批都装得进
#: CPU 缓存，实测反而比一次性算更快。
_COLUMN_CHUNK = 256


def _as_matrix(series: Frame) -> tuple[np.ndarray, bool]:
    """把单票/面板统一成二维矩阵，并告知是否需要在返回时降回一维。"""
    values = np.asarray(series, dtype=float)
    single = values.ndim == 1
    return (values[:, None] if single else values), single


def _require_rolling_periods(periods: int, name: str) -> None:
    """复刻 ``rolling`` 的周期校验：负数报错，0 合法（结果全为空值）。"""
    if periods < 0:
        raise ValueError(f"{name} 的周期不能为负")


def _rolling_column_chunks(
    matrix: np.ndarray,
    periods: int,
    kernel: Callable[[np.ndarray], np.ndarray],
) -> np.ndarray:
    """按列分块地对滑动窗口调用 ``kernel``，返回与 ``matrix`` 同形的结果。

    ``kernel`` 收到 ``(rows-N+1, chunk, N)`` 的窗口视图（时间轴在最后一维，
    最旧在前），必须返回 ``(rows-N+1, chunk)``。不足 N 根的前 N-1 行留空值，
    与 ``rolling`` 的 ``min_periods=N`` 一致。
    """
    rows, cols = matrix.shape
    out = np.full((rows, cols), np.nan, dtype=float)
    if periods <= 0 or rows < periods or cols == 0:
        return out
    for start in range(0, cols, _COLUMN_CHUNK):
        stop = min(start + _COLUMN_CHUNK, cols)
        windows = sliding_window_view(matrix[:, start:stop], periods, axis=0)
        out[periods - 1 :, start:stop] = kernel(windows)
    return out


def _to_float_flags(condition: Frame) -> Frame:
    """把条件转成 0/1 浮点。

    条件通常已经是比较运算的结果（bool dtype），此时不含 NaN——pandas 对
    含 NaN 的比较直接给 False，语义上等同通达信"数据不足即不成立"。
    若传进来的是数值序列，非零视为成立，NaN 保持 NaN 以免把缺数据
    当成信号。
    """
    return condition.astype(float)


def _like(template: Frame, values: np.ndarray) -> Frame:
    """把 numpy 结果套回与输入同形的 pandas 对象。"""
    if isinstance(template, pd.DataFrame):
        return pd.DataFrame(values, index=template.index, columns=template.columns)
    return pd.Series(np.asarray(values).reshape(-1), index=template.index, name=template.name)
