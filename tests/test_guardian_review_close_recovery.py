"""持仓新票不在证券目录时，日复盘仍要取得可核对的收盘价。"""
from datetime import datetime
from zoneinfo import ZoneInfo

import pandas as pd
import pytest

from src.market import MarketStore
from src.market.infrastructure.adapters import tdx_adapter, wudao_adapter
from src.ops.application import guardian_review_data as review


DAY = "2026-09-22"
CLOSED = datetime(2026, 9, 22, 15, tzinfo=ZoneInfo("Asia/Shanghai"))


def _frame(close: float, *, wudao: bool) -> pd.DataFrame:
    return pd.DataFrame([{
        "date": DAY.replace("-", "") if wudao else DAY,
        "open": 58.5, "high": 60.0, "low": 58.0, "close": close,
        "volume": 2000000 if wudao else 200000000,
        "amount": 12000000000,
    }])


def _market(tmp_path):
    return MarketStore(tmp_path / "market.db")


def test_missing_held_close_uses_wudao_and_tdx_without_catalog_entry(tmp_path, monkeypatch):
    monkeypatch.setattr(wudao_adapter, "wudao_adapter_enabled", lambda: True)
    monkeypatch.setattr(wudao_adapter.WudaoAdapter, "fetch_daily_many",
                        lambda self, codes, bars: {"688825": _frame(58.62, wudao=True)})
    monkeypatch.setattr(tdx_adapter.TdxAdapter, "fetch_daily_window",
                        lambda self, code, bars: _frame(58.62, wudao=False))
    monkeypatch.setattr(review, "guardian_account_at", lambda *_args, **_kwargs: {
        "positions": [{"code": "688825", "name": "长鑫科技", "quantity": 400}],
    })
    monkeypatch.setattr(review, "mark_guardian_account",
                        lambda _state, quotes, _at: {"quotes": quotes})
    with _market(tmp_path) as market:
        assert market.instruments_meta(["688825"]) == {}
        account = review.closing_account(market, [], DAY, 10000000)
        row = market.history("688825", start=DAY, end=DAY, adjust="none").iloc[-1]
    assert account["quotes"]["688825"]["price"] == 58.62
    assert account["closing_sources"][0]["source"] == "tdx"
    assert row["volume"] == 200000000


def test_wudao_only_close_keeps_unknown_volume_out_of_market_db(tmp_path, monkeypatch):
    monkeypatch.setattr(wudao_adapter, "wudao_adapter_enabled", lambda: True)
    monkeypatch.setattr(wudao_adapter.WudaoAdapter, "fetch_daily_many",
                        lambda self, codes, bars: {"688825": _frame(58.62, wudao=True)})
    monkeypatch.setattr(tdx_adapter.TdxAdapter, "fetch_daily_window",
                        lambda self, code, bars: (_ for _ in ()).throw(RuntimeError("TDX unavailable")))
    with _market(tmp_path) as market:
        review._recover_closing_quote(market, "688825", DAY, CLOSED)
        row = market.history("688825", start=DAY, end=DAY, adjust="none").iloc[-1]
    assert row["source"] == "wudao"
    assert row["close"] == 58.62
    assert pd.isna(row["volume"])


def test_disagreeing_sources_do_not_write_close(tmp_path, monkeypatch):
    monkeypatch.setattr(wudao_adapter, "wudao_adapter_enabled", lambda: True)
    monkeypatch.setattr(wudao_adapter.WudaoAdapter, "fetch_daily_many",
                        lambda self, codes, bars: {"688825": _frame(58.62, wudao=True)})
    monkeypatch.setattr(tdx_adapter.TdxAdapter, "fetch_daily_window",
                        lambda self, code, bars: _frame(59.62, wudao=False))
    with _market(tmp_path) as market:
        with pytest.raises(ValueError, match="收盘价不一致"):
            review._recover_closing_quote(market, "688825", DAY, CLOSED)
        assert market.history("688825", start=DAY, end=DAY, adjust="none").empty
