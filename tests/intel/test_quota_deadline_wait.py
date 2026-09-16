"""The actual quota wait loop honors the request's remaining transport budget."""
from types import SimpleNamespace

import pytest

from src.intel.infrastructure import quota, mcp_deadline


def test_wait_stops_at_deadline_without_reserving_or_charging(monkeypatch):
    clock = [100.0]
    slept = []
    def sleep(seconds):
        slept.append(seconds)
        clock[0] += seconds
    timer = SimpleNamespace(monotonic=lambda: clock[0], sleep=sleep)
    monkeypatch.setattr(quota, "time", timer)
    monkeypatch.setattr(mcp_deadline, "time", timer)
    monkeypatch.setattr(quota, "quota_limits", lambda: quota.McpQuotaLimits(5000, 3000, 2000, 1))
    monkeypatch.setattr(quota, "trade_date_today", lambda: "2026-09-15")
    monkeypatch.setattr(quota, "_tenant", lambda: "deadline_test")
    monkeypatch.setattr(quota, "_read_counts", lambda _: {"structured": 0, "skill": 0})
    monkeypatch.setattr(quota, "_INFLIGHT", {})
    monkeypatch.setattr(quota, "_MINUTE_WINDOW", {"deadline_test": [100.0]})
    with pytest.raises(TimeoutError):
        quota.acquire_quota("skill", deadline=100.25)
    assert clock[0] == 100.25
    assert slept and max(slept) <= 0.1
    assert quota._INFLIGHT == {}
    assert quota._MINUTE_WINDOW["deadline_test"] == [100.0]
