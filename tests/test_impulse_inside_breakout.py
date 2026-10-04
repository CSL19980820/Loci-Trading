"""Concrete five-candle examples for the built-in impulse/inside breakout indicator."""
from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from src.strategy.application.impulse_inside_breakout import ImpulseInsideBreakoutV1
from src.strategy.domain.base import StrategyError


PRICE_FIELDS = ("open", "high", "low", "close")


def example(*, bars: int = 180, code: str = "300001", name: str = "普通样本") -> dict:
    """One large candle, three strictly inside candles, then a valid breakout."""
    days = pd.bdate_range("2025-01-02", periods=bars).strftime("%Y-%m-%d")
    panels = {
        field: pd.DataFrame(value, index=days, columns=[code], dtype=float)
        for field, value in {"open": 10.0, "high": 10.2, "low": 9.9,
                             "close": 10.1, "volume": 100.0}.items()
    }
    candles = [
        (10.0, 10.85, 9.95, 10.8, 300.0),
        (10.6, 10.75, 10.45, 10.65, 80.0),
        (10.65, 10.75, 10.45, 10.55, 350.0),
        (10.55, 10.75, 10.45, 10.6, 100.0),
        (10.6, 10.95, 10.55, 10.9, 250.0),
    ]
    for position, candle in zip(range(bars - 5, bars), candles, strict=True):
        for field, value in zip((*PRICE_FIELDS, "volume"), candle, strict=True):
            panels[field].iloc[position, 0] = value
    for field in PRICE_FIELDS:
        panels[f"__raw_{field}"] = panels[field].copy()
    panels["__instrument_names__"] = {code: name}
    return panels


def set_price(panels: dict, field: str, position: int, value: float) -> None:
    panels[field].iloc[position, 0] = value
    panels[f"__raw_{field}"].iloc[position, 0] = value


def selected(panels: dict) -> bool:
    return bool(ImpulseInsideBreakoutV1().compute(panels).signals.iloc[-1, 0])


def test_valid_shape_keeps_all_candidates_and_exposes_concrete_explanation():
    first = example()
    growth = example(code="301001")
    panels = {
        key: pd.concat([value, growth[key]], axis=1)
        for key, value in first.items() if isinstance(value, pd.DataFrame)
    }
    panels["__instrument_names__"] = {
        **first["__instrument_names__"], **growth["__instrument_names__"],
    }
    result = ImpulseInsideBreakoutV1().compute(panels)
    assert result.signals.iloc[-1].to_dict() == {"300001": True, "301001": True}
    assert result.factors["大阳线高点"].iloc[-1, 0] == pytest.approx(10.85)
    assert result.factors["突破量比"].iloc[-1, 0] == pytest.approx(250 / (530 / 3))
    assert result.factors["有效日K根数"].iloc[-1, 0] == 180


@pytest.mark.parametrize("bars, expected", [(179, False), (180, True)])
def test_history_gate_counts_180_observed_bars(bars, expected):
    assert selected(example(bars=bars)) is expected


@pytest.mark.parametrize("invalid", [np.nan, np.inf, 0.0])
def test_missing_or_invalid_old_close_does_not_count_towards_180_bars(invalid):
    panels = example()
    set_price(panels, "close", 10, invalid)
    result = ImpulseInsideBreakoutV1().compute(panels)
    assert result.factors["有效日K根数"].iloc[-1, 0] == 179
    assert not result.signals.iloc[-1, 0]


@pytest.mark.parametrize("code, expected, upper", [
    ("600001", True, 11.66), ("000001", True, 11.66),
    ("300001", True, 12.72), ("301001", True, 12.72),
    ("688001", True, 12.72), ("689001", True, 12.72),
    ("830001", True, 13.78), ("920001", True, 13.78),
])
def test_all_input_boards_are_evaluated_with_their_actual_limit_ratio(code, expected, upper):
    panels = example(code=code)
    result = ImpulseInsideBreakoutV1().compute(panels)
    assert bool(result.signals.iloc[-1, 0]) is expected
    if upper is not None:
        assert result.factors["涨停价"].iloc[-1, 0] == pytest.approx(upper)
    assert_projection_matches_reference(panels, [panels["close"].index[-1]])


