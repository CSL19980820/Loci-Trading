"""Cross-sectional scoring keeps the original gates and selects at most two per day."""
from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from src.strategy.application.compute_runtime import project_result, truncate_panels
from src.strategy.application.impulse_inside_breakout import ImpulseInsideBreakoutV1
from tests.test_impulse_inside_breakout import example
from tools.research_impulse_scoring import context_scores, rank_filtered


COMPONENTS = {
    "整理收敛分(30)": 30,
    "三日缩量分(25)": 25,
    "突破放量分(25)": 25,
    "收盘位置分(20)": 20,
}


def _pool(volumes: dict[str, float], *, bars: int = 200) -> dict:
    samples = []
    for code, volume in volumes.items():
        sample = example(bars=bars, code=code)
        sample["volume"].iloc[-1, 0] = volume
        samples.append(sample)
    panels = {
        name: pd.concat([sample[name] for sample in samples], axis=1)
        for name, frame in samples[0].items() if isinstance(frame, pd.DataFrame)
    }
    panels["__instrument_names__"] = {
        code: name for sample in samples for code, name in sample["__instrument_names__"].items()
    }
    return panels


def _two_breakout_days() -> tuple[dict, list[str]]:
    panels = _pool({"300003": 250., "300001": 600., "300002": 400.})
    for frame in panels.values():
        if isinstance(frame, pd.DataFrame):
            frame.iloc[175:180] = frame.iloc[-5:].to_numpy()
    panels["volume"].iloc[179] = [600., 250., 400.]
    return panels, [panels["close"].index[179], panels["close"].index[-1]]


def _assert_same_result(actual, expected) -> None:
    pd.testing.assert_frame_equal(actual.signals, expected.signals, check_exact=True)
    assert actual.watch_signals is expected.watch_signals is None
    assert actual.factors.keys() == expected.factors.keys()
    for name, frame in expected.factors.items():
        pd.testing.assert_frame_equal(actual.factors[name], frame, check_exact=True, obj=name)


def test_scoring_metadata_declares_coupled_top_two_selection():
    engine = ImpulseInsideBreakoutV1()
    assert engine.screen_top_n == 2
    assert engine.screen_rank_factor == "score"
    assert engine.execution_profile().column_mode == "coupled"
    assert engine.version == "v1.4"
    assert engine.strategy_revision == "builtin:impulse-inside-breakout-v1:5"
    assert getattr(engine, "default_universe", None) is None
    assert "统一股票池" in engine.description


def test_score_components_rank_all_qualified_stocks_and_keep_only_the_best_two():
    panels = _pool({"300003": 250., "300001": 400., "300002": 600.})
    result = ImpulseInsideBreakoutV1().compute(panels)
    day = panels["close"].index[-1]
    assert result.factors["条件候选"].loc[day].all()
    assert result.picks_on(day, rank_by="score") == ["300002", "300001"]
    assert result.factors["候选排名"].loc[day].to_dict() == {
        "300003": 3., "300001": 2., "300002": 1.,
    }
    pd.testing.assert_series_equal(
        result.signals.loc[day], result.factors["每日前二"].loc[day], check_names=False,
    )
    prior_volume = 530 / 3
    for code, volume in {"300003": 250., "300001": 400., "300002": 600.}.items():
        expected = [30 * (1 - .3 / .9), 25 * (1 - prior_volume / 300),
                    12.5 * min(volume / prior_volume - 1, 2), 20 * (.35 / .4)]
        for (name, maximum), value in zip(COMPONENTS.items(), expected, strict=True):
            actual = result.factors[name].at[day, code]
            assert 0 <= actual <= maximum
            assert actual == pytest.approx(value, abs=1e-4)
        score = result.factors["score"].at[day, code]
        assert 0 <= score <= 100
        assert score == round(score, 4)
        original = result.factors["原形态分(100)"].at[day, code]
        assert original == pytest.approx(round(sum(expected), 4), abs=1e-8)
        assert original == pytest.approx(sum(result.factors[name].at[day, code] for name in COMPONENTS),
                                         abs=2e-4)
        assert result.factors["位置评分上下文有效"].at[day, code]
        assert result.factors["形态前120日位置(%)"].at[day, code] == pytest.approx(200 / 3)
        assert result.factors["趋势修复"].at[day, code]
        assert result.factors["中期趋势向上"].at[day, code]
        assert result.factors["形态贡献分"].at[day, code] == pytest.approx(.7 * original)
        assert result.factors["位置加分(20)"].at[day, code] == pytest.approx(40 / 3)
        assert result.factors["趋势修复分(10)"].at[day, code] == 10
        assert score == round(.7 * original + 40 / 3 + 5 + 5, 4)


