"""Research scores use past context and only reorder the original candidates."""
from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from tools.research_impulse_scoring import context_scores, rank_filtered

VARIANTS = {"baseline", "low80", "context70", "trend80", "context80"}


def _history(close_values: dict[str, float], *, days: int = 200) -> dict[str, pd.DataFrame]:
    index = pd.Index(pd.bdate_range("2024-01-02", periods=days).strftime("%Y-%m-%d"))
    close = pd.DataFrame(close_values, index=index, dtype=float)
    return {"close": close, "high": close * 0 + 30, "low": close * 0 + 10}


def _old_scores(panels: dict[str, pd.DataFrame], values: dict[str, float]) -> pd.DataFrame:
    return pd.DataFrame(values, index=panels["close"].index, dtype=float)


def test_position_uses_exactly_120_sessions_ending_at_t_minus_five():
    panels = _history({"300001": 20.})
    old = _old_scores(panels, {"300001": 80.})
    day = old.index[-1]
    cutoff = len(old) - 6
    panels["close"].iloc[cutoff, 0] = 16.
    # The bar immediately before the 120-session window is deliberately extreme.
    panels["high"].iloc[cutoff - 120, 0] = 1000.
    panels["low"].iloc[cutoff - 120, 0] = .01
    _, original = context_scores(panels, old)
    assert original["position120_before_pattern"].at[day, "300001"] == pytest.approx(.3)

    changed = {name: frame.copy() for name, frame in panels.items()}
    # T-4..T-1 and the signal bar belong to the five-bar pattern, not its prior context.
    for name, value in {"close": 10000., "high": 20000., "low": .01}.items():
        changed[name].iloc[-5:, 0] = value
    _, after_pattern_changes = context_scores(changed, old)
    assert after_pattern_changes["position120_before_pattern"].at[day, "300001"] == pytest.approx(.3)
    assert after_pattern_changes["comfort"].at[day, "300001"] == pytest.approx(1.)

    changed["close"].iloc[cutoff, 0] = 18.
    _, after_cutoff_change = context_scores(changed, old)
    assert after_cutoff_change["position120_before_pattern"].at[day, "300001"] == pytest.approx(.4)


def test_missing_bar_inside_120_session_context_falls_back_without_removing_candidate():
    panels = _history({"300001": 20.})
    old = _old_scores(panels, {"300001": 79.1234})
    day = old.index[-1]
    first_context_bar = len(old) - 6 - 119
    panels["high"].iloc[first_context_bar, 0] = np.nan
    scores, features = context_scores(panels, old)
    candidates = old * 0 == 1
    candidates.at[day, "300001"] = True

    assert not features["context_valid"].at[day, "300001"]
    assert pd.isna(features["position120_before_pattern"].at[day, "300001"])
    assert set(scores) == VARIANTS
    for variant, score in scores.items():
        assert score.at[day, "300001"] == old.at[day, "300001"], variant
        selected, _, _ = rank_filtered(candidates, score, candidates)
        assert selected.at[day, "300001"], variant


def test_all_scores_features_and_top_two_are_unchanged_by_future_bars():
    panels = _history({"300003": 12., "300001": 28., "300002": 22.}, days=240)
    for column, slope in {"300003": .01, "300001": -.01, "300002": .005}.items():
        panels["close"][column] += np.arange(240) * slope
    old = _old_scores(panels, {"300003": 70., "300001": 80., "300002": 75.})
    cutoff = old.index[199]
    prefix = {name: frame.loc[:cutoff].copy() for name, frame in panels.items()}
    # Extreme future observations would expose whole-sample ranges or normalization.
    for name, value in {"close": 10000., "high": 20000., "low": .01}.items():
        panels[name].iloc[200:] = value
    full_scores, full_features = context_scores(panels, old)
    prefix_scores, prefix_features = context_scores(prefix, old.loc[:cutoff])

    assert set(full_scores) == VARIANTS
    for name, frame in prefix_features.items():
        pd.testing.assert_frame_equal(frame, full_features[name].loc[:cutoff], check_exact=True, obj=name)
    for variant, frame in prefix_scores.items():
        pd.testing.assert_frame_equal(frame, full_scores[variant].loc[:cutoff], check_exact=True, obj=variant)
        prefix_candidates = frame.notna()
        prefix_selected, _, _ = rank_filtered(prefix_candidates, frame, prefix_candidates)
        full_candidates = full_scores[variant].notna()
        full_selected, _, _ = rank_filtered(full_candidates, full_scores[variant], full_candidates)
        pd.testing.assert_frame_equal(prefix_selected, full_selected.loc[:cutoff], check_exact=True)


def test_top_two_reorders_the_complete_candidate_pool_and_keeps_non_candidates_out():
    panels = _history({"300003": 12., "300001": 28., "300002": 22., "301001": 14.})
    old = _old_scores(panels, {"300003": 70., "300001": 80., "300002": 75., "301001": 100.})
    scores, _ = context_scores(panels, old)
    candidates = pd.DataFrame(True, index=old.index, columns=old.columns)
    candidates["301001"] = False
    day = old.index[-1]
    baseline, _, _ = rank_filtered(candidates, scores["baseline"], candidates)
    low_selected, _, low_ranks = rank_filtered(candidates, scores["low80"], candidates)

    assert set(baseline.columns[baseline.loc[day]]) == {"300001", "300002"}
    assert set(low_selected.columns[low_selected.loc[day]]) == {"300003", "300002"}
    assert low_ranks.at[day, "300003"] == 1
    assert pd.isna(low_ranks.at[day, "301001"])
    for variant, score in scores.items():
        selected, _, _ = rank_filtered(candidates, score, candidates)
        assert selected.sum(axis=1).eq(2).all(), variant
        assert not selected["301001"].any(), variant


@pytest.mark.parametrize("count", [0, 1, 2])
def test_zero_to_two_original_candidates_keep_the_same_selection_for_every_variant(count):
    panels = _history({"300003": 12., "300001": 28., "300002": 22.})
    old = _old_scores(panels, {"300003": 70., "300001": 80., "300002": 75.})
    candidates = pd.DataFrame(False, index=old.index, columns=old.columns)
    candidates.loc[old.index[-1], ["300001", "300002"][:count]] = True
    scores, _ = context_scores(panels, old.where(candidates))

    assert set(scores) == VARIANTS
    for variant, score in scores.items():
        selected, _, _ = rank_filtered(candidates, score, candidates)
        pd.testing.assert_frame_equal(selected, candidates, check_exact=True, obj=variant)
