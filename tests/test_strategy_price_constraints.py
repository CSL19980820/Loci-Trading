"""未复权价格附加面板的通用契约，与任一专属战法解耦。"""
from __future__ import annotations

import pandas as pd
import pytest

from src.market import MarketStore
from src.strategy.application.price_constraints import attach_raw_limit_close

CODES = ["300001", "300002"]


@pytest.fixture
def market_fixture(tmp_path):
    path = tmp_path / "market.db"
    dates = pd.bdate_range("2023-01-03", periods=140).strftime("%Y-%m-%d").tolist()
    with MarketStore(path) as store:
        store.upsert_instruments(
            {"code": code, "name": f"样本{code}", "market": "sz", "board": "chi_next",
             "instrument_type": "STOCK", "list_date": "2015-01-05"}
            for code in CODES
        )
        store.conn.executemany(
            "INSERT INTO quotes_daily(trade_date,code,open,high,low,close,volume,amount,"
            "outstanding_share,turnover,source,fetched_at) VALUES(?,?,?,?,?,?,?,?,?,?,?,?)",
            [(day, code, 20.0, 20.04, 19.96, 20.0, 2_000_000.0, 40_000_000.0,
              100_000_000.0, 0.02, "tdx", day + "T15:30:00")
             for day in dates for code in CODES],
        )
        store.conn.commit()
        store.rebuild_calendar()
        for code in CODES:
            store.upsert_adjust_factors(
                code, pd.DataFrame({"date": [dates[0], dates[130]], "hfq_factor": [1.0, 2.0]}),
                source="fixture",
            )
    return path, dates


@pytest.mark.parametrize("adjust", ["none", "qfq", "hfq"])
def test_raw_close_is_available_for_every_supported_adjustment(market_fixture, monkeypatch, adjust):
    path, dates = market_fixture
    calls = []
    original = MarketStore.load_panel

    def observed_load(self, **kwargs):
        calls.append(dict(kwargs))
        return original(self, **kwargs)

    monkeypatch.setattr(MarketStore, "load_panel", observed_load)
    with MarketStore(path) as store:
        panels = store.load_panel(fields=("close",), codes=CODES, start=dates[0],
                                  end=dates[-1], adjust=adjust, min_bars=1)
        calls.clear()
        attach_raw_limit_close(store, panels, enabled=True, adjust=adjust, codes=CODES,
                               start=dates[0], end=dates[-1], min_bars=1)
        raw = original(store, fields=("close",), codes=CODES, start=dates[0],
                       end=dates[-1], adjust="none", min_bars=1)["close"]
        pd.testing.assert_frame_equal(panels["__raw_close"], raw)
        if adjust == "none":
            assert not calls
            assert panels["__raw_close"] is panels["close"]
        else:
            assert [call["adjust"] for call in calls] == ["none"]
            assert not panels["close"].equals(raw)


def test_raw_close_attachment_still_requires_the_engine_opt_in(market_fixture):
    path, dates = market_fixture
    with MarketStore(path) as store:
        panels = store.load_panel(fields=("close",), codes=CODES, start=dates[0],
                                  end=dates[-1], adjust="none", min_bars=1)
        attach_raw_limit_close(store, panels, enabled=False, adjust="none", codes=CODES,
                               start=dates[0], end=dates[-1], min_bars=1)
        assert "__raw_close" not in panels


@pytest.mark.parametrize("adjust", ["none", "qfq", "hfq"])
@pytest.mark.parametrize("min_bars", [1, 141])
def test_same_read_raw_ohlc_matches_separate_reads_without_second_quote_query(
    market_fixture, monkeypatch, adjust, min_bars,
):
    path, dates = market_fixture
    fields = ("open", "high", "low", "close", "volume")
    with MarketStore(path) as store:
        kwargs = dict(fields=fields, codes=CODES, start=dates[0], end=dates[-1], min_bars=min_bars)
        expected = store.load_panel(**kwargs, adjust=adjust)
        raw = store.load_panel(**kwargs, adjust="none")
        calls = []
        original = store._read_raw_panels

        def observed_read(*args, **options):
            calls.append(1)
            return original(*args, **options)

        monkeypatch.setattr(store, "_read_raw_panels", observed_read)
        actual = store.load_panel(**kwargs, adjust=adjust, raw_price_fields=fields[:4])
        attach_raw_limit_close(store, actual, enabled=True, adjust=adjust, codes=CODES,
                               start=dates[0], end=dates[-1], min_bars=min_bars, include_ohlc=True)
        assert len(calls) == 1
        for field in fields:
            pd.testing.assert_frame_equal(actual[field], expected[field], check_exact=True)
        for field in fields[:4]:
            pd.testing.assert_frame_equal(actual[f"__raw_{field}"], raw[field], check_exact=True)
        assert "__raw_volume" not in actual
