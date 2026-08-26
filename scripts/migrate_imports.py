#!/usr/bin/env python
"""One-shot import path rewriter for DDD layout. Run from repo root."""
from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

# Longest-first replacements
REPLACEMENTS: list[tuple[str, str]] = [
    # strategies → strategy layers
    ("src.strategies.converter", "src.strategy.application.converter"),
    ("src.strategies.screener", "src.strategy.application.screener"),
    ("src.strategies.lugaowen", "src.strategy.application.backup.lugaowen-legacy"),
    ("src.strategies.qianlong", "src.strategy.application.qianlong"),
    ("src.strategies.audit", "src.strategy.application.audit"),
    ("src.strategies.base", "src.strategy.domain.base"),
    ("src.strategies.custom", "src.strategy.infrastructure.custom"),
    ("src.strategies", "src.strategy"),
    # market layers
    ("src.market.adapters", "src.market.infrastructure.adapters"),
    ("src.market.live_tape", "src.market.infrastructure.live_tape"),
    ("src.market.sentinel", "src.market.infrastructure.sentinel"),
    ("src.market.tencent", "src.market.infrastructure.tencent"),
    ("src.market.sources", "src.market.infrastructure.sources"),
    ("src.market.store", "src.market.infrastructure.store"),
    ("src.market.sync", "src.market.infrastructure.sync"),
    ("src.market.sina", "src.market.infrastructure.sina"),
    ("src.market.universe", "src.market.domain.universe"),
    # review
    ("src.review.portfolio_guard", "src.review.application.portfolio_guard"),
    ("src.review.attribution", "src.review.application.attribution"),
    ("src.review.capacity", "src.review.application.capacity"),
    ("src.review.outcomes", "src.review.application.outcomes"),
    ("src.review.overlap", "src.review.application.overlap"),
    ("src.review.alerts", "src.review.application.alerts"),
    ("src.review.equity", "src.review.application.equity"),
    ("src.review.replay", "src.review.application.replay"),
    ("src.review.decay", "src.review.application.decay"),
    ("src.review.drift", "src.review.application.drift"),
    # ops
    ("src.ops.skill_runtime", "src.ops.application.skill_runtime"),
    ("src.ops.skill_runs", "src.ops.application.skill_runs"),
    ("src.ops.skill_cli", "src.ops.application.skill_cli"),
    ("src.ops.scheduler", "src.ops.infrastructure.scheduler"),
    ("src.ops.skills", "src.ops.application.skills"),
    ("src.ops.notify", "src.ops.application.notify"),
    ("src.ops.store", "src.ops.infrastructure.store"),
    ("src.ops.jobs", "src.ops.application.jobs"),
    # ai
    ("src.ai.multi_agent", "src.ai.application.multi_agent"),
    ("src.ai.providers", "src.ai.infrastructure.providers"),
    ("src.ai.toolbus", "src.ai.application.toolbus"),
    ("src.ai.client", "src.ai.infrastructure.client"),
    ("src.ai.crypto", "src.ai.infrastructure.crypto"),
    ("src.ai.agent", "src.ai.application.agent"),
    # intel
    ("src.intel.builtin_market_mcp", "src.intel.infrastructure.builtin_market_mcp"),
    ("src.intel.mcp_config", "src.intel.infrastructure.mcp_config"),
    ("src.intel.registry", "src.intel.infrastructure.registry"),
    ("src.intel.mcp", "src.intel.infrastructure.mcp"),
    # formula
    ("src.formula.functions", "src.formula.domain.functions"),
    ("src.formula.chips", "src.formula.domain.chips"),
    ("src.formula.board", "src.formula.domain.board"),
    # backtest
    ("src.backtest.engine", "src.backtest.application.engine"),
    ("src.backtest.runner", "src.backtest.application.runner"),
    # shared / ledger / app / qianlong
    ("src.desktop_shortcut", "src.shared.desktop_shortcut"),
    ("src.paths", "src.shared.paths"),
    ("src.palace_api", "src.app.main"),
    ("src.palace", "src.ledger"),
    ("src.qianlong", "src.formula.domain.qianlong"),
    ("src.routers.quant", "src.app.legacy.quant_router"),
    ("src.routers", "src.app.legacy"),
]

SKIP_DIRS = {".venv", ".git", "__pycache__", "node_modules", ".pytest_cache", ".codegraph"}


def rewrite_text(text: str) -> str:
    for old, new in REPLACEMENTS:
        text = text.replace(old, new)
    return text


def main() -> None:
    changed = 0
    for path in ROOT.rglob("*"):
        if not path.is_file():
            continue
        if any(part in SKIP_DIRS for part in path.parts):
            continue
        if path.suffix not in {".py", ".md", ".txt", ".ps1", ".spec", ".vue", ".ts"}:
            continue
        if path.name == "migrate_imports.py":
            continue
        original = path.read_text(encoding="utf-8")
        updated = rewrite_text(original)
        if updated != original:
            path.write_text(updated, encoding="utf-8")
            changed += 1
            print(f"updated {path.relative_to(ROOT)}")
    print(f"done, {changed} files")


if __name__ == "__main__":
    main()
