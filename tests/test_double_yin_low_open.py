"""开盘因果性、弱趋势/严重破位拦截、质量评分与板块去重的确定性样本。"""
from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from src.strategy.application.double_yin_low_open import DoubleYinLowOpenV1
from src.strategy.domain.base import StrategyError


FIELDS = ("open", "high", "low", "close", "volume")


def example(*, code="600001", gain=8.0, bars=61, name="普通样本"):
    days = pd.bdate_range("2025-01-02", periods=bars).strftime("%Y-%m-%d")
    panels = {
        field: pd.DataFrame(value, index=days, columns=[code], dtype=float)
        for field, value in {"open": 10.0, "high": 12.0, "low": 8.0,
                             "close": 10.0, "volume": 100.0}.items()
    }
    anchor = round(10 * (1 + gain / 100), 3)
    candle(panels, -3, open_=10, close=anchor, high=max(anchor, 10) + 0.1,
           low=min(anchor, 10) - 0.1, volume=100)
    # 阴线日低开，并未要求高开；这也不破坏原形态定义。
    candle(panels, -2, open_=round(anchor - 0.1, 3), close=round(anchor - 0.2, 3),
           high=anchor, low=round(anchor - 0.3, 3), volume=200)
    for field in FIELDS:
        panels[field].iloc[-1, 0] = round(anchor - 0.3, 3) if field == "open" else np.nan
    panels["__instrument_names__"] = {code: name}
    panels["__sector_groups__"] = {code: (f"industry:{code}",)}
    return panels


def candle(panels, pos, *, open_, close, high, low, volume=100):
    for field, value in zip(FIELDS, (open_, high, low, close, volume), strict=True):
        panels[field].iloc[pos, 0] = value


def together(*items):
    panels = {field: pd.concat([item[field] for item in items], axis=1) for field in FIELDS}
    for key in ("__instrument_names__", "__sector_groups__"):
        panels[key] = {code: value for item in items for code, value in item[key].items()}
    return panels


def selected(panels, params=None):
    result = DoubleYinLowOpenV1().compute(panels, params)
    return result.picks_on(panels["open"].index[-1], rank_by="score")


def rising_example(**kwargs):
    panels = example(**kwargs)
    prices = np.linspace(9.2, 10, len(panels["open"]) - 3)
    for field, values in {"open": prices, "close": prices,
                          "high": prices + 0.3, "low": prices - 0.3}.items():
        panels[field].iloc[:-3, 0] = values
    return panels


def declining_rebound_example(**kwargs):
    panels = example(**kwargs)
    # 较高的旧价格陆续离开MA20，使大阳之前的均线下行；两根反弹K线
    # 又足以把截至昨日的MA20拉成向上，不能据此抹掉反弹前的趋势。
    for pos in range(-28, -23):
        candle(panels, pos, open_=10.3, close=10.3, high=10.4, low=10.2)
    for pos in range(-23, -4):
        candle(panels, pos, open_=10.05, close=10.05, high=10.15, low=9.95)
    return panels


def low_quality_example(**kwargs):
    panels = example(gain=25, **kwargs)
    # 趋势尚可，但离均线较远、开盘位于区间高处、昨日影线破低，合计不足50分。
    panels["low"].iloc[-2, 0] = 9.8
    panels["open"].iloc[-1, 0] = 11.3
    return panels


@pytest.mark.parametrize("code,gain,expected", [
    ("600001", 8, True), ("000001", 8, True), ("002001", 8, True),
    ("600001", 7.99, False), ("300001", 10, False), ("301001", 10, False),
    ("300001", 20, False), ("301001", 20, False),
    ("300001", 9.99, False), ("301001", 8, False),
    ("688001", 10, False), ("830001", 10, False), ("920001", 10, False),
    ("900901", 10, False), ("200001", 10, False), ("510050", 10, False),
    ("60001", 10, False), ("600001.SH", 10, False),
])
def test_main_threshold_and_non_main_excluded_from_history_opening_and_picks(code, gain, expected):
    panels = example(code=code, gain=gain)
    result = DoubleYinLowOpenV1().compute(panels)
    assert bool(result.factors["历史形态候选"].iloc[-1, 0]) is expected
    assert bool(result.factors["条件候选"].iloc[-1, 0]) is expected
    assert bool(result.signals.iloc[-1, 0]) is expected


def test_yin_day_does_not_need_high_open_but_broken_support_is_not_preferred():
    panels = example()
    assert panels["open"].iloc[-2, 0] < panels["close"].iloc[-3, 0]
    assert selected(panels) == ["600001"]
    candle(panels, -2, open_=10.6, close=9.8, high=10.7, low=8.5, volume=200)
    panels["open"].iloc[-1, 0] = 9.7
    result = DoubleYinLowOpenV1().compute(panels)
    assert result.factors["历史形态候选"].iloc[-1, 0]
    assert not result.factors["支撑质量合格"].iloc[-1, 0]
    assert np.isnan(result.factors["score"].iloc[-1, 0])
    assert selected(panels) == []


