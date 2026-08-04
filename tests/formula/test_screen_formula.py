from __future__ import annotations

import inspect
import unittest

import numpy as np
import pandas as pd

from src.formula import (
    ABS,
    ATR,
    AVEDEV,
    BARSCOUNT,
    BARSLAST,
    BARSSINCE,
    BOLL_LOWER,
    BOLL_MID,
    BOLL_UPPER,
    CCI,
    COUNT,
    CROSS,
    DMA,
    EMA,
    EVERY,
    EXIST,
    FILTER,
    FormulaCompileError,
    FormulaEvaluationError,
    HHV,
    HHVBARS,
    IF,
    LLV,
    LLVBARS,
    MACD,
    MACD_DEA,
    MACD_DIF,
    MA,
    MAX,
    MIN,
    OBV,
    REF,
    ROC,
    RSI,
    SMA,
    STD,
    SUM,
    TR,
    WMA,
    WR,
    ZTPRICE,
    FORMULA_FUNCTIONS,
    build_formula_explanation,
    build_manifest_explanation,
    compile_screen_formula,
    evaluate_screen_formula,
)
from src.formula.application import screen_formula as public_api
from src.formula.domain import screen_formula_compiler as compiler_module


def _manifest(
    *,
    entry_timing: str = "next_open",
    min_bars: int = 6,
    signal: str = "PICK",
    factors: list[str] | None = None,
    params: dict[str, dict[str, object]] | None = None,
) -> dict[str, object]:
    return {
        "schema_version": 1,
        "entry_timing": entry_timing,
        "min_bars": min_bars,
        "params": params
        if params is not None
        else {
            "N": {"type": "int", "default": 3, "min": 2, "max": 5, "label": "窗口"},
            "VOL_MULT": {"type": "float", "default": 1.5, "min": 1.0, "max": 3.0, "label": "放量倍数"},
        },
        "output": {"signal": signal},
        "factors": factors if factors is not None else ["BASE_MA", "VOL_RATIO", "BREAKOUT"],
    }


def _panels(rows: int = 24) -> dict[str, pd.DataFrame]:
    index = pd.date_range("2026-01-01", periods=rows, freq="D").strftime("%Y-%m-%d")
    up = np.linspace(10.0, 13.0, rows)
    flat = np.linspace(8.0, 8.4, rows)
    close = pd.DataFrame({"000001": up, "000002": flat}, index=index)
    close.iloc[-1, 0] = 16.0
    open_ = close - 0.2
    high = close + 0.3
    low = close - 0.4
    volume = pd.DataFrame({"000001": np.full(rows, 100.0), "000002": np.full(rows, 90.0)}, index=index)
    volume.iloc[-1, 0] = 260.0
    amount = close * volume
    turnover = pd.DataFrame({"000001": np.full(rows, 0.02), "000002": np.full(rows, 0.015)}, index=index)
    return {
        "open": open_,
        "high": high,
        "low": low,
        "close": close,
        "volume": volume,
        "amount": amount,
        "turnover": turnover,
    }


