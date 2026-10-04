"""评分口径、完整创业板池每日排名与因果投影。"""
from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from src.strategy.application.compute_runtime import project_result, truncate_panels
from src.strategy.application.contraction_rebreakout import ContractionRebreakoutV1
from tests.test_contraction_rebreakout import FIELDS, mango_example, threshold_example


COMPONENTS = ("10日动量分(40)", "回调缩量分(15)", "回调深度分(15)", "再突破放量分(10)", "收盘位置分(20)")
WEIGHTS = (40, 15, 15, 10, 20)
PANEL_FIELDS = (*FIELDS, "__raw_close")


def pool(volumes: dict[str, float], *, bars: int = 31) -> dict:
    samples = []
    for code, volume in volumes.items():
        sample = threshold_example(bars=bars)
        for field in PANEL_FIELDS:
            sample[field].columns = [code]
        sample["volume"].iloc[-1, 0] = volume
        samples.append(sample)
    panels = {field: pd.concat([sample[field] for sample in samples], axis=1) for field in PANEL_FIELDS}
    panels["__instrument_names__"] = {code: "创业样本" for code in volumes}
    return panels


def two_days() -> tuple[dict, list[str]]:
    panels = pool({"300003": 90., "301001": 120., "300002": 180.}, bars=70)
    for field in PANEL_FIELDS:
        panels[field].iloc[20:34] = panels[field].iloc[-14:].to_numpy()
    panels["volume"].iloc[33] = [180., 120., 90.]
    return panels, [panels["close"].index[33], panels["close"].index[-1]]


def assert_same(actual, expected) -> None:
    pd.testing.assert_frame_equal(actual.signals, expected.signals, check_exact=True)
    assert actual.watch_signals is expected.watch_signals is None
    assert actual.factors.keys() == expected.factors.keys()
    for name, frame in expected.factors.items():
        pd.testing.assert_frame_equal(actual.factors[name], frame, check_exact=True, obj=name)


def test_metadata_declares_fixed_score_coupled_top_two_and_causal_full_origin():
    engine = ContractionRebreakoutV1()
    assert engine.default_params() == {}
    assert getattr(engine, "default_universe", None) is None
    assert engine.screen_top_n == 2
    assert engine.screen_rank_factor == "score"
    assert engine.version == "v1.2"
    assert engine.strategy_revision == "builtin:contraction-rebreakout-v1:3"
    profile = engine.execution_profile()
    assert profile.pure and profile.causal
    assert profile.column_mode == "coupled"
    assert profile.origin == "sensitive"
    assert profile.metadata_fields == ("__raw_close", "__instrument_names__")
    assert not engine.screen_managed_job
    assert not engine.range_prime_enabled


def test_known_mango_score_uses_five_disclosed_components_without_outcome_data():
    result = ContractionRebreakoutV1().compute(mango_example())
    expected = [29.0341237710, 12.3681454585, 10.5768235903, 3.9576448437, 16.5384615385]
    for name, value, maximum in zip(COMPONENTS, expected, WEIGHTS, strict=True):
        actual = result.factors[name].at["2026-09-29", "300413"]
        assert actual == pytest.approx(value, abs=1e-8)
        assert 0 <= actual <= maximum
    assert result.factors["score"].at["2026-09-29", "300413"] == 72.4752
    assert "已知案例校准" in ContractionRebreakoutV1.entry_instructions


def test_real_six_candidate_calibration_ranks_guangkang_and_mango_first_and_excludes_closing_limit():
    fixture = json.loads((Path(__file__).parent / "fixtures" /
                          "contraction_rebreakout_candidates_20260929.json").read_text(encoding="utf-8"))
    panels = {field: pd.DataFrame(values, index=fixture["dates"], columns=fixture["codes"], dtype=float)
              for field, values in fixture["panels"].items()}
    panels["__instrument_names__"] = fixture["names"]
    result = ContractionRebreakoutV1().compute(panels)
    day = fixture["as_of"]
    assert max(fixture["dates"]) == day
    assert result.picks_on(day, rank_by="score") == ["300804", "300413"]
    assert result.factors["score"].at[day, "300804"] == 72.8576
    assert result.factors["score"].at[day, "300413"] == 72.4752
    assert not result.factors["条件候选"].at[day, "301513"]
    assert not result.factors["收盘非涨停"].at[day, "301513"]
    # 重命名不改变排名，排名依据不依赖已知目标名称。
    panels["__instrument_names__"] = dict.fromkeys(fixture["codes"], "创业样本")
    pd.testing.assert_frame_equal(result.signals, ContractionRebreakoutV1().compute(panels).signals)


def test_all_candidates_are_scored_then_only_two_highest_remain_in_signals():
    panels = pool({"300003": 90., "301001": 120., "300002": 180.})
    result = ContractionRebreakoutV1().compute(panels)
    day = panels["close"].index[-1]
    assert result.factors["条件候选"].loc[day].all()
    assert result.picks_on(day, rank_by="score") == ["300002", "301001"]
    assert result.factors["候选排名"].loc[day].to_dict() == {
        "300003": 3., "301001": 2., "300002": 1.,
    }
    pd.testing.assert_frame_equal(result.signals, result.factors["每日前二"])
    for code in panels["close"].columns:
        score = result.factors["score"].at[day, code]
        assert score == round(score, 4)
        assert score == pytest.approx(sum(result.factors[name].at[day, code] for name in COMPONENTS), abs=5e-5)


