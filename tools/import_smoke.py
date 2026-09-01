"""导入冒烟：逐个 import `src/**` 的每个模块。

为什么不能只靠 `compileall`：`tools/reindent.py` 能修出**语法正确但语义错位**
的代码（实测：一整个 `with` 块掉出方法体落进类体，compileall 全绿而 import
当场炸）。这一关才是真门禁。
"""
from __future__ import annotations

import importlib
import pkgutil
import sys
from pathlib import Path

# 脚本在 tools/ 下，直接跑时仓库根不在 sys.path 上。
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

PACKAGES = (
    "src.identity",
    "src.community",
    "src.ops",
    "src.ai",
    "src.market",
    "src.app",
    "src.shared",
    "src.strategy",
    "src.ledger",
    "src.review",
    "src.intel",
    "src.backtest",
    "src.research",
    "src.formula",
    "cli",
)


def main() -> int:
    failures: list[tuple[str, str, str]] = []
    total = 0
    for package in PACKAGES:
        try:
            module = importlib.import_module(package)
        except Exception as exc:  # noqa: BLE001
            failures.append((package, type(exc).__name__, str(exc)[:120]))
            continue
        total += 1
        for info in pkgutil.walk_packages(module.__path__, package + "."):
            if ".__pycache__" in info.name:
                continue
            total += 1
            try:
                importlib.import_module(info.name)
            except Exception as exc:  # noqa: BLE001
                failures.append((info.name, type(exc).__name__, str(exc)[:120]))
    print(f"imported {total} modules; {len(failures)} failed")
    for name, kind, message in failures:
        print(f"  {name}: {kind}: {message}")
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