@pytest.mark.parametrize("reverse", [False, True])
def test_equal_scores_break_ties_by_stock_code_independent_of_input_order(reverse):
    codes = ["300003", "301001", "301002", "300001", "300002"]
    if reverse:
        codes.reverse()
    panels = _pool(dict.fromkeys(codes, 250.))
    result = ImpulseInsideBreakoutV1().compute(panels)
    day = panels["close"].index[-1]
    assert result.factors["score"].loc[day].nunique() == 1
    assert result.picks_on(day, rank_by="score") == ["300001", "300002"]
    expected = {code: float(rank) for rank, code in enumerate(sorted(codes), 1)}
    assert result.factors["候选排名"].loc[day].to_dict() == expected


@pytest.mark.parametrize("count", [0, 1, 2])
def test_fewer_than_two_eligible_stocks_are_never_padded(count):
    codes = ["300001", "300002", "300003"]
    panels = _pool(dict.fromkeys(codes, 250.))
    for code in codes[count:]:
        panels["volume"].iloc[-1, panels["volume"].columns.get_loc(code)] = 0.
    result = ImpulseInsideBreakoutV1().compute(panels)
    day = panels["close"].index[-1]
    assert result.picks_on(day, rank_by="score") == codes[:count]
    assert int(result.factors["条件候选"].loc[day].sum()) == count
    assert int(result.signals.loc[day].sum()) == count


def test_top_two_is_applied_on_each_day_instead_of_across_the_whole_range():
    panels, days = _two_breakout_days()
    result = ImpulseInsideBreakoutV1().compute(panels)
    assert result.picks_on(days[0], rank_by="score") == ["300003", "300002"]
    assert result.picks_on(days[1], rank_by="score") == ["300001", "300002"]
    assert result.signals.sum(axis=1).le(2).all()
    assert int(result.signals.to_numpy().sum()) == 4


@pytest.mark.parametrize("selection", ["last", "both", "sparse_reverse"])
def test_full_and_projected_scores_ranks_and_all_existing_factors_match_bit_for_bit(selection):
    panels, days = _two_breakout_days()
    dates = ([days[-1]] if selection == "last" else days if selection == "both"
             else [days[-1], panels["close"].index[20], days[0]])
    engine = ImpulseInsideBreakoutV1()
    _assert_same_result(engine.compute_projection(panels, None, dates),
                        project_result(engine.compute(panels), dates))


def test_later_breakouts_cannot_change_past_scores_ranks_or_winners():
    panels, days = _two_breakout_days()
    engine = ImpulseInsideBreakoutV1()
    truncated = truncate_panels(panels, days[0])
    expected = engine.compute(truncated)
    actual = project_result(engine.compute(panels), list(expected.signals.index))
    _assert_same_result(actual, expected)
    _assert_same_result(engine.compute_projection(panels, None, [days[0]]),
                        project_result(expected, [days[0]]))


def test_nonfinite_score_does_not_take_a_slot_from_eligible_finite_candidates():
    panels = _pool({"301001": 250., "300002": 250., "300001": 250.})
    # Today and yesterday stay positive, but malformed older volumes make the
    # prior average unable to produce a finite volume score.
    panels["volume"].loc[panels["volume"].index[-4:-1], "301001"] = [-1000., 10., 100.]
    result = ImpulseInsideBreakoutV1().compute(panels)
    day = panels["close"].index[-1]
    assert not np.isfinite(result.factors["score"].at[day, "301001"])
    assert not result.signals.at[day, "301001"]
    assert result.picks_on(day, rank_by="score") == ["300001", "300002"]
    assert result.factors["候选排名"].at[day, "300001"] == 1
    assert result.factors["候选排名"].at[day, "300002"] == 2


def test_infinite_breakout_ratio_cannot_be_selected_even_when_component_clips_to_full_marks():
    from src.formula import MA, REF
    from src.strategy.application.impulse_inside_breakout import _context_factors, _ranked_result

    panels = _pool({"301001": 250., "300002": 250., "300001": 250.})
    baseline = ImpulseInsideBreakoutV1().compute(panels)
    day = panels["close"].index[-1]
    candidates = baseline.factors["条件候选"]
    ratios = baseline.factors["突破量比"].copy()
    # A finite volume divided by a sufficiently small positive average can
    # overflow. Clipping that ratio must not disguise it as a valid full score.
    ratios.at[day, "301001"] = np.inf
    result = _ranked_result(
        candidates, {"突破量比": ratios},
        close=panels["close"], high=panels["high"], low=panels["low"],
        volume=panels["volume"], prior_volume=REF(MA(panels["volume"], 3), 1),
        context_factors=_context_factors(panels["close"], panels["high"], panels["low"]),
    )

    assert candidates.at[day, "301001"]
    assert result.factors["突破放量分(25)"].at[day, "301001"] == 25
    assert pd.isna(result.factors["score"].at[day, "301001"])
    assert pd.isna(result.factors["候选排名"].at[day, "301001"])
    assert not result.signals.at[day, "301001"]
    assert result.picks_on(day, rank_by="score") == ["300001", "300002"]


