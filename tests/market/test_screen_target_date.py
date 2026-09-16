"""休市及历史选股检查目标日，不能要求自然日有行情。"""
from datetime import datetime
from contextlib import nullcontext
from types import SimpleNamespace
from unittest.mock import patch
from zoneinfo import ZoneInfo

import pytest

from src.market.application.screen_spot import (
    ScreenSpotError, ensure_today_quotes_for_screen, resolve_screen_trade_date,
)
from src.market import MarketStore

TZ = ZoneInfo("Asia/Shanghai")


@pytest.fixture
def market(tmp_path):
    with MarketStore(tmp_path / "market.db") as store:
        store.upsert_instruments([
            {"code": "600000", "name": "测试", "market": "SH", "status": "normal"},
        ])
        store.upsert_quote_bars([
            {"code": "600000", "date": "2026-09-11", "open": 10, "high": 11,
             "low": 9, "close": 10, "volume": 100, "amount": 1000},
        ], source="tdx")
        yield store


@pytest.mark.parametrize("clock,target", [
    ("2026-09-12T21:00:00", "2026-09-11"),
    ("2026-09-13T12:00:00", "2026-09-11"),
    ("2026-09-14T08:00:00", "2026-09-11"),
    ("2026-09-14T10:00:00", "2026-09-14"),
    ("2026-09-14T16:00:00", "2026-09-14"),
])
def test_default_target_follows_session(market, clock, target):
    assert resolve_screen_trade_date(market, now=datetime.fromisoformat(clock)) == target


def test_weekend_reuses_friday_without_spot_even_when_forced(market):
    with patch("src.market.application.screen_spot.datetime") as clock, patch(
        "src.market.infrastructure.sync_spot.apply_today_spot"
    ) as spot:
        clock.now.return_value = datetime(2026, 9, 12, 21, tzinfo=TZ)
        result = ensure_today_quotes_for_screen(market, ["600000"], force_refresh=True)
    spot.assert_not_called()
    assert result["coverage"] == {
        "trade_date": "2026-09-11", "listed": 1, "present": 1, "ratio": 1.0,
    }
    assert result["degraded"] is False


def test_missing_historical_day_cannot_soft_pass_or_refresh_today(market):
    with patch("src.market.application.screen_spot.datetime") as clock, patch(
        "src.market.infrastructure.sync_spot.apply_today_spot"
    ) as spot:
        clock.now.return_value = datetime(2026, 9, 14, 10, tzinfo=TZ)
        with pytest.raises(ScreenSpotError, match="2026-09-10.*覆盖 0/1"):
            ensure_today_quotes_for_screen(market, ["600000"], trade_date="2026-09-10")
    spot.assert_not_called()


def test_explicit_history_and_future(market):
    now = datetime(2026, 9, 14, 10, tzinfo=TZ)
    assert resolve_screen_trade_date(market, "2026-09-10", now=now) == "2026-09-10"
    with pytest.raises(ScreenSpotError, match="尚未到来"):
        resolve_screen_trade_date(market, "2026-09-15", now=now)


@pytest.mark.parametrize("tenant", ["__primary__", "screen-date-user"])
def test_job_passes_checked_date_to_engine_for_each_tenant(market, tenant):
    from src.ops.application.jobs.screen import execute_screen
    from src.shared.tenancy import tenant_scope

    context = SimpleNamespace(market=lambda: nullcontext(market))
    with tenant_scope(tenant), patch("src.market.application.screen_spot.datetime") as clock, patch(
        "src.market.should_overlay_live", return_value=False
    ), patch("src.strategy.get", return_value=SimpleNamespace(requires_full_history=True)), patch(
        "src.strategy.screen", side_effect=RuntimeError("engine reached")
    ) as engine, patch("src.market.infrastructure.sync_spot.apply_today_spot") as spot:
        clock.now.return_value = datetime(2026, 9, 12, 21, tzinfo=TZ)
        with pytest.raises(RuntimeError, match="engine reached"):
            execute_screen({"strategy": "test"}, context)
    assert engine.call_args.kwargs["trade_date"] == "2026-09-11"
    spot.assert_not_called()
