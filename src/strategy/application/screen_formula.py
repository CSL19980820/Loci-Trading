"""Screen Skill 公式到 StrategyEngine 的薄适配。"""
from __future__ import annotations

from dataclasses import dataclass, field
import hashlib
import json
import math
import os
import time
from typing import Any

import pandas as pd

from src.formula import (
    CompiledScreenFormula,
    FormulaCompileError,
    FormulaDiagnostic,
    FormulaEvaluationError,
    FormulaEvaluationResult,
    ScreenFormulaManifest,
    compile_screen_formula as compile_formula,
    evaluate_screen_formula as evaluate_formula,
)
from src.formula.domain.screen_formula_compiler import (
    FIELD_ALIASES,
    FUNCTIONS,
    MAX_WINDOW,
    BoundExpr,
    BoundStatement,
)
from src.strategy.application.execution_profile import ExecutionProfile
from src.strategy.domain.base import SignalResult, StrategyError


# Function families describe the controlled runtime, not particular formula slugs.
# A function added to the compiler is unknown here until its execution semantics
# have been checked. In particular FILTER remembers an accepted-signal cooldown.
_FINITE_WINDOWS = frozenset({
    "MA", "WMA", "SUM", "HHV", "LLV", "STD", "AVEDEV", "COUNT", "EVERY",
    "EXIST", "HHVBARS", "LLVBARS", "BOLL_MID", "BOLL_UPPER", "BOLL_LOWER",
})
_ORIGIN_FUNCTIONS = {
    "EMA": (2, (1,)), "SMA": (3, (1,)), "DMA": (2, ()),
    "FILTER": (2, (1,)), "BARSLAST": (1, ()), "BARSSINCE": (1, ()),
    "BARSCOUNT": (1, ()), "RSI": (2, (1,)), "OBV": (2, ()),
    "MACD_DIF": (3, (1, 2)), "MACD_DEA": (4, (1, 2, 3)),
    "MACD": (4, (1, 2, 3)),
}
_POINTWISE_ARITY = {"IF": 3, "ABS": 1, "MAX": 2, "MIN": 2, "ZTPRICE": 2}
_BINARY_OPERATORS = frozenset({
    "AND", "OR", "+", "-", "*", "/", "=", "!=", "<>", ">", ">=", "<", "<=",
})


class _UnknownExecutionProfile(ValueError):
    pass


class ScreenFormulaError(StrategyError):
    def __init__(
        self, message: str, diagnostics: tuple[FormulaDiagnostic, ...] = ()
    ) -> None:
        super().__init__(message)
        self.diagnostics = diagnostics

    @classmethod
    def from_formula_error(
        cls, exc: FormulaCompileError | FormulaEvaluationError
    ) -> ScreenFormulaError:
        return cls(str(exc), getattr(exc, "diagnostics", ()))

    def to_dict(self) -> dict[str, Any]:
        primary = self.diagnostics[0] if self.diagnostics else None
        return {
            "code": primary.code if primary else "E_SCREEN_FORMULA",
            "severity": primary.severity if primary else "error",
            "line": primary.line if primary else None,
            "column": primary.column if primary else None,
            "message": str(self),
        }


@dataclass(slots=True)
class FormulaScreenEngine:
    # Quote provenance aggregates cover every requested input; detailed receipts
    # remain in the source store and are explicitly marked as omitted here.
    source_evidence_summary = True
    slug: str
    name: str
    description: str
    entry_timing: str
    strategy_revision: str
    default_param_values: dict[str, Any]
    required_field_names: tuple[str, ...]
    min_bars_value: int
    compiled: CompiledScreenFormula
    runtime: str = "formula"
    dialect: str = "loci"
    entrypoint: str | None = None
    adjust: str = "qfq"
    default_universe: dict[str, Any] | None = None
    source_kind: str = "formula"
    editable: bool = True
    # 目录元数据在 catalog 侧合并；保留槽位以兼容读取引擎元数据的调用方。
    version_history: list[dict[str, Any]] = field(default_factory=list)

    def default_params(self) -> dict[str, Any]:
        return dict(self.default_param_values)

    def required_fields(self) -> tuple[str, ...]:
        return self.required_field_names

    def min_bars(self) -> int:
        return self.min_bars_value

    @property
    def requires_full_history(self) -> bool:
        return self.compiled.requires_full_history

    def execution_profile(self, params: dict[str, Any] | None = None) -> ExecutionProfile:
        """从已绑定公式推导执行能力，不改变历史加载或现有选股信号。"""
        return _formula_execution_profile(self.compiled, params)

    def working_frames(self) -> int:
        """Conservative simultaneous array estimate for bounded stock batches."""
        from src.formula.domain.screen_formula_runtime import estimate_formula_working_frames

        return estimate_formula_working_frames(self.compiled)

    def compute(
        self,
        panels: dict[str, pd.DataFrame],
        params: dict[str, Any] | None = None,
    ) -> SignalResult:
        from src.formula.domain.functions import formula_execution_budget
        from src.strategy.application.compute_runtime import remaining_formula_seconds

        try:
            budget = float(os.environ.get("LOCI_FORMULA_COMPUTE_TIMEOUT_SECONDS", "30"))
            if not math.isfinite(budget) or budget <= 0:
                budget = 30.0
        except ValueError:
            budget = 30.0
        remaining = remaining_formula_seconds()
        if remaining is not None:
            budget = min(budget, remaining)
        with formula_execution_budget(time.monotonic() + budget):
            result = evaluate_screen_formula(self.compiled, panels, params)
        signals = _coerce_frame(result.signals, fallback_columns=("SIGNAL",))
        factor_columns = tuple(signals.columns)
        factors = {
            name: _coerce_frame(panel, fallback_columns=factor_columns)
            for name, panel in result.factors.items()
        }
        return SignalResult(signals=signals.fillna(False).astype(bool), factors=factors)


