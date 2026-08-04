"""Verify screen-skill tech design doc exists with required sections."""
from __future__ import annotations

import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parents[1]
DOC = ROOT / "docs" / "architecture" / "screen-skill-tech-design.md"
REQUIRED = (
    "用户体验原则",
    "能力矩阵",
    "架构",
    "技能包",
    "数据选择",
    "可解释与来源契约",
    "Definition of Done",
)


def main() -> int:
    if not DOC.is_file():
        print(f"missing: {DOC}", file=sys.stderr)
        return 1
    text = DOC.read_text(encoding="utf-8")
    missing = [item for item in REQUIRED if item not in text]
    if missing:
        print(f"missing sections: {missing}", file=sys.stderr)
        return 1
    print(f"ok: {DOC}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