class CompileAndEvaluateTests(unittest.TestCase):
    def test_next_dip_allows_close_high_low_and_declares_timing(self) -> None:
        formula = "PICK: RSI(CLOSE,14)<30 AND CLOSE>OPEN AND (CLOSE-LOW)/(HIGH-LOW)>0.6;"
        compiled = compile_screen_formula(
            formula,
            _manifest(
                entry_timing="next_dip",
                min_bars=20,
                params={},
                factors=[],
            ),
        )
        self.assertEqual(compiled.manifest.entry_timing, "next_dip")
        self.assertEqual(compiled.required_fields, ("close", "high", "low", "open"))

    def test_compiles_and_evaluates_breakout_formula(self) -> None:
        formula = """
        {大小写、注释、参数与因子}
        base_ma:=MA(CLOSE,N);
        hh:=HHV(REF(HIGH,1),N);
        vol_ratio:=VOL/MA(VOL,5);
        breakout:=CLOSE>HH;
        pick: breakout AND vol_ratio>=VOL_MULT AND CLOSE>base_ma;
        """
        compiled = compile_screen_formula(formula, _manifest())
        self.assertEqual(compiled.required_fields, ("close", "high", "volume"))
        self.assertEqual(compiled.min_bars_required, 6)
        self.assertEqual(compiled.signal_name, "PICK")
        result = evaluate_screen_formula(compiled, _panels())
        self.assertTrue(result.signals.iloc[-1, 0])
        self.assertFalse(result.signals.iloc[-1, 1])
        self.assertIn("VOL_RATIO", result.factors)
        self.assertGreater(float(result.factors["VOL_RATIO"].iloc[-1, 0]), 1.5)

    def test_open_requires_intraday_fields_to_be_lagged(self) -> None:
        with self.assertRaises(FormulaCompileError) as caught:
            compile_screen_formula("PICK: CLOSE>REF(CLOSE,1);", _manifest(entry_timing="open", factors=[]))
        self.assertEqual(caught.exception.diagnostics[0].code, "E_ENTRY_TIMING_LOOKAHEAD")

    def test_close_disallows_current_high_low(self) -> None:
        with self.assertRaises(FormulaCompileError) as caught:
            compile_screen_formula("PICK: HIGH>REF(HIGH,1);", _manifest(entry_timing="close", factors=[]))
        self.assertEqual(caught.exception.diagnostics[0].code, "E_ENTRY_TIMING_LOOKAHEAD")

    def test_open_allows_open_and_lagged_high(self) -> None:
        compiled = compile_screen_formula(
            "X:=REF(HIGH,1); PICK: OPEN>X;",
            _manifest(entry_timing="open", min_bars=2, factors=["X"], params={}),
        )
        result = evaluate_screen_formula(compiled, _panels())
        self.assertEqual(result.signals.shape, _panels()["close"].shape)

    def test_entry_timing_field_matrix(self) -> None:
        allowed = {
            "open": {"OPEN"},
            "close": {"OPEN", "CLOSE", "VOL", "AMOUNT", "HSL"},
            "next_open": {"OPEN", "HIGH", "LOW", "CLOSE", "VOL", "AMOUNT", "HSL"},
        }
        for timing, fields in allowed.items():
            for field in ("OPEN", "HIGH", "LOW", "CLOSE", "VOL", "AMOUNT", "HSL"):
                formula = f"PICK: {field}>0;"
                with self.subTest(entry_timing=timing, field=field):
                    if field in fields:
                        compile_screen_formula(formula, _manifest(entry_timing=timing, factors=[]))
                    else:
                        with self.assertRaises(FormulaCompileError) as caught:
                            compile_screen_formula(formula, _manifest(entry_timing=timing, factors=[]))
                        self.assertEqual(caught.exception.diagnostics[0].code, "E_ENTRY_TIMING_LOOKAHEAD")
                lagged = f"PICK: REF({field},1)>0;"
                with self.subTest(entry_timing=timing, field=f"REF({field},1)"):
                    compile_screen_formula(lagged, _manifest(entry_timing=timing, min_bars=2, factors=[]))