@pytest.mark.parametrize("name", ["ST样本", "*ST样本", "st样本", "退市样本", "样本退", "", "  "])
def test_st_delisting_and_missing_names_excluded(name):
    assert selected(example(name=name)) == []


def test_missing_name_entry_excluded_and_missing_name_metadata_errors():
    panels = example()
    panels["__instrument_names__"] = {}
    assert selected(panels) == []
    del panels["__instrument_names__"]
    with pytest.raises(StrategyError, match="证券名称"):
        selected(panels)


@pytest.mark.parametrize("bars,expected", [(60, False), (61, True), (80, True)])
def test_minimum_history_excludes_short_samples(bars, expected):
    assert bool(selected(example(bars=bars))) is expected


@pytest.mark.parametrize("field,pos,value", [
    ("close", -4, 0), ("close", -4, np.nan), ("close", -4, np.inf),
    ("volume", -3, 0), ("volume", -2, 0),
    ("volume", -2, 199.9), ("volume", -2, np.nan),
    ("low", -20, 0), ("high", -20, np.inf),
])
def test_invalid_history_and_insufficient_volume_do_not_match(field, pos, value):
    panels = example()
    panels[field].iloc[pos, 0] = value
    assert selected(panels) == []


@pytest.mark.parametrize("boundary", ["anchor_doji", "anchor_red", "yin_doji", "yin_red"])
def test_anchor_requires_positive_body_and_yesterday_negative_body(boundary):
    panels = example()
    if boundary.startswith("anchor"):
        panels["open"].iloc[-3, 0] = 10.8 if boundary.endswith("doji") else 10.9
        panels["high"].iloc[-3, 0] = 11
    else:
        panels["open"].iloc[-2, 0] = 10.6 if boundary.endswith("doji") else 10.5
    assert selected(panels) == []


@pytest.mark.parametrize("open_price,expected", [(6, False), (5.99, False), (6.01, True),
                                                 (6.095, False), (6.096, False),
                                                 (np.nan, False), (np.inf, False)])
def test_low_open_and_six_yuan_boundary_use_current_open(open_price, expected):
    panels = example()
    # 6.01元必须对应约6元的有效支撑，不能用从10元突然跳空至6元的破位样本。
    for field in ("open", "high", "low", "close"):
        panels[field] *= 0.575
    panels["close"].iloc[-2, 0] = 6.095
    panels["open"].iloc[-1, 0] = open_price
    assert bool(selected(panels)) is expected


@pytest.mark.parametrize("recent_gain,expected", [(30, True), (30.01, False), (29.99, True)])
def test_recent_gain_includes_anchor_and_obeys_rounded_threshold(recent_gain, expected):
    panels = example()
    anchor = panels["close"].iloc[-3, 0]
    previous = anchor / (1 + recent_gain / 100)
    candle(panels, -13, open_=previous, close=previous, high=previous + 0.1,
           low=previous - 0.1)
    result = DoubleYinLowOpenV1().compute(panels)
    assert result.factors["近期累计涨幅(%)"].iloc[-1, 0] == recent_gain
    assert bool(result.signals.iloc[-1, 0]) is expected


def test_night_snapshot_preserves_all_shape_candidates_with_nan_today():
    panels = together(example(code="600001"), example(code="600002"), example(code="603001", gain=10))
    for field in FIELDS:
        panels[field].iloc[-1] = np.nan
    panels["__sector_groups__"] = {}
    result = DoubleYinLowOpenV1().compute(panels)
    assert result.factors["历史形态候选"].iloc[-1].all()
    assert not result.factors["条件候选"].iloc[-1].any()
    assert result.factors["score"].iloc[-1].isna().all()
    assert not result.signals.iloc[-1].any()


def test_night_snapshot_does_not_filter_low_price_or_sort_top_two():
    panels = together(*(example(code=f"60000{number}") for number in range(1, 5)))
    for field in ("open", "high", "low", "close"):
        panels[field] *= 0.5
    panels["open"].iloc[-1] = np.nan
    result = DoubleYinLowOpenV1().compute(panels)
    assert result.factors["历史形态候选"].iloc[-1].sum() == 4
    assert not result.factors["条件候选"].iloc[-1].any()


def test_current_close_high_low_and_volume_never_change_latest_results():
    panels = example()
    engine = DoubleYinLowOpenV1()
    before = engine.compute(panels)
    for field, value in {"close": 1000, "high": -10, "low": np.inf, "volume": -500}.items():
        panels[field].iloc[-1, 0] = value
    after = engine.compute(panels)
    pd.testing.assert_series_equal(before.signals.iloc[-1], after.signals.iloc[-1])
    for key in before.factors:
        pd.testing.assert_series_equal(before.factors[key].iloc[-1], after.factors[key].iloc[-1])