@pytest.mark.parametrize("name", ["ST样本", "*ST样本", "st样本", "样本退", "退市样本", "", "  "])
def test_names_do_not_restrict_the_input_pool(name):
    assert selected(example(name=name))


@pytest.mark.parametrize("code,name,upper", [
    ("600001", "ST样本", 11.13), ("000001", "*ST样本", 11.13),
    ("300001", "ST样本", 12.72), ("688001", "ST样本", 12.72),
    ("830001", "ST样本", 13.78),
])
def test_st_names_choose_the_real_limit_ratio_without_excluding_the_stock(code, name, upper):
    panels = example(code=code, name=name)
    result = ImpulseInsideBreakoutV1().compute(panels)
    assert result.signals.iloc[-1, 0]
    assert result.factors["涨停价"].iloc[-1, 0] == pytest.approx(upper)
    assert_projection_matches_reference(panels, [panels["close"].index[-1]])


@pytest.mark.parametrize("scale", [0.1, 0.5, 1.0, 10.0])
def test_absolute_price_does_not_change_the_shape_or_score(scale):
    panels = example()
    expected = ImpulseInsideBreakoutV1().compute(panels)
    for field in PRICE_FIELDS:
        panels[field] *= scale
        panels[f"__raw_{field}"] *= scale
    actual = ImpulseInsideBreakoutV1().compute(panels)
    assert actual.signals.iloc[-1, 0]
    assert actual.factors["score"].iloc[-1, 0] == pytest.approx(expected.factors["score"].iloc[-1, 0])
    assert_projection_matches_reference(panels, [panels["close"].index[-1]])


def test_same_shape_on_main_and_star_boards_keeps_equal_scores_and_top_two():
    samples = [example(code="600001"), example(code="688001")]
    panels = {key: pd.concat([sample[key] for sample in samples], axis=1)
              for key, value in samples[0].items() if isinstance(value, pd.DataFrame)}
    panels["__instrument_names__"] = {code: "普通样本" for code in panels["close"].columns}
    result = ImpulseInsideBreakoutV1().compute(panels)
    assert result.picks_on(panels["close"].index[-1]) == ["600001", "688001"]
    assert result.factors["score"].iloc[-1, 0] == result.factors["score"].iloc[-1, 1]
    assert result.factors["涨停价"].iloc[-1].tolist() == pytest.approx([11.66, 12.72])


@pytest.mark.parametrize("gap, expected", [(0.0, False), (0.01, False), (0.02, True)])
def test_close_must_be_two_cents_below_limit_even_if_intraday_high_touches_it(gap, expected):
    panels = example()
    set_price(panels, "close", -1, 12.72 - gap)
    set_price(panels, "high", -1, 12.72)
    result = ImpulseInsideBreakoutV1().compute(panels)
    assert bool(result.signals.iloc[-1, 0]) is expected
    assert bool(result.factors["距涨停至少2分钱"].iloc[-1, 0]) is expected


def test_limit_prices_round_half_up_to_cents():
    # The main-board limit uses half-up rounding on the real unadjusted price.
    panels = example(code="600001")
    set_price(panels, "open", -2, 10.10)
    set_price(panels, "close", -2, 10.05)
    set_price(panels, "low", -2, 10.0)
    result = ImpulseInsideBreakoutV1().compute(panels)
    assert result.signals.iloc[-1, 0]
    assert result.factors["涨停价"].iloc[-1, 0] == pytest.approx(11.06)
    assert result.factors["跌停价"].iloc[-1, 0] == pytest.approx(9.05)


