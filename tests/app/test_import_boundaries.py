"""组合根导入边界回归。"""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path


def test_market_router_imports_without_eagerly_building_app() -> None:
    result = subprocess.run(
        [
            sys.executable,
            "-c",
            "from src.market.api.router import build_market_router; print(build_market_router.__name__)",
        ],
        cwd=Path(__file__).resolve().parents[2],
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == "build_market_router"
