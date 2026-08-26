"""Screen Skill Python runtime 适配。"""
from __future__ import annotations

from dataclasses import dataclass, field
import hashlib
import json
from pathlib import Path
import tempfile
import threading
from typing import Any

import pandas as pd

from src.formula import FormulaDiagnostic, FormulaEvaluationError, ScreenFormulaParam
from src.strategy.domain.base import ENTRY_TIMINGS, SignalResult

_PYTHON_RUNTIME_VERSION = "screen-python-v1"
_FIELD_ALIASES = {
    "open": "open",
    "high": "high",
    "low": "low",
    "close": "close",
    "vol": "volume",
    "volume": "volume",
    "amount": "amount",
    "hsl": "turnover",
    "turnover": "turnover",
    "outstanding_share": "outstanding_share",
}


from src.strategy.application.screen_python_load import (
    ScreenPythonError,
    _entrypoint_source_path,
    _load_module,
    _normalize_code,
    _python_source_fingerprints,
    _resolve_entrypoint,
    _stable_sha256,
)


@dataclass(slots=True)
class PythonScreenEngine:
    slug: str
    name: str
    description: str
    entry_timing: str
    strategy_revision: str
    default_param_values: dict[str, Any]
    param_specs: tuple[ScreenFormulaParam, ...]
    required_field_names: tuple[str, ...]
    min_bars_value: int
    code: str
    entrypoint: str = "strategy.py:compute"
    runtime: str = "python"
    dialect: str = "python"
    adjust: str = "qfq"
    default_universe: dict[str, Any] | None = None
    source_kind: str = "python"
    editable: bool = True
    install_path: str = ""
    package_files: dict[str, str] | None = None
    _callable: Any = field(default=None, init=False, repr=False)
    _tempdir: tempfile.TemporaryDirectory[str] | None = field(
        default=None, init=False, repr=False
    )
    _lock: threading.RLock = field(
        default_factory=threading.RLock, init=False, repr=False
    )

    def default_params(self) -> dict[str, Any]:
        return dict(self.default_param_values)

    def required_fields(self) -> tuple[str, ...]:
        return self.required_field_names

    def min_bars(self) -> int:
        return self.min_bars_value

    def validate(self) -> None:
        """导入模块并解析入口点，不执行选股函数。"""
        self._load_callable()

    def compute(
        self,
        panels: dict[str, pd.DataFrame],
        params: dict[str, Any] | None = None,
    ) -> SignalResult:
        resolved = _resolve_runtime_params(self.param_specs, params)
        package_root = self._package_root()
        source_path = _entrypoint_source_path(package_root, self.entrypoint)
        try:
            outcome = self._load_callable()(panels, resolved)
        except ScreenPythonError:
            raise
        except FormulaEvaluationError as exc:
            raise ScreenPythonError.from_eval_error(exc) from exc
        except Exception as exc:
            raise ScreenPythonError.from_runtime_failure(
                "E_PYTHON_EXEC",
                exc,
                entrypoint=self.entrypoint,
                package_root=package_root,
                source_path=source_path,
            ) from exc
        return _coerce_signal_result(outcome)

    def _load_callable(self):
        with self._lock:
            if self._callable is not None:
                return self._callable
            package_root = self._package_root()
            module_name, source_path, attr_path = _resolve_entrypoint(
                package_root, self.entrypoint, self.strategy_revision
            )
            module = _load_module(module_name, source_path, package_root)
            target = module
            for part in attr_path.split("."):
                if not hasattr(target, part):
                    raise ScreenPythonError.simple(
                        "E_PYTHON_ENTRYPOINT",
                        f"entrypoint 缺少可调用对象：{self.entrypoint}",
                    )
                target = getattr(target, part)
            if not callable(target):
                raise ScreenPythonError.simple(
                    "E_PYTHON_ENTRYPOINT",
                    f"entrypoint 不是可调用对象：{self.entrypoint}",
                )
            self._callable = target
            return target

    def _package_root(self) -> Path:
        if self.install_path:
            return Path(self.install_path)
        if self.package_files is None:
            raise ScreenPythonError.simple("E_PYTHON_PACKAGE", "缺少 Python 技能包文件")
        if self._tempdir is None:
            self._tempdir = tempfile.TemporaryDirectory(prefix="screen-python-")
            root = Path(self._tempdir.name)
            for relative, content in self.package_files.items():
                target = root / relative
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_text(content, encoding="utf-8")
        return Path(self._tempdir.name)

    def __del__(self) -> None:  # pragma: no cover - 进程退出期清理
        try:
            if self._tempdir is not None:
                self._tempdir.cleanup()
        except Exception:
            pass