@pytest.mark.parametrize("boundary", ["equal_previous_body_average", "equal_price_average", "anchor_doji"])
def test_anchor_requires_a_positive_body_above_prior_average_and_close_above_ma20(boundary):
    panels = example()
    if boundary == "anchor_doji":
        set_price(panels, "open", -5, 10.8)
    else:
        if boundary == "equal_previous_body_average":
            # The anchor still closes above MA20; its 0.8 body only equals the prior mean.
            prices = {"open": 9.6, "close": 10.4, "high": 10.45, "low": 9.55}
        else:
            # The anchor's 0.8 body exceeds the prior 0.1 bodies, but C equals MA20.
            prices = {"open": 10.7, "close": 10.8, "high": 10.9, "low": 10.65}
        for field, value in prices.items():
            panels[field].iloc[-25:-5, 0] = value
            panels[f"__raw_{field}"].iloc[-25:-5, 0] = value
    result = ImpulseInsideBreakoutV1().compute(panels)
    assert not result.factors["大阳线成立"].iloc[-1, 0]
    assert not result.signals.iloc[-1, 0]


@pytest.mark.parametrize("boundary", ["equal_high", "equal_low", "equal_body"])
def test_inside_candles_require_strict_high_low_and_body_contraction(boundary):
    panels = example()
    if boundary == "equal_high":
        set_price(panels, "high", -3, 10.85)
    elif boundary == "equal_low":
        set_price(panels, "low", -3, 9.95)
    else:
        for field, value in {"open": 10.0, "close": 10.8, "low": 9.98, "high": 10.82}.items():
            set_price(panels, field, -3, value)
    assert not selected(panels)


def test_contraction_uses_three_day_average_without_requiring_daily_volume_decline():
    panels = example()
    # 80 -> 350 -> 100 is not monotonic; one inside bar even exceeds the anchor's 300.
    assert panels["volume"].iloc[-3, 0] > panels["volume"].iloc[-5, 0]
    assert selected(panels)


@pytest.mark.parametrize("boundary", ["equal_average", "equal_breakout_volume", "equal_breakout_high", "doji"])
def test_volume_contraction_and_breakout_conditions_are_strict(boundary):
    panels = example()
    if boundary == "equal_average":
        panels["volume"].iloc[-4:-1, 0] = 300.0
    elif boundary == "equal_breakout_volume":
        panels["volume"].iloc[-4:, 0] = 100.0
    elif boundary == "equal_breakout_high":
        set_price(panels, "close", -1, 10.85)
    else:
        set_price(panels, "open", -1, 10.9)
    assert not selected(panels)


@pytest.mark.parametrize("position", [-1, -2])
def test_today_and_previous_volume_must_be_positive(position):
    panels = example()
    panels["volume"].iloc[position, 0] = 0
    assert not selected(panels)


@pytest.mark.parametrize("scale, raw_close, expected", [(0.5, 12.70, True), (2.0, 12.71, False)])
def test_adjusted_shape_and_raw_two_cent_limit_gate_use_separate_price_panels(scale, raw_close, expected):
    panels = example()
    set_price(panels, "close", -1, raw_close)
    set_price(panels, "high", -1, 12.72)
    for field in PRICE_FIELDS:
        panels[field] *= scale
    result = ImpulseInsideBreakoutV1().compute(panels)
    assert bool(result.signals.iloc[-1, 0]) is expected
    assert result.factors["未复权收盘价"].iloc[-1, 0] == pytest.approx(raw_close)
    assert result.factors["涨停价"].iloc[-1, 0] == pytest.approx(12.72)
    assert result.factors["大阳线高点"].iloc[-1, 0] == pytest.approx(10.85 * scale)


@pytest.mark.parametrize("field, value, expected", [
    ("high", 12.7205, True), ("high", 12.7211, False),
    ("low", 8.4795, True), ("low", 8.4789, False),
])
def test_raw_day_range_must_remain_within_limit_price_tolerance(field, value, expected):
    panels = example()
    set_price(panels, field, -1, value)
    assert selected(panels) is expected