@pytest.mark.parametrize("reverse", [False, True])
def test_high_scores_from_all_input_boards_compete_for_the_same_top_two(reverse):
    volumes = {"600001": 600., "000001": 600., "688001": 600.,
               "300003": 250., "301001": 400., "300002": 350.}
    if reverse:
        volumes = dict(reversed(list(volumes.items())))
    panels = _pool(volumes)
    engine = ImpulseInsideBreakoutV1()
    result = engine.compute(panels)
    day = panels["close"].index[-1]
    assert result.picks_on(day, rank_by="score") == ["000001", "600001"]
    for code in ("600001", "000001", "688001"):
        assert result.factors["基础过滤"].at[day, code]
        assert result.factors["条件候选"].at[day, code]
        assert pd.notna(result.factors["score"].at[day, code])
    assert result.factors["候选排名"].at[day, "300003"] == 6
    _assert_same_result(engine.compute_projection(panels, None, [day]),
                        project_result(result, [day]))


def test_original_score_is_rounded_before_context70_weighting_and_final_rounding():
    # This volume makes the old unrounded sum 52.000049. Rounding only after
    # weighting would yield 59.7334; the frozen two-stage rule yields 59.7333.
    volume = (52.000049 - 35.27777777777778) * (530 / 3) / 12.5
    panels = _pool({"300001": volume})
    result = ImpulseInsideBreakoutV1().compute(panels)
    day = panels["close"].index[-1]
    original_unrounded = sum(result.factors[name].at[day, "300001"] for name in COMPONENTS)

    assert original_unrounded == pytest.approx(52.000049, abs=1e-8)
    assert result.factors["原形态分(100)"].at[day, "300001"] == 52.
    assert result.factors["score"].at[day, "300001"] == 59.7333
    assert round(.7 * original_unrounded + 40 / 3 + 5 + 5, 4) == 59.7334


def test_long_context_can_replace_original_third_rank_without_changing_shape_candidates():
    panels = _pool({"300001": 600., "300002": 400., "300003": 350.})
    # An old high lies inside the 120-session range but outside both current MAs.
    panels["high"].iloc[-80, panels["high"].columns.get_loc("300001")] = 20.
    result = ImpulseInsideBreakoutV1().compute(panels)
    day = panels["close"].index[-1]
    original_top_two = result.factors["原形态分(100)"].loc[day].nlargest(2).index.tolist()

    assert result.factors["条件候选"].loc[day].all()
    assert original_top_two == ["300001", "300002"]
    assert result.picks_on(day, rank_by="score") == ["300002", "300003"]
    assert result.factors["候选排名"].at[day, "300001"] == 3
    assert result.factors["候选排名"].at[day, "300003"] == 2
    assert int(result.signals.loc[day].sum()) == 2
    _assert_same_result(ImpulseInsideBreakoutV1().compute_projection(panels, None, [day]),
                        project_result(result, [day]))


@pytest.mark.parametrize("repairing", [False, True])
def test_low_position_needs_ma20_repair_and_does_not_claim_ma60_uptrend(repairing):
    panels = _pool({"300001": 250.})
    # The distant higher-price stretch keeps MA60 above MA20. Ending it five
    # sessions later also keeps the ten-session MA20 comparison downward, while
    # both stretches leave the original anchor's prior 20 bars untouched.
    end = -30 if repairing else -25
    for field, value in {"open": 10.9, "high": 11.1, "low": 10.8, "close": 11.}.items():
        panels[field].iloc[-80:end, 0] = value
        panels[f"__raw_{field}"].iloc[-80:end, 0] = value
    engine = ImpulseInsideBreakoutV1()
    result = engine.compute(panels)
    day = panels["close"].index[-1]

    assert result.factors["条件候选"].at[day, "300001"]
    assert result.factors["位置评分上下文有效"].at[day, "300001"]
    assert result.factors["形态前120日位置(%)"].at[day, "300001"] == pytest.approx(100 / 6)
    assert bool(result.factors["趋势修复"].at[day, "300001"]) is repairing
    assert not result.factors["中期趋势向上"].at[day, "300001"]
    assert result.factors["位置加分(20)"].at[day, "300001"] == pytest.approx(50 / 3 if repairing else 0)
    assert result.factors["趋势修复分(10)"].at[day, "300001"] == (5 if repairing else 0)
    original = result.factors["原形态分(100)"].at[day, "300001"]
    assert result.factors["score"].at[day, "300001"] == round(.7 * original + (50 / 3 + 5 if repairing else 0), 4)
    assert result.signals.at[day, "300001"]
    _assert_same_result(engine.compute_projection(panels, None, [day]), project_result(result, [day]))


