"""Runtime trust follows canonical native code; explicit audits remain complete."""
from __future__ import annotations

from types import MethodType

import numpy as np
import pandas as pd
import pytest

from src.strategy.application import audit
from src.strategy.application.audit_policy import runtime_audit_mode
from src.strategy.application.contraction_rebreakout import ContractionRebreakoutV1
from src.strategy.application.execution_profile import ExecutionProfile
from src.strategy.application.impulse_inside_breakout import ImpulseInsideBreakoutV1
from src.strategy.application.qianlong import QianlongCloseePickerV3
from src.strategy.application.screen_formula import build_formula_engine
from src.strategy.application.screen_python import build_python_engine
from src.strategy.application.tail_resonance import SanyuanTailResonance
from src.strategy.application.yangshi_tail import YangshiTailPickerV1
from src.strategy.domain.base import SignalResult


BUILTINS = (ContractionRebreakoutV1, ImpulseInsideBreakoutV1, QianlongCloseePickerV3, SanyuanTailResonance, YangshiTailPickerV1)


class FutureFactorEngine:
    slug = "unknown-python"
    entry_timing = "next_open"

    def required_fields(self):
        return ("close",)

    def min_bars(self):
        return 2

    def execution_profile(self, params=None):
        # Self-reporting cannot make this user implementation trusted.
        return ExecutionProfile(pure=True, causal=True, column_mode="independent", origin="finite", lookback_bars=1)

    def compute(self, panels, params=None):
        return SignalResult(panels["close"] > 0, {"future": panels["close"].shift(-1)})


@pytest.mark.parametrize("engine_type", BUILTINS)
def test_shipped_exact_builtin_implementations_use_release_validation(engine_type):
    assert runtime_audit_mode(engine_type()) == "release-tested"


@pytest.mark.parametrize("engine_type", BUILTINS)
def test_subclasses_never_inherit_runtime_audit_trust(engine_type):
    subclass = type("UserSubclass", (engine_type,), {})
    assert runtime_audit_mode(subclass()) == "dynamic"


@pytest.mark.parametrize("name", [
    "compute", "compute_projection", "execution_profile", "default_params", "required_fields", "min_bars",
])
def test_instance_method_overrides_remove_trust(name):
    engine = ImpulseInsideBreakoutV1()
    setattr(engine, name, MethodType(lambda _engine, *args, **kwargs: None, engine))
    assert runtime_audit_mode(engine) == "dynamic"


def test_adding_a_projector_to_a_builtin_without_one_removes_trust():
    engine = QianlongCloseePickerV3()
    engine.compute_projection = MethodType(lambda _engine, *args: None, engine)
    assert runtime_audit_mode(engine) == "dynamic"


@pytest.mark.parametrize("name", ["compute", "compute_projection", "execution_profile"])
def test_class_method_replacement_cannot_redefine_the_canonical_snapshot(monkeypatch, name):
    monkeypatch.setattr(ImpulseInsideBreakoutV1, name, lambda _engine, *args: None)
    assert runtime_audit_mode(ImpulseInsideBreakoutV1()) == "dynamic"


def test_rebound_method_must_belong_to_the_actual_instance():
    engine = ImpulseInsideBreakoutV1()
    engine.compute = ImpulseInsideBreakoutV1().compute
    assert runtime_audit_mode(engine) == "dynamic"


@pytest.mark.parametrize("engine_type", BUILTINS)
def test_changed_entry_timing_removes_release_validation_basis(engine_type):
    engine = engine_type()
    engine.entry_timing = "open"
    assert runtime_audit_mode(engine) == "dynamic"


def test_unknown_code_cannot_gain_trust_from_builtin_identity_labels_or_profile():
    engine = FutureFactorEngine()
    engine.slug = ImpulseInsideBreakoutV1.slug
    engine.strategy_revision = ImpulseInsideBreakoutV1.strategy_revision
    assert engine.execution_profile().pure and engine.execution_profile().causal
    assert runtime_audit_mode(engine) == "dynamic"