@pytest.mark.parametrize("field", PRICE_FIELDS)
def test_missing_raw_price_metadata_fails_explicitly(field):
    panels = example()
    panels.pop(f"__raw_{field}")
    with pytest.raises(StrategyError, match="未复权 OHLC"):
        ImpulseInsideBreakoutV1().compute(panels)
    with pytest.raises(StrategyError, match="未复权 OHLC"):
        ImpulseInsideBreakoutV1().compute_projection(panels, None, [panels["close"].index[-1]])


def test_missing_name_metadata_fails_explicitly():
    panels = example()
    panels.pop("__instrument_names__")
    with pytest.raises(StrategyError, match="证券名称"):
        ImpulseInsideBreakoutV1().compute(panels)
    with pytest.raises(StrategyError, match="证券名称"):
        ImpulseInsideBreakoutV1().compute_projection(panels, None, [panels["close"].index[-1]])


@pytest.mark.parametrize("field", PRICE_FIELDS)
def test_missing_recent_raw_price_never_produces_a_signal(field):
    panels = example()
    panels[f"__raw_{field}"].iloc[-2, 0] = np.nan
    assert not selected(panels)


def test_future_bars_do_not_change_any_past_signal_or_factor():
    panels = example()
    before = ImpulseInsideBreakoutV1().compute(panels)
    future_dates = pd.bdate_range(pd.Timestamp(panels["close"].index[-1]) + pd.Timedelta(days=1), periods=20)
    extended = {}
    for key, value in panels.items():
        if isinstance(value, pd.DataFrame):
            suffix = pd.DataFrame(1000.0, index=future_dates.strftime("%Y-%m-%d"), columns=value.columns)
            extended[key] = pd.concat([value, suffix])
        else:
            extended[key] = value.copy()
    after = ImpulseInsideBreakoutV1().compute(extended)
    pd.testing.assert_frame_equal(before.signals, after.signals.loc[before.signals.index])
    for key, factor in before.factors.items():
        pd.testing.assert_frame_equal(factor, after.factors[key].loc[factor.index])


def assert_projection_matches_reference(panels: dict, dates: list[str]) -> None:
    from src.strategy.application.compute_runtime import project_result

    engine = ImpulseInsideBreakoutV1()
    expected = project_result(engine.compute(panels), dates)
    actual = engine.compute_projection(panels, None, dates)
    pd.testing.assert_frame_equal(actual.signals, expected.signals, check_exact=True)
    assert actual.watch_signals is expected.watch_signals is None
    assert actual.factors.keys() == expected.factors.keys()
    for name, frame in expected.factors.items():
        pd.testing.assert_frame_equal(actual.factors[name], frame, check_exact=True)


@pytest.mark.parametrize("boundary", [
    "valid", "one_cent", "two_cents", "equal_body_mean", "equal_close_mean",
    "equal_inside_high", "old_missing_close", "recent_missing_raw", "qfq_half", "hfq_double",
])
def test_projection_matches_every_reference_factor_at_formula_boundaries(boundary):
    panels = example()
    if boundary in {"one_cent", "two_cents"}:
        set_price(panels, "close", -1, 12.71 if boundary == "one_cent" else 12.70)
        set_price(panels, "high", -1, 12.72)
    elif boundary in {"equal_body_mean", "equal_close_mean"}:
        prior = ({"open": 9.6, "close": 10.4, "high": 10.45, "low": 9.55}
                 if boundary == "equal_body_mean"
                 else {"open": 10.7, "close": 10.8, "high": 10.9, "low": 10.65})
        for field, value in prior.items():
            panels[field].iloc[-25:-5, 0] = value
            panels[f"__raw_{field}"].iloc[-25:-5, 0] = value
    elif boundary == "equal_inside_high":
        set_price(panels, "high", -3, 10.85)
    elif boundary == "old_missing_close":
        set_price(panels, "close", 10, np.nan)
    elif boundary == "recent_missing_raw":
        panels["__raw_close"].iloc[-2, 0] = np.nan
    elif boundary in {"qfq_half", "hfq_double"}:
        scale = 0.5 if boundary == "qfq_half" else 2.0
        for field in PRICE_FIELDS:
            panels[field] *= scale
    assert_projection_matches_reference(panels, list(panels["close"].index[-3:]))


