"""Representative production strategy and stopped trades on deterministic synthetic bars."""
from __future__ import annotations

import hashlib
from typing import Any

import numpy as np
import pandas as pd

from src.backtest import BacktestConfig, run_backtest
from src.strategy.application.audit import guard_strategy
from src.strategy.application.qianlong import QianlongCloseePickerV3
from tests.benchmarks.baseline_support import measure_case


def measure_strategy_scale() -> dict[str, dict[str, Any]]:
    rng = np.random.default_rng(42)
    dates = pd.bdate_range("2023-01-01", periods=370).strftime("%Y-%m-%d")
    codes = [str(600000 + i) for i in range(2000)]
    close = pd.DataFrame(
        10 * np.exp(np.cumsum(rng.normal(0, 0.02, (370, 2000)), axis=0)),
        index=dates, columns=codes,
    )
    panels = {
        "close": close, "open": close * 0.999, "high": close * 1.02,
        "low": close * 0.98, "volume": close * 100000,
        "turnover": close * 0.3, "__raw_close": close,
    }
    signals = pd.DataFrame(rng.random(close.shape) < 0.02, index=dates, columns=codes)
    engine = QianlongCloseePickerV3()

    def compute() -> dict[str, Any]:
        result = engine.compute(panels)
        digest = hashlib.sha256(result.signals.to_numpy().tobytes())
        if result.watch_signals is not None:
            digest.update(result.watch_signals.to_numpy().tobytes())
        return {"shape": list(close.shape), "signals_sha256": digest.hexdigest()}

    def audit() -> dict[str, Any]:
        return guard_strategy(engine, panels).to_dict()

    def stopped_backtest() -> dict[str, Any]:
        result = run_backtest(
            signals, panels, entry_timing="next_open",
            config=BacktestConfig(hold_days=3, stop_loss_pct=-6),
            strategy_slug="scale-stopped-trades",
        )
        return {"trades": len(result.trades), "metrics": result.metrics, "skipped": result.skipped}

    return {
        "strategy_compute_2000x370": measure_case("strategy_compute_2000x370", compute),
        "strategy_audit_2000x370": measure_case("strategy_audit_2000x370", audit),
        "backtest_stops_2000x370": measure_case("backtest_stops_2000x370", stopped_backtest),
    }