class CompilerGuardTests(unittest.TestCase):
    def test_rejects_unsupported_function(self) -> None:
        with self.assertRaises(FormulaCompileError) as caught:
            compile_screen_formula("PICK: SAR(HIGH,LOW,0.02,0.2)>0;", _manifest(factors=[]))
        self.assertEqual(caught.exception.diagnostics[0].code, "E_UNSUPPORTED_FUNCTION")

    def test_rejects_series_for_scalar_formula_arguments(self) -> None:
        for formula in (
            "PICK: SMA(CLOSE,3,OPEN)>0;",
            "PICK: ZTPRICE(REF(CLOSE,1),CLOSE)>0;",
        ):
            with self.subTest(formula=formula), self.assertRaises(FormulaCompileError) as caught:
                compile_screen_formula(formula, _manifest(factors=[]))
            self.assertEqual(caught.exception.diagnostics[0].code, "E_ARGUMENT_TYPE")

    def test_rejects_duplicate_binding(self) -> None:
        formula = "A:=CLOSE; A:=OPEN; PICK: A>0;"
        with self.assertRaises(FormulaCompileError) as caught:
            compile_screen_formula(formula, _manifest(factors=["A"], params={}))
        self.assertEqual(caught.exception.diagnostics[0].code, "E_DUPLICATE_BINDING")

    def test_rejects_undefined_identifier(self) -> None:
        with self.assertRaises(FormulaCompileError) as caught:
            compile_screen_formula("PICK: UNKNOWN>0;", _manifest(factors=[]))
        self.assertEqual(caught.exception.diagnostics[0].code, "E_UNDEFINED_IDENTIFIER")

    def test_rejects_parameter_redefinition(self) -> None:
        with self.assertRaises(FormulaCompileError) as caught:
            compile_screen_formula("N:=3; PICK: CLOSE>0;", _manifest(factors=[]))
        self.assertEqual(caught.exception.diagnostics[0].code, "E_PARAM_REDEFINED")

    def test_rejects_market_field_redefinition(self) -> None:
        with self.assertRaises(FormulaCompileError) as caught:
            compile_screen_formula("CLOSE:=OPEN; PICK: CLOSE>0;", _manifest(factors=[], params={}))
        self.assertEqual(caught.exception.diagnostics[0].code, "E_FIELD_REDEFINED")

    def test_rejects_non_boolean_signal(self) -> None:
        with self.assertRaises(FormulaCompileError) as caught:
            compile_screen_formula("PICK: MA(CLOSE,3);", _manifest(factors=[]))
        self.assertEqual(caught.exception.diagnostics[0].code, "E_SIGNAL_TYPE")

    def test_rejects_dynamic_window_and_negative_ref(self) -> None:
        with self.assertRaises(FormulaCompileError) as dynamic:
            compile_screen_formula("LOOKBACK:=2; PICK: CLOSE>MA(CLOSE,LOOKBACK);", _manifest(factors=["LOOKBACK"], params={}))
        self.assertEqual(dynamic.exception.diagnostics[0].code, "E_WINDOW_DYNAMIC")
        with self.assertRaises(FormulaCompileError) as negative:
            compile_screen_formula("PICK: REF(CLOSE,-1)>0;", _manifest(factors=[]))
        self.assertEqual(negative.exception.diagnostics[0].code, "E_WINDOW_RANGE")

    def test_rejects_manifest_min_bars_smaller_than_inferred(self) -> None:
        formula = "A:=HHV(REF(HIGH,1),N); PICK: CLOSE>A;"
        with self.assertRaises(FormulaCompileError) as caught:
            compile_screen_formula(formula, _manifest(min_bars=3, factors=["A"]))
        self.assertEqual(caught.exception.diagnostics[0].code, "E_MIN_BARS_DECLARED")

    def test_rejects_resource_limits(self) -> None:
        huge_formula = "A:=CLOSE;\n" + ("A:=A+A;\n" * 9000) + "PICK: A>0;"
        with self.assertRaises(FormulaCompileError) as size_error:
            compile_screen_formula(huge_formula, _manifest(factors=[]))
        self.assertEqual(size_error.exception.diagnostics[0].code, "E_FORMULA_SIZE")
        params = {"N": {"type": "int", "default": 3, "min": 2, "max": 1001}}
        with self.assertRaises(FormulaCompileError) as window_error:
            compile_screen_formula("PICK: CLOSE>MA(CLOSE,N);", _manifest(factors=[], params=params, min_bars=1002))
        self.assertEqual(window_error.exception.diagnostics[0].code, "E_WINDOW_LIMIT")