def test_score_uses_prior_sixty_day_range_and_nearest_prior_ma():
    panels = example()
    result = DoubleYinLowOpenV1().compute(panels)
    price = panels["open"].iloc[-1, 0]
    high = panels["high"].iloc[-61:-1, 0].max()
    low = panels["low"].iloc[-61:-1, 0].min()
    position = np.clip((price - low) / (high - low), 0, 1)
    averages = {period: panels["close"].iloc[-period - 1:-1, 0].mean() for period in (5, 10, 20)}
    nearest = min(averages, key=lambda period: abs(price / averages[period] - 1))
    distance = abs(price / averages[nearest] - 1)
    low_score = 20 * (1 - position)
    ma_score = 20 * np.clip(1 - distance / 0.03, 0, 1)
    retained = (price - panels["open"].iloc[-3, 0]) / (
        panels["close"].iloc[-3, 0] - panels["open"].iloc[-3, 0])
    support_score = 20 * retained + 10
    assert result.factors["最近均线周期"].iloc[-1, 0] == nearest
    assert result.factors["最近均线价格"].iloc[-1, 0] == pytest.approx(averages[nearest], abs=1e-6)
    assert result.factors["区间位置"].iloc[-1, 0] == pytest.approx(position, abs=1e-6)
    assert result.factors["低位分(20)"].iloc[-1, 0] == round(low_score, 4)
    assert result.factors["临近均线分(20)"].iloc[-1, 0] == round(ma_score, 4)
    assert result.factors["趋势分(30)"].iloc[-1, 0] == 30
    assert result.factors["支撑分(30)"].iloc[-1, 0] == round(support_score, 4)
    assert result.factors["大阳实体保留比例"].iloc[-1, 0] == round(retained, 6)
    assert result.factors["score"].iloc[-1, 0] == round(low_score + ma_score + 30 + support_score, 4)
    explanation = result.explain(panels["open"].index[-1], "600001")
    assert explanation["最近均线周期"] == nearest


def test_ma_score_twenty_at_exact_average_and_far_open_only_loses_ma_points():
    panels = example()
    panels["close"].iloc[:-3, 0] = 9.8
    for pos in (-6, -5):
        candle(panels, pos, open_=10.5, close=10.5, high=10.6, low=10.4)
    candle(panels, -4, open_=10, close=10, high=10.1, low=9.9)
    ma = panels["close"].iloc[-6:-1, 0].mean()
    panels["open"].iloc[-1, 0] = ma
    exact = DoubleYinLowOpenV1().compute(panels)
    assert exact.factors["条件候选"].iloc[-1, 0]
    assert exact.factors["临近均线分(20)"].iloc[-1, 0] == 20
    far = DoubleYinLowOpenV1().compute(example(gain=25))
    assert far.factors["基础开盘候选"].iloc[-1, 0]
    assert far.factors["趋势方向合格"].iloc[-1, 0]
    assert far.factors["支撑质量合格"].iloc[-1, 0]
    assert not far.factors["均线距离合格"].iloc[-1, 0]
    assert far.factors["临近均线分(20)"].iloc[-1, 0] == 0
    assert far.factors["开盘质量总分"].iloc[-1, 0] >= 50
    assert far.factors["条件候选"].iloc[-1, 0]
    assert far.signals.iloc[-1, 0]


@pytest.mark.parametrize("relative_distance,accepted", [
    (0.029999, True), (0.03, True), (0.030001, False),
])
def test_nearest_ma_three_percent_boundary_is_diagnostic_and_score_saturation(relative_distance, accepted):
    panels = example(gain=9.5)
    ma5 = panels["close"].iloc[-6:-1, 0].mean()
    panels["open"].iloc[-1, 0] = ma5 * (1 + relative_distance)
    result = DoubleYinLowOpenV1().compute(panels)
    assert result.factors["基础开盘候选"].iloc[-1, 0]
    assert result.factors["趋势方向合格"].iloc[-1, 0]
    assert result.factors["支撑质量合格"].iloc[-1, 0]
    assert bool(result.factors["均线距离合格"].iloc[-1, 0]) is accepted
    assert result.signals.iloc[-1, 0]
    assert result.factors["最近均线周期"].iloc[-1, 0] == 5
    assert result.factors["均线偏离(%)"].iloc[-1, 0] == round(relative_distance * 100, 4)
    assert result.factors["临近均线分(20)"].iloc[-1, 0] == round(
        20 * max(1 - relative_distance / 0.03, 0), 4)


def test_lower_range_position_has_priority_when_ma_distance_same():
    panels = together(example(code="600001"), example(code="600002"))
    panels["high"].iloc[0, 0] = 40
    result = DoubleYinLowOpenV1().compute(panels)
    assert result.factors["临近均线分(20)"].iloc[-1, 0] == result.factors["临近均线分(20)"].iloc[-1, 1]
    assert result.factors["低位分(20)"].iloc[-1, 0] > result.factors["低位分(20)"].iloc[-1, 1]
    assert result.factors["候选名次"].iloc[-1].to_dict() == {"600001": 1, "600002": 2}


@pytest.mark.parametrize("first,second", [
    (("industry:食品饮料",), ("industry:食品饮料",)),
    (("industry:食品饮料", "family:消费"), ("industry:零售", "family:消费")),
])
def test_same_or_adjacent_consumer_sector_skips_second_and_picks_third(first, second):
    panels = together(*(example(code=f"60000{number}") for number in range(1, 4)))
    panels["__sector_groups__"] = {"600001": first, "600002": second, "600003": ("industry:电力",)}
    result = DoubleYinLowOpenV1().compute(panels)
    day = panels["open"].index[-1]
    assert result.picks_on(day, rank_by="score") == ["600001", "600003"]
    assert result.factors["候选名次"].loc[day].to_dict() == {"600001": 1, "600002": 2, "600003": 3}
    assert result.factors["同板块排除"].at[day, "600002"]
    assert result.factors["精选名次"].at[day, "600003"] == 2
    assert np.isfinite(result.factors["score"].at[day, "600002"])


