"""Audit keeps probe evidence without retaining previous factor matrices."""
from __future__ import annotations

import weakref
from typing import Any

import pandas as pd
import pytest

from src.strategy.application.audit import audit_truncation
from src.strategy.domain.base import SignalResult


@pytest.mark.parametrize("missing_probe", [False, True])
def test_previous_result_is_released_before_next_compute(missing_probe: bool) -> None:
    previous: list[weakref.ReferenceType[SignalResult]] = []
    dates = pd.date_range("2026-01-01", periods=6).strftime("%Y-%m-%d")
    close = pd.DataFrame({"600000": [10.0] * 6}, index=dates)

    class Engine:
        slug = "lifetime-test"
        entry_timing = "next_open"

        def min_bars(self) -> int:
            return 1

        def compute(
            self, panels: dict[str, pd.DataFrame], params: dict[str, Any] | None = None
        ) -> SignalResult:
            assert all(item() is None for item in previous)
            signals = panels["close"] > 0
            if previous and missing_probe:
                signals = signals.iloc[:-1]
            result = SignalResult(signals, {"factor": panels["close"].copy()}, ~signals)
            previous.append(weakref.ref(result))
            return result

    report = audit_truncation(Engine(), {"close": close})
    assert len(previous) == 3
    assert report.failed is missing_probe
    assert all(item() is None for item in previous)
