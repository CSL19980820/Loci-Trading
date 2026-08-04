"""限界上下文 API 的导入边界。"""
from __future__ import annotations

import ast
from pathlib import Path


def test_market_api_does_not_import_infrastructure_directly() -> None:
    api_root = Path(__file__).parents[2] / "src" / "market" / "api"
    violations: list[str] = []

    for path in sorted(api_root.glob("*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree):
            module = ""
            if isinstance(node, ast.Import):
                module = ", ".join(alias.name for alias in node.names)
            elif isinstance(node, ast.ImportFrom):
                module = node.module or ""
            if module.startswith("src.market.infrastructure"):
                violations.append(f"{path.name}:{node.lineno}: {module}")

    assert violations == [], "market API must depend on application, not infrastructure:\n" + "\n".join(violations)
