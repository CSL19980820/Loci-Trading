from __future__ import annotations

from dataclasses import dataclass

from src.formula.domain.screen_formula_types import FormulaCompileError, FormulaDiagnostic


@dataclass(frozen=True)
class Token:
    kind: str
    text: str
    line: int
    column: int


@dataclass(frozen=True)
class Expr:
    line: int
    column: int


@dataclass(frozen=True)
class LiteralExpr(Expr):
    value: int | float | bool


@dataclass(frozen=True)
class NameExpr(Expr):
    name: str


@dataclass(frozen=True)
class UnaryExpr(Expr):
    op: str
    operand: Expr


@dataclass(frozen=True)
class BinaryExpr(Expr):
    op: str
    left: Expr
    right: Expr


@dataclass(frozen=True)
class CallExpr(Expr):
    name: str
    args: tuple[Expr, ...]


@dataclass(frozen=True)
class Statement:
    name: str
    kind: str
    expr: Expr
    line: int
    column: int


KEYWORDS = {"AND", "OR", "NOT", "TRUE", "FALSE"}
OPERATORS = {
    ":=": "ASSIGN",
    ":": "SIGNAL",
    ";": "SEMICOLON",
    ",": "COMMA",
    "(": "LPAREN",
    ")": "RPAREN",
    "+": "PLUS",
    "-": "MINUS",
    "*": "STAR",
    "/": "SLASH",
    ">=": "GE",
    "<=": "LE",
    "!=": "NE",
    "<>": "NE",
    ">": "GT",
    "<": "LT",
    "=": "EQ",
}


def _raise(code: str, message: str, *, line: int | None = None, column: int | None = None) -> None:
    diagnostic = FormulaDiagnostic(code=code, message=message, line=line, column=column)
    raise FormulaCompileError(message, (diagnostic,))


def tokenize_formula(source: str) -> tuple[Token, ...]:
    tokens: list[Token] = []
    index = 0
    line = 1
    column = 1
    length = len(source)
    while index < length:
        char = source[index]
        if char in " \t\r":
            index += 1
            column += 1
            continue
        if char == "\n":
            index += 1
            line += 1
            column = 1
            continue
        if char == "{":
            start_line, start_column = line, column
            index += 1
            column += 1
            while index < length and source[index] != "}":
                if source[index] == "\n":
                    line += 1
                    column = 1
                    index += 1
                    continue
                index += 1
                column += 1
            if index >= length:
                _raise("E_COMMENT_UNTERMINATED", "注释缺少右花括号", line=start_line, column=start_column)
            index += 1
            column += 1
            continue
        pair = source[index : index + 2]
        if pair in OPERATORS:
            tokens.append(Token(OPERATORS[pair], pair, line, column))
            index += 2
            column += 2
            continue
        if char in OPERATORS:
            tokens.append(Token(OPERATORS[char], char, line, column))
            index += 1
            column += 1
            continue
        if char.isdigit() or (char == "." and index + 1 < length and source[index + 1].isdigit()):
            start = index
            start_column = column
            dots = 0
            while index < length and (source[index].isdigit() or source[index] == "."):
                if source[index] == ".":
                    dots += 1
                if dots > 1:
                    _raise("E_NUMBER", "数字字面量格式错误", line=line, column=start_column)
                index += 1
                column += 1
            text = source[start:index]
            tokens.append(Token("NUMBER", text, line, start_column))
            continue
        if char.isalpha() or char == "_":
            start = index
            start_column = column
            while index < length and (source[index].isalnum() or source[index] == "_"):
                index += 1
                column += 1
            text = source[start:index]
            upper = text.upper()
            tokens.append(Token(upper if upper in KEYWORDS else "IDENT", text, line, start_column))
            continue
        _raise("E_CHAR", f"不支持的字符 {char!r}", line=line, column=column)
    tokens.append(Token("EOF", "", line, column))
    return tuple(tokens)


