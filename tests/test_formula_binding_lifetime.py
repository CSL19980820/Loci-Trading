"""Last-use release preserves full evaluation while bounding live dense intermediates."""
from __future__ import annotations

import weakref

import numpy as np
import pandas as pd
import pytest

from src.formula.domain.screen_formula_compiler import compile_screen_formula
from src.formula.domain import screen_formula_runtime as runtime
from src.formula.domain.screen_formula_types import FormulaEvaluationError, FormulaEvaluationResult


def compile_formula(source, *, factors=None, params=None):
    return compile_screen_formula(source, {
        "schema_version": 1, "entry_timing": "next_open", "min_bars": 1000,
        "params": params or {}, "factors": factors or [], "output": {"signal": "PICK"},
    })


def legacy_evaluate(compiled, panels, params=None):
    """Old all-bindings-retained execution, independent of the release schedule."""
    resolved = runtime._resolve_runtime_params(compiled.manifest, params)
    reference, fields = runtime._load_reference(compiled, panels)
    diagnostics = []
    env = {}
    signal = None
    for statement in compiled.program:
        value = runtime._eval_expr(statement.expr, env, resolved, fields, reference, diagnostics)
        runtime._scan_non_finite(statement.name, value, diagnostics)
        runtime._scan_shape(statement.name, value, reference, diagnostics)
        env[statement.name] = value
        if statement.kind == "signal":
            signal = value
    signal = runtime._truthy(runtime._ensure_like(reference, signal)).fillna(False).astype(bool)
    factors = {name: runtime._ensure_like(reference, env[name]) for name in compiled.factor_names}
    for name, value in factors.items():
        runtime._scan_shape(name, value, reference, diagnostics)
        runtime._scan_non_finite(name, value, diagnostics)
    return FormulaEvaluationResult(signal, factors, resolved)


def assert_result_equal(observed, expected):
    compare = pd.testing.assert_frame_equal if isinstance(expected.signals, pd.DataFrame) else pd.testing.assert_series_equal
    compare(observed.signals, expected.signals, check_exact=True)
    assert observed.factors.keys() == expected.factors.keys()
    for name in expected.factors:
        compare(observed.factors[name], expected.factors[name], check_exact=True)
    assert observed.params == expected.params and observed.diagnostics == expected.diagnostics


def track_statement_frames(monkeypatch):
    refs = []
    peak = {"frames": 0, "bytes": 0}
    original = runtime._scan_shape

    def scan(name, value, reference, diagnostics):
        original(name, value, reference, diagnostics)
        if isinstance(value, (pd.Series, pd.DataFrame)):
            refs.append((name, weakref.ref(value)))
            live = {id(ref()): ref() for _, ref in refs if ref() is not None}
            peak["frames"] = max(peak["frames"], len(live))
            peak["bytes"] = max(peak["bytes"], sum(frame.to_numpy(copy=False).nbytes for frame in live.values()))
    monkeypatch.setattr(runtime, "_scan_shape", scan)
    return refs, peak


@pytest.mark.parametrize("length", [100, 200])
def test_real_dense_assignment_chains_release_intermediates_at_last_use(monkeypatch, length):
    source = "A0:=CLOSE+1;" + "".join(f"A{i}:=A{i-1}+1;" for i in range(1, length))
    source += f"PICK:A{length-1}>CLOSE;"
    compiled = compile_formula(source)
    close = pd.DataFrame(np.arange(512 * 16, dtype=float).reshape(512, 16))
    refs, peak = track_statement_frames(monkeypatch)
    observed = runtime.evaluate_screen_formula(compiled, {"close": close})
    optimized_peak = peak.copy()
    assert optimized_peak["frames"] <= 3
    assert optimized_peak["bytes"] <= 3 * close.to_numpy().nbytes
    assert all(ref() is None for name, ref in refs if name.startswith("A"))
    refs.clear()
    peak.update(frames=0, bytes=0)
    expected = legacy_evaluate(compiled, {"close": close})
    assert peak["frames"] >= length
    assert peak["bytes"] >= length * close.to_numpy().nbytes
    assert_result_equal(observed, expected)
    # A longer chain does not reserve one complete matrix per statement anymore.
    assert runtime.estimate_formula_working_frames(compiled) == runtime.estimate_formula_working_frames(
        compile_formula("A0:=CLOSE+1; A1:=A0+1; PICK:A1>CLOSE;"))