def build_python_engine(skill: dict[str, Any]) -> PythonScreenEngine:
    manifest = _extract_manifest(skill)
    params = _load_params(manifest.get("params") or {})
    required_fields = _extract_fields(manifest)
    entrypoint = _extract_entrypoint(skill)
    code = _extract_code(skill)
    install_path = str(skill.get("install_path") or "")
    package_files = _extract_package_files(skill, code, entrypoint, install_path)
    data = manifest.get("data") if isinstance(manifest.get("data"), dict) else {}
    payload = {
        "runtime": "python",
        "dialect": "python",
        "entrypoint": entrypoint,
        "manifest": manifest,
        "code_sha256": _stable_sha256(_normalize_code(code)),
        "python_sources": _python_source_fingerprints(package_files, install_path),
    }
    strategy_revision = (
        f"{_PYTHON_RUNTIME_VERSION}:"
        f"{_stable_sha256(json.dumps(payload, ensure_ascii=False, sort_keys=True))}"
    )
    return PythonScreenEngine(
        slug=_extract_meta(skill, "slug"),
        name=_extract_meta(skill, "name", fallback=_extract_meta(skill, "slug")),
        description=_extract_meta(skill, "description"),
        entry_timing=str(manifest["entry_timing"]),
        strategy_revision=strategy_revision,
        default_param_values={item.name: item.default for item in params},
        param_specs=params,
        required_field_names=required_fields,
        min_bars_value=int(manifest["min_bars"]),
        code=code,
        entrypoint=entrypoint,
        adjust=str(data.get("adjust") or "qfq"),
        default_universe=data.get("universe")
        if isinstance(data.get("universe"), dict)
        else None,
        install_path=install_path,
        package_files=package_files,
    )


def _extract_manifest(skill: dict[str, Any]) -> dict[str, Any]:
    manifest = skill.get("manifest") or skill.get("screen") or {}
    if not isinstance(manifest, dict):
        raise ScreenPythonError.simple("E_MANIFEST", "manifest 必须是对象")
    normalized = dict(manifest)
    schema_version = normalized.get("schema_version", 1)
    if schema_version not in {1, 2}:
        raise ScreenPythonError.simple("E_SCHEMA_VERSION", "schema_version 目前只支持 1/2")
    entry_timing = str(normalized.get("entry_timing") or "").strip()
    if entry_timing not in ENTRY_TIMINGS:
        raise ScreenPythonError.simple(
            "E_ENTRY_TIMING", "entry_timing 只支持 open/close/next_open/next_dip"
        )
    min_bars = normalized.get("min_bars", 0)
    if isinstance(min_bars, bool) or not isinstance(min_bars, int) or min_bars < 1:
        raise ScreenPythonError.simple("E_MIN_BARS", "min_bars 必须是正整数")
    output = normalized.get("output")
    if not isinstance(output, dict):
        output = {}
    signal = normalized.pop("signal", None)
    if signal and not output.get("signal"):
        output["signal"] = signal
    output.setdefault("signal", "PICK")
    normalized["output"] = output
    normalized.setdefault("params", {})
    normalized.setdefault("factors", [])
    normalized.setdefault("logic", [])
    normalized.setdefault("references", [])
    normalized.setdefault("data", {})
    return normalized


def _load_params(raw_params: dict[str, Any]) -> tuple[ScreenFormulaParam, ...]:
    if not isinstance(raw_params, dict):
        raise ScreenPythonError.simple("E_PARAMS", "params 必须是对象映射")
    specs: list[ScreenFormulaParam] = []
    seen: set[str] = set()
    for raw_name, payload in raw_params.items():
        if not isinstance(payload, dict):
            raise ScreenPythonError.simple(
                "E_PARAMS", f"参数 {raw_name!r} 的定义必须是对象"
            )
        try:
            spec = ScreenFormulaParam.from_mapping(str(raw_name), payload)
        except Exception as exc:
            if hasattr(exc, "diagnostics"):
                raise ScreenPythonError(str(exc), getattr(exc, "diagnostics", ())) from exc
            raise
        if spec.name in seen:
            raise ScreenPythonError.simple(
                "E_PARAM_DUPLICATE", f"参数 {spec.name} 重复定义"
            )
        seen.add(spec.name)
        specs.append(spec)
    return tuple(specs)


def _extract_fields(manifest: dict[str, Any]) -> tuple[str, ...]:
    data = manifest.get("data") or {}
    if not isinstance(data, dict):
        raise ScreenPythonError.simple("E_DATA", "manifest.data 必须是对象")
    fields = data.get("fields") or []
    if not isinstance(fields, list):
        raise ScreenPythonError.simple("E_DATA_FIELDS", "manifest.data.fields 必须是数组")
    resolved: list[str] = []
    for raw in fields:
        key = str(raw or "").strip().lower()
        if not key:
            continue
        mapped = _FIELD_ALIASES.get(key)
        if not mapped:
            raise ScreenPythonError.simple(
                "E_DATA_FIELDS", f"不支持的字段：{raw!r}"
            )
        if mapped not in resolved:
            resolved.append(mapped)
    if not resolved:
        raise ScreenPythonError.simple(
            "E_DATA_FIELDS", "python runtime 必须声明 manifest.data.fields"
        )
    return tuple(resolved)