class Parser:
    def __init__(self, tokens: tuple[Token, ...]) -> None:
        self.tokens = tokens
        self.index = 0

    @property
    def current(self) -> Token:
        return self.tokens[self.index]

    def consume(self, kind: str) -> Token:
        token = self.current
        if token.kind != kind:
            _raise(
                "E_TOKEN",
                f"期待 {kind}，实际是 {token.kind or token.text!r}",
                line=token.line,
                column=token.column,
            )
        self.index += 1
        return token

    def match(self, *kinds: str) -> Token | None:
        token = self.current
        if token.kind not in kinds:
            return None
        self.index += 1
        return token

    def parse(self) -> tuple[Statement, ...]:
        statements: list[Statement] = []
        while self.current.kind != "EOF":
            statements.append(self.parse_statement())
        if not statements:
            _raise("E_EMPTY_FORMULA", "公式不能为空", line=1, column=1)
        return tuple(statements)

    def parse_statement(self) -> Statement:
        name = self.consume("IDENT")
        operator = self.match("ASSIGN", "SIGNAL")
        if operator is None:
            _raise("E_STATEMENT", "语句必须使用 := 或 :", line=self.current.line, column=self.current.column)
        expr = self.parse_expression()
        self.consume("SEMICOLON")
        return Statement(
            name=name.text.upper(),
            kind="signal" if operator.kind == "SIGNAL" else "assign",
            expr=expr,
            line=name.line,
            column=name.column,
        )

    def parse_expression(self) -> Expr:
        return self.parse_or()

    def parse_or(self) -> Expr:
        expr = self.parse_and()
        while token := self.match("OR"):
            expr = BinaryExpr(token.line, token.column, "OR", expr, self.parse_and())
        return expr

    def parse_and(self) -> Expr:
        expr = self.parse_not()
        while token := self.match("AND"):
            expr = BinaryExpr(token.line, token.column, "AND", expr, self.parse_not())
        return expr

    def parse_not(self) -> Expr:
        token = self.match("NOT")
        if token is not None:
            return UnaryExpr(token.line, token.column, "NOT", self.parse_not())
        return self.parse_comparison()

    def parse_comparison(self) -> Expr:
        expr = self.parse_additive()
        while token := self.match("EQ", "NE", "GT", "GE", "LT", "LE"):
            expr = BinaryExpr(token.line, token.column, token.text.upper(), expr, self.parse_additive())
        return expr

    def parse_additive(self) -> Expr:
        expr = self.parse_multiplicative()
        while token := self.match("PLUS", "MINUS"):
            expr = BinaryExpr(token.line, token.column, token.text, expr, self.parse_multiplicative())
        return expr

    def parse_multiplicative(self) -> Expr:
        expr = self.parse_unary()
        while token := self.match("STAR", "SLASH"):
            expr = BinaryExpr(token.line, token.column, token.text, expr, self.parse_unary())
        return expr

    def parse_unary(self) -> Expr:
        token = self.match("PLUS", "MINUS")
        if token is not None:
            return UnaryExpr(token.line, token.column, token.text, self.parse_unary())
        return self.parse_primary()

    def parse_primary(self) -> Expr:
        token = self.current
        if self.match("NUMBER"):
            if "." in token.text:
                return LiteralExpr(token.line, token.column, float(token.text))
            return LiteralExpr(token.line, token.column, int(token.text))
        if self.match("TRUE"):
            return LiteralExpr(token.line, token.column, True)
        if self.match("FALSE"):
            return LiteralExpr(token.line, token.column, False)
        if self.match("IDENT"):
            if self.match("LPAREN"):
                args: list[Expr] = []
                if self.current.kind != "RPAREN":
                    while True:
                        args.append(self.parse_expression())
                        if self.match("COMMA") is None:
                            break
                self.consume("RPAREN")
                return CallExpr(token.line, token.column, token.text.upper(), tuple(args))
            return NameExpr(token.line, token.column, token.text.upper())
        if self.match("LPAREN"):
            expr = self.parse_expression()
            self.consume("RPAREN")
            return expr
        _raise("E_PRIMARY", f"无法解析的表达式起始 token {token.kind}", line=token.line, column=token.column)


def parse_formula(source: str) -> tuple[Statement, ...]:
    return Parser(tokenize_formula(source)).parse()