def test_conflict_is_against_selected_groups_not_previously_rejected_candidates():
    panels = together(*(example(code=f"60000{number}") for number in range(1, 4)))
    panels["__sector_groups__"] = {
        "600001": ("industry:A",), "600002": ("industry:A", "family:B"),
        "600003": ("industry:C", "family:B"),
    }
    assert selected(panels) == ["600001", "600003"]


@pytest.mark.parametrize("groups", [None, {}, {"600001": ()}, {"600001": "industry:A"},
                                    {"600001": ("",)}, {"600001": (None,)}])
def test_missing_or_invalid_groups_preserve_candidate_and_score_but_no_pick(groups):
    panels = example()
    panels["__sector_groups__"] = groups
    result = DoubleYinLowOpenV1().compute(panels)
    assert result.factors["条件候选"].iloc[-1, 0]
    assert np.isfinite(result.factors["score"].iloc[-1, 0])
    assert not result.factors["行业数据完整"].iloc[-1, 0]
    assert not result.signals.iloc[-1, 0]


def test_undersubscribed_two_does_not_add_non_candidates_or_conflicting_sectors():
    panels = together(example(code="600001"), example(code="600002"))
    panels["__sector_groups__"] = {code: ("industry:A",) for code in panels["open"].columns}
    assert selected(panels) == ["600001"]
    panels["volume"].iloc[-2] = 100
    assert selected(panels) == []


def test_ties_use_code_order_and_top_n_is_configurable():
    panels = together(example(code="600003"), example(code="600001"), example(code="600002"))
    assert selected(panels) == ["600001", "600002"]
    assert selected(panels, {"top_n": 1}) == ["600001"]
    assert selected(panels, {"top_n": 3}) == ["600001", "600002", "600003"]


def test_configured_history_requirement_and_execution_profile_agree():
    engine = DoubleYinLowOpenV1()
    assert engine.default_universe["boards"] == ["main"]
    assert engine.screen_allowed_boards == ("main",)
    assert engine.version == "v3"
    assert engine.strategy_revision == "builtin:double-volume-yin-low-open-v1:3.1"
    assert engine.history_bars() == 61
    assert engine.history_bars({"position_lookback": 90}) == 91
    assert engine.history_bars({"recent_days": 100}) == 103
    assert selected(example(), {"position_lookback": 90}) == []
    assert selected(example(bars=91), {"position_lookback": 90}) == ["600001"]
    profile = engine.execution_profile({"position_lookback": 90})
    assert profile.pure and profile.causal and profile.column_mode == "coupled"
    assert profile.origin == "finite" and profile.lookback_bars == 91
    assert profile.metadata_fields == ("__instrument_names__", "__sector_groups__")


def test_finite_history_latest_result_matches_full_history():
    panels = together(rising_example(code="600001", bars=100),
                      declining_rebound_example(code="600002", bars=100))
    engine = DoubleYinLowOpenV1()
    full = engine.compute(panels)
    assert full.signals.iloc[-1].to_dict() == {"600001": True, "600002": False}
    sliced = {key: value.iloc[-engine.history_bars():] if isinstance(value, pd.DataFrame) else value
              for key, value in panels.items()}
    limited = engine.compute(sliced)
    pd.testing.assert_series_equal(full.signals.iloc[-1], limited.signals.iloc[-1])
    for key in full.factors:
        pd.testing.assert_series_equal(full.factors[key].iloc[-1], limited.factors[key].iloc[-1])


