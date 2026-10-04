"""固定通达信口径、真实 9/29 样本、输入异常与因果边界。"""
from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from src.formula import compile_screen_formula, evaluate_screen_formula
from src.strategy.application.contraction_rebreakout import ContractionRebreakoutV1
from src.strategy.domain.base import StrategyError


FIELDS = ("open", "high", "low", "close", "volume")
FORMULA = """
QZ:=REF(COUNT(CLOSE/REF(CLOSE,1)>=1.05 AND CLOSE>OPEN,10),3)>0;
HC:=REF(CLOSE,1)<REF(CLOSE,2) AND REF(CLOSE,2)<REF(CLOSE,3);
SL:=REF(VOL,1)<REF(MA(VOL,5),1) AND REF(VOL,2)<REF(MA(VOL,5),2);
TP:=CLOSE>REF(HHV(HIGH,5),1);
FL:=VOL>=REF(VOL,1)*1.5;
QD:=CLOSE>OPEN AND CLOSE/REF(CLOSE,1)>=1.03;
XG:BARSCOUNT(CLOSE)>30 AND QZ AND HC AND SL AND TP AND FL AND QD;
"""


def mango_example(*, bars: int | None = None, code: str = "300413", name: str = "芒果超媒") -> dict:
    fixture = json.loads((Path(__file__).parent / "fixtures" /
                          "contraction_rebreakout_300413_20260929.json").read_text(encoding="utf-8"))
    rows = fixture["rows"] if bars is None else fixture["rows"][-bars:]
    days = pd.to_datetime([row["date"] for row in rows]).strftime("%Y-%m-%d")
    panels = {
        field: pd.DataFrame([row[field] for row in rows], index=days, columns=[code], dtype=float)
        for field in FIELDS
    }
    panels["__instrument_names__"] = {code: name}
    panels["__raw_close"] = panels["close"].copy()
    return panels


def threshold_example(*, bars: int = 31) -> dict:
    """31 根合法日 K，强阳 5%、当日涨幅 3% 和放量 1.5 倍恰好达标。"""
    days = pd.bdate_range("2026-08-03", periods=bars).strftime("%Y-%m-%d")
    panels = {
        field: pd.DataFrame(value, index=days, columns=["300001"], dtype=float)
        for field, value in zip(FIELDS, [9.95, 10.1, 9.9, 10., 100.], strict=True)
    }
    for offset, candle in {
        -9: [10.2, 10.5, 10.1, 10.5, 100.],
        -4: [10.1, 10.15, 10., 10.1, 100.],
        -3: [10.07, 10.1, 10., 10.05, 80.],
        -2: [10.02, 10.05, 9.99, 10., 60.],
        -1: [10., 10.4, 9.98, 10.3, 90.],
    }.items():
        for field, value in zip(FIELDS, candle, strict=True):
            panels[field].iloc[offset, 0] = value
    panels["__instrument_names__"] = {"300001": "创业样本"}
    panels["__raw_close"] = panels["close"].copy()
    return panels


def selected(panels: dict) -> bool:
    return bool(ContractionRebreakoutV1().compute(panels).signals.iloc[-1, 0])


def test_known_mango_20260929_matches_all_formula_conditions_and_explains_values():
    result = ContractionRebreakoutV1().compute(mango_example())
    assert result.picks_on("2026-09-29", rank_by="score") == ["300413"]
    for name in ("基础过滤", "前期强阳", "两日回调", "回调缩量",
                 "收盘突破前五日高点", "当日放量", "阳线涨幅确认"):
        assert result.factors[name].at["2026-09-29", "300413"], name
    assert result.factors["有效日K根数"].at["2026-09-29", "300413"] == 35
    assert result.factors["前五日最高价"].at["2026-09-29", "300413"] == 19.68
    assert result.factors["前期强阳次数"].at["2026-09-29", "300413"] == 2
    assert result.factors["突破量比"].at["2026-09-29", "300413"] == pytest.approx(1.791529816)
    assert result.factors["当日涨幅(%)"].at["2026-09-29", "300413"] == pytest.approx(5.54371002)


