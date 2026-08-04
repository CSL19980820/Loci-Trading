from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
import math
from typing import Any, Mapping

import pandas as pd

COMPILER_VERSION = "loci-formula-p0-v1"
ENTRY_TIMINGS = ("open", "close", "next_open", "next_dip")
PARAM_KINDS = ("int", "float", "bool")


@dataclass(frozen=True)
class FormulaDiagnostic:
    code: str
    message: str
    severity: str = "error"
    line: int | None = None
    column: int | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "code": self.code,
            "message": self.message,
            "severity": self.severity,
            "line": self.line,
            "column": self.column,
        }


class FormulaError(RuntimeError):
    def __init__(self, message: str, diagnostics: tuple[FormulaDiagnostic, ...]) -> None:
        super().__init__(message)
        self.diagnostics = diagnostics


class FormulaCompileError(FormulaError):
    pass


class FormulaEvaluationError(FormulaError):
    pass


def _as_compile_error(code: str, message: str) -> FormulaCompileError:
    diagnostic = FormulaDiagnostic(code=code, message=message)
    return FormulaCompileError(message, (diagnostic,))


def _normalize_identifier(raw: str, *, role: str) -> str:
    text = str(raw or "").strip().upper()
    if not text:
        raise _as_compile_error("E_IDENTIFIER_EMPTY", f"{role} 不能为空")
    if len(text) > 64:
        raise _as_compile_error("E_IDENTIFIER_TOO_LONG", f"{role} {text!r} 超过 64 个字符")
    return text


def stable_sha256(payload: str) -> str:
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


@dataclass(frozen=True)
class ScreenFormulaParam:
    name: str
    kind: str
    default: int | float | bool
    min_value: int | float | bool | None = None
    max_value: int | float | bool | None = None
    label: str = ""

    @classmethod
    def from_mapping(cls, name: str, payload: Mapping[str, Any]) -> ScreenFormulaParam:
        normalized = _normalize_identifier(name, role="参数名")
        kind = str(payload.get("type", "")).strip().lower()
        if kind not in PARAM_KINDS:
            raise _as_compile_error("E_PARAM_KIND", f"参数 {normalized} 的 type 只支持 int/float/bool")
        default = cls._coerce_value(kind, payload.get("default"), normalized, "default")
        min_value = payload.get("min")
        max_value = payload.get("max")
        if kind in {"int", "float"}:
            if min_value is None or max_value is None:
                raise _as_compile_error("E_PARAM_RANGE", f"参数 {normalized} 必须声明有限的 min/max")
            min_value = cls._coerce_value(kind, min_value, normalized, "min")
            max_value = cls._coerce_value(kind, max_value, normalized, "max")
            if min_value > max_value:
                raise _as_compile_error("E_PARAM_RANGE", f"参数 {normalized} 的 min 不能大于 max")
            if default < min_value or default > max_value:
                raise _as_compile_error("E_PARAM_RANGE", f"参数 {normalized} 的 default 超出 min/max")
        label = str(payload.get("label", "") or "")
        return cls(
            name=normalized,
            kind=kind,
            default=default,
            min_value=min_value,
            max_value=max_value,
            label=label,
        )

    @staticmethod
    def _coerce_value(kind: str, value: Any, name: str, field: str) -> int | float | bool:
        if kind == "bool":
            if isinstance(value, bool):
                return value
            if value in (0, 1):
                return bool(value)
            raise _as_compile_error("E_PARAM_TYPE", f"参数 {name} 的 {field} 必须是 bool")
        if isinstance(value, bool):
            raise _as_compile_error("E_PARAM_TYPE", f"参数 {name} 的 {field} 不能是 bool")
        if isinstance(value, (int, float)) and not math.isfinite(value):
            raise _as_compile_error("E_PARAM_TYPE", f"参数 {name} 的 {field} 必须是有限数值")
        if kind == "int":
            if isinstance(value, int):
                return value
            if isinstance(value, float) and float(value).is_integer():
                return int(value)
            raise _as_compile_error("E_PARAM_TYPE", f"参数 {name} 的 {field} 必须是 int")
        if isinstance(value, (int, float)):
            return float(value)
        raise _as_compile_error("E_PARAM_TYPE", f"参数 {name} 的 {field} 必须是 float")

    def coerce_runtime(self, value: Any) -> int | float | bool:
        try:
            coerced = self._coerce_value(self.kind, value, self.name, "value")
        except FormulaCompileError as exc:
            raise FormulaEvaluationError(str(exc), exc.diagnostics) from exc
        if self.kind in {"int", "float"}:
            assert self.min_value is not None and self.max_value is not None
            if coerced < self.min_value or coerced > self.max_value:
                raise FormulaEvaluationError(
                    f"参数 {self.name} 超出范围",
                    (
                        FormulaDiagnostic(
                            code="E_PARAM_OUT_OF_RANGE",
                            message=(
                                f"参数 {self.name}={coerced!r} 超出范围 "
                                f"[{self.min_value}, {self.max_value}]"
                            ),
                        ),
                    ),
                )
        return coerced