def test_flat_ma_rolling_tail_error_matches_finite_window_without_hiding_real_decline():
    # 600618在2024-12-11的真实收盘序列。原470根历史的尾差只需62根即可重现；
    # 固定序列使回归测试无需行情库或外部数据，其他OHLC按收盘包络构造有效日K。
    closes = [
        7.55, 7.44, 7.4, 7.36, 7.35, 7.27, 7.27, 7.43, 7.37, 7.48, 7.92,
        7.91, 8.23, 8.45, 9.18, 9.58, 8.82, 8.83, 8.53, 8.68, 8.44, 8.46,
        8.28, 8.42, 8.36, 8.52, 8.61, 8.56, 8.81, 9.11, 8.84, 8.85, 9.31,
        9.36, 9.61, 9.66, 9.6, 9.64, 9.57, 9.74, 9.62, 9.65, 9.39, 9.31,
        9.28, 9.62, 9.9, 9.87, 9.42, 9.48, 9.39, 9.3, 9.42, 9.45, 9.65,
        9.63, 9.46, 9.59, 9.75, 10.73, 11.02, 11.13,
    ]
    panels = example(code="600618", bars=len(closes))
    for field, offset in {"open": 0, "close": 0, "high": 0.1, "low": -0.1}.items():
        panels[field].iloc[:, 0] = np.asarray(closes) + offset
    candle(panels, -3, open_=9.84, close=10.73, high=10.73, low=9.76, volume=21481700)
    candle(panels, -2, open_=11.48, close=11.02, high=11.8, low=10.97, volume=56297600)
    panels["open"].iloc[-1, 0] = 11.01
    for field in ("close", "high", "low", "volume"):
        panels[field].iloc[-1, 0] = np.nan
    engine = DoubleYinLowOpenV1()
    short = {key: value.iloc[-engine.history_bars():] if isinstance(value, pd.DataFrame) else value
             for key, value in panels.items()}
    # 数学上均为9.546，rolling的累计尾差会让两种输入分别误报下降/上升。
    full_ma = panels["close"].shift(3).rolling(20).mean()
    short_ma = short["close"].shift(3).rolling(20).mean()
    assert full_ma.iloc[-1, 0] < full_ma.iloc[-6, 0]
    assert short_ma.iloc[-1, 0] > short_ma.iloc[-6, 0]
    full = engine.compute(panels)
    limited = engine.compute(short)
    assert full.factors["趋势分(30)"].iloc[-1, 0] == 30
    assert full.signals.iloc[-1, 0]
    pd.testing.assert_series_equal(full.signals.iloc[-1], limited.signals.iloc[-1])
    for key in full.factors:
        pd.testing.assert_series_equal(full.factors[key].iloc[-1], limited.factors[key].iloc[-1])

    descending = {key: value.copy() if isinstance(value, pd.DataFrame) else value
                  for key, value in panels.items()}
    # 显著增大旧窗口独有的一根收盘，造成真实下降；容差不能消除这7.5分扣分。
    candle(descending, -28, open_=9.68, close=9.68, high=9.78, low=9.58)
    falling = engine.compute(descending)
    assert falling.factors["大涨前20日均线五日变化(%)"].iloc[-1, 0] < -0.01
    assert falling.factors["趋势分(30)"].iloc[-1, 0] == 22.5
    assert not falling.factors["大涨前弱趋势"].iloc[-1, 0]
    # 再使大涨前价格低于下行MA，组合弱趋势必须继续硬拦。
    candle(descending, -4, open_=9.53, close=9.53, high=9.63, low=9.43)
    weak = engine.compute(descending)
    assert weak.factors["历史形态候选"].iloc[-1, 0]
    assert weak.factors["大涨前弱趋势"].iloc[-1, 0]
    assert not weak.factors["趋势方向合格"].iloc[-1, 0]
    assert not weak.signals.iloc[-1, 0]


def test_truncated_history_with_real_signal_matches_all_past_factors():
    panels = example(bars=80)
    candle(panels, 62, open_=10, close=10.8, high=10.9, low=9.9)
    candle(panels, 63, open_=10.7, close=10.6, high=10.8, low=10.5, volume=200)
    panels["open"].iloc[64, 0] = 10.5
    engine = DoubleYinLowOpenV1()
    full = engine.compute(panels)
    assert full.signals.iloc[64, 0]
    truncated = {key: value.iloc[:65] if isinstance(value, pd.DataFrame) else value
                 for key, value in panels.items()}
    prefix = engine.compute(truncated)
    pd.testing.assert_frame_equal(full.signals.iloc[:65], prefix.signals)
    for key in full.factors:
        pd.testing.assert_frame_equal(full.factors[key].iloc[:65], prefix.factors[key])


@pytest.mark.parametrize("rising", [False, True])
def test_healthy_flat_or_rising_trend_and_intact_support_remain_candidates(rising):
    panels = rising_example() if rising else example()
    result = DoubleYinLowOpenV1().compute(panels)
    assert result.factors["历史趋势合格"].iloc[-1, 0]
    assert result.factors["趋势方向合格"].iloc[-1, 0]
    assert result.factors["支撑质量合格"].iloc[-1, 0]
    pre_rally_change = result.factors["大涨前20日均线五日变化(%)"].iloc[-1, 0]
    assert pre_rally_change > 0 if rising else pre_rally_change == 0
    assert selected(panels) == ["600001"]


def test_rebound_cannot_turn_preexisting_decline_into_a_preferred_candidate():
    panels = declining_rebound_example()
    result = DoubleYinLowOpenV1().compute(panels)
    assert result.factors["历史形态候选"].iloc[-1, 0]
    assert result.factors["20日均线五日变化(%)"].iloc[-1, 0] > 0
    assert result.factors["大涨前20日均线五日变化(%)"].iloc[-1, 0] < 0
    assert result.factors["昨日守住20日均线"].iloc[-1, 0]
    assert result.factors["开盘守住20日均线"].iloc[-1, 0]
    assert result.factors["支撑质量合格"].iloc[-1, 0]
    assert not result.factors["历史趋势合格"].iloc[-1, 0]
    assert not result.factors["趋势方向合格"].iloc[-1, 0]
    assert not result.factors["条件候选"].iloc[-1, 0]
    assert np.isnan(result.factors["score"].iloc[-1, 0])
    assert selected(panels) == []