def _formula_execution_profile(
    compiled: CompiledScreenFormula, params: dict[str, Any] | None,
) -> ExecutionProfile:
    specs = compiled.manifest.params_by_name
    resolved = {name: item.default for name, item in specs.items()}
    bindings: dict[str, int | None] = {}
    try:
        for raw_name, value in (params or {}).items():
            name = str(raw_name).upper()
            if name not in specs:
                return ExecutionProfile()
            resolved[name] = specs[name].coerce_runtime(value)
        if not isinstance(compiled.program, tuple) or not compiled.program:
            return ExecutionProfile()
        for statement in compiled.program:
            if (not isinstance(statement, BoundStatement)
                    or statement.kind not in {"assign", "signal"}
                    or statement.name in bindings):
                return ExecutionProfile()
            bindings[statement.name] = _formula_lookback(statement.expr, bindings, resolved)
    except (FormulaEvaluationError, _UnknownExecutionProfile):
        return ExecutionProfile()
    sensitive = any(bars is None for bars in bindings.values())
    return ExecutionProfile(
        pure=True, column_mode="independent", causal=True,
        origin="sensitive" if sensitive else "finite",
        lookback_bars=None if sensitive else max(1, *bindings.values()),
    )


def _formula_lookback(
    expr: BoundExpr, bindings: dict[str, int | None], params: dict[str, Any],
) -> int | None:
    """None 表示起点有状态；未知节点/函数/周期不授予任何执行能力。"""
    if not isinstance(expr, BoundExpr):
        raise _UnknownExecutionProfile()
    if expr.kind in {"literal", "field", "param", "binding"}:
        if expr.args:
            raise _UnknownExecutionProfile()
        if expr.kind == "literal":
            if not isinstance(expr.value, (int, float, bool)) or not math.isfinite(expr.value):
                raise _UnknownExecutionProfile()
            return 0
        if expr.kind == "field" and expr.value in FIELD_ALIASES:
            return 1
        if expr.kind == "param" and expr.value in params:
            return 0
        if expr.kind == "binding" and expr.value in bindings:
            return bindings[expr.value]
        raise _UnknownExecutionProfile()
    if expr.kind == "unary":
        if expr.value not in {"+", "-", "NOT"} or len(expr.args) != 1:
            raise _UnknownExecutionProfile()
    elif expr.kind == "binary":
        if expr.value not in _BINARY_OPERATORS or len(expr.args) != 2:
            raise _UnknownExecutionProfile()
    elif expr.kind != "call" or expr.value not in FUNCTIONS:
        raise _UnknownExecutionProfile()
    children = [_formula_lookback(arg, bindings, params) for arg in expr.args]
    base = None if None in children else max(children, default=0)
    if expr.kind in {"unary", "binary"}:
        return base
    name = expr.value
    if name in _ORIGIN_FUNCTIONS:
        arity, windows = _ORIGIN_FUNCTIONS[name]
        if len(expr.args) != arity:
            raise _UnknownExecutionProfile()
        for position in windows:
            _formula_period(expr.args[position], params)
        return None
    if name in _POINTWISE_ARITY:
        if len(expr.args) != _POINTWISE_ARITY[name]:
            raise _UnknownExecutionProfile()
        return base
    if name in _FINITE_WINDOWS:
        arity = 3 if name in {"BOLL_UPPER", "BOLL_LOWER"} else 2
        if len(expr.args) != arity:
            raise _UnknownExecutionProfile()
        extra = _formula_period(expr.args[1], params) - 1
    elif name in {"REF", "ROC"}:
        if len(expr.args) != 2:
            raise _UnknownExecutionProfile()
        extra = _formula_period(expr.args[1], params, allow_zero=name == "REF")
    elif name in {"CROSS", "TR"}:
        if len(expr.args) != (2 if name == "CROSS" else 3):
            raise _UnknownExecutionProfile()
        extra = 1
    elif name in {"ATR", "WR", "CCI"}:
        if len(expr.args) != 4:
            raise _UnknownExecutionProfile()
        extra = _formula_period(expr.args[3], params) - (name != "ATR")
    else:
        raise _UnknownExecutionProfile()
    return None if base is None else base + extra


