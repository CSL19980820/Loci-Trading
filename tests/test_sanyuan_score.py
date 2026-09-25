"""三源候选池评分：0–100 百分位、无前视、不改变选股。"""
import numpy as np
import pandas as pd
import pytest

from src.strategy.application.persist import factor_reason, score_from_factors
from src.strategy.application.score_percentile import (
    SCORE_PERCENTILE,
    pooled_percentile,
)
from src.strategy.application.tail_resonance import SanyuanTailResonance


def frame(rows):
    return pd.DataFrame(rows, index=[f"2026-09-{day:02d}" for day in range(1, len(rows) + 1)],
                        columns=["A", "B", "C"])


def test_percentile_uses_trailing_pool_with_mid_rank_ties():
    score = frame([[1.0, 2.0, 3.0], [2.0, 2.0, 9.0]])
    pool = frame([[True, True, True], [True, True, False]])
    out = pooled_percentile(score, pool, window=2)
    # 第1天池 {1,2,3}；第2天池 {1,2,3,2,2}（C 不在池中，但仍给出相对池的位置）
    assert out.iloc[0].tolist() == pytest.approx([100 / 6, 50.0, 500 / 6])
    assert out.iloc[1].tolist() == pytest.approx([50.0, 50.0, 100.0])
    assert pooled_percentile(score, pool, window=1).iloc[1, 0] == pytest.approx(50.0)


def test_percentile_never_reads_future_days():
    rng = np.random.default_rng(7)
    score = pd.DataFrame(rng.normal(size=(30, 5)))
    pool = score.gt(-0.5)
    full = pooled_percentile(score, pool, window=10)
    for cut in (5, 12, 29):
        partial = pooled_percentile(score.iloc[: cut + 1], pool.iloc[: cut + 1], window=10)
        pd.testing.assert_series_equal(partial.iloc[cut], full.iloc[cut])


def test_empty_pool_day_is_nan():
    score = frame([[1.0, 2.0, 3.0]])
    assert pooled_percentile(score, frame([[False] * 3]), window=5).isna().all().all()


def test_persist_prefers_normalized_score_and_never_shows_raw_formula_as_score():
    assert score_from_factors({SCORE_PERCENTILE: 97.3456, "横截面评分": 1.73}) == 97.3456
    assert score_from_factors({"横截面评分": 1.73}) is None
    assert score_from_factors({"白线贴近度": 0.978}) == 97.8  # 潜龙不受影响
    assert score_from_factors({SCORE_PERCENTILE: 140.0}) == 100.0


def synthetic_panels(days=110, codes=60, seed=11):
    rng = np.random.default_rng(seed)
    index = pd.bdate_range("2026-03-02", periods=days).strftime("%Y-%m-%d")
    columns = [f"{600000 + i}" for i in range(codes)]
    returns = rng.normal(0.002, 0.03, size=(days, codes))
    close = pd.DataFrame(10 * np.exp(np.cumsum(returns, axis=0)), index=index, columns=columns)
    open_ = close.shift(1).fillna(close) * (1 + rng.normal(0, 0.01, size=(days, codes)))
    high = np.maximum(open_, close) * (1 + rng.uniform(0, 0.02, size=(days, codes)))
    low = np.minimum(open_, close) * (1 - rng.uniform(0, 0.02, size=(days, codes)))
    volume = pd.DataFrame(rng.uniform(1e6, 5e6, size=(days, codes)), index=index, columns=columns)
    turnover = pd.DataFrame(rng.uniform(0.01, 0.15, size=(days, codes)), index=index, columns=columns)
    return {"open": open_, "high": high, "low": low, "close": close, "volume": volume, "turnover": turnover}


