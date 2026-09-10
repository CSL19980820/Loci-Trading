from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import pandas as pd

from src.formula.domain.screen_formula_catalog import FORMULA_FUNCTIONS
from src.formula.domain.screen_formula_parser import BinaryExpr, CallExpr, Expr, LiteralExpr, NameExpr, Statement, UnaryExpr, parse_formula
from src.formula.domain.screen_formula_types import (
    COMPILER_VERSION,
    CompiledScreenFormula,
    FormulaCompileError,
    FormulaDiagnostic,
    FormulaEvaluationResult,
    ScreenFormulaManifest,
    stable_sha256,
)

FIELD_ALIASES = {
    "OPEN": "open",
    "HIGH": "high",
    "LOW": "low",
    "CLOSE": "close",
    "VOL": "volume",
    "AMOUNT": "amount",
    "HSL": "turnover",
}
FUNCTIONS = frozenset(FORMULA_FUNCTIONS)
MAX_FORMULA_BYTES = 64 * 1024
MAX_AST_NODES = 2000
MAX_AST_DEPTH = 64
MAX_IDENTIFIERS = 256
MAX_WINDOW = 1000
_FULL_HISTORY_FUNCTIONS = frozenset(
    {
        "BARSLAST",
        "BARSSINCE",
        "BARSCOUNT",
        "DMA",
        "EMA",
        "MACD",
        "MACD_DEA",
        "MACD_DIF",
        "OBV",
        "RSI",
        "SMA",
    }
)


@dataclass(frozen=True)
class BoundExpr:
    kind: str
    value_kind: str
    is_series: bool
    bars_needed: int
    field_lags: tuple[tuple[str, int], ...]
    line: int
    column: int
    value: Any = None
    args: tuple[BoundExpr, ...] = ()


@dataclass(frozen=True)
class BoundStatement:
    name: str
    kind: str
    expr: BoundExpr
    line: int
    column: int


def _compile_error(diagnostics: list[FormulaDiagnostic]) -> FormulaCompileError:
    message = diagnostics[0].message if diagnostics else "公式编译失败"
    return FormulaCompileError(message, tuple(diagnostics))
def _merge_lags(*groups: tuple[tuple[str, int], ...]) -> tuple[tuple[str, int], ...]:
    merged: dict[str, int] = {}
    for group in groups:
        for field, lag in group:
            merged[field] = lag if field not in merged else min(merged[field], lag)
    return tuple(sorted(merged.items()))
def _count_ast(expr: Expr, depth: int = 1) -> tuple[int, int]:
    if isinstance(expr, (LiteralExpr, NameExpr)):
        return 1, depth
    if isinstance(expr, UnaryExpr):
        nodes, max_depth = _count_ast(expr.operand, depth + 1)
        return nodes + 1, max_depth
    if isinstance(expr, BinaryExpr):
        left_nodes, left_depth = _count_ast(expr.left, depth + 1)
        right_nodes, right_depth = _count_ast(expr.right, depth + 1)
        return left_nodes + right_nodes + 1, max(left_depth, right_depth)
    if isinstance(expr, CallExpr):
        total = 1
        max_depth = depth
        for arg in expr.args:
            nodes, child_depth = _count_ast(arg, depth + 1)
            total += nodes
            max_depth = max(max_depth, child_depth)
        return total, max_depth
    raise AssertionError(f"unknown expr {type(expr)!r}")


def _requires_full_history(expr: Expr) -> bool:
    if isinstance(expr, CallExpr):
        return expr.name in _FULL_HISTORY_FUNCTIONS or any(
            _requires_full_history(arg) for arg in expr.args
        )
    if isinstance(expr, UnaryExpr):
        return _requires_full_history(expr.operand)
    if isinstance(expr, BinaryExpr):
        return _requires_full_history(expr.left) or _requires_full_history(expr.right)
    return False