@pytest.mark.parametrize("series", [False, True])
@pytest.mark.parametrize("source,factors", [
    ("A:=CLOSE+N; B:=A*2; D:=A-1; E:=B+D; F:=MA(E,3); DEAD:=EMA(CLOSE,2); PICK:F>A;",
     ["A", "B", "F"]),
    ("A:=CLOSE+N; PICK:A>CLOSE; LATE:=A*3; DEAD:=MA(CLOSE,2);", ["LATE"]),
    ("A:=CLOSE+N; SCALAR:=N*2; FLAG:=N>1; NEG:=NOT FLAG; PICK:(A>CLOSE) OR NEG;",
     ["SCALAR", "FLAG", "NEG", "A"]),
    ("A:=CLOSE; B:=A; C:=REF(B,0); PICK:C>1;", ["A", "B", "C"]),
    ("A:=MA(CLOSE,3); B:=REF(A,1); SCALAR:=N; PICK:IF(CLOSE>2,B,CLOSE)>A;",
     ["A", "B", "SCALAR"]),
])
def test_exports_forks_scalars_aliases_and_nan_match_all_old_matrix_values(series, source, factors):
    compiled = compile_formula(source, factors=factors,
                               params={"N": {"type": "int", "default": 2, "min": 1, "max": 10}})
    close = pd.DataFrame([[np.nan, 2.0], [3.0, np.nan], [4.0, 8.0], [2.0, 7.0], [8.0, 5.0]],
                         index=pd.Index(["d0", "d1", "d2", "d3", "d4"], name="date"),
                         columns=pd.Index(["x", "y"], name="stock"))
    if series:
        close = close["x"]
    original = close.copy(deep=True)
    observed = runtime.evaluate_screen_formula(compiled, {"close": close}, {"n": 3})
    expected = legacy_evaluate(compiled, {"close": close}, {"n": 3})
    assert_result_equal(observed, expected)
    compare = pd.testing.assert_series_equal if series else pd.testing.assert_frame_equal
    compare(close, original, check_exact=True)


def test_every_exported_factor_stays_pinned_even_before_its_last_computational_use(monkeypatch):
    length = 100
    source = "A0:=CLOSE+1;" + "".join(f"A{i}:=A{i-1}+1;" for i in range(1, length))
    source += f"PICK:A{length-1}>CLOSE;"
    exports = [f"A{i}" for i in range(32)]
    compiled = compile_formula(source, factors=exports)
    close = pd.DataFrame(np.ones((100, 4)))
    refs, peak = track_statement_frames(monkeypatch)
    observed = runtime.evaluate_screen_formula(compiled, {"close": close})
    assert list(observed.factors) == exports
    assert all(ref() is not None for name, ref in refs if name in exports)
    assert all(ref() is None for name, ref in refs if name.startswith("A") and name not in exports)
    assert peak["frames"] <= 35
    assert_result_equal(observed, legacy_evaluate(compiled, {"close": close}))
    assert runtime.estimate_formula_working_frames(compiled) > runtime.estimate_formula_working_frames(
        compile_formula(source))


@pytest.mark.parametrize("source,code", [
    ("DEAD:=CLOSE/0; PICK:CLOSE>0;", "E_RUNTIME_NON_FINITE"),
    ("DEAD:=SMA(CLOSE,2,3); PICK:CLOSE>0;", "E_RUNTIME_FUNCTION"),
    ("PICK:CLOSE>0; DEAD:=CLOSE/0;", "E_RUNTIME_NON_FINITE"),
])
def test_unused_statements_are_still_evaluated_and_raise_the_original_diagnostics(source, code):
    compiled = compile_formula(source)
    panels = {"close": pd.DataFrame([[1.0, np.nan], [2.0, 3.0]])}
    with pytest.raises(FormulaEvaluationError) as original:
        legacy_evaluate(compiled, panels)
    with pytest.raises(FormulaEvaluationError) as observed:
        runtime.evaluate_screen_formula(compiled, panels)
    assert observed.value.diagnostics == original.value.diagnostics
    assert str(observed.value) == str(original.value)
    assert observed.value.diagnostics[0].code == code


def test_unused_shape_error_is_not_skipped(monkeypatch):
    compiled = compile_formula("DEAD:=MA(CLOSE,2); PICK:CLOSE>0;")
    panels = {"close": pd.DataFrame(np.ones((4, 2)))}
    monkeypatch.setattr(runtime, "apply_formula_call", lambda *_: pd.DataFrame(np.ones((3, 2))))
    with pytest.raises(FormulaEvaluationError) as original:
        legacy_evaluate(compiled, panels)
    with pytest.raises(FormulaEvaluationError) as observed:
        runtime.evaluate_screen_formula(compiled, panels)
    assert observed.value.diagnostics == original.value.diagnostics
    assert observed.value.diagnostics[0].code == "E_RUNTIME_SHAPE"


def test_working_estimate_includes_fork_liveness_function_scratch_and_turnover_conversion():
    chain = compile_formula("A:=CLOSE+1; B:=A+1; D:=B+1; PICK:D>CLOSE;")
    fork = compile_formula("A:=CLOSE+1; B:=A+1; D:=CLOSE+2; E:=B+D; PICK:E>A;")
    nested = compile_formula("A:=MAX(MA(CLOSE,2),MAX(EMA(CLOSE,3),MA(CLOSE,4))); PICK:A>CLOSE;")
    turnover = compile_formula("A:=HSL+1; PICK:A>HSL;")
    simple = compile_formula("A:=CLOSE+1; PICK:A>CLOSE;")
    assert runtime.estimate_formula_working_frames(fork) > runtime.estimate_formula_working_frames(chain)
    assert runtime.estimate_formula_working_frames(nested) > runtime.estimate_formula_working_frames(simple)
    assert runtime.estimate_formula_working_frames(turnover) == runtime.estimate_formula_working_frames(simple) + 1