@pytest.mark.parametrize("missing", ["high", "low", "close", "zero_range"])
def test_missing_long_context_falls_back_to_original_score_without_new_filter(missing):
    panels = _pool({"300001": 250.})
    if missing == "zero_range":
        panels["high"].iloc[:-5, 0] = 10.1
        panels["low"].iloc[:-5, 0] = 10.1
    else:
        # A close gap invalidates the lagged MA60; high/low gaps invalidate the
        # first of the 120 bars. None belongs to the five-bar shape itself.
        position = -40 if missing == "close" else -125
        panels[missing].iloc[position, 0] = np.nan
    engine = ImpulseInsideBreakoutV1()
    result = engine.compute(panels)
    day = panels["close"].index[-1]

    assert result.factors["条件候选"].at[day, "300001"]
    assert not result.factors["位置评分上下文有效"].at[day, "300001"]
    assert result.factors["score"].at[day, "300001"] == result.factors["原形态分(100)"].at[day, "300001"]
    assert result.factors["形态贡献分"].at[day, "300001"] == result.factors["原形态分(100)"].at[day, "300001"]
    assert result.factors["位置加分(20)"].at[day, "300001"] == 0
    assert result.factors["趋势修复分(10)"].at[day, "300001"] == 0
    assert result.signals.at[day, "300001"]
    _assert_same_result(engine.compute_projection(panels, None, [day]), project_result(result, [day]))


def test_production_long_position_excludes_every_bar_of_the_five_bar_pattern():
    from src.strategy.application.impulse_inside_breakout import _context_factors

    panels = _pool({"300001": 250.})
    day = panels["close"].index[-1]
    before = _context_factors(panels["close"], panels["high"], panels["low"])
    # The location must still describe the old range after arbitrary current
    # pattern prices; repair and uptrend intentionally remain current-day facts.
    for name, value in {"close": 10000., "high": 20000., "low": .01}.items():
        panels[name].iloc[-5:, 0] = value
    after = _context_factors(panels["close"], panels["high"], panels["low"])

    assert before["形态前120日位置(%)"].at[day, "300001"] == pytest.approx(200 / 3)
    assert after["形态前120日位置(%)"].at[day, "300001"] == before["形态前120日位置(%)"].at[day, "300001"]
    assert after["位置舒适度"].at[day, "300001"] == before["位置舒适度"].at[day, "300001"]
    panels["close"].iloc[-6, 0] = 10.
    changed_cutoff = _context_factors(panels["close"], panels["high"], panels["low"])
    assert changed_cutoff["形态前120日位置(%)"].at[day, "300001"] == pytest.approx(100 / 3)


@pytest.mark.parametrize("history", ["regular", "old_peak", "missing_context", "adjusted"])
def test_production_context70_scores_features_and_top_two_match_frozen_research(history):
    panels, days = _two_breakout_days()
    if history == "old_peak":
        panels["high"].iloc[80, 0] = 20.
    elif history == "missing_context":
        panels["high"].iloc[80, 0] = np.nan
    elif history == "adjusted":
        for name in ("open", "high", "low", "close"):
            panels[name] *= .5
    engine = ImpulseInsideBreakoutV1()
    result = engine.compute(panels)
    expected_scores, expected_features = context_scores(panels, result.factors["原形态分(100)"])
    expected_selection, _, expected_rank = rank_filtered(
        result.factors["条件候选"], expected_scores["context70"], result.factors["条件候选"],
    )

    pd.testing.assert_frame_equal(result.factors["score"], expected_scores["context70"], check_exact=True)
    pd.testing.assert_frame_equal(result.signals, expected_selection, check_exact=True)
    pd.testing.assert_frame_equal(result.factors["候选排名"], expected_rank, check_exact=True)
    for actual_name, expected in {
        "形态前120日位置(%)": expected_features["position120_before_pattern"] * 100,
        "位置舒适度": expected_features["comfort"],
        "位置评分上下文有效": expected_features["context_valid"],
        "趋势修复": expected_features["repair"],
        "中期趋势向上": expected_features["uptrend"],
    }.items():
        pd.testing.assert_frame_equal(result.factors[actual_name], expected, check_exact=True, obj=actual_name)
    _assert_same_result(engine.compute_projection(panels, None, days), project_result(result, days))
