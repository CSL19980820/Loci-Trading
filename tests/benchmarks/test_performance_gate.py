"""The gate must reject regressions even when workloads return successfully."""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from tests.benchmarks.performance_gate import assert_performance_budget


def _measurements() -> dict[str, dict[str, Any]]:
    budgets = json.loads(Path(__file__).with_name("performance_budgets.json").read_text())
    return {
        name: {
            "runs": 5, "warmup_error": None, "successful_runs": 5,
            "error_count": 0, "error_rate": 0.0, "errors": [],
            "p50_ms": 10.0, "p95_ms": 20.0, "peak_rss_bytes": 100_000_000,
            "result_sha256": "fixture", "result": {"trades": 1},
        }
        for name in budgets["p95_ms"]
    }


def test_accepts_complete_healthy_measurements() -> None:
    assert_performance_budget(_measurements())


@pytest.mark.parametrize("field,value", [
    ("p95_ms", 7_200_000), ("peak_rss_bytes", 100 * 1024**3),
    ("p95_ms", float("nan")), ("p95_ms", float("inf")),
    ("peak_rss_bytes", 0), ("runs", 1),
    ("warmup_error", {"type": "RuntimeError"}),
])
def test_rejects_invalid_or_over_budget_measurement(field: str, value: Any) -> None:
    measurements = _measurements()
    measurements["backtest_classic"][field] = value
    with pytest.raises(AssertionError):
        assert_performance_budget(measurements)


def test_cannot_pass_by_omitting_slow_case() -> None:
    measurements = _measurements()
    del measurements["candidate_pool_5000"]
    with pytest.raises(AssertionError, match="case set"):
        assert_performance_budget(measurements)


def test_rejects_fast_engine_result_drift() -> None:
    measurements = _measurements()
    measurements["backtest_fast"]["result"] = {"trades": 2}
    with pytest.raises(AssertionError, match="results differ"):
        assert_performance_budget(measurements)