@dataclass(frozen=True)
class ScreenFormulaManifest:
    schema_version: int
    entry_timing: str
    min_bars: int
    params: tuple[ScreenFormulaParam, ...]
    signal: str
    factors: tuple[str, ...]

    @classmethod
    def from_mapping(cls, payload: Mapping[str, Any]) -> ScreenFormulaManifest:
        schema_version = payload.get("schema_version", 1)
        if not isinstance(schema_version, int) or schema_version != 1:
            raise _as_compile_error("E_SCHEMA_VERSION", "schema_version 目前只支持 1")
        entry_timing = str(payload.get("entry_timing", "")).strip()
        if entry_timing not in ENTRY_TIMINGS:
            raise _as_compile_error(
                "E_ENTRY_TIMING", "entry_timing 只支持 open/close/next_open/next_dip"
            )
        min_bars = payload.get("min_bars", 0)
        if isinstance(min_bars, bool) or not isinstance(min_bars, int) or min_bars < 1:
            raise _as_compile_error("E_MIN_BARS", "min_bars 必须是正整数")

        raw_params = payload.get("params", {})
        if not isinstance(raw_params, Mapping):
            raise _as_compile_error("E_PARAMS", "params 必须是对象映射")
        params: list[ScreenFormulaParam] = []
        seen_params: set[str] = set()
        for name, spec in raw_params.items():
            if not isinstance(spec, Mapping):
                raise _as_compile_error("E_PARAMS", f"参数 {name!r} 的定义必须是对象")
            param = ScreenFormulaParam.from_mapping(str(name), spec)
            if param.name in seen_params:
                raise _as_compile_error("E_PARAM_DUPLICATE", f"参数 {param.name} 重复定义")
            seen_params.add(param.name)
            params.append(param)
        if len(params) > 32:
            raise _as_compile_error("E_PARAM_LIMIT", "P0 最多允许 32 个参数")

        output = payload.get("output", {})
        if not isinstance(output, Mapping):
            raise _as_compile_error("E_OUTPUT", "output 必须是对象")
        signal = _normalize_identifier(output.get("signal", ""), role="主信号")

        raw_factors = payload.get("factors", [])
        if raw_factors is None:
            raw_factors = []
        if not isinstance(raw_factors, list):
            raise _as_compile_error("E_FACTORS", "factors 必须是数组")
        factors: list[str] = []
        seen_factors: set[str] = set()
        for item in raw_factors:
            name = _normalize_identifier(item, role="因子名")
            if name in seen_factors:
                raise _as_compile_error("E_FACTORS", f"因子 {name} 重复声明")
            seen_factors.add(name)
            factors.append(name)
        if len(factors) > 32:
            raise _as_compile_error("E_FACTOR_LIMIT", "P0 最多允许 32 个因子")
        return cls(
            schema_version=schema_version,
            entry_timing=entry_timing,
            min_bars=min_bars,
            params=tuple(params),
            signal=signal,
            factors=tuple(factors),
        )

    @property
    def params_by_name(self) -> dict[str, ScreenFormulaParam]:
        return {item.name: item for item in self.params}

    def semantic_sha256(self) -> str:
        payload = {
            "schema_version": self.schema_version,
            "entry_timing": self.entry_timing,
            "min_bars": self.min_bars,
            "signal": self.signal,
            "factors": list(self.factors),
            "params": [
                {
                    "name": item.name,
                    "kind": item.kind,
                    "default": item.default,
                    "min": item.min_value,
                    "max": item.max_value,
                }
                for item in self.params
            ],
        }
        return stable_sha256(json.dumps(payload, ensure_ascii=False, sort_keys=True))


@dataclass(frozen=True)
class CompiledScreenFormula:
    compiler_version: str
    manifest: ScreenFormulaManifest
    source: str
    source_sha256: str
    manifest_sha256: str
    strategy_revision: str
    required_fields: tuple[str, ...]
    min_bars_required: int
    signal_name: str
    factor_names: tuple[str, ...]
    program: object
    diagnostics: tuple[FormulaDiagnostic, ...] = ()
    #: 递推、累计和位置函数从截断窗口开始会得到错误的初始状态。
    requires_full_history: bool = False


@dataclass(frozen=True)
class FormulaEvaluationResult:
    signals: pd.Series | pd.DataFrame
    factors: dict[str, pd.Series | pd.DataFrame]
    params: dict[str, int | float | bool]
    diagnostics: tuple[FormulaDiagnostic, ...] = ()
