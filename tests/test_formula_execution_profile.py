"""公式执行能力与真实窗口边界；能力分析不改写策略加载和计算语义。"""
from __future__ import annotations

from dataclasses import FrozenInstanceError, replace

import numpy as np
import pandas as pd
import pytest

from src.formula.domain.screen_formula_catalog import formula_functions_catalog
from src.strategy.application.execution_profile import ExecutionProfile
from src.strategy.application.screen_formula import ScreenFormulaError, build_formula_engine
from src.strategy.application.screen_python import build_python_engine


def engine(source, *, params=None, factors=None, slug="arbitrary-new-formula"):
    return build_formula_engine({
        "slug": slug, "name": slug, "code": source,
        "manifest": {
            "schema_version": 1, "entry_timing": "next_open", "min_bars": 1000,
            "params": params or {}, "factors": factors or [],
            "output": {"signal": "PICK"},
        },
    })


def test_default_profile_is_immutable_and_unknown_python_stays_unknown():
    profile = ExecutionProfile()
    assert not profile.pure and not profile.causal
    assert profile.column_mode == "coupled" and profile.origin == "unknown"
    assert profile.lookback_bars is None and profile.metadata_fields == ()
    assert profile.causal_from is None
    with pytest.raises(FrozenInstanceError):
        profile.pure = True
    python = build_python_engine({
        "slug": "unknown-python", "name": "unknown-python", "runtime": "python",
        "code": "def compute(panels, params):\n    return {'signals': panels['close'] > 0}\n",
        "manifest": {"entry_timing": "next_open", "min_bars": 1,
                     "data": {"fields": ["close"]}},
    })
    assert getattr(python, "execution_profile", lambda *_: ExecutionProfile())({}) == profile


def test_composite_ref_ma_infers_actual_lookback_and_suffix_outputs_match():
    formula = engine(
        "BASE:=MA(REF(CLOSE,2),5); SCORE:=REF(BASE,3); PICK:CLOSE>SCORE;",
        factors=["BASE", "SCORE"],
    )
    profile = formula.execution_profile()
    assert profile == ExecutionProfile(
        pure=True, column_mode="independent", origin="finite", lookback_bars=10, causal=True,
    )
    assert profile.causal_from is None
    rng = np.random.default_rng(43)
    close = pd.DataFrame(rng.uniform(2, 20, (60, 4)))
    full = formula.compute({"close": close})
    for cutoff in (20, 39, 59):
        suffix = close.iloc[cutoff - profile.lookback_bars + 1:cutoff + 1]
        observed = formula.compute({"close": suffix})
        pd.testing.assert_series_equal(observed.signals.loc[cutoff], full.signals.loc[cutoff])
        for name in full.factors:
            pd.testing.assert_series_equal(observed.factors[name].loc[cutoff], full.factors[name].loc[cutoff])
    assert not formula.requires_full_history
    # Neither slug nor display name participates in capability inference.
    assert engine(formula.compiled.source, slug="renamed-formula").execution_profile() == profile


def test_resolved_window_params_change_lookback_instead_of_using_the_declared_maximum():
    formula = engine(
        "BASE:=MA(CLOSE,N); OLD:=REF(BASE,LAG); PICK:CLOSE>OLD;",
        params={"N": {"type": "int", "default": 5, "min": 1, "max": 20},
                "LAG": {"type": "int", "default": 2, "min": 0, "max": 10}},
    )
    assert formula.execution_profile().lookback_bars == 7
    assert formula.execution_profile({"N": 12, "LAG": 4}).lookback_bars == 16
    assert formula.execution_profile({"n": 12.0, "lag": 0}).lookback_bars == 12
    assert formula.execution_profile().lookback_bars == 7
    for params in ({"N": True}, {"N": "12"}, {"N": 21}, {"UNKNOWN": 1}):
        assert formula.execution_profile(params) == ExecutionProfile()


