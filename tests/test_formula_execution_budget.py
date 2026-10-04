"""Opt-in cooperative deadlines, clear DSL diagnostics, and unchanged normal values."""
from __future__ import annotations

from time import monotonic
from types import SimpleNamespace

import numpy as np
import pandas as pd
import pytest

from src.formula.domain import functions, screen_formula_runtime as runtime
from src.formula.domain.screen_formula_compiler import compile_screen_formula
from src.formula.domain.screen_formula_types import FormulaEvaluationError


def formula(source):
    return compile_screen_formula(source, {
        "schema_version": 1, "entry_timing": "next_open", "min_bars": 1000,
        "params": {}, "factors": ["VALUE"], "output": {"signal": "PICK"},
    })


def test_nested_deadlines_only_tighten_and_restore_after_errors(monkeypatch):
    now = [5.0]
    monkeypatch.setattr(functions, "monotonic", lambda: now[0])
    with functions.formula_execution_budget(10):
        with functions.formula_execution_budget(20):
            now[0] = 11
            with pytest.raises(functions.FormulaRuntimeBudgetExceeded):
                functions.check_formula_budget()
        now[0] = 5
        with functions.formula_execution_budget(6):
            now[0] = 7
            with pytest.raises(functions.FormulaRuntimeBudgetExceeded):
                functions.check_formula_budget()
        functions.check_formula_budget()  # restored outer deadline 10, not inner 6
    now[0] = 100
    functions.check_formula_budget()  # no deadline remains after leaving the scope


@pytest.mark.parametrize("deadline", [float("nan"), float("inf"), True, "30"])
def test_invalid_deadline_is_explicit_and_does_not_leave_context(deadline):
    with pytest.raises(ValueError, match="monotonic"):
        with functions.formula_execution_budget(deadline):
            pytest.fail("Invalid deadlines must not enter their scope.")
    functions.check_formula_budget()


def test_real_expired_deadline_has_clear_dsl_diagnostic_before_evaluating_statement(monkeypatch):
    compiled = formula("VALUE:=MA(CLOSE,3); PICK:CLOSE>VALUE;")
    panels = {"close": pd.DataFrame(np.ones((10, 3)))}
    original = runtime._eval_expr
    monkeypatch.setattr(runtime, "_eval_expr", lambda *_: pytest.fail("Expired formula must not evaluate."))
    with functions.formula_execution_budget(monotonic() - 1):
        with pytest.raises(FormulaEvaluationError) as raised:
            runtime.evaluate_screen_formula(compiled, panels)
    diagnostic = raised.value.diagnostics[0]
    assert diagnostic.code == "E_FORMULA_RUNTIME_BUDGET" and "时间预算" in diagnostic.message
    assert diagnostic.line == 1 and diagnostic.column is not None
    monkeypatch.setattr(runtime, "_eval_expr", original)
    assert runtime.evaluate_screen_formula(compiled, panels).signals.shape == (10, 3)


def ticking_clock(monkeypatch):
    ticks = []
    def now():
        ticks.append(len(ticks))
        return float(len(ticks))
    monkeypatch.setattr(functions, "monotonic", now)
    return ticks


def test_long_rolling_tiles_are_interrupted_between_actual_kernel_calls(monkeypatch):
    frame = pd.DataFrame(np.random.default_rng(1).normal(size=(1000, 4)))
    monkeypatch.setattr(functions, "_MAX_WINDOW_CELLS", 80)
    original = functions._rolling_column_chunks
    calls = []
    def observed(matrix, periods, kernel):
        def wrapped(windows):
            calls.append(windows.shape)
            return kernel(windows)
        return original(matrix, periods, wrapped)
    monkeypatch.setattr(functions, "_rolling_column_chunks", observed)
    ticks = ticking_clock(monkeypatch)
    with functions.formula_execution_budget(8):
        with pytest.raises(functions.FormulaRuntimeBudgetExceeded):
            functions.AVEDEV(frame, 20)
    assert len(ticks) == 8 and 0 < len(calls) < 981
    functions.check_formula_budget()


@pytest.mark.parametrize("kind", ["WMA", "FILTER", "DMA"])
def test_long_offset_and_state_loops_can_stop_at_the_deadline(monkeypatch, kind):
    frame = pd.DataFrame(np.arange(4000, dtype=float).reshape(1000, 4))
    ticks = ticking_clock(monkeypatch)
    with functions.formula_execution_budget(8):
        with pytest.raises(functions.FormulaRuntimeBudgetExceeded):
            if kind == "WMA":
                functions.WMA(frame, 100)
            elif kind == "FILTER":
                functions.FILTER(frame > 0, 100)
            else:
                functions.DMA(frame, frame * 0 + 0.2)
    assert len(ticks) == 8


def test_mid_kernel_budget_failure_keeps_the_explicit_runtime_code(monkeypatch):
    compiled = formula("VALUE:=AVEDEV(CLOSE,20); PICK:CLOSE>VALUE;")
    monkeypatch.setattr(functions, "_MAX_WINDOW_CELLS", 80)
    ticking_clock(monkeypatch)
    with functions.formula_execution_budget(12):
        with pytest.raises(FormulaEvaluationError) as raised:
            runtime.evaluate_screen_formula(compiled, {"close": pd.DataFrame(np.ones((1000, 4)))})
    assert raised.value.diagnostics[0].code == "E_FORMULA_RUNTIME_BUDGET"
    assert raised.value.diagnostics[0].code != "E_RUNTIME_FUNCTION"


