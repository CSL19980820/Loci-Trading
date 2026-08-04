"""Verify AI assistant design docs exist and contain required sections."""
from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
BACKEND = ROOT / "docs" / "architecture" / "ai-assistant-backend-plan.md"
FRONTEND = ROOT / "docs" / "architecture" / "ai-assistant-frontend-design.md"


def main() -> None:
    assert BACKEND.is_file(), f"missing {BACKEND}"
    assert FRONTEND.is_file(), f"missing {FRONTEND}"
    bt = BACKEND.read_text(encoding="utf-8")
    ft = FRONTEND.read_text(encoding="utf-8")
    assert any(k in bt for k in ("API", "工具", "Agent")), "backend doc missing key sections"
    assert any(k in ft for k in ("悬浮球", "Elements", "历史")), "frontend doc missing key sections"
    print("ok")


if __name__ == "__main__":
    main()