def test_sanyuan_emits_comparable_score_without_changing_picks():
    engine = SanyuanTailResonance()
    panels = synthetic_panels()
    result = engine.compute(panels)
    factors = result.factors
    percentile, raw = factors[SCORE_PERCENTILE], factors["横截面评分"]
    picked_days = [day for day in result.signals.index[-40:] if result.signals.loc[day].any()
                   or result.watch_signals.loc[day].any()]
    assert picked_days, "合成数据应至少出现一次正式或观察信号"
    for day in picked_days:
        codes = result.picks_on(day, rank_by="横截面评分") + result.watch_picks_on(day, rank_by="横截面评分")
        for code in codes:
            value = percentile.at[day, code]
            assert 0.0 <= value <= 100.0
            # 同一天内评分百分位与原始评分同序：换算不改变排序
            same_day = raw.loc[day].dropna()
            higher_raw = same_day[same_day > raw.at[day, code]].index
            assert all(percentile.at[day, other] >= value for other in higher_raw)
    # 真实量纲：原始评分远小于 100，而入库分数落在 0–100 可比区间
    day, code = next((d, c) for d in picked_days for c in result.picks_on(d) + result.watch_picks_on(d))
    explained = result.explain(day, code)
    assert explained["横截面评分"] < 10
    assert score_from_factors(explained) == pytest.approx(round(explained[SCORE_PERCENTILE], 4))
    reason = factor_reason(engine.slug, explained)
    assert reason.startswith("三源尾盘共振（15:30）选中：评分百分位=")
    assert "A_MA25突破" not in reason


def test_percentile_factor_does_not_alter_signals():
    panels = synthetic_panels(seed=3)
    engine = SanyuanTailResonance()
    result = engine.compute(panels)
    shorter = engine.compute({key: frame.iloc[:-5] for key, frame in panels.items()})
    pd.testing.assert_frame_equal(result.signals.iloc[:-5], shorter.signals)
    last = shorter.signals.index[-1]
    pd.testing.assert_series_equal(result.factors[SCORE_PERCENTILE].loc[last],
                                   shorter.factors[SCORE_PERCENTILE].loc[last])


def yangshi_panels(days=70, codes=80, seed=21):
    rng = np.random.default_rng(seed)
    panels = synthetic_panels(days=days, codes=codes, seed=seed)
    index, columns = panels["close"].index, panels["close"].columns
    panels["close"] = panels["close"] * 0 + 8 * np.exp(np.cumsum(rng.normal(0.004, 0.025, size=(days, codes)), axis=0))
    panels["high"] = panels["close"] * 1.02
    panels["low"] = panels["close"] * 0.97
    panels["amount"] = pd.DataFrame(rng.uniform(4e7, 9e7, size=(days, codes)), index=index, columns=columns)
    panels["turnover"] = pd.DataFrame(rng.uniform(0.03, 0.08, size=(days, codes)), index=index, columns=columns)
    panels["outstanding_share"] = pd.DataFrame(1.5e8, index=index, columns=columns)
    return panels


def test_yangshi_scores_on_same_scale_and_keeps_rank_order():
    from src.strategy.application.yangshi_tail import YangshiTailPickerV1

    engine = YangshiTailPickerV1()
    result = engine.compute(yangshi_panels())
    percentile, gain = result.factors[SCORE_PERCENTILE], result.factors["当日涨幅(%)"]
    days = [d for d in result.signals.index[-30:] if result.signals.loc[d].any() or result.watch_signals.loc[d].any()]
    assert days, "合成数据应至少出现一次正式或观察信号"
    for day in days:
        for code in result.picks_on(day, rank_by="当日涨幅(%)") + result.watch_picks_on(day, rank_by="当日涨幅(%)"):
            value = percentile.at[day, code]
            assert 0.0 <= value <= 100.0
            explained = result.explain(day, code)
            assert score_from_factors(explained) == pytest.approx(round(value, 4))
            eligible_gain = gain.loc[day][result.factors["条件候选"].loc[day].astype(bool)]
            assert all(percentile.at[day, other] >= value for other in eligible_gain[eligible_gain > gain.at[day, code]].index)
    reason = factor_reason(engine.slug, result.explain(days[-1], (result.picks_on(days[-1]) + result.watch_picks_on(days[-1]))[0]))
    assert reason.startswith("杨氏尾盘选股（15:30）选中：评分百分位=")
