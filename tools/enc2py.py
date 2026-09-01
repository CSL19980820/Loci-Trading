"""把「缩进编码源」展开成正常的 Python 源码。

为什么存在：AI Agent 大批量生成 Python 时，前导空格是最容易写错的一位。
把缩进从「空白字符」改成「行首一个字母」，走样就无从发生。

行首字符的含义：

- ``A``..``Z``：缩进层级 0..25，展开为 ``4 * level`` 个空格 + 该行剩余内容。
- ``|``：原样输出（去掉这个前缀）。docstring 正文、SQL DDL 等需要保留
  自有缩进的内容用它，避免被强行对齐到 4 的倍数。
- 空行：原样输出空行。

用法：``python tools/enc2py.py src.enc dst.py``（展开后自动 ast.parse 复核）。
"""
from __future__ import annotations

import ast
import sys
from pathlib import Path


def expand(encoded: str) -> str:
    """把编码文本展开为源码；行首字母决定缩进，``|`` 表示原样。"""
    out: list[str] = []
    for lineno, raw in enumerate(encoded.splitlines(), 1):
        if not raw:
            out.append("")
            continue
        head = raw[0]
        if head == "|":
            out.append(raw[1:])
            continue
        if "A" <= head <= "Z":
            out.append(" " * (4 * (ord(head) - 65)) + raw[1:])
            continue
        raise ValueError(f"第 {lineno} 行前缀非法：{raw[:20]!r}")
    return "\n".join(out) + "\n"


def main(argv: list[str]) -> int:
    if len(argv) != 2:
        print("usage: python tools/enc2py.py <src.enc> <dst.py>")
        return 2
    source = Path(argv[0]).read_text(encoding="utf-8")
    expanded = expand(source)
    try:
        ast.parse(expanded)
    except SyntaxError as exc:
        print(f"SYNTAX ERROR line {exc.lineno}: {exc.msg}")
        print((expanded.splitlines() or [""])[max(0, (exc.lineno or 1) - 1)])
        return 1
    dest = Path(argv[1])
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_text(expanded, encoding="utf-8")
    print(f"wrote {dest} ({len(expanded.splitlines())} lines)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
