from __future__ import annotations

from typing import Any

import numpy as np
import pandas as pd

from src.formula.domain.screen_formula_evaluator import apply_formula_call
from src.formula.domain.screen_formula_compiler import BoundExpr, FIELD_ALIASES
from src.formula.domain.screen_formula_types import (
    CompiledScreenFormula,
    FormulaDiagnostic,
    FormulaEvaluationError,
    FormulaEvaluationResult,
    ScreenFormulaManifest,
)


def _eval_error(diagnostics: list[FormulaDiagnostic]) -> FormulaEvaluationError:
    message = diagnostics[0].message if diagnostics else "公式求值失败"
    return FormulaEvaluationError(message, tuple(diagnostics))


def _truthy(value: Any) -> Any:
    if isinstance(value, pd.DataFrame):
        if value.dtypes.eq(bool).all():
            return value.fillna(False).astype(bool)
        return value.fillna(0).ne(0)
    if isinstance(value, pd.Series):
        if value.dtype == bool:
            return value.fillna(False).astype(bool)
        return value.fillna(0).ne(0)
    if pd.isna(value):
        return False
    return bool(value)


def _ensure_like(
    reference: pd.Series | pd.DataFrame, value: Any
) -> pd.Series | pd.DataFrame:
    if isinstance(value, (pd.Series, pd.DataFrame)):
        return value
    if isinstance(reference, pd.DataFrame):
        data = np.full(
            reference.shape,
            value,
            dtype=object if isinstance(value, bool) else float,
        )
        return pd.DataFrame(data, index=reference.index, columns=reference.columns)
    data = np.full(
        reference.shape,
        value,
        dtype=object if isinstance(value, bool) else float,
    )
    return pd.Series(data, index=reference.index)


def _scan_shape(
    name: str,
    value: Any,
    reference: pd.Series | pd.DataFrame,
    diagnostics: list[FormulaDiagnostic],
) -> None:
    if not isinstance(value, (pd.Series, pd.DataFrame)):
        return
    if isinstance(reference, pd.DataFrame):
        ok = (
            isinstance(value, pd.DataFrame)
            and value.index.equals(reference.index)
            and value.columns.equals(reference.columns)
        )
    else:
        ok = isinstance(value, pd.Series) and value.index.equals(reference.index)
    if ok:
        return
    diagnostics.append(
        FormulaDiagnostic(code="E_RUNTIME_SHAPE", message=f"{name} 的结果形状与面板不一致")
    )
    raise _eval_error(diagnostics)


def _scan_non_finite(
    name: str, value: Any, diagnostics: list[FormulaDiagnostic]
) -> None:
    if isinstance(value, pd.DataFrame):
        numeric = value.select_dtypes(include=["number"])
        if not numeric.empty and np.isinf(numeric.to_numpy(dtype=float)).any():
            diagnostics.append(
                FormulaDiagnostic(
                    code="E_RUNTIME_NON_FINITE", message=f"{name} 计算产生了无穷值"
                )
            )
            raise _eval_error(diagnostics)
        return
    if isinstance(value, pd.Series) and pd.api.types.is_numeric_dtype(value):
        if np.isinf(value.to_numpy(dtype=float)).any():
            diagnostics.append(
                FormulaDiagnostic(
                    code="E_RUNTIME_NON_FINITE", message=f"{name} 计算产生了无穷值"
                )
            )
            raise _eval_error(diagnostics)
        return
    if isinstance(value, (int, float)) and np.isinf(value):
        diagnostics.append(
            FormulaDiagnostic(
                code="E_RUNTIME_NON_FINITE", message=f"{name} 计算产生了无穷值"
            )
        )
        raise _eval_error(diagnostics)


def _return_expr(
    expr: BoundExpr, value: Any, diagnostics: list[FormulaDiagnostic]
) -> Any:
    if expr.value_kind == "number":
        _scan_non_finite("表达式", value, diagnostics)
    return value


def _resolve_runtime_params(
    manifest: ScreenFormulaManifest, params: dict[str, Any] | None
) -> dict[str, int | float | bool]:
    resolved = {item.name: item.default for item in manifest.params}
    if not params:
        return resolved
    unknown = {str(name).upper() for name in params} - set(resolved)
    if unknown:
        raise FormulaEvaluationError(
            "存在未知参数",
            (FormulaDiagnostic(code="E_PARAM_UNKNOWN", message=f"未知参数：{sorted(unknown)}"),),
        )
    specs = manifest.params_by_name
    for raw_name, raw_value in params.items():
        name = str(raw_name).upper()
        resolved[name] = specs[name].coerce_runtime(raw_value)
    return resolved