def test_candidates_match_original_compiled_tdx_formula_on_valid_growth_board_data():
    compiled = compile_screen_formula(FORMULA, {
        "schema_version": 1, "entry_timing": "next_open", "min_bars": 31,
        "params": {}, "factors": [], "output": {"signal": "XG"},
    })
    for panels in (mango_example(), threshold_example(), threshold_example(bars=30)):
        expected = evaluate_screen_formula(compiled, panels).signals
        actual = ContractionRebreakoutV1().compute(panels).factors["条件候选"]
        pd.testing.assert_frame_equal(actual, expected, check_exact=True)


@pytest.mark.parametrize("bars, expected", [(30, False), (31, True), (35, True)])
def test_history_gate_uses_more_than_30_observed_closes(bars, expected):
    panels = mango_example(bars=bars)
    assert selected(panels) is expected
    assert ContractionRebreakoutV1().min_bars() == 31


@pytest.mark.parametrize("invalid", [np.nan, np.inf, 0.])
def test_invalid_old_close_cannot_count_as_the_31st_bar(invalid):
    panels = mango_example(bars=31)
    panels["close"].iloc[0, 0] = invalid
    result = ContractionRebreakoutV1().compute(panels)
    assert result.factors["有效日K根数"].iloc[-1, 0] == 30
    assert not result.signals.iloc[-1, 0]


def test_mixed_listing_origins_keep_count_dtypes_missing_values_and_candidate_threshold():
    sample = mango_example()
    codes = ["300001", "300002", "300003"]
    panels = {
        name: pd.concat([frame.rename(columns={"300413": code}) for code in codes], axis=1)
        for name, frame in sample.items() if isinstance(frame, pd.DataFrame)
    }
    panels["__instrument_names__"] = dict.fromkeys(codes, "历史长度边界样本")
    panels["close"].iloc[:4, 1] = np.nan
    panels["close"].iloc[:5, 2] = np.nan
    before = panels["close"].copy(deep=True)
    result = ContractionRebreakoutV1().compute(panels)
    counts = result.factors["有效日K根数"]
    assert counts.iloc[-1].to_dict() == {"300001": 35, "300002": 31., "300003": 30.}
    assert counts.dtypes.to_dict() == {"300001": np.dtype("int64"),
                                      "300002": np.dtype("float64"), "300003": np.dtype("float64")}
    assert counts["300002"].iloc[:4].isna().all()
    assert counts["300003"].iloc[:5].isna().all()
    assert result.signals.iloc[-1].to_dict() == {"300001": True, "300002": True, "300003": False}
    pd.testing.assert_frame_equal(panels["close"], before, check_exact=True)


@pytest.mark.parametrize("code", [
    "300413", "301001", "000001", "600001", "688001", "830001", "920001",
])
def test_all_boards_in_the_resolved_input_pool_are_evaluated(code):
    assert selected(mango_example(code=code))


@pytest.mark.parametrize("name", ["ST样本", "*ST样本", "st样本", "样本退", "退市样本", "", "  ", None, np.nan, 123])
def test_names_do_not_restrict_the_resolved_input_pool(name):
    assert selected(mango_example(name=name))


def test_main_and_star_same_shape_keep_equal_scores_and_board_limit_prices():
    samples = [mango_example(code="600001"), mango_example(code="688001")]
    panels = {key: pd.concat([sample[key] for sample in samples], axis=1)
              for key, value in samples[0].items() if isinstance(value, pd.DataFrame)}
    panels["__instrument_names__"] = {code: "普通样本" for code in panels["close"].columns}
    result = ContractionRebreakoutV1().compute(panels)
    assert result.picks_on(panels["close"].index[-1]) == ["600001", "688001"]
    assert result.factors["score"].iloc[-1, 0] == result.factors["score"].iloc[-1, 1]
    previous = panels["__raw_close"].iloc[-2, 0]
    assert result.factors["涨停价"].iloc[-1].tolist() == pytest.approx(
        [np.floor(previous * ratio * 100 + .5 + 1e-9) / 100 for ratio in (1.1, 1.2)])


def test_main_board_st_is_selected_below_five_percent_limit_and_rejected_at_limit():
    panels = threshold_example()
    for key, value in panels.items():
        if isinstance(value, pd.DataFrame):
            value.columns = ["600001"]
    panels["__instrument_names__"] = {"600001": "ST样本"}
    result = ContractionRebreakoutV1().compute(panels)
    assert result.signals.iloc[-1, 0]
    assert result.factors["涨停价"].iloc[-1, 0] == pytest.approx(10.5)
    panels["close"].iloc[-1, 0] = panels["__raw_close"].iloc[-1, 0] = 10.5
    panels["high"].iloc[-1, 0] = 10.5
    result = ContractionRebreakoutV1().compute(panels)
    assert not result.factors["收盘非涨停"].iloc[-1, 0]
    assert not result.signals.iloc[-1, 0]