def test_unknown_profile_is_not_invoked_while_deciding_trust():
    class Unknown:
        def execution_profile(self, params=None):
            raise AssertionError("unknown user capabilities must not be queried for trust")

    assert runtime_audit_mode(Unknown()) == "dynamic"


def test_formula_compiler_proof_still_uses_dynamic_audit_in_this_policy_version():
    engine = build_formula_engine({
        "slug": "compiled-example", "name": "compiled-example", "code": "PICK:CLOSE>MA(CLOSE,5);",
        "manifest": {"schema_version": 1, "entry_timing": "next_open", "min_bars": 10,
                     "output": {"signal": "PICK"}},
    })
    assert engine.execution_profile().pure and engine.execution_profile().causal
    assert runtime_audit_mode(engine) == "dynamic"


def test_python_screen_wrapper_retains_dynamic_audit():
    engine = build_python_engine({
        "slug": "python-example", "name": "python-example", "runtime": "python",
        "code": "def compute(panels, params):\n    return {'signals': panels['close'] > 0}\n",
        "manifest": {"entry_timing": "next_open", "min_bars": 1, "data": {"fields": ["close"]}},
    })
    assert runtime_audit_mode(engine) == "dynamic"


def test_origin_sensitive_native_params_do_not_need_daily_truncation_probes():
    assert runtime_audit_mode(QianlongCloseePickerV3(), {"death_lookback": 0}) == "release-tested"


def test_release_runtime_report_states_the_basis_without_claiming_a_dynamic_run(monkeypatch):
    def unexpected(*args, **kwargs):
        raise AssertionError("release-tested execution must not run the full guard")

    monkeypatch.setattr(audit, "guard_strategy", unexpected)
    report = audit.guard_runtime_strategy(ImpulseInsideBreakoutV1())
    assert not report.failed
    assert report.findings[0].severity == "info"
    assert report.findings[0].detail["mode"] == "release-tested"
    assert report.findings[0].detail["dynamic_truncation_ran"] is False
    assert "未重复" in report.reason()
    assert report.to_dict()["reason"] != "未发现前视偏差"


def test_dynamic_runtime_guard_preserves_full_guard_arguments_and_report(monkeypatch):
    engine = FutureFactorEngine()
    panels = {"close": pd.DataFrame([10.0, 11.0])}
    params, baseline = {}, object()
    expected = audit.AuditReport(engine.slug, engine.entry_timing)
    called = []

    def full_guard(actual_engine, actual_panels, **kwargs):
        called.append((actual_engine, actual_panels, kwargs))
        return expected

    monkeypatch.setattr(audit, "guard_strategy", full_guard)
    assert audit.guard_runtime_strategy(engine, panels, params=params, baseline=baseline) is expected
    assert called == [(engine, panels, {"params": params, "baseline": baseline})]


def test_unknown_future_factor_remains_blocked_by_real_truncation():
    engine = FutureFactorEngine()
    panels = {"close": pd.DataFrame(
        np.arange(24.0) + 10,
        index=pd.bdate_range("2025-01-02", periods=24).strftime("%Y-%m-%d"),
        columns=["600001"],
    )}
    with pytest.raises(audit.LookAheadError) as captured:
        audit.guard_runtime_strategy(engine, panels, baseline=engine.compute(panels))
    assert any(finding.check == "truncation" and finding.severity == "block"
               for finding in captured.value.report.findings)


def test_explicit_version_validation_entrypoints_still_run_dynamic_auditing(monkeypatch):
    engine = ImpulseInsideBreakoutV1()
    panels = {"close": pd.DataFrame([10.0, 11.0], columns=["600001"])}
    calls = []

    def dynamic(actual_engine, actual_panels, **kwargs):
        calls.append((actual_engine, actual_panels))
        return audit.AuditReport(engine.slug, engine.entry_timing)

    monkeypatch.setattr(audit, "audit_truncation", dynamic)
    assert not audit.guard_strategy(engine, panels).failed
    assert not audit.audit_strategy(engine, panels).failed
    assert len(calls) == 2
