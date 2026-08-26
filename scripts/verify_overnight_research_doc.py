"""Verify overnight research doc exists with required sections."""
from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
research = ROOT / "docs" / "research"
patterns = ("*overnight*", "*weipan*", "*tail-close*", "*尾盘*")
files: list[Path] = []
for pat in patterns:
    files.extend(research.glob(pat))
# Prefer the newest matching overnight distillation doc
files = sorted({f.resolve() for f in files if f.is_file()}, key=lambda p: p.stat().st_mtime, reverse=True)
assert files, f"no research file matching {patterns} under {research}"
target = None
for f in files:
    text = f.read_text(encoding="utf-8")
    if all(k in text for k in ("Sources", "候选", "凝练", "潜龙")):
        target = f
        break
assert target is not None, "no file contains required sections: Sources/候选/凝练/潜龙"
print(target.relative_to(ROOT))
