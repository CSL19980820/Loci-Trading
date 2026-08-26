"""选股前当日行情就绪：覆盖达标跳过 spot（根治与同步抢写）。"""
from __future__ import annotations

from datetime import date
from pathlib import Path
from unittest.mock import patch

import pytest

from src.market.application.screen_spot import (
    ScreenSpotError,
    coverage_ready,
    ensure_today_quotes_for_screen,
    measure_day_coverage,
)
from src.market.infrastructure.store import MarketStore


def _seed_today(store: MarketStore, *, n: int = 10, with_quotes: int = 10) -> str:
    today = date.today().isoformat()
    store.conn.execute(
        "INSERT OR IGNORE INTO trading_calendar(trade_date) VALUES (?)", (today,)
    )
    store.conn.commit()
    store.upsert_instruments(
        [
            {
                "code": f"600{i:03d}",
                "name": f"票{i}",
                "market": "SH",
                "board": "main",
                "industry": "测试",
                "instrument_type": "STOCK",
                "status": "normal",
            }
            for i in range(n)
        ]
    )
    bars = [
        {
            "code": f"600{i:03d}",
            "date": today,
            "open": 10.0,
            "high": 11.0,
            "low": 9.5,
            "close": 10.5,
            "volume": 1000.0,
            "amount": 1e6,
        }
        for i in range(with_quotes)
    ]
    if bars:
        store.upsert_quote_bars(bars, source="test")
    return today


def test_measure_and_ready(tmp_path: Path) -> None:
    store = MarketStore(tmp_path / "m.db")
    _seed_today(store, n=10, with_quotes=9)
    cov = measure_day_coverage(store, date.today().isoformat())
    assert cov["listed"] == 10
    assert cov["present"] == 9
    assert coverage_ready(cov, floor=0.90)
    assert not coverage_ready(cov, floor=0.95)
    store.close()


def test_ensure_skips_spot_when_coverage_ok(tmp_path: Path) -> None:
    store = MarketStore(tmp_path / "m.db")
    _seed_today(store, n=10, with_quotes=10)
    calls: list[int] = []

    def boom(*_a, **_k):
        calls.append(1)
        raise AssertionError("覆盖已达标不应再调 apply_today_spot")

    with patch(
        "src.market.infrastructure.sync_spot.apply_today_spot", side_effect=boom
    ):
        result = ensure_today_quotes_for_screen(
            store, [f"600{i:03d}" for i in range(10)]
        )
    assert result["status"] == "skipped"
    assert calls == []
    assert "跳过" in result["message"]
    store.close()


def test_ensure_reuses_coverage_when_spot_busy(tmp_path: Path) -> None:
    store = MarketStore(tmp_path / "m.db")
    _seed_today(store, n=10, with_quotes=10)

    def locked(*_a, **_k):
        raise RuntimeError("database is locked")

    # force_refresh 才会走进 spot；覆盖仍达标 → 软成功
    with patch(
        "src.market.infrastructure.sync_spot.apply_today_spot", side_effect=locked
    ):
        result = ensure_today_quotes_for_screen(
            store,
            [f"600{i:03d}" for i in range(10)],
            force_refresh=True,
        )
    assert result["status"] == "reused_after_busy"
    assert "继续选股" in result["message"]
    store.close()


def test_ensure_fails_when_coverage_low_and_spot_busy(tmp_path: Path) -> None:
    store = MarketStore(tmp_path / "m.db")
    _seed_today(store, n=10, with_quotes=2)

    def locked(*_a, **_k):
        raise RuntimeError("database is locked")

    with patch(
        "src.market.infrastructure.sync_spot.apply_today_spot", side_effect=locked
    ):
        with pytest.raises(ScreenSpotError) as ctx:
            ensure_today_quotes_for_screen(
                store, [f"600{i:03d}" for i in range(10)]
            )
    msg = str(ctx.value)
    assert "同步占用" in msg or "覆盖" in msg
    assert "OperationalError" not in msg
    store.close()


def test_ensure_refreshes_when_coverage_low(tmp_path: Path) -> None:
    store = MarketStore(tmp_path / "m.db")
    _seed_today(store, n=10, with_quotes=1)

    def fake_spot(store_arg, codes, **_k):
        today = date.today().isoformat()
        bars = [
            {
                "code": code,
                "date": today,
                "open": 10.0,
                "high": 11.0,
                "low": 9.5,
                "close": 10.5,
                "volume": 1000.0,
                "amount": 1e6,
            }
            for code in codes
        ]
        return store_arg.upsert_quote_bars(bars, source="spot")

    with patch(
        "src.market.infrastructure.sync_spot.apply_today_spot", side_effect=fake_spot
    ):
        result = ensure_today_quotes_for_screen(
            store, [f"600{i:03d}" for i in range(10)]
        )
    assert result["status"] == "refreshed"
    assert result["written"] >= 10
    store.close()