@pytest.mark.parametrize("selection", ["first_rows", "sparse_out_of_order", "empty"])
def test_projection_preserves_early_sparse_and_empty_date_selection(selection):
    panels = example()
    index = panels["close"].index
    dates = ([index[0], index[1], index[4], index[20], index[24]] if selection == "first_rows"
             else [index[-1], index[50], index[-3]] if selection == "sparse_out_of_order" else [])
    assert_projection_matches_reference(panels, dates)


def test_projection_preserves_full_origin_rolling_values_with_missing_bars_and_adjustment_change():
    rng = np.random.default_rng(2018)
    days = pd.bdate_range("2025-01-02", periods=260).strftime("%Y-%m-%d")
    codes = [f"300{code:03d}" for code in range(12)]
    raw_close = 12 + np.cumsum(rng.normal(0, 0.05, (len(days), len(codes))), axis=0)
    raw_open = raw_close + rng.normal(0, 0.08, raw_close.shape)
    raw = {
        "close": raw_close, "open": raw_open,
        "high": np.maximum(raw_open, raw_close) + rng.uniform(0.01, 0.15, raw_close.shape),
        "low": np.minimum(raw_open, raw_close) - rng.uniform(0.01, 0.15, raw_close.shape),
    }
    panels = {}
    factor = np.ones(raw_close.shape)
    factor[:140] = 0.75
    for field, values in raw.items():
        panels[f"__raw_{field}"] = pd.DataFrame(values, index=days, columns=codes)
        panels[field] = pd.DataFrame(values * factor, index=days, columns=codes)
    panels["volume"] = pd.DataFrame(rng.integers(10, 500, raw_close.shape).astype(float), index=days, columns=codes)
    panels["__instrument_names__"] = {code: "普通样本" for code in codes}
    panels["__instrument_names__"][codes[2]] = "ST样本"
    panels["close"].iloc[40, 3] = np.nan
    panels["close"].iloc[-4, 5] = np.nan
    panels["__raw_low"].iloc[-2, 7] = np.nan
    panels["volume"].iloc[-3, 8] = 0
    # The late dates need the original rolling sum state; the sparse row spans the adjustment change.
    assert_projection_matches_reference(panels, [days[-3], days[-2], days[-1]])
    assert_projection_matches_reference(panels, [days[142], days[190], days[-1]])


@pytest.mark.parametrize("offset", [-3, -2])
def test_projection_matches_real_truncated_reference_input(offset):
    from src.strategy.application.compute_runtime import truncate_panels

    panels = example(bars=200)
    cutoff = panels["close"].index[offset]
    truncated = truncate_panels(panels, cutoff)
    assert_projection_matches_reference(truncated, [cutoff])


def test_projection_remains_under_real_truncation_audit():
    from src.strategy.application.audit import audit_truncation

    report = audit_truncation(ImpulseInsideBreakoutV1(), example(bars=200))
    assert not report.failed, report.to_dict()
    assert not any(finding.severity == "warn" for finding in report.findings)


def test_future_bars_leave_every_projected_signal_and_factor_unchanged():
    panels = example(bars=200)
    engine = ImpulseInsideBreakoutV1()
    dates = list(panels["close"].index[-3:])
    expected = engine.compute_projection(panels, None, dates)
    future_dates = pd.bdate_range(pd.Timestamp(dates[-1]) + pd.Timedelta(days=1), periods=20).strftime("%Y-%m-%d")
    extended = {
        name: pd.concat([value, pd.DataFrame(1000.0, index=future_dates, columns=value.columns)])
        if isinstance(value, pd.DataFrame) else value.copy()
        for name, value in panels.items()
    }
    actual = engine.compute_projection(extended, None, dates)
    pd.testing.assert_frame_equal(actual.signals, expected.signals, check_exact=True)
    for name, frame in expected.factors.items():
        pd.testing.assert_frame_equal(actual.factors[name], frame, check_exact=True)