@pytest.mark.parametrize("expression", ["MA(CLOSE,10)", "HHV(CLOSE,10)", "EMA(CLOSE,10)",
    "WMA(CLOSE,10)", "AVEDEV(CLOSE,10)", "HHVBARS(CLOSE,10)", "LLVBARS(CLOSE,10)",
    "FILTER(CLOSE>0,10)"])
def test_non_expired_budget_preserves_every_normal_signal_and_factor_bit(expression):
    compiled = formula(f"VALUE:={expression}; PICK:CLOSE>0;")
    close = pd.DataFrame(np.random.default_rng(33).normal(size=(100, 5)))
    close.iloc[20:23, 1] = np.nan
    expected = runtime.evaluate_screen_formula(compiled, {"close": close})
    with functions.formula_execution_budget(monotonic() + 5):
        observed = runtime.evaluate_screen_formula(compiled, {"close": close})
    pd.testing.assert_frame_equal(observed.signals, expected.signals, check_exact=True)
    pd.testing.assert_frame_equal(observed.factors["VALUE"], expected.factors["VALUE"], check_exact=True)


def adapter_engine():
    from src.strategy.application.screen_formula import build_formula_engine

    return build_formula_engine({
        "slug": "budget-adapter-fixture", "name": "budget-adapter-fixture",
        "code": "VALUE:=MA(CLOSE,3); PICK:CLOSE>VALUE;",
        "manifest": {"schema_version": 1, "entry_timing": "next_open", "min_bars": 1000,
                     "params": {}, "factors": ["VALUE"], "output": {"signal": "PICK"}},
    })


def adapter_clock(monkeypatch):
    from src.strategy.application import compute_runtime, screen_formula

    now = [100.0]
    clock = SimpleNamespace(monotonic=lambda: now[0])
    monkeypatch.setattr(compute_runtime, "time", clock)
    monkeypatch.setattr(screen_formula, "time", clock)
    monkeypatch.setattr(functions, "monotonic", clock.monotonic)
    return now


def test_expired_task_budget_rejects_new_formula_and_restores_direct_call_context(monkeypatch):
    from src.strategy.application.compute_runtime import computation_scope, remaining_formula_seconds, _SCOPE
    from src.strategy.application.screen_formula import ScreenFormulaError

    now = adapter_clock(monkeypatch)
    monkeypatch.setenv("LOCI_SCREEN_FORMULA_RUNTIME_SECONDS", "1")
    monkeypatch.setenv("LOCI_FORMULA_COMPUTE_TIMEOUT_SECONDS", "30")
    engine = adapter_engine()
    panels = {"close": pd.DataFrame(np.ones((20, 3)))}
    original = runtime._eval_expr
    monkeypatch.setattr(runtime, "_eval_expr", lambda *_: pytest.fail("Expired task must not start a new formula."))
    with computation_scope(SimpleNamespace(conn=None)):
        now[0] = 102
        assert remaining_formula_seconds() == 0
        with pytest.raises(ScreenFormulaError) as raised:
            engine.compute(panels)
        assert raised.value.diagnostics[0].code == "E_FORMULA_RUNTIME_BUDGET"
        assert functions._FORMULA_DEADLINE.get() is None
        # A task's DSL deadline is metadata, not a blanket timer on builtin functions.
        functions.check_formula_budget()
        assert functions.FILTER(panels["close"] > 0, 2).shape == (20, 3)
    assert _SCOPE.get() is None and remaining_formula_seconds() is None
    monkeypatch.setattr(runtime, "_eval_expr", original)
    assert engine.compute(panels).signals.shape == (20, 3)
    assert functions._FORMULA_DEADLINE.get() is None


def test_adapter_single_call_task_and_outer_context_choose_minimum_and_restore(monkeypatch):
    from src.strategy.application.compute_runtime import computation_scope, _SCOPE

    adapter_clock(monkeypatch)
    monkeypatch.setenv("LOCI_SCREEN_FORMULA_RUNTIME_SECONDS", "5")
    monkeypatch.setenv("LOCI_FORMULA_COMPUTE_TIMEOUT_SECONDS", "2")
    engine = adapter_engine()
    panels = {"close": pd.DataFrame(np.arange(60, dtype=float).reshape(20, 3))}
    expected = runtime.evaluate_screen_formula(engine.compiled, panels)
    original = runtime._eval_expr
    observed_deadlines = []
    def capture(*args, **kwargs):
        observed_deadlines.append(functions._FORMULA_DEADLINE.get())
        return original(*args, **kwargs)
    monkeypatch.setattr(runtime, "_eval_expr", capture)
    with computation_scope(SimpleNamespace(conn=None)):
        assert _SCOPE.get().formula_deadline == 105
        with functions.formula_execution_budget(101.5):
            observed = engine.compute(panels)
            assert set(observed_deadlines) == {101.5}
            assert functions._FORMULA_DEADLINE.get() == 101.5
        assert functions._FORMULA_DEADLINE.get() is None
        observed_deadlines.clear()
        engine.compute(panels)
        assert set(observed_deadlines) == {102.0}
    pd.testing.assert_frame_equal(observed.signals, expected.signals, check_exact=True)
    pd.testing.assert_frame_equal(observed.factors["VALUE"], expected.factors["VALUE"], check_exact=True)
    assert _SCOPE.get() is None and functions._FORMULA_DEADLINE.get() is None