def _load_reference(
    compiled: CompiledScreenFormula,
    panels: dict[str, pd.Series | pd.DataFrame],
) -> tuple[pd.Series | pd.DataFrame, dict[str, pd.Series | pd.DataFrame]]:
    loaded: dict[str, pd.Series | pd.DataFrame] = {}
    reference: pd.Series | pd.DataFrame | None = None
    for field in compiled.required_fields:
        if field not in panels:
            raise FormulaEvaluationError(
                f"缺少字段 {field}",
                (
                    FormulaDiagnostic(
                        code="E_PANEL_FIELD_MISSING", message=f"面板缺少字段 {field}"
                    ),
                ),
            )
        value = panels[field]
        if field == "turnover":
            value = value * 100.0
        if reference is None:
            reference = value
        else:
            mismatch = False
            if isinstance(reference, pd.DataFrame):
                mismatch = not (
                    isinstance(value, pd.DataFrame)
                    and value.index.equals(reference.index)
                    and value.columns.equals(reference.columns)
                )
            else:
                mismatch = not (
                    isinstance(value, pd.Series) and value.index.equals(reference.index)
                )
            if mismatch:
                raise FormulaEvaluationError(
                    "面板字段形状不一致",
                    (
                        FormulaDiagnostic(
                            code="E_PANEL_SHAPE_MISMATCH",
                            message=f"字段 {field} 的形状与其他字段不一致",
                        ),
                    ),
                )
        loaded[field] = value
    assert reference is not None
    return reference, loaded


def _eval_expr(
    expr: BoundExpr,
    env: dict[str, Any],
    params: dict[str, int | float | bool],
    fields: dict[str, pd.Series | pd.DataFrame],
    reference: pd.Series | pd.DataFrame,
    diagnostics: list[FormulaDiagnostic],
) -> Any:
    if expr.kind == "literal":
        return _return_expr(expr, expr.value, diagnostics)
    if expr.kind == "param":
        return _return_expr(expr, params[str(expr.value)], diagnostics)
    if expr.kind == "field":
        return _return_expr(expr, fields[FIELD_ALIASES[str(expr.value)]], diagnostics)
    if expr.kind == "binding":
        return _return_expr(expr, env[str(expr.value)], diagnostics)
    if expr.kind == "unary":
        operand = _eval_expr(
            expr.args[0], env, params, fields, reference, diagnostics
        )
        if expr.value == "NOT":
            return ~_truthy(_ensure_like(reference, operand))
        if expr.value == "+":
            return _return_expr(expr, operand, diagnostics)
        return _return_expr(expr, -operand, diagnostics)
    if expr.kind == "binary":
        left = _eval_expr(expr.args[0], env, params, fields, reference, diagnostics)
        right = _eval_expr(expr.args[1], env, params, fields, reference, diagnostics)
        if expr.value == "AND":
            return _truthy(_ensure_like(reference, left)) & _truthy(
                _ensure_like(reference, right)
            )
        if expr.value == "OR":
            return _truthy(_ensure_like(reference, left)) | _truthy(
                _ensure_like(reference, right)
            )
        if expr.value == "+":
            return _return_expr(expr, left + right, diagnostics)
        if expr.value == "-":
            return _return_expr(expr, left - right, diagnostics)
        if expr.value == "*":
            return _return_expr(expr, left * right, diagnostics)
        if expr.value == "/":
            with np.errstate(divide="ignore", invalid="ignore"):
                return _return_expr(expr, left / right, diagnostics)
        if expr.value == "=":
            return left == right
        if expr.value in {"!=", "<>"}:
            return left != right
        if expr.value == ">":
            return left > right
        if expr.value == ">=":
            return left >= right
        if expr.value == "<":
            return left < right
        if expr.value == "<=":
            return left <= right
    if expr.kind == "call":
        values = tuple(
            _eval_expr(arg, env, params, fields, reference, diagnostics)
            for arg in expr.args
        )
        try:
            value = apply_formula_call(str(expr.value), values, _truthy)
        except (ArithmeticError, TypeError, ValueError) as exc:
            diagnostics.append(
                FormulaDiagnostic(
                    code="E_RUNTIME_FUNCTION",
                    message=f"{expr.value} 参数或运行结果无效",
                    line=expr.line,
                    column=expr.column,
                )
            )
            raise _eval_error(diagnostics) from exc
        return _return_expr(expr, value, diagnostics)
    raise AssertionError(f"unknown bound expr {expr.kind}")


def evaluate_screen_formula(
    compiled: CompiledScreenFormula,
    panels: dict[str, pd.Series | pd.DataFrame],
    params: dict[str, Any] | None = None,
) -> FormulaEvaluationResult:
    resolved_params = _resolve_runtime_params(compiled.manifest, params)
    reference, fields = _load_reference(compiled, panels)
    diagnostics: list[FormulaDiagnostic] = []
    env: dict[str, Any] = {}
    signal_value: Any = None
    for statement in compiled.program:
        value = _eval_expr(
            statement.expr,
            env,
            resolved_params,
            fields,
            reference,
            diagnostics,
        )
        _scan_non_finite(statement.name, value, diagnostics)
        _scan_shape(statement.name, value, reference, diagnostics)
        env[statement.name] = value
        if statement.kind == "signal":
            signal_value = value
    assert signal_value is not None
    signal_frame = _ensure_like(reference, signal_value)
    signal_frame = _truthy(signal_frame).fillna(False).astype(bool)
    factors = {
        name: _ensure_like(reference, env[name]) for name in compiled.factor_names
    }
    for name, value in factors.items():
        _scan_shape(name, value, reference, diagnostics)
        _scan_non_finite(name, value, diagnostics)
    return FormulaEvaluationResult(
        signals=signal_frame,
        factors=factors,
        params=resolved_params,
    )
