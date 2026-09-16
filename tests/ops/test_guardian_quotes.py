"""Primary and fallback prices must pass the same execution quote contract."""
from __future__ import annotations

import asyncio
import copy
import threading
import time
from concurrent.futures import CancelledError
from datetime import datetime, timedelta
from types import SimpleNamespace
from unittest.mock import Mock
from zoneinfo import ZoneInfo

import pytest

from src.intel import McpError
from src.ops import JobCancelled, JobTimedOut
from src.ops.application import guardian_tools
from src.ops.application.guardian_quotes import quote_error, validated_quotes
from src.shared.tenancy import current_tenant, tenant_scope

NOW = datetime(2026, 9, 15, 10, tzinfo=ZoneInfo("Asia/Shanghai"))
CODE = "600001"


def quote(**changes):
    return {"code": CODE, "price": 10, "trade_date": NOW.date().isoformat(),
            "trade_time": "10:00:00", "source": "fallback", **changes}


def payload(**changes):
    return {"structured": {"stock": {"code": CODE},
                           "points": [{"time": NOW.isoformat(), "price": 10}], **changes}}


@pytest.fixture
def sources(monkeypatch):
    primary = Mock(return_value=payload())
    backup = Mock(return_value=SimpleNamespace(quotes={CODE: quote()}))
    monkeypatch.setattr(guardian_tools, "data_source", lambda: {"server": "wudao", "wudao": True})
    monkeypatch.setattr("src.intel.call_mcp_tool", primary)
    monkeypatch.setattr("src.market.application.live_cache.build_monitor_snapshot", backup)
    return primary, backup


@pytest.mark.parametrize("bad", [
    {"points": []}, {"points": [{"price": 10}]}, {"points": [{"time": NOW.isoformat()}]},
    {"points": [{"time": (NOW - timedelta(seconds=181)).isoformat(), "price": 10}]},
    {"points": [{"time": (NOW + timedelta(seconds=1)).isoformat(), "price": 10}]},
    {"stock": {"code": "600002"}}, {"stock": [CODE]}, {"points": [10]},
    *[{"points": [{"time": NOW.isoformat(), "price": price}]} for price in (True, 0, -1, float("nan"), float("inf"))],
])
def test_invalid_primary_uses_validated_fallback(sources, bad):
    primary, backup = sources
    primary.return_value = payload(**bad)
    result = guardian_tools.snapshot([CODE], now=NOW, include_minute=True, force_refresh=False)
    row = result.quotes[CODE]
    assert row["source"] == "fallback" and row["primary_error"]
    assert quote_error(CODE, row, NOW) is None
    backup.assert_called_once_with([CODE], include_minute=True, force_refresh=False)
    assert primary.call_args.kwargs["cache"] is False


@pytest.mark.parametrize("bad", [
    {}, {"price": 10}, quote(trade_time="09:56:59"), quote(trade_time="10:00:01"),
    quote(trade_date="2026-09-14"), quote(code="600002"), quote(error="source failed"),
    *[quote(price=price) for price in (True, None, 0, -1, float("nan"), float("inf"))],
])
def test_invalid_fallback_cannot_become_executable_price(sources, bad):
    primary, backup = sources
    primary.return_value = payload(points=[])
    backup.return_value = SimpleNamespace(quotes={CODE: bad})
    result = guardian_tools.snapshot([CODE], now=NOW)
    assert result.quotes[CODE]["error"] and result.quotes[CODE]["fallback_error"]
    assert validated_quotes(result.quotes, NOW) == {}


def test_fresh_primary_does_not_call_backup(sources):
    primary, backup = sources
    result = guardian_tools.snapshot([CODE, CODE], now=NOW)
    assert result.quotes[CODE]["source"] == "wudao"
    assert quote_error(CODE, result.quotes[CODE], NOW) is None
    primary.assert_called_once()
    backup.assert_not_called()


def test_only_failed_codes_are_retried_and_upstream_input_is_not_modified(sources):
    primary, backup = sources
    good, bad = payload(), payload(stock={"code": "600002"}, points=[])
    originals = copy.deepcopy([good, bad])
    primary.side_effect = lambda _name, args, **_kwargs: good if args["code"] == CODE else bad
    backup.return_value = SimpleNamespace(quotes={"600002": quote(code="600002")})
    result = guardian_tools.snapshot([CODE, "600002", CODE], now=NOW)
    assert result.quotes[CODE]["source"] == "wudao"
    assert result.quotes["600002"]["source"] == "fallback"
    assert backup.call_args.args[0] == ["600002"]
    assert [good, bad] == originals


@pytest.mark.parametrize("stage", ["primary", "fallback"])
@pytest.mark.parametrize("error_type", [JobCancelled, JobTimedOut, TimeoutError, CancelledError, asyncio.CancelledError])
@pytest.mark.parametrize("wrapped", [False, True])
def test_stop_propagates_without_becoming_a_quote_error(sources, stage, error_type, wrapped):
    primary, backup = sources
    stop = error_type("stop quotes")
    primary.return_value = payload(points=[])

    def fail(*_args, **_kwargs):
        if wrapped:
            raise McpError("transport wrapper") from stop
        raise stop

    (primary if stage == "primary" else backup).side_effect = fail
    with pytest.raises(error_type) as caught:
        guardian_tools.snapshot([CODE], now=NOW)
    assert caught.value is stop
    if stage == "primary":
        backup.assert_not_called()


def test_one_cancelled_quote_is_not_held_by_another_slow_quote(sources):
    primary, backup = sources
    started, release, finished = threading.Event(), threading.Event(), threading.Event()
    stop = JobCancelled("cancel before all reads finish")

    def fetch(_name, args, **_kwargs):
        if args["code"] == CODE:
            started.set()
            release.wait(3)
            finished.set()
            return payload()
        assert started.wait(2)
        raise stop

    primary.side_effect = fetch
    try:
        with pytest.raises(JobCancelled) as caught:
            guardian_tools.snapshot([CODE, "600002"], now=NOW)
        assert caught.value is stop
        assert not finished.is_set(), "completed cancellation must be read before waiting for every future"
        backup.assert_not_called()
    finally:
        release.set()
        assert finished.wait(3)


def test_expired_deadline_starts_no_sources(sources):
    primary, backup = sources
    with pytest.raises(TimeoutError):
        guardian_tools.snapshot([CODE], now=NOW, deadline=time.monotonic() - 1)
    primary.assert_not_called()
    backup.assert_not_called()


def test_snapshot_passes_absolute_deadline_to_real_mcp_entry(sources):
    primary, _backup = sources
    deadline = time.monotonic() + 20
    guardian_tools.snapshot([CODE], now=NOW, deadline=deadline)
    assert primary.call_args.kwargs["deadline"] == deadline


def test_primary_and_backup_keep_current_tenant_context(sources):
    primary, backup = sources
    seen = []

    def first(*_args, **_kwargs):
        seen.append(("primary", current_tenant()))
        return payload(points=[])

    def second(*_args, **_kwargs):
        seen.append(("fallback", current_tenant()))
        return SimpleNamespace(quotes={CODE: quote()})

    primary.side_effect, backup.side_effect = first, second
    for tenant in ("quote_alice", "quote_bob"):
        with tenant_scope(tenant):
            guardian_tools.snapshot([CODE], now=NOW)
    assert seen == [(stage, tenant) for tenant in ("quote_alice", "quote_bob") for stage in ("primary", "fallback")]