def _extract_entrypoint(skill: dict[str, Any]) -> str:
    entrypoint = str(skill.get("entrypoint") or "strategy.py:compute").strip()
    if ":" not in entrypoint:
        raise ScreenPythonError.simple(
            "E_PYTHON_ENTRYPOINT", "entrypoint 必须是 file.py:callable"
        )
    relative, callable_path = entrypoint.split(":", 1)
    if not relative.strip().endswith(".py"):
        raise ScreenPythonError.simple(
            "E_PYTHON_ENTRYPOINT", "entrypoint 文件必须是 .py"
        )
    if not callable_path.strip():
        raise ScreenPythonError.simple(
            "E_PYTHON_ENTRYPOINT", "entrypoint 缺少 callable 名称"
        )
    return entrypoint


def _extract_code(skill: dict[str, Any]) -> str:
    code = str(skill.get("code") or "").strip()
    if not code:
        code = str(skill.get("formula") or "").strip()
    if not code:
        raise ScreenPythonError.simple("E_PYTHON_CODE", "缺少 python code")
    return _normalize_code(code)


def _extract_meta(skill: dict[str, Any], key: str, *, fallback: str = "") -> str:
    nested = skill.get("skill") if isinstance(skill.get("skill"), dict) else {}
    value = skill.get(key)
    if value is None:
        value = nested.get(key) if isinstance(nested, dict) else None
    text = str(value or fallback).strip()
    if not text and key in {"slug", "name"}:
        raise ScreenPythonError.simple("E_META", f"缺少 {key}")
    return text


def _extract_package_files(
    skill: dict[str, Any],
    code: str,
    entrypoint: str,
    install_path: str,
) -> dict[str, str] | None:
    raw = skill.get("package_files")
    if isinstance(raw, dict):
        return {str(name): str(content) for name, content in raw.items()}
    if install_path:
        return None
    relative, _ = entrypoint.split(":", 1)
    return {relative.replace("\\", "/"): code}


def _resolve_runtime_params(
    specs: tuple[ScreenFormulaParam, ...],
    params: dict[str, Any] | None,
) -> dict[str, Any]:
    resolved = {item.name: item.default for item in specs}
    if not params:
        return resolved
    normalized = {str(name).upper(): value for name, value in params.items()}
    unknown = set(normalized) - set(resolved)
    if unknown:
        raise ScreenPythonError(
            "存在未知参数",
            (
                FormulaDiagnostic(
                    code="E_PARAM_UNKNOWN", message=f"未知参数：{sorted(unknown)}"
                ),
            ),
        )
    by_name = {item.name: item for item in specs}
    for name, value in normalized.items():
        try:
            resolved[name] = by_name[name].coerce_runtime(value)
        except FormulaEvaluationError as exc:
            raise ScreenPythonError.from_eval_error(exc) from exc
    return resolved


def _coerce_signal_result(value: Any) -> SignalResult:
    if isinstance(value, SignalResult):
        return value
    if not isinstance(value, dict):
        raise ScreenPythonError.simple(
            "E_PYTHON_RETURN", "compute 必须返回 SignalResult 或 dict"
        )
    signals = value.get("signals")
    factors = value.get("factors") or {}
    if not isinstance(factors, dict):
        raise ScreenPythonError.simple("E_PYTHON_RETURN", "factors 必须是对象映射")
    frame = _coerce_frame(signals, fallback_columns=("SIGNAL",), role="signals")
    factor_columns = tuple(frame.columns)
    normalized_factors = {
        str(name): _coerce_frame(panel, fallback_columns=factor_columns, role=str(name))
        for name, panel in factors.items()
    }
    return SignalResult(
        signals=frame.fillna(False).astype(bool), factors=normalized_factors
    )


def _coerce_frame(
    value: pd.Series | pd.DataFrame | None,
    *,
    fallback_columns: tuple[str, ...],
    role: str,
) -> pd.DataFrame:
    if isinstance(value, pd.DataFrame):
        return value
    if isinstance(value, pd.Series):
        column = fallback_columns[0] if fallback_columns else "VALUE"
        return value.to_frame(name=column)
    raise ScreenPythonError.simple(
        "E_PYTHON_RETURN", f"{role} 必须是 pandas Series/DataFrame"
    )
