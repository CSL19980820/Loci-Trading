"""把行首点号占位还原成空格再编译校验。写入时 4 个点 = 4 空格缩进。"""
import py_compile
import re
import sys
from pathlib import Path

P = re.compile(r"^(\.+)(.*)$")

def convert(path):
    out = []
    n = 0
    for line in path.read_text(encoding="utf-8").split(chr(10)):
        m = P.match(line)
        if m and m.group(1):
            out.append(" " * len(m.group(1)) + m.group(2))
            n += 1
        else:
            out.append(line)
    path.write_text(chr(10).join(out), encoding="utf-8")
    return n


def main(argv):
    if not argv:
        print("usage: dedent_dots.py FILE...")
        return 2
    for name in argv:
        p = Path(name)
        n = convert(p)
        py_compile.compile(str(p), doraise=True)
        print(str(p) + ": " + str(n) + " lines dedented, compiles")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
