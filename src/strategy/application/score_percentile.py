"""把战法自有量纲的排序分换成候选池可比的 0–100 评分。

候选池 ``score`` 列按 0–100 展示（进度条满格 100）。潜龙的白线贴近度天然落在这个区间，
三源的横截面评分 ``4*r1+2*r5+1.5*r20+0.35*CLV+0.12*量比`` 却通常只有 1–3——原先直接
夹到 [0,100] 入库，最好的一只也只显示 1.x 分，看上去像“几乎不合格”。

这里用“近 N 个交易日（含当日）同战法候选的评分分布”做参照，给出中位秩百分位：
- 只读当日及以前的数据，没有前视；
- 对同一天是单调变换，不改变任何选股排序、信号或回测；
- 跨日可比：弱市日即便排第一，若绝对强度只是近期中等水平，分数也会如实偏低。
"""
from __future__ import annotations

import numpy as np
import pandas as pd

#: 战法输出的 0–100 评分因子名；``persist.score_from_factors`` 优先采用。
SCORE_PERCENTILE = "评分百分位"


def pooled_percentile(score: pd.DataFrame, pool: pd.DataFrame, *, window: int) -> pd.DataFrame:
    """``score`` 在近 ``window`` 个交易日（含当日）``pool`` 成员评分分布中的百分位（0–100）。

    ``pool`` 为与 ``score`` 同形的布尔面板（通常是战法的原始候选集）。池外或无效评分
    自身也会得到百分位（相对池的位置），池为空的日期为 NaN。并列取中位秩。
    """
    if window < 1:
        raise ValueError("评分百分位窗口必须为正整数")
    values = score.to_numpy(dtype=float)
    member = pool.reindex(index=score.index, columns=score.columns).fillna(False).to_numpy(dtype=bool)
    member = member & np.isfinite(values)
    daily = [values[row][member[row]] for row in range(values.shape[0])]
    out = np.full(values.shape, np.nan)
    for row in range(values.shape[0]):
        pooled = np.concatenate(daily[max(0, row - window + 1): row + 1])
        if not pooled.size:
            continue
        pooled.sort()
        current = values[row]
        finite = np.isfinite(current)
        below = np.searchsorted(pooled, current[finite], side="left")
        through = np.searchsorted(pooled, current[finite], side="right")
        out[row, finite] = (below + through) / 2.0 / pooled.size * 100.0
    return pd.DataFrame(out, index=score.index, columns=score.columns)