def test_absent_name_metadata_is_an_explicit_error():
    panels = mango_example()
    del panels["__instrument_names__"]
    with pytest.raises(StrategyError, match="证券名称"):
        ContractionRebreakoutV1().compute(panels)


@pytest.mark.parametrize("field", FIELDS)
@pytest.mark.parametrize("offset", [-14, -3, -1])
@pytest.mark.parametrize("invalid", [np.nan, np.inf, -1., 0.])
def test_missing_non_finite_non_positive_dependency_data_fails_closed(field, offset, invalid):
    panels = mango_example()
    panels[field].iloc[offset, 0] = invalid
    assert not selected(panels)


@pytest.mark.parametrize("field, offset, value", [
    ("high", -1, 19.79), ("low", -1, 18.52),
    ("high", -14, 1.), ("low", -14, 100.),
])
def test_illegal_ohlc_ranges_in_the_formula_dependency_window_fail_closed(field, offset, value):
    panels = mango_example()
    panels[field].iloc[offset, 0] = value
    assert not selected(panels)


def test_fixed_formula_thresholds_include_exact_5pct_3pct_and_1_5_times_volume():
    assert selected(threshold_example())


@pytest.mark.parametrize("field, offset, value", [
    ("close", -9, np.nextafter(10.5, 0.)),
    ("close", -1, np.nextafter(10.3, 0.)),
    ("volume", -1, np.nextafter(90., 0.)),
])
def test_just_below_each_inclusive_threshold_does_not_select(field, offset, value):
    panels = threshold_example()
    panels[field].iloc[offset, 0] = value
    assert not selected(panels)


def test_equal_closes_equal_prior_high_and_equal_ma_volume_do_not_pass_strict_conditions():
    panels = mango_example()
    panels["close"].iloc[-2, 0] = 19.
    assert not selected(panels)
    panels = mango_example()
    panels["close"].iloc[-1, 0] = 19.68
    assert not selected(panels)
    panels = threshold_example()
    panels["volume"].iloc[-6:-1, 0] = 100.
    panels["volume"].iloc[-1, 0] = 150.
    assert not selected(panels)


@pytest.mark.parametrize("offset, expected", [(-13, True), (-14, False), (-4, True)])
def test_earlier_impulse_window_is_exactly_t_minus_12_through_t_minus_3(offset, expected):
    panels = threshold_example()
    panels["open"].iloc[-9, 0] = 9.95
    panels["high"].iloc[-9, 0] = 10.1
    panels["low"].iloc[-9, 0] = 9.9
    panels["close"].iloc[-9, 0] = 10.
    for field, value in zip(FIELDS, [10.2, 10.6, 10.1, 10.5, 100.], strict=True):
        panels[field].iloc[offset, 0] = value
    panels["close"].iloc[-1, 0] = 11.
    panels["high"].iloc[-1, 0] = 11.1
    assert selected(panels) is expected


def test_current_strong_bullish_day_does_not_replace_a_missing_prior_impulse():
    panels = threshold_example()
    panels["close"].iloc[-9, 0] = 10.
    panels["open"].iloc[-9, 0] = 9.95
    panels["low"].iloc[-9, 0] = 9.9
    panels["close"].iloc[-1, 0] = 11.
    panels["high"].iloc[-1, 0] = 11.1
    assert not selected(panels)


def test_close_limit_up_is_excluded_and_strategy_keeps_next_open_entry():
    panels = threshold_example()
    panels["close"].iloc[-1, 0] = 12.
    panels["high"].iloc[-1, 0] = 12.
    panels["__raw_close"].iloc[-1, 0] = 12.
    assert not selected(panels)
    engine = ContractionRebreakoutV1()
    assert engine.entry_timing == "next_open"
    assert engine.execution_adjust == "none"
    assert not getattr(engine, "requires_raw_limit_ohlc", False)
    assert engine.requires_raw_limit_price


def test_unknown_parameters_cannot_silently_change_the_fixed_strategy():
    with pytest.raises(StrategyError, match="不认识的参数"):
        ContractionRebreakoutV1().compute(mango_example(), {"volume_ratio": 2.})
