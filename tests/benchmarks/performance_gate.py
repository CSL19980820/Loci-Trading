"""Validate complete measurements against reviewed, versioned resource ceilings."""
from __future__ import annotations

import json
import math
from pathlib import Path
from typing import Any


def assert_performance_budget(measurements: dict[str, dict[str, Any]]) -> None:
    budgets = json.loads(Path(__file__).with_name("performance_budgets.json").read_text())
    limits = budgets["p95_ms"]
    assert set(measurements) == set(limits), "performance case set changed; review budgets"
    for name, item in measurements.items():
        assert item["runs"] >= budgets["min_runs"], (name, "insufficient samples")
        assert item["warmup_error"] is None, (name, "warmup failed", item["warmup_error"])
        assert item["successful_runs"] == item["runs"], (name, "failed samples")
        assert item["error_count"] == 0 and item["error_rate"] == 0, (name, item["errors"])
        for key in ("p50_ms", "p95_ms", "peak_rss_bytes"):
            value = item[key]
            assert isinstance(value, (int, float)) and math.isfinite(value), (name, key, value)
            assert value > 0, (name, key, "missing or invalid measurement")
        assert item["p50_ms"] <= item["p95_ms"], (name, "invalid quantiles")
        assert item["p95_ms"] <= limits[name], (name, "p95_ms", item["p95_ms"], limits[name])
        # This is the process high-water mark, not a per-case allocation estimate.
        assert item["peak_rss_bytes"] <= budgets["process_peak_rss_bytes"], (
            name, "process_peak_rss_bytes", item["peak_rss_bytes"], budgets["process_peak_rss_bytes"]
        )
        assert item["result_sha256"], (name, "missing result fingerprint")

    assert measurements["backtest_classic"]["result"] == measurements["backtest_fast"]["result"], (
        "classic/fast results differ on the identical fixture"
    )
