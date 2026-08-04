"""可选加速回测旁路：numpy 向量化入场对齐。

权威路径仍是 ``engine.run_backtest``（含一字板/T+1/止损止盈细规则）。
本模块用于 ops Job 参数扫描：``LOCI_BACKTEST_FAST=1`` 时启用。

硬约束：
- ``entry_timing`` 只能来自策略引擎，不可由 Job 覆盖。
- 与经典引擎同一成本公式（``BacktestConfig.round_trip_cost_pct``）。
- 不写 palace；不发明信号。
- 有止损/止盈细规则时回退经典引擎（``run_backtest``）。
"""
from __future__ import annotations

import os
from dataclasses import asdict
from typing import Any

import numpy as np
import pandas as pd

from src.backtest.application.engine import (
    BacktestConfig,
    BacktestResult,
    Trade,
    _tradable_exit,
    compute_metrics,
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
    """加速路径；任一步失败回退经典 ``run_backtest``。

    有止损/止盈细规则时直接回退经典引擎——numpy 批量路径不实现盘中触价。
    """
    cfg = config or BacktestConfig()
    if entry_timing == "next_dip":
        return run_backtest(
            signals,
            panels,
            entry_timing=entry_timing,
            entry_price_panel=entry_price_panel,
            config=cfg,
            strategy_slug=strategy_slug,
            benchmark_close=benchmark_close,
        )
    if cfg.stop_loss_pct is not None or cfg.take_profit_pct is not None:
        return run_backtest(
            signals,
            panels,
            entry_timing=entry_timing,
            entry_price_panel=entry_price_panel,
            config=cfg,
            strategy_slug=strategy_slug,
            benchmark_close=benchmark_close,
        )
    try:
        return _run_numpy_batch(
            signals,
            panels,
            entry_timing=entry_timing,
            config=cfg,
            strategy_slug=strategy_slug,
            benchmark_close=benchmark_close,
        )
    except Exception:
        return run_backtest(
            signals,
            panels,
            entry_timing=entry_timing,
            config=cfg,
            strategy_slug=strategy_slug,
            benchmark_close=benchmark_close,
        )


def _entry_offset(entry_timing: str) -> tuple[int, bool]:
    if entry_timing == "next_open":
        return 1, False
    if entry_timing == "close":
        return 0, True
    return 0, False


def _run_numpy_batch(
    signals: pd.DataFrame,
    panels: dict[str, pd.DataFrame],
    *,
    entry_timing: str,
    config: BacktestConfig,
    strategy_slug: str,
    benchmark_close: pd.Series | None,
) -> BacktestResult:
    """无止损止盈细规则的快速路径：固定持有 hold_days + 成本。

    若配置了 stop/take，回退经典引擎以保证口径。
    """
    if config.stop_loss_pct is not None or config.take_profit_pct is not None:
        return run_backtest(
            signals,
            panels,
            entry_timing=entry_timing,
            config=config,
            strategy_slug=strategy_slug,
            benchmark_close=benchmark_close,
        )

    result = BacktestResult(strategy_slug=strategy_slug, config=asdict(config))
    if signals.empty:
        result.metrics = compute_metrics([])
        return result

    open_a = panels["open"].to_numpy(dtype=float)
    close_a = panels["close"].to_numpy(dtype=float)
    high_a = panels["high"].to_numpy(dtype=float)
    low_a = panels["low"].to_numpy(dtype=float)
    one_word = np.isclose(high_a, low_a) & np.isfinite(high_a)
    volume = panels.get("volume")
    volume_a = volume.to_numpy(dtype=float) if volume is not None else None
    dates = list(signals.index)
    codes = list(signals.columns)
    offset, at_close = _entry_offset(entry_timing)
    entry_px = close_a if at_close else open_a
    hold = max(1, int(config.hold_days))
    cost = config.round_trip_cost_pct()

    rows, cols = np.nonzero(signals.fillna(False).to_numpy(dtype=bool))
    trades: list[Trade] = []
    skipped: dict[str, int] = {}

    def skip(reason: str) -> None:
        skipped[reason] = skipped.get(reason, 0) + 1

    for row, col in zip(rows.tolist(), cols.tolist()):
        entry_idx = row + offset
        if entry_idx >= len(dates):
            skip("入场日超出数据范围")
            continue
        price = entry_px[entry_idx, col]
        if not np.isfinite(price) or price <= 0:
            skip("入场日无行情（停牌或缺数据）")
            continue
        if volume_a is not None and not volume_a[entry_idx, col] > 0:
            skip("入场日停牌")
            continue
        if one_word[entry_idx, col] and not config.allow_limit_up_entry:
            skip("入场日一字板买不进")
            continue
        last_index = len(dates) - 1
        planned_exit = entry_idx + hold
        if planned_exit > last_index:
            exit_idx = last_index
            exit_price = close_a[exit_idx, col]
            exit_reason = "data_end"
        else:
            exit_price, resolved = _tradable_exit(
                col,
                planned_exit,
                None,
                config,
                close_a,
                one_word,
                volume_a,
                last_index,
            )
            if resolved is None:
                skip("持有期内始终无法卖出")
                continue
            exit_idx = resolved
            exit_reason = "hold_expired"
        if not np.isfinite(exit_price) or exit_price <= 0:
            skip("持有期内始终无法卖出")
            continue
        window = slice(entry_idx, exit_idx + 1)
        highs = high_a[window, col]
        lows = low_a[window, col]
        mfe = (np.nanmax(highs) / price - 1) * 100 if highs.size else 0.0
        mae = (np.nanmin(lows) / price - 1) * 100 if lows.size else 0.0
        gross = (exit_price / price - 1) * 100
        net = gross - cost
        bench = None
        if benchmark_close is not None:
            try:
                b0 = float(benchmark_close.loc[dates[entry_idx]])
                b1 = float(benchmark_close.loc[dates[exit_idx]])
                if b0 > 0 and np.isfinite(b0) and np.isfinite(b1):
                    bench = (b1 / b0 - 1) * 100
            except Exception:
                bench = None
        trades.append(
            Trade(
                code=codes[col],
                signal_date=str(dates[row]),
                entry_date=str(dates[entry_idx]),
                entry_price=round(float(price), 4),
                exit_date=str(dates[exit_idx]),
                exit_price=round(float(exit_price), 4),
                hold_days=int(exit_idx - entry_idx),
                gross_return_pct=round(float(gross), 4),
                net_return_pct=round(float(net), 4),
                mae_pct=round(float(mae), 4),
                mfe_pct=round(float(mfe), 4),
                exit_reason=exit_reason,
                benchmark_return_pct=None if bench is None else round(float(bench), 4),
            )
        )

    result.trades = trades
    result.skipped = skipped
    result.metrics = compute_metrics(trades)
    result.config["engine"] = "numpy_fast"
    return result


def describe_fast_backend() -> dict[str, Any]:
    return {
        "enabled": fast_backtest_enabled(),
        "engine": "numpy_fast",
        "env": "LOCI_BACKTEST_FAST",
    }