def _expect(condition: bool, diagnostics: list[FormulaDiagnostic], code: str, message: str, *, line: int, column: int) -> None:
    if condition:
        return
    diagnostics.append(FormulaDiagnostic(code=code, message=message, line=line, column=column))
    raise _compile_error(diagnostics)
class Binder:
    def __init__(self, manifest: ScreenFormulaManifest, diagnostics: list[FormulaDiagnostic]) -> None:
        self.manifest = manifest
        self.diagnostics = diagnostics
        self.params = manifest.params_by_name
        self.bound: dict[str, BoundExpr] = {}
        self.identifiers: set[str] = set(self.params)

    def bind_program(self, statements: tuple[Statement, ...]) -> tuple[BoundStatement, ...]:
        signals = [item for item in statements if item.kind == "signal"]
        if len(signals) != 1:
            raise _compile_error(
                [
                    FormulaDiagnostic(
                        code="E_SIGNAL_COUNT",
                        message="公式必须且只能声明一个主信号语句",
                        line=signals[1].line if len(signals) > 1 else statements[0].line,
                        column=signals[1].column if len(signals) > 1 else statements[0].column,
                    )
                ]
            )
        signal_stmt = signals[0]
        if signal_stmt.name != self.manifest.signal:
            raise _compile_error(
                [
                    FormulaDiagnostic(
                        code="E_SIGNAL_NAME",
                        message=f"主信号必须命名为 {self.manifest.signal}，实际为 {signal_stmt.name}",
                        line=signal_stmt.line,
                        column=signal_stmt.column,
                    )
                ]
            )
        bound_statements: list[BoundStatement] = []
        for statement in statements:
            if statement.name in self.params:
                raise _compile_error(
                    [
                        FormulaDiagnostic(
                            code="E_PARAM_REDEFINED",
                            message=f"参数 {statement.name} 不能在公式内再次赋值",
                            line=statement.line,
                            column=statement.column,
                        )
                    ]
                )
            if statement.name in FIELD_ALIASES:
                raise _compile_error(
                    [
                        FormulaDiagnostic(
                            code="E_FIELD_REDEFINED",
                            message=f"行情字段 {statement.name} 不能在公式内再次赋值",
                            line=statement.line,
                            column=statement.column,
                        )
                    ]
                )
            if statement.name in self.bound:
                raise _compile_error(
                    [
                        FormulaDiagnostic(
                            code="E_DUPLICATE_BINDING",
                            message=f"标识符 {statement.name} 重复定义",
                            line=statement.line,
                            column=statement.column,
                        )
                    ]
                )
            self.identifiers.add(statement.name)
            if len(self.identifiers) > MAX_IDENTIFIERS:
                raise _compile_error(
                    [
                        FormulaDiagnostic(
                            code="E_IDENTIFIER_LIMIT",
                            message="P0 最多允许 256 个唯一标识符",
                            line=statement.line,
                            column=statement.column,
                        )
                    ]
                )
            expr = self.bind_expr(statement.expr)
            if statement.kind == "signal" and expr.value_kind != "bool":
                raise _compile_error(
                    [
                        FormulaDiagnostic(
                            code="E_SIGNAL_TYPE",
                            message="主信号必须是布尔表达式",
                            line=statement.line,
                            column=statement.column,
                        )
                    ]
                )
            self._audit_entry_timing(statement.name, expr)
            self.bound[statement.name] = expr
            bound_statements.append(BoundStatement(statement.name, statement.kind, expr, statement.line, statement.column))
        for factor in self.manifest.factors:
            if factor not in self.bound:
                raise _compile_error(
                    [FormulaDiagnostic(code="E_FACTOR_UNKNOWN", message=f"因子 {factor} 未定义")]
                )
        return tuple(bound_statements)

    def bind_expr(self, expr: Expr) -> BoundExpr:
        if isinstance(expr, LiteralExpr):
            value_kind = "bool" if isinstance(expr.value, bool) else "number"
            return BoundExpr("literal", value_kind, False, 0, (), expr.line, expr.column, expr.value)
        if isinstance(expr, NameExpr):
            if len(expr.name) > 64:
                raise _compile_error(
                    [FormulaDiagnostic(code="E_IDENTIFIER_TOO_LONG", message=f"标识符 {expr.name!r} 超过 64 个字符", line=expr.line, column=expr.column)]
                )
            if expr.name in FIELD_ALIASES:
                return BoundExpr("field", "number", True, 1, ((expr.name, 0),), expr.line, expr.column, expr.name)
            if expr.name in self.params:
                param = self.params[expr.name]
                value_kind = "bool" if param.kind == "bool" else "number"
                return BoundExpr("param", value_kind, False, 0, (), expr.line, expr.column, expr.name)
            if expr.name in self.bound:
                target = self.bound[expr.name]
                return BoundExpr("binding", target.value_kind, target.is_series, target.bars_needed, target.field_lags, expr.line, expr.column, expr.name)
            raise _compile_error(
                [FormulaDiagnostic(code="E_UNDEFINED_IDENTIFIER", message=f"未定义标识符 {expr.name}", line=expr.line, column=expr.column)]
            )
        if isinstance(expr, UnaryExpr):
            operand = self.bind_expr(expr.operand)
            if expr.op == "NOT":
                return BoundExpr("unary", "bool", operand.is_series, operand.bars_needed, operand.field_lags, expr.line, expr.column, expr.op, (operand,))
            _expect(operand.value_kind == "number", self.diagnostics, "E_UNARY_TYPE", "一元 +/- 只接受数值", line=expr.line, column=expr.column)
            if operand.kind == "literal":
                factor = -1 if expr.op == "-" else 1
                return BoundExpr("literal", "number", False, 0, (), expr.line, expr.column, factor * operand.value)
            return BoundExpr("unary", "number", operand.is_series, operand.bars_needed, operand.field_lags, expr.line, expr.column, expr.op, (operand,))
        if isinstance(expr, BinaryExpr):
            left = self.bind_expr(expr.left)
            right = self.bind_expr(expr.right)
            lags = _merge_lags(left.field_lags, right.field_lags)
            bars = max(left.bars_needed, right.bars_needed)
            if expr.op in {"AND", "OR"}:
                return BoundExpr("binary", "bool", left.is_series or right.is_series, bars, lags, expr.line, expr.column, expr.op, (left, right))
            if expr.op in {"+", "-", "*", "/"}:
                _expect(left.value_kind == right.value_kind == "number", self.diagnostics, "E_BINARY_TYPE", "算术运算只接受数值", line=expr.line, column=expr.column)
                return BoundExpr("binary", "number", left.is_series or right.is_series, bars, lags, expr.line, expr.column, expr.op, (left, right))
            if expr.op in {"=", "!=", "<>", ">", ">=", "<", "<="}:
                if expr.op in {">", ">=", "<", "<="}:
                    _expect(left.value_kind == right.value_kind == "number", self.diagnostics, "E_COMPARE_TYPE", "大小比较只接受数值", line=expr.line, column=expr.column)
                return BoundExpr("binary", "bool", left.is_series or right.is_series, bars, lags, expr.line, expr.column, expr.op, (left, right))
        if isinstance(expr, CallExpr):
            return self.bind_call(expr)
        raise AssertionError(f"unknown expr {type(expr)!r}")

    def bind_call(self, expr: CallExpr) -> BoundExpr:
        if expr.name not in FUNCTIONS:
            raise _compile_error(
                [FormulaDiagnostic(code="E_UNSUPPORTED_FUNCTION", message=f"不支持函数 {expr.name}", line=expr.line, column=expr.column)]
            )
        args = tuple(self.bind_expr(arg) for arg in expr.args)
        technical = self._bind_technical_call(expr, args)
        if technical is not None:
            return technical
        if expr.name == "REF":
            _expect(len(args) == 2, self.diagnostics, "E_ARGUMENT_COUNT", "REF 需要 2 个参数", line=expr.line, column=expr.column)
            minimum, maximum = self._window_range(args[1], allow_zero=True)
            _expect(minimum >= 0, self.diagnostics, "E_WINDOW_RANGE", "REF 不支持负偏移", line=expr.line, column=expr.column)
            lags = tuple((field, lag + minimum) for field, lag in args[0].field_lags)
            return BoundExpr("call", args[0].value_kind, args[0].is_series, args[0].bars_needed + maximum, lags, expr.line, expr.column, expr.name, args)
        if expr.name in {"MA", "EMA", "WMA", "SUM", "HHV", "LLV", "STD", "AVEDEV", "HHVBARS", "LLVBARS"}:
            _expect(len(args) == 2, self.diagnostics, "E_ARGUMENT_COUNT", f"{expr.name} 需要 2 个参数", line=expr.line, column=expr.column)
            _expect(args[0].value_kind == "number", self.diagnostics, "E_ARGUMENT_TYPE", f"{expr.name} 第 1 个参数必须是数值", line=expr.line, column=expr.column)
            _, maximum = self._window_range(args[1], allow_zero=False)
            return BoundExpr("call", "number", args[0].is_series, args[0].bars_needed + maximum - 1, args[0].field_lags, expr.line, expr.column, expr.name, args)
        if expr.name == "SMA":
            _expect(len(args) == 3, self.diagnostics, "E_ARGUMENT_COUNT", "SMA 需要 3 个参数", line=expr.line, column=expr.column)
            _expect(args[0].value_kind == args[2].value_kind == "number", self.diagnostics, "E_ARGUMENT_TYPE", "SMA 的第 1、3 个参数必须是数值", line=expr.line, column=expr.column)
            _expect(not args[2].is_series, self.diagnostics, "E_ARGUMENT_TYPE", "SMA 的第 3 个参数必须是标量常量或参数", line=expr.line, column=expr.column)
            _, maximum = self._window_range(args[1], allow_zero=False)
            return BoundExpr("call", "number", args[0].is_series, args[0].bars_needed + maximum - 1, args[0].field_lags, expr.line, expr.column, expr.name, args)
        if expr.name == "DMA":
            _expect(len(args) == 2 and args[0].value_kind == args[1].value_kind == "number", self.diagnostics, "E_ARGUMENT_TYPE", "DMA 需要两个数值参数", line=expr.line, column=expr.column)
            return BoundExpr("call", "number", args[0].is_series or args[1].is_series, max(args[0].bars_needed, args[1].bars_needed), _merge_lags(args[0].field_lags, args[1].field_lags), expr.line, expr.column, expr.name, args)
        if expr.name in {"COUNT", "EVERY", "EXIST", "FILTER"}:
            _expect(len(args) == 2, self.diagnostics, "E_ARGUMENT_COUNT", f"{expr.name} 需要 2 个参数", line=expr.line, column=expr.column)
            _, maximum = self._window_range(args[1], allow_zero=False)
            value_kind = "number" if expr.name == "COUNT" else "bool"
            return BoundExpr("call", value_kind, args[0].is_series, args[0].bars_needed + maximum - 1, args[0].field_lags, expr.line, expr.column, expr.name, args)
        if expr.name == "IF":
            _expect(len(args) == 3, self.diagnostics, "E_ARGUMENT_COUNT", "IF 需要 3 个参数", line=expr.line, column=expr.column)
            left_kind = args[1].value_kind
            _expect(left_kind == args[2].value_kind, self.diagnostics, "E_ARGUMENT_TYPE", "IF 的真值/假值分支类型必须一致", line=expr.line, column=expr.column)
            return BoundExpr("call", left_kind, any(arg.is_series for arg in args), max(arg.bars_needed for arg in args), _merge_lags(*(arg.field_lags for arg in args)), expr.line, expr.column, expr.name, args)
        if expr.name == "ABS":
            _expect(len(args) == 1 and args[0].value_kind == "number", self.diagnostics, "E_ARGUMENT_TYPE", "ABS 需要 1 个数值参数", line=expr.line, column=expr.column)
            return BoundExpr("call", "number", args[0].is_series, args[0].bars_needed, args[0].field_lags, expr.line, expr.column, expr.name, args)
        if expr.name in {"BARSLAST", "BARSSINCE"}:
            _expect(len(args) == 1, self.diagnostics, "E_ARGUMENT_COUNT", f"{expr.name} 需要 1 个参数", line=expr.line, column=expr.column)
            return BoundExpr("call", "number", args[0].is_series, args[0].bars_needed, args[0].field_lags, expr.line, expr.column, expr.name, args)
        if expr.name == "BARSCOUNT":
            _expect(len(args) == 1 and args[0].value_kind == "number", self.diagnostics, "E_ARGUMENT_TYPE", "BARSCOUNT 需要 1 个数值参数", line=expr.line, column=expr.column)
            return BoundExpr("call", "number", args[0].is_series, args[0].bars_needed, args[0].field_lags, expr.line, expr.column, expr.name, args)
        if expr.name in {"MAX", "MIN"}:
            _expect(len(args) == 2 and args[0].value_kind == args[1].value_kind == "number", self.diagnostics, "E_ARGUMENT_TYPE", f"{expr.name} 只接受数值参数", line=expr.line, column=expr.column)
            return BoundExpr("call", "number", any(arg.is_series for arg in args), max(arg.bars_needed for arg in args), _merge_lags(args[0].field_lags, args[1].field_lags), expr.line, expr.column, expr.name, args)
        if expr.name == "CROSS":
            _expect(len(args) == 2 and args[0].value_kind == args[1].value_kind == "number", self.diagnostics, "E_ARGUMENT_TYPE", "CROSS 需要两个数值参数", line=expr.line, column=expr.column)
            return BoundExpr("call", "bool", True, max(args[0].bars_needed, args[1].bars_needed) + 1, _merge_lags(args[0].field_lags, args[1].field_lags), expr.line, expr.column, expr.name, args)
        if expr.name == "ZTPRICE":
            _expect(len(args) == 2 and args[0].value_kind == args[1].value_kind == "number", self.diagnostics, "E_ARGUMENT_TYPE", "ZTPRICE 需要两个数值参数", line=expr.line, column=expr.column)
            _expect(not args[1].is_series, self.diagnostics, "E_ARGUMENT_TYPE", "ZTPRICE 的第 2 个参数必须是标量常量或参数", line=expr.line, column=expr.column)
            return BoundExpr("call", "number", args[0].is_series, args[0].bars_needed, args[0].field_lags, expr.line, expr.column, expr.name, args)
        raise AssertionError(f"unhandled function {expr.name}")

    def _bind_technical_call(self, expr: CallExpr, args: tuple[BoundExpr, ...]) -> BoundExpr | None:
        specs = {
            "TR": (3, (0, 1, 2), ()), "ATR": (4, (0, 1, 2), (3,)),
            "RSI": (2, (0,), (1,)), "ROC": (2, (0,), (1,)),
            "WR": (4, (0, 1, 2), (3,)), "CCI": (4, (0, 1, 2), (3,)),
            "OBV": (2, (0, 1), ()), "MACD_DIF": (3, (0,), (1, 2)),
            "MACD_DEA": (4, (0,), (1, 2, 3)), "MACD": (4, (0,), (1, 2, 3)),
            "BOLL_MID": (2, (0,), (1,)), "BOLL_UPPER": (3, (0,), (1,)),
            "BOLL_LOWER": (3, (0,), (1,)),
        }
        spec = specs.get(expr.name)
        if spec is None:
            return None
        arity, numeric, integer = spec
        _expect(len(args) == arity, self.diagnostics, "E_ARGUMENT_COUNT", f"{expr.name} 参数数量不正确", line=expr.line, column=expr.column)
        for position in numeric:
            _expect(args[position].value_kind == "number", self.diagnostics, "E_ARGUMENT_TYPE", f"{expr.name} 参数必须是数值", line=expr.line, column=expr.column)
        if expr.name in {"BOLL_UPPER", "BOLL_LOWER"}:
            _expect(args[2].value_kind == "number" and not args[2].is_series, self.diagnostics, "E_ARGUMENT_TYPE", f"{expr.name} 的倍数参数必须是标量数值", line=expr.line, column=expr.column)
        windows: list[int] = []
        for position in integer:
            _expect(not args[position].is_series, self.diagnostics, "E_ARGUMENT_TYPE", f"{expr.name} 的周期参数必须是标量整数", line=expr.line, column=expr.column)
            _, maximum = self._window_range(args[position], allow_zero=False)
            windows.append(maximum)
        base = max((arg.bars_needed for arg in args), default=0)
        if expr.name in {"TR", "ATR"}:
            bars = base + (windows[0] if windows else 1)
        elif expr.name == "RSI":
            bars = base + windows[0]
        elif expr.name == "ROC":
            bars = base + windows[0]
        elif expr.name in {"WR", "CCI", "BOLL_MID", "BOLL_UPPER", "BOLL_LOWER"}:
            bars = base + windows[0] - 1
        elif expr.name in {"MACD_DEA", "MACD"}:
            bars = base + max(windows[0], windows[1]) + windows[2] - 2
        else:
            bars = base + (max(windows) - 1 if windows else 0)
        return BoundExpr("call", "number", any(arg.is_series for arg in args), bars, _merge_lags(*(arg.field_lags for arg in args)), expr.line, expr.column, expr.name, args)

    def _window_range(self, expr: BoundExpr, *, allow_zero: bool) -> tuple[int, int]:
        if expr.kind == "literal" and expr.value_kind == "number" and float(expr.value).is_integer():
            value = int(expr.value)
            self._check_window_bounds(value, value, allow_zero, expr.line, expr.column)
            return value, value
        if expr.kind == "param":
            param = self.params[str(expr.value)]
            _expect(param.kind == "int", self.diagnostics, "E_WINDOW_KIND", f"窗口参数 {param.name} 必须是 int", line=expr.line, column=expr.column)
            assert isinstance(param.min_value, int) and isinstance(param.max_value, int)
            self._check_window_bounds(param.min_value, param.max_value, allow_zero, expr.line, expr.column)
            return param.min_value, param.max_value
        raise _compile_error(
            [FormulaDiagnostic(code="E_WINDOW_DYNAMIC", message="窗口/偏移参数必须是整数常量或受限 int 参数", line=expr.line, column=expr.column)]
        )

    def _check_window_bounds(self, minimum: int, maximum: int, allow_zero: bool, line: int, column: int) -> None:
        lower_ok = minimum >= 0 if allow_zero else minimum >= 1
        _expect(lower_ok, self.diagnostics, "E_WINDOW_RANGE", "窗口参数必须为正整数", line=line, column=column)
        _expect(maximum <= MAX_WINDOW, self.diagnostics, "E_WINDOW_LIMIT", f"窗口参数不能超过 {MAX_WINDOW}", line=line, column=column)

    def _audit_entry_timing(self, name: str, expr: BoundExpr) -> None:
        allowed = {
            "next_open": {"OPEN", "HIGH", "LOW", "CLOSE", "VOL", "AMOUNT", "HSL"},
            "next_dip": {"OPEN", "HIGH", "LOW", "CLOSE", "VOL", "AMOUNT", "HSL"},
            "close": {"OPEN", "CLOSE", "VOL", "AMOUNT", "HSL"},
            "open": {"OPEN"},
        }[self.manifest.entry_timing]
        for field, lag in expr.field_lags:
            if lag > 0 or field in allowed:
                continue
            raise _compile_error(
                [
                    FormulaDiagnostic(
                        code="E_ENTRY_TIMING_LOOKAHEAD",
                        message=f"{name} 在 entry_timing={self.manifest.entry_timing} 下不能直接引用当期 {field}",
                        line=expr.line,
                        column=expr.column,
                    )
                ]
            )