def test_pre_rally_declining_ma_without_price_below_it_only_loses_direction_points():
    panels = example()
    for pos in range(-28, -23):
        candle(panels, pos, open_=10.1, close=10.1, high=10.2, low=10)
    result = DoubleYinLowOpenV1().compute(panels)
    assert result.factors["大涨前20日均线五日变化(%)"].iloc[-1, 0] < 0
    assert panels["close"].iloc[-4, 0] >= result.factors["大涨前MA20"].iloc[-1, 0]
    assert not result.factors["大涨前弱趋势"].iloc[-1, 0]
    assert result.factors["历史趋势合格"].iloc[-1, 0]
    assert result.factors["趋势分(30)"].iloc[-1, 0] == 22.5
    assert selected(panels) == ["600001"]


@pytest.mark.parametrize("below_ma", [False, True])
def test_declining_yesterday_ma20_only_rejects_when_close_and_open_are_below_it(below_ma):
    panels = example()
    for pos in (-28, -27):
        candle(panels, pos, open_=8, close=8, high=8.1, low=7.9)
    for pos in (-23, -22):
        candle(panels, pos, open_=12, close=12, high=12.1, low=11.9)
    candle(panels, -4, open_=10.3, close=10.3, high=10.4, low=10.2)
    candle(panels, -3, open_=9.8, close=11.124, high=11.2, low=9.7)
    yesterday = 10.04 if below_ma else 10.924
    candle(panels, -2, open_=11.024, close=yesterday, high=11.124, low=yesterday - 0.1, volume=200)
    panels["open"].iloc[-1, 0] = 10.03 if below_ma else 10.75
    result = DoubleYinLowOpenV1().compute(panels)
    assert result.factors["历史形态候选"].iloc[-1, 0]
    assert result.factors["大涨前20日均线五日变化(%)"].iloc[-1, 0] > 0
    assert panels["close"].iloc[-4, 0] >= result.factors["大涨前MA20"].iloc[-1, 0]
    assert result.factors["20日均线五日变化(%)"].iloc[-1, 0] < 0
    assert result.factors["支撑质量合格"].iloc[-1, 0]
    assert result.factors["均线距离合格"].iloc[-1, 0]
    assert result.factors["历史趋势合格"].iloc[-1, 0]
    assert bool(result.factors["当前弱趋势"].iloc[-1, 0]) is below_ma
    assert bool(result.factors["趋势方向合格"].iloc[-1, 0]) is not below_ma
    assert selected(panels) == ([] if below_ma else ["600001"])


def test_pre_rally_price_below_rising_ma20_loses_points_without_weak_trend_rejection():
    panels = example()
    for field in ("open", "close"):
        panels[field].iloc[-23:-4, 0] = 10.2
    result = DoubleYinLowOpenV1().compute(panels)
    assert result.factors["历史形态候选"].iloc[-1, 0]
    assert result.factors["大涨前20日均线五日变化(%)"].iloc[-1, 0] > 0
    assert result.factors["20日均线五日变化(%)"].iloc[-1, 0] > 0
    assert panels["close"].iloc[-4, 0] < result.factors["大涨前MA20"].iloc[-1, 0]
    assert result.factors["昨日守住20日均线"].iloc[-1, 0]
    assert result.factors["开盘守住20日均线"].iloc[-1, 0]
    assert result.factors["支撑质量合格"].iloc[-1, 0]
    assert result.factors["均线距离合格"].iloc[-1, 0]
    assert result.factors["历史趋势合格"].iloc[-1, 0]
    assert not result.factors["大涨前弱趋势"].iloc[-1, 0]
    assert result.factors["趋势分(30)"].iloc[-1, 0] == 22.5
    assert selected(panels) == ["600001"]


@pytest.mark.parametrize("position,value,factor,accepted", [
    (-2, 9.9, "昨日未跌破大阳低点", True),
    (-2, 9.899, "昨日未跌破大阳低点", False),
    (-1, 10.4, "开盘守住大阳实体中点", True),
    (-1, 10.399, "开盘守住大阳实体中点", False),
])
def test_midpoint_or_shadow_break_loses_support_points_without_hard_rejection(position, value, factor, accepted):
    panels = example()
    panels["low" if position == -2 else "open"].iloc[position, 0] = value
    result = DoubleYinLowOpenV1().compute(panels)
    assert result.factors["历史形态候选"].iloc[-1, 0]
    assert bool(result.factors[factor].iloc[-1, 0]) is accepted
    assert result.factors["支撑质量合格"].iloc[-1, 0]
    retained = (panels["open"].iloc[-1, 0] - 10) / 0.8
    low_held = panels["low"].iloc[-2, 0] >= 9.9
    assert result.factors["支撑分(30)"].iloc[-1, 0] == round(20 * retained + 10 * low_held, 4)
    assert result.signals.iloc[-1, 0]


