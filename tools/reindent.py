"""把「缩进被写歪了」的 Python 源码重排成合法 4 空格缩进。

为什么需要它：本仓由 AI Agent 大批量生成 Python 文件，模型偶发漏写/多写前导
空格，产出 IndentationError。人工逐行修比整体重排贵得多。

做法（栈式重排，等价于编辑器的 re-indent）：

1. 逐行扫描；三引号字符串内部与括号未闭合的续行区域原样保留，那里缩进无语义。
2. 维护「当前已打开的缩进层级」栈。上一条逻辑行以冒号结尾 → 下一行必须深一级。
3. 否则在栈里挑一个与原缩进最接近的层级，并弹掉比它更深的层级。
4. 顶层保护：函数/类体内的一行若被写成 0 缩进，但它不像一条新的顶层语句
   （def/class/@/import/from/if __name__/常量赋值），就不允许它回到 0 级。
   这是实测最常见也最致命的一种走样。
5. 用 level * 4 个空格重写该行前导空白。

只改前导空白，绝不改行内容；字符串字面量、注释、行尾一律原样保留。
重排后请务必 ast.parse 复核，本工具不保证还原作者本意，只保证语法自洽。

用法：python tools/reindent.py <file> [<file> ...]（原地重写）。
"""
from __future__ import annotations

import ast
import sys
from pathlib import Path

_OPEN = "([{"
_CLOSE = ")]}"
_TOPLEVEL_STARTS = (
    "def ",
    "async def ",
    "class ",
    "@",
    "import ",
    "from ",
    "if __name__",
    "#",
    '"""',
    "'''",
)


def _looks_toplevel(stripped, actual, blank_run):
    """该行是否像一条新的顶层语句（可以合法回到 0 缩进）。

    ``blank_run`` 是它前面连续空行数。PEP 8 要求顶层定义之间空两行，
    所以「原缩进为 0 且前面有 ≥2 个空行」是极强的顶层信号——
    少了这一条，``app = create_app()`` 这类小写顶层赋值会被吸进上一个函数体，
    语法完全合法，但模块级符号凭空消失（真踩过：uvicorn 报
    ``Attribute "app" not found in module``，而 compileall 与 import 都是绿的）。
    """
    if stripped.startswith(_TOPLEVEL_STARTS):
        return True
    if actual == 0 and blank_run >= 2:
        return True
    head = stripped.split("=")[0].strip()
    return bool(head) and head.replace("_", "").isupper()


def _scan_line(line, depth, quote):
    """返回 (括号深度, 未闭合的三引号, 该行是否以冒号结尾)。"""
    i = 0
    n = len(line)
    ends_colon = False
    while i < n:
        ch = line[i]
        if quote:
            if line.startswith(quote, i):
                i += len(quote)
                quote = ""
            else:
                i += 1
            continue
        if ch == "#":
            break
        if line.startswith('"""', i) or line.startswith("'''", i):
            quote = line[i : i + 3]
            i += 3
            continue
        if ch == '"' or ch == "'":
            j = i + 1
            while j < n:
                if line[j] == "\\":
                    j += 2
                    continue
                if line[j] == ch:
                    break
                j += 1
            i = j + 1
            continue
        if ch in _OPEN:
            depth += 1
        elif ch in _CLOSE:
            depth = max(0, depth - 1)
        i += 1
    if not quote and depth == 0:
        code = line.split("#")[0].rstrip()
        ends_colon = code.endswith(":")
    return depth, quote, ends_colon


def reindent(source):
    """返回缩进重排后的源码文本。"""
    out = []
    stack = [0]
    depth = 0
    quote = ""
    expect_deeper = False
    blank_run = 0
    for raw in source.splitlines():
        stripped = raw.strip()
        continuation = depth > 0 or bool(quote)
        if continuation or not stripped:
            out.append(raw)
            depth, quote, ends_colon = _scan_line(raw, depth, quote)
            # 多行 `if (...):` 的冒号落在续行末尾。不在这里更新 expect_deeper，
            # 下一行就会被判成同级，整个块体被拉平（真踩过：paths.py 的
            # _configured_data_dir 被拍平成 `return default` 与 if 同级）。
            if stripped and depth == 0 and not quote:
                expect_deeper = ends_colon
            blank_run = 0 if stripped else blank_run + 1
            continue
        actual = len(raw) - len(raw.lstrip(" \t"))
        target = actual / 4.0
        if expect_deeper:
            level = stack[-1] + 1
            stack.append(level)
        else:
            choices = list(stack)
            if len(stack) > 1 and not _looks_toplevel(stripped, actual, blank_run):
                choices = [lv for lv in stack if lv > 0]
            level = min(choices, key=lambda lv: (abs(lv - target), -lv))
            while stack[-1] > level:
                stack.pop()
        out.append(" " * (4 * level) + stripped)
        depth, quote, ends_colon = _scan_line(raw, depth, quote)
        expect_deeper = ends_colon
        blank_run = 0
    tail = "\n" if source.endswith("\n") else ""
    return "\n".join(out) + tail


def main(argv):
    if not argv:
        print("usage: python tools/reindent.py <file> [<file> ...]")
        return 2
    changed = 0
    broken = 0
    for name in argv:
        path = Path(name)
        original = path.read_text(encoding="utf-8")
        fixed = reindent(original)
        if fixed != original:
            path.write_text(fixed, encoding="utf-8")
            changed += 1
            print("reindented " + str(path))
        try:
            ast.parse(fixed)
        except SyntaxError as exc:
            broken += 1
            print("STILL BROKEN " + str(path) + " line " + str(exc.lineno) + ": " + str(exc.msg))
    print(str(changed) + " changed, " + str(broken) + " still broken")
    return 1 if broken else 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