class FunctionRegistryParityTests(unittest.TestCase):
    def test_recursive_and_position_functions_require_full_history(self) -> None:
        cases = {
            "EMA": "PICK: EMA(CLOSE,3)>0;",
            "SMA": "PICK: SMA(CLOSE,3,1)>0;",
            "BARSLAST": "PICK: BARSLAST(CLOSE>OPEN)>=0;",
            "BARSCOUNT": "PICK: BARSCOUNT(CLOSE)>0;",
            "MACD": "PICK: MACD(CLOSE,2,4,2)>0;",
        }
        for name, formula in cases.items():
            with self.subTest(name=name):
                compiled = compile_screen_formula(formula, _manifest(factors=[], params={}, min_bars=10))
                self.assertTrue(compiled.requires_full_history)

        bounded = compile_screen_formula(
            "PICK: FILTER(CLOSE>OPEN,3);",
            _manifest(factors=[], params={}, min_bars=3),
        )
        self.assertFalse(bounded.requires_full_history)

    def test_invalid_indicator_arguments_raise_a_formula_evaluation_error(self) -> None:
        compiled = compile_screen_formula(
            "PICK: MACD(CLOSE,26,12,9)>0;",
            _manifest(factors=[], params={}, min_bars=40),
        )

        with self.assertRaises(FormulaEvaluationError) as caught:
            evaluate_screen_formula(compiled, _panels(rows=40))

        self.assertEqual(caught.exception.diagnostics[0].code, "E_RUNTIME_FUNCTION")

    def test_constant_arguments_and_branches_are_evaluated(self) -> None:
        panels = _panels(rows=6)
        formula = "A:=IF(CLOSE>OPEN,1,0); B:=MAX(1,2); C:=MIN(3,2); PICK: A>0;"
        compiled = compile_screen_formula(
            formula,
            _manifest(factors=["A", "B", "C"], params={}, min_bars=1),
        )
        result = evaluate_screen_formula(compiled, panels)
        expected_a = (panels["close"] > panels["open"]).astype(float)
        expected_b = pd.DataFrame(2.0, index=expected_a.index, columns=expected_a.columns)
        expected_c = pd.DataFrame(2.0, index=expected_a.index, columns=expected_a.columns)
        pd.testing.assert_frame_equal(result.factors["A"], expected_a, check_dtype=False)
        pd.testing.assert_frame_equal(result.factors["B"], expected_b, check_dtype=False)
        pd.testing.assert_frame_equal(result.factors["C"], expected_c, check_dtype=False)

    def test_every_catalog_function_routes_to_existing_vectorized_operator(self) -> None:
        panels = _panels()
        close = panels["close"]
        open_ = panels["open"]
        high = panels["high"]
        low = panels["low"]
        turnover_pct = panels["turnover"] * 100.0
        cases: dict[str, tuple[str, pd.DataFrame, bool]] = {
            "REF": ("F:=REF(CLOSE,1); PICK: F>0;", REF(close, 1), False),
            "MA": ("F:=MA(CLOSE,3); PICK: F>0;", MA(close, 3), False),
            "EMA": ("F:=EMA(CLOSE,3); PICK: F>0;", EMA(close, 3), False),
            "SMA": ("F:=SMA(CLOSE,3,1); PICK: F>0;", SMA(close, 3, 1), False),
            "WMA": ("F:=WMA(CLOSE,3); PICK: F>0;", WMA(close, 3), False),
            "DMA": ("F:=DMA(CLOSE,0.2); PICK: F>0;", DMA(close, 0.2), False),
            "SUM": ("F:=SUM(CLOSE,3); PICK: F>0;", SUM(close, 3), False),
            "HHV": ("F:=HHV(HIGH,3); PICK: F>0;", HHV(high, 3), False),
            "LLV": ("F:=LLV(LOW,3); PICK: F>0;", LLV(low, 3), False),
            "STD": ("F:=STD(CLOSE,3); PICK: F>0;", STD(close, 3), False),
            "AVEDEV": ("F:=AVEDEV(CLOSE,3); PICK: F>0;", AVEDEV(close, 3), False),
            "COUNT": ("F:=COUNT(CLOSE>OPEN,3); PICK: F>0;", COUNT(close > open_, 3), False),
            "EVERY": ("F:=EVERY(CLOSE>OPEN,3); PICK: F;", EVERY(close > open_, 3), True),
            "EXIST": ("F:=EXIST(CLOSE>OPEN,3); PICK: F;", EXIST(close > open_, 3), True),
            "FILTER": ("F:=FILTER(CLOSE>OPEN,2); PICK: F;", FILTER(close > open_, 2), True),
            "BARSLAST": ("F:=BARSLAST(CLOSE>OPEN); PICK: F>=0;", BARSLAST(close > open_), False),
            "BARSSINCE": ("F:=BARSSINCE(CLOSE>OPEN); PICK: F>=0;", BARSSINCE(close > open_), False),
            "BARSCOUNT": ("F:=BARSCOUNT(CLOSE); PICK: F>0;", BARSCOUNT(close), False),
            "HHVBARS": ("F:=HHVBARS(HIGH,3); PICK: F>=0;", HHVBARS(high, 3), False),
            "LLVBARS": ("F:=LLVBARS(LOW,3); PICK: F>=0;", LLVBARS(low, 3), False),
            "IF": ("F:=IF(CLOSE>OPEN,CLOSE,OPEN); PICK: F>0;", IF(close > open_, close, open_), False),
            "ABS": ("F:=ABS(CLOSE-OPEN); PICK: F>=0;", ABS(close - open_), False),
            "MAX": ("F:=MAX(CLOSE,OPEN); PICK: F>0;", MAX(close, open_), False),
            "MIN": ("F:=MIN(CLOSE,OPEN); PICK: F>0;", MIN(close, open_), False),
            "CROSS": ("F:=CROSS(CLOSE,MA(CLOSE,3)); PICK: F;", CROSS(close, MA(close, 3)), True),
            "ZTPRICE": ("F:=ZTPRICE(REF(CLOSE,1),0.1); PICK: F>0;", ZTPRICE(REF(close, 1), 0.1), False),
            "TR": ("F:=TR(HIGH,LOW,CLOSE); PICK: F>0;", TR(high, low, close), False),
            "ATR": ("F:=ATR(HIGH,LOW,CLOSE,3); PICK: F>0;", ATR(high, low, close, 3), False),
            "RSI": ("F:=RSI(CLOSE,3); PICK: F>0;", RSI(close, 3), False),
            "ROC": ("F:=ROC(CLOSE,3); PICK: F>0;", ROC(close, 3), False),
            "WR": ("F:=WR(HIGH,LOW,CLOSE,3); PICK: F<0;", WR(high, low, close, 3), False),
            "CCI": ("F:=CCI(HIGH,LOW,CLOSE,3); PICK: F>0;", CCI(high, low, close, 3), False),
            "OBV": ("F:=OBV(CLOSE,VOL); PICK: F>=0;", OBV(close, panels["volume"]), False),
            "MACD_DIF": ("F:=MACD_DIF(CLOSE,2,4); PICK: F>0;", MACD_DIF(close, 2, 4), False),
            "MACD_DEA": ("F:=MACD_DEA(CLOSE,2,4,2); PICK: F>0;", MACD_DEA(close, 2, 4, 2), False),
            "MACD": ("F:=MACD(CLOSE,2,4,2); PICK: F>0;", MACD(close, 2, 4, 2), False),
            "BOLL_MID": ("F:=BOLL_MID(CLOSE,3); PICK: F>0;", BOLL_MID(close, 3), False),
            "BOLL_UPPER": ("F:=BOLL_UPPER(CLOSE,3,2); PICK: F>0;", BOLL_UPPER(close, 3, 2), False),
            "BOLL_LOWER": ("F:=BOLL_LOWER(CLOSE,3,2); PICK: F>0;", BOLL_LOWER(close, 3, 2), False),
            "HSL": ("F:=HSL; PICK: F>0;", turnover_pct, False),
        }
        self.assertEqual(set(cases) - {"HSL"}, set(FORMULA_FUNCTIONS))
        for name, (formula, expected, is_bool) in cases.items():
            with self.subTest(function=name):
                compiled = compile_screen_formula(formula, _manifest(factors=["F"], params={}, min_bars=50))
                result = evaluate_screen_formula(compiled, panels)
                actual = result.factors["F"]
                if is_bool:
                    pd.testing.assert_frame_equal(actual.astype(bool), expected.astype(bool), obj=name)
                else:
                    pd.testing.assert_frame_equal(actual.astype(float), expected.astype(float), check_exact=False, atol=1e-10, rtol=1e-10, obj=name)

    def test_position_functions_have_no_extra_window_requirement(self) -> None:
        for name, formula in {
            "BARSLAST": "F:=BARSLAST(CLOSE>OPEN); PICK: F>=0;",
            "BARSSINCE": "F:=BARSSINCE(CLOSE>OPEN); PICK: F>=0;",
            "BARSCOUNT": "F:=BARSCOUNT(CLOSE); PICK: F>0;",
        }.items():
            with self.subTest(function=name):
                compiled = compile_screen_formula(formula, _manifest(factors=["F"], params={}, min_bars=1))
                self.assertEqual(compiled.min_bars_required, 1)


