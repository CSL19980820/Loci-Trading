"""Runtime audit trust comes from controlled implementations, never strategy metadata."""
from __future__ import annotations

from typing import Any

from src.strategy.application.execution_profile import ExecutionProfile
from src.strategy.application.contraction_rebreakout import ContractionRebreakoutV1
from src.strategy.application.impulse_inside_breakout import ImpulseInsideBreakoutV1
from src.strategy.application.qianlong import QianlongCloseePickerV3
from src.strategy.application.tail_resonance import SanyuanTailResonance
from src.strategy.application.yangshi_tail import YangshiTailPickerV1


_METHODS = (
    "compute", "compute_projection", "execution_profile",
    "default_params", "required_fields", "min_bars",
)
_BUILTINS = (
    ContractionRebreakoutV1, ImpulseInsideBreakoutV1, QianlongCloseePickerV3,
    SanyuanTailResonance, YangshiTailPickerV1,
)
# Capture the shipped functions once. A later class or instance override does not
# become trusted because it retains the same slug, module name or class identity.
_CANONICAL = {
    engine_type: (
        engine_type.entry_timing,
        {name: getattr(engine_type, name, None) for name in _METHODS},
    )
    for engine_type in _BUILTINS
}


def runtime_audit_mode(engine: Any, params: dict | None = None) -> str:
    """Release-tested built-ins omit daily probes; all other implementations remain dynamic.

    Formula engines still use dynamic auditing in this policy version. Their
    compiler-derived capabilities are not treated as a blanket audit exemption.
    """
    canonical = _CANONICAL.get(type(engine))
    if canonical is None:
        return "dynamic"
    timing, methods = canonical
    actual_timing = getattr(engine, "entry_timing", None)
    if type(actual_timing) is not str or actual_timing != timing:
        return "dynamic"
    for name, expected in methods.items():
        actual = getattr(engine, name, None)
        if expected is None:
            if actual is not None:
                return "dynamic"
        elif (getattr(actual, "__self__", None) is not engine
              or getattr(actual, "__func__", None) is not expected):
            return "dynamic"
    # Only the matched shipped method can grant execution capabilities here.
    # Unknown strategies' self-reported pure/causal flags are never consulted.
    profile = methods["execution_profile"](engine, params)
    if type(profile) is not ExecutionProfile or not profile.pure or not profile.causal:
        return "dynamic"
    return "release-tested"