def _formula_period(
    expr: BoundExpr, params: dict[str, Any], *, allow_zero: bool = False,
) -> int:
    if expr.is_series or expr.kind not in {"literal", "param"}:
        raise _UnknownExecutionProfile()
    value = params.get(str(expr.value)) if expr.kind == "param" else expr.value
    if (isinstance(value, bool) or not isinstance(value, (int, float))
            or not math.isfinite(value) or not float(value).is_integer()
            or value < (0 if allow_zero else 1) or value > MAX_WINDOW):
        raise _UnknownExecutionProfile()
    return int(value)


def compile_screen_formula(
    source: str,
    manifest: ScreenFormulaManifest | dict[str, Any],
) -> CompiledScreenFormula:
    try:
        return compile_formula(_normalize_source(source), manifest)
    except FormulaCompileError as exc:
        raise ScreenFormulaError.from_formula_error(exc) from exc


def evaluate_screen_formula(
    compiled: CompiledScreenFormula,
    panels: dict[str, pd.DataFrame],
    params: dict[str, Any] | None = None,
) -> FormulaEvaluationResult:
    try:
        return evaluate_formula(compiled, panels, params)
    except FormulaEvaluationError as exc:
        raise ScreenFormulaError.from_formula_error(exc) from exc


def build_formula_engine(skill: dict[str, Any]) -> FormulaScreenEngine:
    manifest = _extract_manifest(skill)
    compiled = compile_screen_formula(
        str(skill.get("code") or skill.get("formula") or ""), manifest
    )
    slug = _extract_meta(skill, "slug")
    name = _extract_meta(skill, "name", fallback=slug)
    description = _extract_meta(skill, "description")
    default_params = {item.name: item.default for item in compiled.manifest.params}
    min_bars_value = max(compiled.manifest.min_bars, compiled.min_bars_required)
    data = manifest.get("data") if isinstance(manifest.get("data"), dict) else {}
    data_semantics = json.dumps(data, ensure_ascii=False, sort_keys=True)
    strategy_revision = (
        "screen-formula-v2:"
        + hashlib.sha256(
            f"{compiled.strategy_revision}\0{data_semantics}".encode("utf-8")
        ).hexdigest()
    )
    return FormulaScreenEngine(
        slug=slug,
        name=name,
        description=description,
        entry_timing=compiled.manifest.entry_timing,
        strategy_revision=strategy_revision,
        default_param_values=default_params,
        required_field_names=tuple(compiled.required_fields),
        min_bars_value=min_bars_value,
        compiled=compiled,
        dialect=_extract_dialect(skill),
        adjust=str(data.get("adjust") or "qfq"),
        default_universe=data.get("universe")
        if isinstance(data.get("universe"), dict)
        else None,
    )


def _extract_manifest(skill: dict[str, Any]) -> dict[str, Any]:
    manifest = skill.get("manifest") or skill.get("screen") or {}
    if not isinstance(manifest, dict):
        raise ScreenFormulaError("manifest 必须是对象")
    normalized = dict(manifest)
    schema_version = normalized.get("schema_version", 1)
    if schema_version not in {1, 2}:
        raise ScreenFormulaError("schema_version 目前只支持 1/2")
    output = normalized.get("output")
    if not isinstance(output, dict):
        output = {}
    signal = normalized.pop("signal", None)
    if signal and not output.get("signal"):
        output["signal"] = signal
    normalized["output"] = output
    normalized["schema_version"] = 1
    if normalized.get("params") is None:
        normalized["params"] = {}
    if normalized.get("factors") is None:
        normalized["factors"] = []
    return normalized


def _extract_meta(skill: dict[str, Any], key: str, *, fallback: str = "") -> str:
    nested = skill.get("skill") if isinstance(skill.get("skill"), dict) else {}
    value = skill.get(key)
    if value is None:
        value = nested.get(key) if isinstance(nested, dict) else None
    text = str(value or fallback).strip()
    if not text and key in {"slug", "name"}:
        raise ScreenFormulaError(f"缺少 {key}")
    return text


def _extract_dialect(skill: dict[str, Any]) -> str:
    dialect = str(skill.get("dialect") or "").strip().lower()
    if dialect in {"", "formula"}:
        return "loci"
    if dialect not in {"loci", "tdx", "ths"}:
        raise ScreenFormulaError(f"formula runtime 不支持 dialect={dialect!r}")
    return dialect


def _coerce_frame(
    value: pd.Series | pd.DataFrame,
    *,
    fallback_columns: tuple[str, ...],
) -> pd.DataFrame:
    if isinstance(value, pd.DataFrame):
        return value
    column = fallback_columns[0] if fallback_columns else "VALUE"
    return value.to_frame(name=column)


def _normalize_source(source: str) -> str:
    return str(source or "").rstrip() + "\n"