@pytest.mark.parametrize("yesterday_close,held", [(10.4, True), (10.399, False)])
def test_yesterday_and_opening_midpoint_breaks_are_diagnostics_with_partial_body_retention(yesterday_close, held):
    panels = example()
    candle(panels, -2, open_=10.7, close=yesterday_close, high=10.8, low=10.3, volume=200)
    panels["open"].iloc[-1, 0] = yesterday_close - 0.01
    result = DoubleYinLowOpenV1().compute(panels)
    assert result.factors["历史形态候选"].iloc[-1, 0]
    assert bool(result.factors["昨日守住大阳实体中点"].iloc[-1, 0]) is held
    assert not result.factors["开盘守住大阳实体中点"].iloc[-1, 0]
    assert result.factors["支撑质量合格"].iloc[-1, 0]
    assert 0 < result.factors["大阳实体保留比例"].iloc[-1, 0] < 0.5
    assert selected(panels) == ["600001"]


def test_body_retention_above_anchor_close_is_capped_at_full_support_points():
    panels = example()
    candle(panels, -2, open_=11.2, close=11.1, high=11.3, low=10.9, volume=200)
    panels["open"].iloc[-1, 0] = 11
    result = DoubleYinLowOpenV1().compute(panels)
    assert result.factors["基础开盘候选"].iloc[-1, 0]
    assert result.factors["大阳实体保留比例"].iloc[-1, 0] == 1
    assert result.factors["支撑分(30)"].iloc[-1, 0] == 30
    assert selected(panels) == ["600001"]


@pytest.mark.parametrize("opening_offset,held", [(0, True), (-0.001, False)])
def test_opening_ma20_support_equality_and_break(opening_offset, held):
    panels = example()
    panels["open"].iloc[-3, 0] = 9.2
    panels["low"].iloc[-3, 0] = 9.1
    ma20 = panels["close"].iloc[-21:-1, 0].mean()
    panels["open"].iloc[-1, 0] = ma20 + opening_offset
    result = DoubleYinLowOpenV1().compute(panels)
    assert result.factors["历史形态候选"].iloc[-1, 0]
    assert result.factors["支撑质量合格"].iloc[-1, 0]
    assert bool(result.factors["开盘守住20日均线"].iloc[-1, 0]) is held
    assert result.factors["历史趋势合格"].iloc[-1, 0]
    assert result.factors["趋势方向合格"].iloc[-1, 0]
    assert result.factors["趋势分(30)"].iloc[-1, 0] == (30 if held else 22.5)
    assert result.signals.iloc[-1, 0]


@pytest.mark.parametrize("yesterday_close,held", [(10, True), (9.99, False)])
def test_yesterday_ma20_support_equality_and_break(yesterday_close, held):
    panels = example()
    candle(panels, -10, open_=9.2, close=9.2, high=9.3, low=9.1)
    candle(panels, -3, open_=9, close=10.8, high=10.9, low=8.9)
    candle(panels, -2, open_=10.7, close=yesterday_close, high=10.8, low=9.95, volume=200)
    panels["open"].iloc[-1, 0] = yesterday_close - 0.01
    result = DoubleYinLowOpenV1().compute(panels)
    assert result.factors["基础开盘候选"].iloc[-1, 0]
    assert result.factors["历史趋势合格"].iloc[-1, 0]
    assert result.factors["支撑质量合格"].iloc[-1, 0]
    assert result.factors["均线距离合格"].iloc[-1, 0]
    assert bool(result.factors["昨日守住20日均线"].iloc[-1, 0]) is held
    assert not result.factors["开盘守住20日均线"].iloc[-1, 0]
    assert result.factors["20日均线五日变化(%)"].iloc[-1, 0] > 0
    assert not result.factors["当前弱趋势"].iloc[-1, 0]
    assert selected(panels) == ["600001"]


@pytest.mark.parametrize("good_count", [0, 1, 2])
def test_default_quota_never_backfills_trend_or_support_failures(good_count):
    failed_support = example(code="600003")
    failed_support["open"].iloc[-1, 0] = 9.99
    items = [declining_rebound_example(code="600004"), failed_support,
             low_quality_example(code="600005")]
    items.extend(example(code=f"60000{number}") for number in range(1, good_count + 1))
    panels = together(*items)
    result = DoubleYinLowOpenV1().compute(panels)
    assert result.factors["历史形态候选"].iloc[-1].all()
    assert result.picks_on(panels["open"].index[-1], rank_by="score") == [
        f"60000{number}" for number in range(1, good_count + 1)
    ]
    for code in ("600003", "600004", "600005"):
        assert not result.factors["条件候选"].iloc[-1][code]
        assert np.isnan(result.factors["score"].iloc[-1][code])
    assert result.factors["趋势方向合格"].iloc[-1]["600005"]
    assert result.factors["支撑质量合格"].iloc[-1]["600005"]
    assert not result.factors["最低评分合格"].iloc[-1]["600005"]


@pytest.mark.parametrize("opening,accepted", [(10, True), (9.999, False)])
def test_anchor_open_support_equality_and_complete_body_loss_boundary(opening, accepted):
    panels = example()
    panels["open"].iloc[-1, 0] = opening
    result = DoubleYinLowOpenV1().compute(panels)
    assert result.factors["基础开盘候选"].iloc[-1, 0]
    assert bool(result.factors["大阳实体失守"].iloc[-1, 0]) is not accepted
    assert bool(result.factors["支撑质量合格"].iloc[-1, 0]) is accepted
    assert bool(result.signals.iloc[-1, 0]) is accepted