@pytest.mark.parametrize("reverse", [False, True])
def test_score_ties_are_resolved_by_code_across_the_complete_pool(reverse):
    codes = ["301002", "300003", "300002", "301001", "300001"]
    if reverse:
        codes.reverse()
    panels = pool(dict.fromkeys(codes, 120.))
    result = ContractionRebreakoutV1().compute(panels)
    day = panels["close"].index[-1]
    assert result.factors["score"].loc[day].nunique() == 1
    assert result.picks_on(day, rank_by="score") == ["300001", "300002"]
    assert result.factors["候选排名"].loc[day].to_dict() == {
        code: float(rank) for rank, code in enumerate(sorted(codes), 1)
    }


@pytest.mark.parametrize("count", [0, 1, 2])
def test_fewer_than_two_candidates_are_never_filled_by_ineligible_stocks(count):
    codes = ["300001", "300002", "301001"]
    panels = pool(dict.fromkeys(codes, 120.))
    for code in codes[count:]:
        panels["volume"].iloc[-1, panels["volume"].columns.get_loc(code)] = 0.
    result = ContractionRebreakoutV1().compute(panels)
    day = panels["close"].index[-1]
    assert result.picks_on(day, rank_by="score") == codes[:count]
    assert int(result.factors["条件候选"].loc[day].sum()) == count
    assert result.factors["score"].loc[day, codes[count:]].isna().all()


def test_rank_and_two_stock_cap_restart_independently_each_day():
    panels, days = two_days()
    result = ContractionRebreakoutV1().compute(panels)
    assert result.picks_on(days[0], rank_by="score") == ["300003", "301001"]
    assert result.picks_on(days[1], rank_by="score") == ["300002", "301001"]
    assert result.signals.sum(axis=1).le(2).all()
    assert int(result.signals.to_numpy().sum()) == 4


def test_contraction_and_breakout_saturation_caps_at_disclosed_weights():
    panels = threshold_example()
    panels["volume"].iloc[-3, 0] = 40.
    panels["volume"].iloc[-2, 0] = 30.
    panels["volume"].iloc[-1, 0] = 90.
    result = ContractionRebreakoutV1().compute(panels)
    assert result.signals.iloc[-1, 0]
    assert result.factors["回调均量比"].iloc[-1, 0] < .5
    assert result.factors["回调缩量分(15)"].iloc[-1, 0] == 15.
    assert result.factors["再突破放量分(10)"].iloc[-1, 0] == 10.
    panels["volume"].iloc[-1, 0] = 900.
    assert ContractionRebreakoutV1().compute(panels).factors["再突破放量分(10)"].iloc[-1, 0] == 10.


def test_depth_at_or_beyond_ten_percent_has_zero_component_without_changing_formula_candidate():
    panels = threshold_example()
    for offset, candle in {
        -4: [11.7, 12.1, 11.7, 12., 100.],
        -3: [11.6, 11.6, 11.4, 11.5, 80.],
        -2: [10.6, 10.6, 10.4, 10.5, 60.],
        -1: [10.5, 13.1, 10.5, 13., 90.],
    }.items():
        for field, value in zip(FIELDS, candle, strict=True):
            panels[field].iloc[offset, 0] = value
    result = ContractionRebreakoutV1().compute(panels)
    assert result.factors["条件候选"].iloc[-1, 0]
    assert result.factors["回调深度(%)"].iloc[-1, 0] == 12.5
    assert result.factors["回调深度分(15)"].iloc[-1, 0] == 0.


def test_close_at_the_high_has_full_close_location_component():
    panels = threshold_example()
    panels["high"].iloc[-1, 0] = 10.3
    result = ContractionRebreakoutV1().compute(panels)
    assert result.signals.iloc[-1, 0]
    assert result.factors["收盘位置分(20)"].iloc[-1, 0] == 20.


@pytest.mark.parametrize("momentum, expected", [(-.10, 0.), (0., 0.), (.10, 20.), (.20, 40.), (.50, 40.)])
def test_momentum_uses_tenth_prior_close_and_caps_at_forty(momentum, expected):
    panels = threshold_example()
    prior = panels["close"].iloc[-1, 0] / (1 + momentum)
    panels["open"].iloc[-11, 0] = prior
    panels["close"].iloc[-11, 0] = prior
    panels["low"].iloc[-11, 0] = prior * .99
    panels["high"].iloc[-11, 0] = prior * 1.01
    result = ContractionRebreakoutV1().compute(panels)
    assert result.factors["10日动量分(40)"].iloc[-1, 0] == pytest.approx(expected)


def test_overflowed_derived_volume_ratio_does_not_claim_a_finite_high_score_or_occupy_a_slot():
    panels = threshold_example()
    panels["volume"].iloc[-2, 0] = .01
    panels["volume"].iloc[-1, 0] = 1e308
    result = ContractionRebreakoutV1().compute(panels)
    assert not result.factors["条件候选"].iloc[-1, 0]
    assert not result.signals.iloc[-1, 0]
    assert np.isnan(result.factors["score"].iloc[-1, 0])


@pytest.mark.parametrize("selection", ["last", "both", "sparse_reverse", "missing"])
def test_projection_matches_reference_for_every_signal_score_rank_and_condition(selection):
    panels, days = two_days()
    dates = {"last": [days[-1]], "both": days,
             "sparse_reverse": [days[-1], panels["close"].index[20], days[0]],
             "missing": ["1900-01-01", days[-1]]}[selection]
    engine = ContractionRebreakoutV1()
    assert_same(engine.compute_projection(panels, None, dates), project_result(engine.compute(panels), dates))


def test_later_market_data_cannot_change_any_past_signal_factor_score_or_rank():
    panels, days = two_days()
    engine = ContractionRebreakoutV1()
    prefix = truncate_panels(panels, days[0])
    expected = engine.compute(prefix)
    actual = project_result(engine.compute(panels), list(prefix["close"].index))
    assert_same(actual, expected)
