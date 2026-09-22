"""交易研究的确定性十进制计算器，不执行模型生成的Python代码。"""
from __future__ import annotations

import ast
from decimal import Decimal, InvalidOperation, localcontext
import operator
from typing import Any

_BINARY = {ast.Add: operator.add, ast.Sub: operator.sub, ast.Mult: operator.mul,
           ast.Div: operator.truediv, ast.Mod: operator.mod}


CALCULATE_TOOL = "guardian_calculate"


def calculation_schema(protocol: str) -> dict[str, Any]:
    """Shared deterministic tool, independent of live data/provider discovery."""
    from src.ai.application.tool_schema import tool_schema

    return tool_schema(protocol, CALCULATE_TOOL,
        "50位精度的十进制算术，支持加减乘除、括号、余数和整数幂；不执行Python程序。",
        {"type": "object", "properties": {"expression": {"type": "string", "minLength": 1, "maxLength": 8192}},
         "required": ["expression"], "additionalProperties": False})


def calculate(expression: str) -> dict[str, Any]:
    if not isinstance(expression, str) or not expression.strip() or len(expression) > 8192:
        raise ValueError("请提供1至8192字符的算式，可用括号、加减乘除、余数和整数幂")
    tree = ast.parse(expression, mode="eval")
    if sum(1 for _ in ast.walk(tree)) > 512:
        raise ValueError("算式过大，请拆成可核对的步骤")

    def visit(node: ast.AST) -> Decimal:
        if isinstance(node, ast.Expression):
            return visit(node.body)
        if isinstance(node, ast.Constant) and type(node.value) in (int, float):
            value = Decimal(ast.get_source_segment(expression, node).replace("_", ""))
        elif isinstance(node, ast.UnaryOp) and isinstance(node.op, (ast.UAdd, ast.USub)):
            value = visit(node.operand) * (-1 if isinstance(node.op, ast.USub) else 1)
        elif isinstance(node, ast.BinOp) and type(node.op) in _BINARY:
            value = _BINARY[type(node.op)](visit(node.left), visit(node.right))
        elif isinstance(node, ast.BinOp) and isinstance(node.op, ast.Pow):
            left, right = visit(node.left), visit(node.right)
            if right != right.to_integral_value() or abs(right) > 100:
                raise ValueError("幂指数须为-100至100的整数")
            value = left ** int(right)
        else:
            raise ValueError("仅接受数值算式；不支持变量、函数调用、属性访问或文件操作")
        if not value.is_finite() or abs(value.adjusted()) > 10000:
            raise ValueError("计算结果超出可核对的有限数值范围")
        return value

    try:
        with localcontext() as context:
            context.prec = 50
            result = visit(tree)
    except (ArithmeticError, InvalidOperation) as exc:
        raise ValueError(f"算式不可计算：{exc}") from exc
    return {"expression": expression, "decimal_result": str(result), "precision_digits": 50,
            "note": "纯算术结果；输入数字来源由研究证据确认，不代表收益预测。"}