def test_yesterday_complete_body_loss_rejects_even_with_high_other_quality_scores():
    panels = example()
    panels["high"].iloc[0, 0] = 40
    candle(panels, -2, open_=10.7, close=9.99, high=10.8, low=9.89, volume=200)
    panels["open"].iloc[-1, 0] = 9.98
    result = DoubleYinLowOpenV1().compute(panels)
    assert result.factors["基础开盘候选"].iloc[-1, 0]
    assert result.factors["大阳实体失守"].iloc[-1, 0]
    assert not result.factors["支撑质量合格"].iloc[-1, 0]
    assert result.factors["开盘质量总分"].iloc[-1, 0] >= 50
    assert not result.signals.iloc[-1, 0]


@pytest.mark.parametrize("offset,accepted", [(-0.000001, False), (0, True), (0.000001, True)])
def test_minimum_score_uses_unrounded_total_at_fifty_even_when_display_rounds_equal(offset, accepted):
    panels = example(gain=25)
    panels["high"].iloc[0, 0] = 13
    panels["low"].iloc[-2, 0] = 9.8
    panels["open"].iloc[-1, 0] = 12 + offset
    result = DoubleYinLowOpenV1().compute(panels)
    assert result.factors["基础开盘候选"].iloc[-1, 0]
    assert result.factors["趋势方向合格"].iloc[-1, 0]
    assert result.factors["支撑质量合格"].iloc[-1, 0]
    assert result.factors["临近均线分(20)"].iloc[-1, 0] == 0
    assert result.factors["开盘质量总分"].iloc[-1, 0] == 50.0
    assert bool(result.factors["最低评分合格"].iloc[-1, 0]) is accepted
    assert bool(result.factors["条件候选"].iloc[-1, 0]) is accepted
    assert bool(result.signals.iloc[-1, 0]) is accepted
    assert (result.factors["score"].iloc[-1, 0] == 50.0) if accepted else np.isnan(
        result.factors["score"].iloc[-1, 0])


@pytest.mark.parametrize("bars", [20, 25, 60])
def test_insufficient_history_cannot_create_a_trend_qualified_pick(bars):
    result = DoubleYinLowOpenV1().compute(example(bars=bars))
    assert not result.factors["条件候选"].iloc[-1, 0]
    assert np.isnan(result.factors["score"].iloc[-1, 0])
    assert not result.signals.iloc[-1, 0]


def test_nan_in_pre_rally_trend_window_fails_closed():
    panels = example()
    panels["close"].iloc[-23, 0] = np.nan
    result = DoubleYinLowOpenV1().compute(panels)
    assert not result.factors["历史趋势合格"].iloc[-1, 0]
    assert not result.factors["趋势方向合格"].iloc[-1, 0]
    assert not result.factors["条件候选"].iloc[-1, 0]
    assert np.isnan(result.factors["score"].iloc[-1, 0])
    assert not result.signals.iloc[-1, 0]


@pytest.mark.parametrize("params", [
    {"recent_days": 0}, {"recent_days": 1.5}, {"top_n": False}, {"top_n": -1},
    {"position_lookback": 0}, {"position_lookback": "60"},
    {"volume_ratio": 0.9}, {"volume_ratio": np.inf},
    {"price_floor": -1}, {"price_floor": np.nan}, {"price_floor": True},
    {"max_recent_gain_pct": -1}, {"max_recent_gain_pct": "30"}, {"unknown": 1},
])
def test_invalid_or_unknown_parameters_rejected(params):
    with pytest.raises(StrategyError):
        selected(example(), params)


def test_parameters_change_actual_conditions():
    panels = example()
    assert selected(panels, {"volume_ratio": 2.1}) == []
    assert selected(panels, {"max_recent_gain_pct": 7.99}) == []
    assert selected(panels, {"price_floor": 10.5}) == []
    assert selected(panels, {"price_floor": 10.49}) == ["600001"]


def test_missing_field_and_duplicate_axis_rejected():
    panels = example()
    del panels["volume"]
    with pytest.raises(StrategyError, match="volume"):
        selected(panels)
    panels = example()
    panels["open"].index = ["2025-01-02"] * len(panels["open"])
    with pytest.raises(StrategyError, match="唯一"):
        selected(panels)


def test_auction_strategy_does_not_enter_eod_restart_catchup():
    from datetime import datetime
    from zoneinfo import ZoneInfo
    from src.ops.application.eod_catchup import jobs_due_for_eod_catchup

    engine = DoubleYinLowOpenV1()
    job = {"name": "screen:" + engine.slug, "kind": "screen", "enabled": True,
           "cron": "25 9 * * mon-fri", "config": dict(engine.screen_job_config)}
    options = {"last_trading_day": "2026-09-30",
               "now": datetime(2026, 10, 3, 21, tzinfo=ZoneInfo("Asia/Shanghai"))}
    assert jobs_due_for_eod_catchup([job], **options) == []
    job["config"].pop("catch_up")
    assert len(jobs_due_for_eod_catchup([job], **options)) == 1
