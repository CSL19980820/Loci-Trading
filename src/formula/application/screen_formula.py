from __future__ import annotations

from typing import Any

from src.formula.domain.screen_formula_compiler import compile_screen_formula as _compile
from src.formula.domain.screen_formula_compiler import evaluate_screen_formula as _evaluate
from src.formula.domain.screen_formula_types import CompiledScreenFormula, FormulaEvaluationResult, ScreenFormulaManifest


def compile_screen_formula(
    source: str,
    manifest: ScreenFormulaManifest | dict[str, Any],
) -> CompiledScreenFormula:
    """把 Screen Skill 公式编译成可缓存的 IR。"""
    return _compile(source, manifest)


def evaluate_screen_formula(
    compiled: CompiledScreenFormula,
    panels: dict[str, Any],
    params: dict[str, Any] | None = None,
) -> FormulaEvaluationResult:
    """对已编译公式求值，返回主信号与因子面板。"""
    return _evaluate(compiled, panels, params)
