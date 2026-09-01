"""盘中选股实时 overlay：只叠内存，不写库。"""
from __future__ import annotations

from datetime import datetime
from zoneinfo import ZoneInfo

import pandas as pd
import pytest

from src.market.application.screen_live import (
    ScreenLiveError,
    fetch_live_spot_bars,
    in_live_screen_clock,
    overlay_live_day,
    reset_live_spot_cache,
    should_overlay_live,
)


TZ = ZoneInfo("Asia/Shanghai")


def test_clock_and_target_day() -> None:
    at_1450 = datetime(2026, 9, 1, 14, 50, tzinfo=TZ)
    at_1530 = datetime(2026, 9, 1, 15, 30, tzinfo=TZ)
    sunday = datetime(2026, 8, 30, 14, 50, tzinfo=TZ)
    assert in_live_screen_clock(at_1450)
    assert not in_live_screen_clock(at_1530)
    assert not in_live_screen_clock(sunday)
    assert should_overlay_live(None, now=at_1450)
    assert should_overlay_live("2026-09-01", now=at_1450)
    assert not should_overlay_live("2026-08-31", now=at_1450)
    assert not should_overlay_live("2026-09-01", now=at_1530)


def test_overlay_appends_today_and_fills_turnover() -> None:
    days = ["2026-08-28", "2026-08-31"]
    close = pd.DataFrame({"600001": [10.0, 10.2]}, index=days)
    volume = pd.DataFrame({"600001": [1e6, 1.1e6]}, index=days)
    amount = pd.DataFrame({"600001": [1e7, 1.1e7]}, index=days)
    shares = pd.DataFrame({"600001": [1e8, 1e8]}, index=days)
    turnover = pd.DataFrame({"600001": [0.01, 0.011]}, index=days)
    panels = {
        "close": close,
        "volume": volume,
        "amount": amount,
        "outstanding_share": shares,
        "turnover": turnover,
        "__raw_close": close.copy(),
    }
    bars = {
        "600001": {
            "open": 10.3,
            "high": 10.8,
            "low": 10.2,
            "close": 10.6,
            "volume": 2e6,
            "amount": 2.12e7,
        }
    }
    out = overlay_live_day(panels, bars, "2026-09-01")
    assert "2026-09-01" in out["close"].index
    assert out["close"].loc["2026-09-01", "600001"] == pytest.approx(10.6)
    assert out["__raw_close"].loc["2026-09-01", "600001"] == pytest.approx(10.6)
    assert out["outstanding_share"].loc["2026-09-01", "600001"] == pytest.approx(1e8)
    assert out["turnover"].loc["2026-09-01", "600001"] == pytest.approx(2.12e7 / (10.6 * 1e8))


def test_fetch_rejects_empty_and_does_not_write(monkeypatch: pytest.MonkeyPatch) -> None:
    reset_live_spot_cache()
    writes: list[str] = []

    def boom(*_a, **_k):
        writes.append("spot")
        return pd.DataFrame(), "tdx"

    monkeypatch.setattr(
        "src.market.infrastructure.adapters.fetch_spot_routed", boom
    )
    monkeypatch.setattr(
        "src.market.infrastructure.sync_spot.dated_spot_adapter_ids",
        lambda: ["tdx"],
    )
    with pytest.raises(ScreenLiveError):
        fetch_live_spot_bars(["600001"])
    assert writes == ["spot"]


def test_fetch_keeps_today_rows_only(monkeypatch: pytest.MonkeyPatch) -> None:
    reset_live_spot_cache()
    today = datetime.now(TZ).date().isoformat()
    frame = pd.DataFrame(
        [
            {
                "code": "600001",
                "date": today,
                "open": 10.0,
                "high": 11.0,
                "low": 9.8,
                "close": 10.5,
                "volume": 1000.0,
                "amount": 1.05e6,
            },
            {
                "code": "600002",
                "date": "2020-01-01",
                "open": 1.0,
                "high": 1.0,
                "low": 1.0,
                "close": 1.0,
                "volume": 1.0,
                "amount": 1.0,
            },
        ]
    )
    monkeypatch.setattr(
        "src.market.infrastructure.adapters.fetch_spot_routed",
        lambda *_a, **_k: (frame, "tdx"),
    )
    monkeypatch.setattr(
        "src.market.infrastructure.sync_spot.dated_spot_adapter_ids",
        lambda: ["tdx"],
    )
    bars = fetch_live_spot_bars(["600001", "600002"])
    assert "600001" in bars
    assert "600002" not in bars
    assert bars["600001"]["close"] == pytest.approx(10.5)