class ExplanationTests(unittest.TestCase):
    def test_formula_ir_explanation_uses_chinese_deterministic_steps(self) -> None:
        compiled = compile_screen_formula("BASE:=MA(CLOSE,3); PICK: CLOSE>BASE;", _manifest(factors=["BASE"], params={}, min_bars=3))
        explanation = build_formula_explanation(compiled, _manifest(factors=["BASE"], params={}, min_bars=3))
        self.assertEqual(explanation["mode"], "compiler")
        self.assertEqual(explanation["steps"][-1]["title"], "主信号 PICK")
        self.assertIn("收盘价", explanation["steps"][-1]["plain_text"])
        self.assertEqual(explanation["steps"][0]["functions"], ["MA"])

    def test_python_manifest_explanation_preserves_user_logic(self) -> None:
        manifest = _manifest(factors=[])
        manifest["logic"] = [{"id": "trend", "title": "趋势向上", "expression": "close > ma", "explanation": "收盘价高于均线", "citations": []}]
        explanation = build_manifest_explanation(runtime="python", manifest=manifest, required_fields=["close"], min_bars=20)
        self.assertEqual(explanation["mode"], "manifest")
        self.assertEqual(explanation["steps"][0]["plain_text"], "收盘价高于均线")
        self.assertEqual(explanation["steps"][0]["fields"], ["close"])

    def test_p0_functions_match_nan_and_boundary_behavior(self) -> None:
        index = pd.date_range("2026-02-01", periods=6, freq="D").strftime("%Y-%m-%d")
        close = pd.DataFrame({"000001": [1.0, np.nan, 3.0, 3.0, 2.0, 5.0]}, index=index)
        open_ = pd.DataFrame({"000001": [1.0, 2.0, 2.5, 3.5, 2.0, 4.0]}, index=index)
        high = pd.DataFrame({"000001": [1.0, 2.0, 4.0, 4.0, 2.5, 5.0]}, index=index)
        low = pd.DataFrame({"000001": [1.0, 1.5, 2.0, 2.5, 1.5, 4.0]}, index=index)
        volume = pd.DataFrame({"000001": [1.0, 2.0, 3.0, 0.0, 5.0, 8.0]}, index=index)
        amount = close.fillna(0) * volume
        turnover = pd.DataFrame({"000001": [0.01, np.nan, 0.03, 0.04, 0.05, 0.06]}, index=index)
        panels = {"open": open_, "high": high, "low": low, "close": close, "volume": volume, "amount": amount, "turnover": turnover}
        cases: dict[str, tuple[str, pd.DataFrame, bool, int]] = {
            "REF": ("F:=REF(CLOSE,1); PICK: F>0;", REF(close, 1), False, 2),
            "MA": ("F:=MA(CLOSE,3); PICK: F>0;", MA(close, 3), False, 3),
            "WMA": ("F:=WMA(CLOSE,3); PICK: F>0;", WMA(close, 3), False, 3),
            "SUM": ("F:=SUM(CLOSE,3); PICK: F>0;", SUM(close, 3), False, 3),
            "HHV": ("F:=HHV(HIGH,3); PICK: F>0;", HHV(high, 3), False, 3),
            "LLV": ("F:=LLV(LOW,3); PICK: F>0;", LLV(low, 3), False, 3),
            "STD": ("F:=STD(CLOSE,3); PICK: F>0;", STD(close, 3), False, 3),
            "COUNT": ("F:=COUNT(CLOSE>OPEN,3); PICK: F>0;", COUNT(close > open_, 3), False, 3),
            "EVERY": ("F:=EVERY(CLOSE>OPEN,3); PICK: F;", EVERY(close > open_, 3), True, 3),
            "EXIST": ("F:=EXIST(CLOSE>OPEN,3); PICK: F;", EXIST(close > open_, 3), True, 3),
            "FILTER": ("F:=FILTER(CLOSE>OPEN,2); PICK: F;", FILTER(close > open_, 2), True, 2),
            "IF": ("F:=IF(CLOSE>OPEN,CLOSE,OPEN); PICK: F>0;", IF(close > open_, close, open_), False, 1),
            "ABS": ("F:=ABS(CLOSE-OPEN); PICK: F>=0;", ABS(close - open_), False, 1),
            "MAX": ("F:=MAX(CLOSE,OPEN); PICK: F>0;", MAX(close, open_), False, 1),
            "MIN": ("F:=MIN(CLOSE,OPEN); PICK: F>0;", MIN(close, open_), False, 1),
            "CROSS": ("F:=CROSS(CLOSE,MA(CLOSE,3)); PICK: F;", CROSS(close, MA(close, 3)), True, 4),
            "HSL": ("F:=HSL; PICK: F>0;", turnover * 100.0, False, 1),
        }
        for name, (formula, expected, is_bool, min_bars) in cases.items():
            with self.subTest(function=name):
                compiled = compile_screen_formula(formula, _manifest(factors=["F"], params={}, min_bars=min_bars))
                actual = evaluate_screen_formula(compiled, panels).factors["F"]
                if is_bool:
                    pd.testing.assert_frame_equal(actual.astype(bool), expected.astype(bool), obj=name)
                else:
                    pd.testing.assert_frame_equal(actual.astype(float), expected.astype(float), check_exact=False, atol=1e-10, rtol=1e-10, obj=name)


