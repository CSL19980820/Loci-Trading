"""权威日结定向补数；退役来源不得再被隐式调用或伪造成交量。"""
from datetime import datetime
from zoneinfo import ZoneInfo

import pandas as pd
import pytest

from src.market import MarketStore
from src.market.infrastructure.adapters import tdx_adapter
import src.market as market_api
from src.ops.application import guardian_review_data as review

DAY = "2026-09-22"
CLOSED = datetime(2026, 9, 22, 15, tzinfo=ZoneInfo("Asia/Shanghai"))


def _frame(close=58.62, day=DAY):
    return pd.DataFrame([{"date": day, "open": 58.5, "high": 60.0, "low": 58.0,
                          "close": close, "volume": 200000000, "amount": 12000000000}])


@pytest.fixture(autouse=True)
def enabled(monkeypatch):
    monkeypatch.setattr(market_api, "lane_provider_enabled", lambda *args, **kwargs: True)


def test_missing_held_close_uses_tdx_without_catalog_entry(tmp_path, monkeypatch):
    monkeypatch.setattr(tdx_adapter.TdxAdapter, "fetch_daily_window",
                        lambda self, code, bars: _frame())
    monkeypatch.setattr(review, "guardian_account_at", lambda *_args, **_kwargs: {
        "positions": [{"code": "688825", "name": "测试证券", "quantity": 400}],
    })
    monkeypatch.setattr(review, "mark_guardian_account", lambda _state, quotes, _at: {"quotes": quotes})
    with MarketStore(tmp_path / "market.db") as market:
        assert market.instruments_meta(["688825"]) == {}
        account = review.closing_account(market, [], DAY, 10000000)
        row = market.history("688825", start=DAY, end=DAY, adjust="none").iloc[-1]
    assert account["quotes"]["688825"]["price"] == 58.62
    assert account["closing_sources"][0]["source"] == "tdx"
    assert row["volume"] == 200000000


def test_unavailable_authority_preserves_existing_facts(tmp_path, monkeypatch):
    def unavailable(*args, **kwargs):
        raise RuntimeError("TDX unavailable")
    monkeypatch.setattr(tdx_adapter.TdxAdapter, "fetch_daily_window", unavailable)
    with MarketStore(tmp_path / "market.db") as market:
        market.upsert_quote_bars([{"code": "688825", **_frame().iloc[0].to_dict()}], source="sina")
        before = market.history("688825", start=DAY, end=DAY, adjust="none").to_dict("records")
        with pytest.raises(ValueError, match="未取得有效通达信"):
            review._recover_closing_quote(market, "688825", DAY, CLOSED)
        assert market.history("688825", start=DAY, end=DAY, adjust="none").to_dict("records") == before


@pytest.mark.parametrize("frame", [_frame(day="2026-09-21"), _frame(close=float("nan")), _frame(close=61)])
def test_invalid_or_other_day_bar_never_becomes_close(tmp_path, monkeypatch, frame):
    monkeypatch.setattr(tdx_adapter.TdxAdapter, "fetch_daily_window", lambda *args, **kwargs: frame)
    with MarketStore(tmp_path / "market.db") as market:
        with pytest.raises(ValueError, match="未取得有效通达信"):
            review._recover_closing_quote(market, "688825", DAY, CLOSED)
        assert market.history("688825", start=DAY, end=DAY, adjust="none").empty


def test_disabled_source_cannot_be_called_by_recovery(tmp_path, monkeypatch):
    monkeypatch.setattr(market_api, "lane_provider_enabled", lambda *args, **kwargs: False)
    monkeypatch.setattr(tdx_adapter.TdxAdapter, "fetch_daily_window",
                        lambda *args, **kwargs: pytest.fail("disabled source was called"))
    with MarketStore(tmp_path / "market.db") as market:
        with pytest.raises(ValueError, match="已停用"):
            review._recover_closing_quote(market, "688825", DAY, CLOSED)
