"""Explicit performance baseline benchmark.

This module is intentionally named ``baseline_benchmark.py`` rather than
``test_*.py``.  Run it explicitly when a baseline artifact is needed:

    python -m pytest -q tests/benchmarks/baseline_benchmark.py
"""
from __future__ import annotations

import json
import os
from pathlib import Path
import threading
import time
from typing import Any

import pandas as pd
import pytest

from src.backtest import BacktestConfig, run_backtest
from src.backtest.application.fast_engine import run_backtest_fast
from src.ops import OpsStore
from src.ops.application.jobs.market_gate import market_heavy_slot
from src.research.application.profile import build_research_profile
from src.research.application.technical import build_kline_dimension

from tests.benchmarks.baseline_support import (
    BaselineWorkspace,
    artifact_payload,
    benchmark_panels,
    build_workspace,
    measure_case,
    seed_candidate_pool,
    synthetic_bars,
    synthetic_signals,
)
from tests.benchmarks.strategy_scale import measure_strategy_scale


def test_write_performance_baseline() -> None:
    """Measure production read/calculation paths and write a JSON artifact."""
    data_root = Path(os.environ["LOCI_DATA_DIR"]) / "performance-baseline"
    workspace = build_workspace(data_root)
    try:
        _, repeated_input_sha256 = synthetic_bars(workspace.codes, workspace.dates)
        assert repeated_input_sha256 == workspace.input_sha256
        panels = benchmark_panels(workspace, codes=workspace.codes[:64])
        close = panels["close"]
        signals = synthetic_signals(close.index, close.columns)
        benchmark_close = close.mean(axis=1)
        kline_frame = workspace.market.history(
            workspace.codes[0],
            start=workspace.dates[0],
            end=workspace.dates[-1],
            adjust="qfq",
        )

        measurements = {
            "market_panel_64x240": measure_case(
                "market_panel_64x240",
                lambda: _panel_result(benchmark_panels(workspace, codes=workspace.codes[:64])),
            ),
            "market_panel_256x240": measure_case(
                "market_panel_256x240",
                lambda: _panel_result(benchmark_panels(workspace)),
            ),
            "research_profile": measure_case(
                "research_profile",
                lambda: _research_profile_result(workspace),
            ),
            "backtest_classic": measure_case(
                "backtest_classic",
                lambda: _backtest_result(
                    run_backtest(
                        signals,
                        panels,
                        entry_timing="next_open",
                        config=BacktestConfig(
                            hold_days=3,
                            stop_loss_pct=None,
                            take_profit_pct=None,
                        ),
                        strategy_slug="synthetic-baseline",
                        benchmark_close=benchmark_close,
                    )
                ),
            ),
            "backtest_fast": measure_case(
                "backtest_fast",
                lambda: _backtest_result(
                    run_backtest_fast(
                        signals,
                        panels,
                        entry_timing="next_open",
                        config=BacktestConfig(
                            hold_days=3,
                            stop_loss_pct=None,
                            take_profit_pct=None,
                        ),
                        strategy_slug="synthetic-baseline",
                        benchmark_close=benchmark_close,
                    )
                ),
            ),
            "kline_dimension": measure_case(
                "kline_dimension",
                lambda: _kline_result(
                    build_kline_dimension(
                        kline_frame,
                        observed_at="2026-08-08T00:00:00+00:00",
                        market_revision="synthetic-baseline-v1",
                    )
                ),
            ),
            "candidate_pool_1000": measure_case(
                "candidate_pool_1000",
                lambda: _candidate_result(workspace, size=1000),
            ),
            "candidate_pool_5000": measure_case(
                "candidate_pool_5000",
                lambda: _candidate_result(workspace, size=5000),
            ),
            "market_slot_lock_wait": measure_case(
                "market_slot_lock_wait",
                lambda: _market_slot_lock_wait(),
            ),
            "job_claim_lock_wait": measure_case(
                "job_claim_lock_wait",
                lambda: _job_claim_lock_wait(workspace),
            ),
        }

        measurements.update(measure_strategy_scale())
        artifact = artifact_payload(workspace, measurements)
        _write_artifact(artifact)
        _assert_measurements(measurements)
    finally:
        workspace.close()


def _panel_result(panel_map: dict[str, pd.DataFrame]) -> dict[str, Any]:
    close = panel_map["close"]
    return {
        "fields": sorted(panel_map),
        "rows": int(close.shape[0]),
        "codes": int(close.shape[1]),
        "close_sum": round(float(close.to_numpy(dtype=float).sum()), 6),
    }


def _research_profile_result(workspace: BaselineWorkspace) -> dict[str, Any]:
    profile = build_research_profile(
        workspace.market,
        workspace.codes[0],
        budget="standard",
        as_of=workspace.dates[-1],
    )
    kline = next(item for item in profile.dimensions if item.key == "2_kline")
    return {
        "code": profile.code,
        "dimension_count": len(profile.dimensions),
        "kline_bars": int(kline.values.get("bars") or 0),
        "kline_quality": kline.quality,
        "market_revision": str(profile.market_snapshot.get("market_revision") or ""),
    }


def _backtest_result(result: Any) -> dict[str, Any]:
    return {
        "strategy": result.strategy_slug,
        "trades": len(result.trades),
        "skipped": dict(result.skipped),
        "metrics": dict(result.metrics),
    }


def _kline_result(dimension: Any) -> dict[str, Any]:
    return {
        "key": dimension.key,
        "quality": dimension.quality,
        "bars": int(dimension.values.get("bars") or 0),
        "ma200": dimension.values.get("ma200"),
        "rsi14": dimension.values.get("rsi14"),
        "recent_rows": len(dimension.values.get("recent") or []),
    }


