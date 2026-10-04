"""Causal boundaries of the isolated scoring transfer experiment."""
import numpy as np
import pandas as pd

from tools.research_multi_strategy_scoring import SPECS, context_scores, rank_candidates


def panels():
    index = pd.bdate_range("2024-01-01", periods=180).strftime("%Y-%m-%d")
    close = pd.DataFrame({"600002": np.linspace(8, 12, 180), "600001": np.linspace(9, 11, 180)}, index=index)
    return {"close": close, "high": close + .4, "low": close - .3}


def test_open_proxy_scores_ignore_current_hlc():
    p = panels()
    old = pd.DataFrame(60., index=p["close"].index, columns=p["close"].columns)
    spec = SPECS["double-volume-yin-low-open-v1"]
    expected, _ = context_scores(p, old, spec)
    changed = {k: v.copy() for k, v in p.items()}
    for v in changed.values():
        v.iloc[-1] = np.nan
    actual, _ = context_scores(changed, old, spec)
    for key in expected:
        pd.testing.assert_frame_equal(actual[key], expected[key])


def test_position_ends_before_earliest_pattern_and_missing_keeps_original():
    p = panels()
    old = pd.DataFrame(61., index=p["close"].index, columns=p["close"].columns)
    for spec in SPECS.values():
        scores, features = context_scores(p, old, spec)
        lag = spec["position_lag"]
        row = len(old)-1-lag
        lo = p["low"].iloc[row-119:row+1].min()
        hi = p["high"].iloc[row-119:row+1].max()
        expected = (p["close"].iloc[row]-lo)/(hi-lo)
        np.testing.assert_allclose(features["position120"].iloc[-1], expected)
        for score in scores.values():
            pd.testing.assert_frame_equal(score.iloc[:100], old.iloc[:100])


def test_future_prices_cannot_change_any_past_score():
    p = panels()
    old = pd.DataFrame(50., index=p["close"].index, columns=p["close"].columns)
    for spec in SPECS.values():
        full, _ = context_scores(p, old, spec)
        prefix, _ = context_scores({k: v.iloc[:160] for k,v in p.items()}, old.iloc[:160], spec)
        for key in full:
            pd.testing.assert_frame_equal(full[key].iloc[:160], prefix[key])


def test_quantization_ties_preserve_native_order_and_candidate_count():
    candidates = pd.DataFrame([[True, True, False], [False, True, False]], columns=["600002", "600001", "600003"])
    score = pd.DataFrame([[99.,99.,100.], [99.,99.,100.]],columns=candidates.columns)
    native = pd.DataFrame([[4.91,4.90,4.99], [4.91,4.90,4.99]],columns=candidates.columns)
    selected = rank_candidates(candidates,score,native,1)
    assert selected.iloc[0].to_dict() == {"600002":True,"600001":False,"600003":False}
    assert selected.iloc[1].to_dict() == {"600002":False,"600001":True,"600003":False}
