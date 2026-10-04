"""开盘因果性、晚间完整形态快照、规则评分与板块去重的确定性样本。"""
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


def test_yin_day_does_not_need_high_open_or_support_hold():
    panels = example()
    assert panels["open"].iloc[-2, 0] < panels["close"].iloc[-3, 0]
    candle(panels, -2, open_=10.6, close=9.8, high=10.7, low=8.5, volume=200)
    panels["open"].iloc[-1, 0] = 9.7
    assert selected(panels) == ["600001"]


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
                                                 (10.6, False), (10.61, False),
                                                 (np.nan, False), (np.inf, False)])
def test_low_open_and_six_yuan_boundary_use_current_open(open_price, expected):
    panels = example()
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
    low_score = 60 * (1 - position)
    ma_score = 40 * np.clip(1 - distance / 0.03, 0, 1)
    assert result.factors["最近均线周期"].iloc[-1, 0] == nearest
    assert result.factors["最近均线价格"].iloc[-1, 0] == pytest.approx(averages[nearest], abs=1e-6)
    assert result.factors["区间位置"].iloc[-1, 0] == pytest.approx(position, abs=1e-6)
    assert result.factors["低位分(60)"].iloc[-1, 0] == round(low_score, 4)
    assert result.factors["临近均线分(40)"].iloc[-1, 0] == round(ma_score, 4)
    assert result.factors["score"].iloc[-1, 0] == round(low_score + ma_score, 4)
    explanation = result.explain(panels["open"].index[-1], "600001")
    assert explanation["最近均线周期"] == nearest


def test_ma_score_forty_at_exact_average_zero_at_three_percent_or_more():
    panels = example()
    ma = panels["close"].iloc[-6:-1, 0].mean()
    panels["open"].iloc[-1, 0] = ma
    exact = DoubleYinLowOpenV1().compute(panels)
    assert exact.factors["临近均线分(40)"].iloc[-1, 0] == 40
    panels["open"].iloc[-1, 0] = 6.01
    far = DoubleYinLowOpenV1().compute(panels)
    assert far.factors["临近均线分(40)"].iloc[-1, 0] == 0
    assert 0 <= far.factors["score"].iloc[-1, 0] <= 100


def test_lower_range_position_has_priority_when_ma_distance_same():
    panels = together(example(code="600001"), example(code="600002"))
    panels["high"].iloc[0, 0] = 40
    result = DoubleYinLowOpenV1().compute(panels)
    assert result.factors["临近均线分(40)"].iloc[-1, 0] == result.factors["临近均线分(40)"].iloc[-1, 1]
    assert result.factors["低位分(60)"].iloc[-1, 0] > result.factors["低位分(60)"].iloc[-1, 1]
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
    assert engine.version == "v2"
    assert engine.strategy_revision == "builtin:double-volume-yin-low-open-v1:2"
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
    panels = example(bars=100)
    engine = DoubleYinLowOpenV1()
    full = engine.compute(panels)
    sliced = {key: value.iloc[-engine.history_bars():] if isinstance(value, pd.DataFrame) else value
              for key, value in panels.items()}
    limited = engine.compute(sliced)
    pd.testing.assert_series_equal(full.signals.iloc[-1], limited.signals.iloc[-1])
    for key in full.factors:
        pd.testing.assert_series_equal(full.factors[key].iloc[-1], limited.factors[key].iloc[-1])


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
