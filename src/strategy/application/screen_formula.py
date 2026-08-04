"""Screen Skill 公式到 StrategyEngine 的薄适配。"""
from __future__ import annotations

from dataclasses import dataclass, field
import hashlib
import json
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
from src.strategy.domain.base import SignalResult, StrategyError


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

    def compute(
        self,
        panels: dict[str, pd.DataFrame],
        params: dict[str, Any] | None = None,
    ) -> SignalResult:
        result = evaluate_screen_formula(self.compiled, panels, params)
        signals = _coerce_frame(result.signals, fallback_columns=("SIGNAL",))
        factor_columns = tuple(signals.columns)
        factors = {
            name: _coerce_frame(panel, fallback_columns=factor_columns)
            for name, panel in result.factors.items()
        }
        return SignalResult(signals=signals.fillna(False).astype(bool), factors=factors)


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