def _candidate_result(workspace: BaselineWorkspace, *, size: int) -> dict[str, Any]:
    pool_id = f"baseline-{size}"
    rows = workspace.palace.candidates_payload(
        occurred_on="2026-08-08",
        include_backfill=True,
    )
    if not any(row["pool_id"] == pool_id for row in rows):
        seed_candidate_pool(
            workspace.palace,
            size=size,
            occurred_on="2026-08-08",
        )
    rows = workspace.palace.candidates_payload(
        occurred_on="2026-08-08",
        include_backfill=True,
    )
    pool_rows = [row for row in rows if row["pool_id"] == pool_id]
    return {
        "pool_id": pool_id,
        "rows": len(pool_rows),
        "score_sum": round(sum(float(row["score"] or 0) for row in pool_rows), 6),
    }


def _market_slot_lock_wait() -> dict[str, Any]:
    entered = threading.Event()
    failures: list[BaseException] = []
    result: dict[str, float] = {}

    def holder() -> None:
        try:
            with market_heavy_slot("sync", "baseline-holder"):
                entered.set()
                time.sleep(0.02)
        except BaseException as exc:  # pragma: no cover - reported by caller
            failures.append(exc)

    def waiter() -> None:
        try:
            if not entered.wait(timeout=1.0):
                raise TimeoutError("market lock holder did not start")
            started = time.perf_counter()
            with market_heavy_slot("screen", "baseline-waiter"):
                result["wait_ms"] = (time.perf_counter() - started) * 1000.0
        except BaseException as exc:  # pragma: no cover - reported by caller
            failures.append(exc)

    holder_thread = threading.Thread(target=holder, name="baseline-market-holder")
    waiter_thread = threading.Thread(target=waiter, name="baseline-market-waiter")
    holder_thread.start()
    if not entered.wait(timeout=1.0):
        raise TimeoutError("market lock holder did not start")
    waiter_thread.start()
    holder_thread.join(timeout=2.0)
    waiter_thread.join(timeout=2.0)
    if holder_thread.is_alive() or waiter_thread.is_alive():
        raise TimeoutError("market lock benchmark thread did not finish")
    if failures:
        raise RuntimeError(str(failures[0])) from failures[0]
    return {"wait_ms": round(result["wait_ms"], 3), "contended": True}


def _job_claim_lock_wait(workspace: BaselineWorkspace) -> dict[str, Any]:
    job_id = workspace.ops.create_job(
        name=f"baseline-lock-{time.monotonic_ns()}",
        kind="sync",
        config={"synthetic": True},
    )
    job = workspace.ops.get_job(job_id)
    if job is None:
        raise RuntimeError("benchmark job disappeared")

    entered = threading.Event()
    waiter_ready = threading.Event()
    failures: list[BaseException] = []
    result: dict[str, Any] = {}

    def hold_sqlite_write_lock() -> None:
        holder = OpsStore(workspace.ops.db_path)
        try:
            holder.conn.execute("BEGIN IMMEDIATE")
            entered.set()
            time.sleep(0.02)
        except BaseException as exc:  # pragma: no cover - reported by caller
            failures.append(exc)
        finally:
            if holder.conn.in_transaction:
                holder.conn.rollback()
            holder.close()

    def claim_waiting_run() -> None:
        waiter = OpsStore(workspace.ops.db_path)
        try:
            waiter_ready.set()
            if not entered.wait(timeout=1.0):
                raise TimeoutError("SQLite lock holder did not start")
            started = time.perf_counter()
            run_id, claimed = waiter.claim_run(job, trigger="benchmark")
            result.update(
                run_id=run_id,
                claimed=bool(claimed),
                wait_ms=round((time.perf_counter() - started) * 1000.0, 3),
            )
        except BaseException as exc:  # pragma: no cover - reported by caller
            failures.append(exc)
        finally:
            waiter.close()

    holder_thread = threading.Thread(
        target=hold_sqlite_write_lock,
        name="baseline-sqlite-holder",
    )
    waiter_thread = threading.Thread(
        target=claim_waiting_run,
        name="baseline-sqlite-waiter",
    )
    try:
        waiter_thread.start()
        if not waiter_ready.wait(timeout=1.0):
            raise TimeoutError("SQLite lock waiter did not initialize")
        holder_thread.start()
        if not entered.wait(timeout=1.0):
            raise TimeoutError("SQLite lock holder did not start")
        holder_thread.join(timeout=2.0)
        waiter_thread.join(timeout=2.0)
        if holder_thread.is_alive() or waiter_thread.is_alive():
            raise TimeoutError("SQLite lock benchmark thread did not finish")
        if failures:
            raise RuntimeError(str(failures[0])) from failures[0]
        if not result.get("claimed"):
            raise RuntimeError("SQLite lock benchmark did not claim a run")
        workspace.ops.finish_run(result["run_id"], status="success", duration_ms=0)
        return {
            "wait_ms": float(result["wait_ms"]),
            "claimed": bool(result["claimed"]),
        }
    finally:
        holder_thread.join(timeout=2.0)
        waiter_thread.join(timeout=2.0)


def _assert_measurements(measurements: dict[str, dict[str, Any]]) -> None:
    from tests.benchmarks.performance_gate import assert_performance_budget

    assert_performance_budget(measurements)


def _write_artifact(payload: dict[str, Any]) -> None:
    raw_path = os.environ.get(
        "LOCI_BASELINE_ARTIFACT",
        "output/benchmarks/performance-baseline.json",
    )
    path = Path(raw_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True, allow_nan=False)
        + "\n",
        encoding="utf-8",
    )


if __name__ == "__main__":
    pytest.main([__file__, "-q"])