@pytest.mark.parametrize("expression", [
    "EMA(CLOSE,5)", "SMA(CLOSE,5,1)", "DMA(CLOSE,0.2)",
    "BARSLAST(CLOSE>REF(CLOSE,1))", "BARSSINCE(CLOSE>10)", "BARSCOUNT(CLOSE)",
    "RSI(CLOSE,5)", "OBV(CLOSE,VOL)", "MACD(CLOSE,3,8,3)",
])
def test_recursive_and_position_functions_preserve_origin_sensitivity(expression):
    formula = engine(f"VALUE:={expression}; PICK:CLOSE>0;", factors=["VALUE"])
    profile = formula.execution_profile()
    assert profile.pure and profile.causal and profile.column_mode == "independent"
    assert profile.origin == "sensitive" and profile.lookback_bars is None
    assert formula.requires_full_history


def test_filter_is_sensitive_without_changing_legacy_history_or_signal():
    formula = engine("VALUE:=FILTER(CLOSE>0,3); PICK:VALUE;", factors=["VALUE"])
    profile = formula.execution_profile()
    assert profile.origin == "sensitive" and profile.lookback_bars is None
    assert profile.pure and profile.causal
    assert not formula.requires_full_history
    close = pd.DataFrame(1.0, index=range(10), columns=["A"])
    full = formula.compute({"close": close})
    shifted = formula.compute({"close": close.loc[1:]})
    assert not full.signals.loc[9, "A"] and shifted.signals.loc[9, "A"]


@pytest.mark.parametrize("row", formula_functions_catalog(), ids=lambda row: row["name"])
def test_all_current_public_formula_primitives_have_analyzed_capabilities(row):
    formula = engine(f"VALUE:={row['examples'][0]}; PICK:CLOSE>0;", factors=["VALUE"])
    profile = formula.execution_profile()
    assert profile.pure and profile.causal and profile.column_mode == "independent"
    assert profile.origin in {"finite", "sensitive"}


@pytest.mark.parametrize("source", [
    "PICK:REF(CLOSE,-1)>0;", "PICK:BACKSET(CLOSE>0,3);", "PICK:ZIG(CLOSE,5)>0;",
    "PICK:MA(CLOSE,CLOSE)>0;", "PICK:MA(CLOSE,N+1)>0;",
])
def test_future_and_dynamic_window_expressions_are_rejected_by_the_compiler(source):
    with pytest.raises(ScreenFormulaError):
        engine(source, params={"N": {"type": "int", "default": 5, "min": 1, "max": 20}})


def test_unknown_ast_or_dynamic_window_never_inherits_compiler_bars_as_a_proof():
    formula = engine("VALUE:=MA(CLOSE,5); PICK:CLOSE>VALUE;")
    statement, signal = formula.compiled.program
    future = replace(statement, expr=replace(statement.expr, value="FUTURE_FUNCTION"))
    formula.compiled = replace(formula.compiled, program=(future, signal))
    assert formula.execution_profile() == ExecutionProfile()
    dynamic = replace(statement, expr=replace(
        statement.expr, args=(statement.expr.args[0], statement.expr.args[0]),
    ))
    formula.compiled = replace(formula.compiled, program=(dynamic, signal))
    assert formula.execution_profile() == ExecutionProfile()


@pytest.mark.parametrize("expression,bars", [
    ("TR(HIGH,LOW,CLOSE)", 2), ("ATR(HIGH,LOW,CLOSE,5)", 6),
    ("ROC(CLOSE,5)", 6), ("WR(HIGH,LOW,CLOSE,5)", 5),
    ("CCI(HIGH,LOW,CLOSE,5)", 5), ("BOLL_UPPER(CLOSE,5,2)", 5),
    ("CROSS(CLOSE,MA(CLOSE,5))", 6),
])
def test_technical_rolling_dependencies_include_the_required_previous_bar(expression, bars):
    formula = engine(f"VALUE:={expression}; PICK:CLOSE>0;", factors=["VALUE"])
    assert formula.execution_profile().lookback_bars == bars
