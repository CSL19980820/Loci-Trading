"""Verify PanWatch vs Loci deep-dive research doc structure."""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DOC = ROOT / "docs" / "research" / "2026-08-panwatch-vs-loci.md"

REQUIRED = (
    "轮次1",
    "轮次2",
    "轮次3",
    "轮次4",
    "轮次5",
    "建议动作",
)


def main() -> int:
    if not DOC.is_file():
        print(f"missing: {DOC}", file=sys.stderr)
        return 1
    text = DOC.read_text(encoding="utf-8")
    missing = [s for s in REQUIRED if s not in text]
    if missing:
        print(f"missing sections: {missing}", file=sys.stderr)
        return 1
    print(DOC.as_posix())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