def compile_screen_formula(source: str, manifest: ScreenFormulaManifest | dict[str, Any]) -> CompiledScreenFormula:
    if isinstance(manifest, dict):
        manifest = ScreenFormulaManifest.from_mapping(manifest)
    if len(source.encode("utf-8")) > MAX_FORMULA_BYTES:
        raise FormulaCompileError("公式文件超过 64 KiB", (FormulaDiagnostic(code="E_FORMULA_SIZE", message="formula.tdx 不能超过 64 KiB"),))
    statements = parse_formula(source)
    node_count = 0
    max_depth = 0
    for statement in statements:
        count, depth = _count_ast(statement.expr)
        node_count += count + 1
        max_depth = max(max_depth, depth)
    if node_count > MAX_AST_NODES:
        raise FormulaCompileError("AST 节点数超限", (FormulaDiagnostic(code="E_AST_NODE_LIMIT", message=f"AST 节点数不能超过 {MAX_AST_NODES}"),))
    if max_depth > MAX_AST_DEPTH:
        raise FormulaCompileError("AST 深度超限", (FormulaDiagnostic(code="E_AST_DEPTH_LIMIT", message=f"AST 深度不能超过 {MAX_AST_DEPTH}"),))
    diagnostics: list[FormulaDiagnostic] = []
    binder = Binder(manifest, diagnostics)
    program = binder.bind_program(statements)
    required_fields = sorted({FIELD_ALIASES[field] for statement in program for field, _ in statement.expr.field_lags})
    if not required_fields:
        raise FormulaCompileError("公式未引用任何行情字段", (FormulaDiagnostic(code="E_REQUIRED_FIELDS", message="公式至少要引用一个行情字段"),))
    min_bars_required = max(statement.expr.bars_needed for statement in program)
    if min_bars_required > MAX_WINDOW:
        raise FormulaCompileError("最大回看窗口超限", (FormulaDiagnostic(code="E_WINDOW_LIMIT", message=f"最大回看窗口不能超过 {MAX_WINDOW}"),))
    if manifest.min_bars < min_bars_required:
        raise FormulaCompileError(
            "manifest min_bars 小于编译推导值",
            (
                FormulaDiagnostic(
                    code="E_MIN_BARS_DECLARED",
                    message=f"manifest min_bars={manifest.min_bars} 小于编译推导值 {min_bars_required}",
                ),
            ),
        )
    source_sha = stable_sha256(source)
    manifest_sha = manifest.semantic_sha256()
    strategy_revision = stable_sha256(f"{COMPILER_VERSION}:{source_sha}:{manifest_sha}")
    return CompiledScreenFormula(
        compiler_version=COMPILER_VERSION,
        manifest=manifest,
        source=source,
        source_sha256=source_sha,
        manifest_sha256=manifest_sha,
        strategy_revision=strategy_revision,
        required_fields=tuple(required_fields),
        min_bars_required=min_bars_required,
        signal_name=manifest.signal,
        factor_names=manifest.factors,
        program=program,
        requires_full_history=any(
            _requires_full_history(statement.expr) for statement in statements
        ),
    )


def evaluate_screen_formula(
    compiled: CompiledScreenFormula,
    panels: dict[str, pd.Series | pd.DataFrame],
    params: dict[str, Any] | None = None,
) -> FormulaEvaluationResult:
    from src.formula.domain.screen_formula_runtime import (
        evaluate_screen_formula as evaluate_runtime,
    )

    return evaluate_runtime(compiled, panels, params)
