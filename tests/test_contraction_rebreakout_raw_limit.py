"""收盘涨停剔除使用原始前收盘，保持分位边界和完整池排名。"""
from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from src.strategy.application.compute_runtime import project_result
from src.strategy.application.contraction_rebreakout import ContractionRebreakoutV1
from src.strategy.domain.base import StrategyError
from tests.test_contraction_rebreakout import FIELDS, mango_example, threshold_example


@pytest.mark.parametrize("gap, expected", [(0., False), (.01, True), (.02, True)])
def test_only_close_at_limit_is_removed_while_one_cent_retreat_and_intraday_touch_pass(gap, expected):
    panels = threshold_example()
    # qfq 形态仍成立；价格触板不等于封板，raw 收盘价决定是否剔除。
    panels["high"].iloc[-1, 0] = 12.
    panels["__raw_close"].iloc[-1, 0] = 12. - gap
    result = ContractionRebreakoutV1().compute(panels)
    assert result.factors["涨停价"].iloc[-1, 0] == 12.
    assert bool(result.factors["收盘非涨停"].iloc[-1, 0]) is expected
    assert bool(result.signals.iloc[-1, 0]) is expected


@pytest.mark.parametrize("previous, limit", [(16.67, 20.), (10.04, 12.05), (10.0375, 12.05)])
def test_twenty_percent_limit_uses_half_up_cent_rounding(previous, limit):
    panels = threshold_example()
    panels["__raw_close"].iloc[-2, 0] = previous
    panels["__raw_close"].iloc[-1, 0] = limit
    result = ContractionRebreakoutV1().compute(panels)
    assert result.factors["涨停价"].iloc[-1, 0] == limit
    assert not result.signals.iloc[-1, 0]
    panels["__raw_close"].iloc[-1, 0] = limit - .01
    assert ContractionRebreakoutV1().compute(panels).signals.iloc[-1, 0]


@pytest.mark.parametrize("noise", [-1e-11, 0., 1e-11])
def test_float_noise_around_a_sealed_limit_does_not_create_an_available_candidate(noise):
    panels = threshold_example()
    panels["__raw_close"].iloc[-1, 0] = 12. + noise
    assert not ContractionRebreakoutV1().compute(panels).signals.iloc[-1, 0]


def test_adjusted_close_cannot_hide_a_real_sealed_limit():
    panels = threshold_example()
    assert panels["close"].iloc[-1, 0] == 10.3
    panels["__raw_close"].iloc[-1, 0] = 12.
    result = ContractionRebreakoutV1().compute(panels)
    assert not result.signals.iloc[-1, 0]
    assert not result.factors["条件候选"].iloc[-1, 0]
    assert np.isnan(result.factors["score"].iloc[-1, 0])


def test_adjusted_price_touching_its_apparent_limit_cannot_remove_a_non_limit_raw_close():
    panels = threshold_example()
    panels["close"].iloc[-1, 0] = 12.
    panels["high"].iloc[-1, 0] = 12.
    # Shape prices and execution prices are deliberately different.
    assert panels["__raw_close"].iloc[-1, 0] == 10.3
    result = ContractionRebreakoutV1().compute(panels)
    assert result.signals.iloc[-1, 0]
    assert result.factors["收盘非涨停"].iloc[-1, 0]


def test_raw_close_is_required_and_never_silently_substituted_with_adjusted_prices():
    panels = mango_example()
    del panels["__raw_close"]
    with pytest.raises(StrategyError, match="未复权收盘价"):
        ContractionRebreakoutV1().compute(panels)


@pytest.mark.parametrize("offset", [-2, -1])
@pytest.mark.parametrize("invalid", [np.nan, np.inf, 0., -1.])
def test_invalid_raw_current_or_previous_close_fails_closed(offset, invalid):
    panels = mango_example()
    panels["__raw_close"].iloc[offset, 0] = invalid
    result = ContractionRebreakoutV1().compute(panels)
    assert not result.signals.iloc[-1, 0]
    assert not result.factors["收盘非涨停"].iloc[-1, 0]


def test_raw_limit_filter_is_applied_before_score_rank_so_sealed_stock_occupies_no_slot():
    samples = []
    codes = ["300001", "300002", "301001"]
    for code in codes:
        sample = threshold_example()
        for field in (*FIELDS, "__raw_close"):
            sample[field].columns = [code]
        samples.append(sample)
    panels = {field: pd.concat([sample[field] for sample in samples], axis=1) for field in (*FIELDS, "__raw_close")}
    panels["__instrument_names__"] = dict.fromkeys(codes, "创业边界样本")
    day = panels["close"].index[-1]
    panels["__raw_close"].at[day, "300001"] = 12.
    result = ContractionRebreakoutV1().compute(panels)
    assert set(result.picks_on(day, rank_by="score")) == {"300002", "301001"}
    assert not result.factors["条件候选"].at[day, "300001"]
    assert np.isnan(result.factors["候选排名"].at[day, "300001"])
    assert np.isnan(result.factors["score"].at[day, "300001"])
    assert set(result.factors["候选排名"].loc[day].dropna()) == {1., 2.}


def test_projection_matches_every_raw_limit_factor_and_rank_including_a_filtered_day():
    panels = mango_example()
    panels["__raw_close"].iloc[-1, 0] = 22.51
    engine = ContractionRebreakoutV1()
    days = list(panels["close"].index[-3:])
    actual = engine.compute_projection(panels, None, days)
    expected = project_result(engine.compute(panels), days)
    pd.testing.assert_frame_equal(actual.signals, expected.signals, check_exact=True)
    assert actual.factors.keys() == expected.factors.keys()
    for name in expected.factors:
        pd.testing.assert_frame_equal(actual.factors[name], expected.factors[name], check_exact=True)
