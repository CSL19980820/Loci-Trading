"""旧快速回测入口：共享权威成交实现，保留调用与配置兼容。"""
from __future__ import annotations

import os
from typing import Any

import pandas as pd

from src.backtest.application.engine import (
    BacktestConfig,
    BacktestResult,
    run_backtest,
)


def fast_backtest_enabled() -> bool:
    raw = (os.environ.get("LOCI_BACKTEST_FAST") or "").strip().lower()
    return raw in {"1", "true", "yes", "on"}


def run_backtest_fast(
    signals: pd.DataFrame,
    panels: dict[str, pd.DataFrame],
    *,
    entry_timing: str,
    entry_price_panel: pd.DataFrame | None = None,
    config: BacktestConfig | None = None,
    strategy_slug: str = "",
    benchmark_close: pd.Series | None = None,
) -> BacktestResult:
    """兼容旧参数扫描调用；成交规则只维护一份，结果回显真实引擎。"""
    cfg = config or BacktestConfig()

    def _classic(reason: str) -> BacktestResult:
        result = run_backtest(
            signals,
            panels,
            entry_timing=entry_timing,
            entry_price_panel=entry_price_panel,
            config=cfg,
            strategy_slug=strategy_slug,
            benchmark_close=benchmark_close,
        )
        result.config["fast"] = {
            **describe_fast_backend(),
            "engine": "classic",
            "fallback_reason": reason,
        }
        return result

    if entry_timing == "next_dip":
        return _classic("next_dip 需要盘中触价判断")
    if cfg.stop_loss_pct is not None or cfg.take_profit_pct is not None:
        return _classic("配置了止损/止盈细规则")
    return _classic("重复成交循环已合并到共享引擎")


def describe_fast_backend() -> dict[str, Any]:
    return {
        "enabled": fast_backtest_enabled(),
        "engine": "classic",
        "env": "LOCI_BACKTEST_FAST",
    }
