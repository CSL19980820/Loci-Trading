"""将已编译的公式 IR 转为前台可读的确定性说明。"""
from __future__ import annotations

from typing import Any

from src.formula.domain.screen_formula_catalog import FORMULA_FUNCTIONS
from src.formula.domain.screen_formula_types import CompiledScreenFormula

_FIELD_LABELS = {
    "OPEN": "开盘价", "HIGH": "最高价", "LOW": "最低价", "CLOSE": "收盘价",
    "VOL": "成交量", "AMOUNT": "成交额", "HSL": "换手率",
}
_FIELD_NAMES = {
    "OPEN": "open", "HIGH": "high", "LOW": "low", "CLOSE": "close",
    "VOL": "volume", "AMOUNT": "amount", "HSL": "turnover",
}
_TIMING_TEXT = {
    "open": "当日开盘前按可用数据判定，于开盘成交",
    "close": "当日尾盘按可用数据判定，于收盘成交",
    "next_open": "收盘后生成信号，于下一交易日开盘成交",
    "next_dip": "收盘后生成信号，于下一交易日按预挂价触价低吸",
}


def build_formula_explanation(
    compiled: CompiledScreenFormula,
    manifest: dict[str, Any],
) -> dict[str, Any]:
    """只使用 compiler 的 Bound IR，不通过 LLM 推断公式逻辑。"""
    factors = set(compiled.factor_names)
    steps = []
    for index, statement in enumerate(compiled.program, start=1):
        fields = _fields_from_expr(statement.expr)
        functions = _functions_from_expr(statement.expr)
        expression = f"{statement.name}{':' if statement.kind == 'signal' else ':='}{_render_expr(statement.expr)}"
        if statement.kind == "signal":
            kind = "signal"
            title = f"主信号 {statement.name}"
            plain_text = f"满足该条件时，标的进入 {statement.name} 选股结果。"
        elif statement.name in factors:
            kind = "factor"
            title = f"因子 {statement.name}"
            plain_text = f"计算 {statement.name}，用于展示该标的为什么被选中。"
        else:
            kind = "intermediate"
            title = f"中间计算 {statement.name}"
            plain_text = f"计算 {statement.name}，供后续条件引用。"
        if fields:
            plain_text += " 使用" + "、".join(_FIELD_LABELS.get(name, name) for name in _upper_fields(statement.expr)) + "。"
        steps.append(
            {
                "id": f"compiler-{index}-{statement.name.lower()}",
                "title": title,
                "kind": kind,
                "expression": expression,
                "plain_text": plain_text,
                "line": statement.line,
                "fields": fields,
                "functions": functions,
            }
        )
    return {
        "mode": "compiler",
        "summary": (
            f"公式共 {len(steps)} 步，主信号为 {compiled.signal_name}，"
            f"最少需要 {compiled.min_bars_required} 根日 K。"
        ),
        "steps": steps,
        "data_requirements": _data_requirements(compiled.required_fields, compiled.min_bars_required, manifest),
        "timing": _timing(compiled.manifest.entry_timing),
    }


def build_manifest_explanation(
    *,
    runtime: str,
    manifest: dict[str, Any],
    required_fields: tuple[str, ...] | list[str],
    min_bars: int,
) -> dict[str, Any]:
    """Python 运行时不解析源码语义，只展示用户保存的 manifest.logic。"""
    logic = manifest.get("logic") if isinstance(manifest.get("logic"), list) else []
    fields = [str(field) for field in required_fields]
    steps = [
        {
            "id": str(item.get("id") or f"manifest-{index}"),
            "title": str(item.get("title") or f"逻辑 {index}"),
            "kind": "signal" if index == len(logic) else "intermediate",
            "expression": str(item.get("expression") or ""),
            "plain_text": str(item.get("explanation") or ""),
            "line": None,
            "fields": fields,
            "functions": [],
        }
        for index, item in enumerate(logic, start=1)
        if isinstance(item, dict)
    ]
    return {
        "mode": "manifest",
        "summary": (
            f"{'Python' if runtime == 'python' else '公式'}运行时使用资料里保存的 {len(steps)} 条逻辑说明；"
            "源码语义不由编译器推断。"
        ),
        "steps": steps,
        "data_requirements": _data_requirements(fields, min_bars, manifest),
        "timing": _timing(str(manifest.get("entry_timing") or "next_open")),
    }


def _data_requirements(
    fields: tuple[str, ...] | list[str], min_bars: int, manifest: dict[str, Any]
) -> dict[str, Any]:
    data = manifest.get("data") if isinstance(manifest.get("data"), dict) else {}
    return {
        "fields": list(fields),
        "min_bars": int(min_bars),
        "adjust": str(data.get("adjust") or "qfq"),
        "universe": data.get("universe"),
    }


def _timing(entry_timing: str) -> dict[str, str]:
    return {
        "entry_timing": entry_timing,
        "plain_text": _TIMING_TEXT.get(entry_timing, entry_timing),
    }


def _render_expr(expr: Any) -> str:
    if expr.kind in {"literal", "param", "field", "binding"}:
        if expr.kind == "literal":
            return "TRUE" if expr.value is True else "FALSE" if expr.value is False else str(expr.value)
        return str(expr.value)
    if expr.kind == "unary":
        return f"{expr.value}({_render_expr(expr.args[0])})"
    if expr.kind == "binary":
        return f"({_render_expr(expr.args[0])} {expr.value} {_render_expr(expr.args[1])})"
    if expr.kind == "call":
        return f"{expr.value}(" + ", ".join(_render_expr(arg) for arg in expr.args) + ")"
    return "<unknown>"


def _upper_fields(expr: Any) -> list[str]:
    return sorted({str(field) for field, _lag in expr.field_lags})


def _fields_from_expr(expr: Any) -> list[str]:
    return [_FIELD_NAMES.get(field, field.lower()) for field in _upper_fields(expr)]


def _functions_from_expr(expr: Any) -> list[str]:
    found: list[str] = []

    def visit(node: Any) -> None:
        if node.kind == "call":
            name = str(node.value)
            if name in FORMULA_FUNCTIONS and name not in found:
                found.append(name)
        for child in node.args:
            visit(child)

    visit(expr)
    return found