class RuntimeGuardTests(unittest.TestCase):
    def test_rejects_unknown_and_out_of_range_runtime_params(self) -> None:
        compiled = compile_screen_formula("PICK: CLOSE>MA(CLOSE,N);", _manifest(factors=[]))
        with self.assertRaises(FormulaEvaluationError) as unknown:
            evaluate_screen_formula(compiled, _panels(), {"unknown": 1})
        self.assertEqual(unknown.exception.diagnostics[0].code, "E_PARAM_UNKNOWN")
        with self.assertRaises(FormulaEvaluationError) as out_of_range:
            evaluate_screen_formula(compiled, _panels(), {"N": 99})
        self.assertEqual(out_of_range.exception.diagnostics[0].code, "E_PARAM_OUT_OF_RANGE")

    def test_rejects_non_finite_runtime_and_manifest_params(self) -> None:
        for value in (float("nan"), float("inf"), float("-inf")):
            with self.subTest(stage="manifest", value=value):
                with self.assertRaises(FormulaCompileError) as caught:
                    compile_screen_formula(
                        "PICK: CLOSE>MA(CLOSE,N);",
                        _manifest(factors=[], params={"N": {"type": "float", "default": value, "min": 1.0, "max": 5.0}}),
                    )
                self.assertEqual(caught.exception.diagnostics[0].code, "E_PARAM_TYPE")
            with self.subTest(stage="runtime", value=value):
                compiled = compile_screen_formula(
                    "PICK: CLOSE>MA(CLOSE,N);",
                    _manifest(factors=[], params={"N": {"type": "int", "default": 3, "min": 2, "max": 5}}),
                )
                with self.assertRaises(FormulaEvaluationError) as caught:
                    evaluate_screen_formula(compiled, _panels(), {"N": value})
                self.assertEqual(caught.exception.diagnostics[0].code, "E_PARAM_TYPE")

    def test_rejects_missing_field_and_shape_mismatch(self) -> None:
        compiled = compile_screen_formula("PICK: CLOSE>OPEN;", _manifest(factors=[]))
        panels = _panels()
        broken = dict(panels)
        broken.pop("close")
        with self.assertRaises(FormulaEvaluationError) as missing:
            evaluate_screen_formula(compiled, broken)
        self.assertEqual(missing.exception.diagnostics[0].code, "E_PANEL_FIELD_MISSING")
        shifted = dict(panels)
        shifted["close"] = shifted["close"].iloc[:-1]
        with self.assertRaises(FormulaEvaluationError) as mismatch:
            evaluate_screen_formula(compiled, shifted)
        self.assertEqual(mismatch.exception.diagnostics[0].code, "E_PANEL_SHAPE_MISMATCH")

    def test_rejects_non_finite_factor(self) -> None:
        formula = "R:=VOL/(CLOSE-CLOSE); PICK: CLOSE>REF(CLOSE,1);"
        compiled = compile_screen_formula(formula, _manifest(factors=["R"]))
        with self.assertRaises(FormulaEvaluationError) as caught:
            evaluate_screen_formula(compiled, _panels())
        self.assertEqual(caught.exception.diagnostics[0].code, "E_RUNTIME_NON_FINITE")

    def test_rejects_non_finite_signal_only_expression(self) -> None:
        compiled = compile_screen_formula("PICK: VOL/(CLOSE-CLOSE)>0;", _manifest(factors=[]))
        with self.assertRaises(FormulaEvaluationError) as caught:
            evaluate_screen_formula(compiled, _panels())
        self.assertEqual(caught.exception.diagnostics[0].code, "E_RUNTIME_NON_FINITE")

    def test_public_api_stays_thin_and_no_eval_exec(self) -> None:
        public_source = inspect.getsource(public_api)
        compiler_source = inspect.getsource(compiler_module)
        self.assertIn("_compile", public_source)
        self.assertNotIn("eval(", compiler_source)
        self.assertNotIn("exec(", compiler_source)


if __name__ == "__main__":
    unittest.main()
