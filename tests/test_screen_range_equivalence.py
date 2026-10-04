"""Range execution must match independent days across origin and qfq changes."""
import pandas as pd
import pytest

from src.market import MarketStore
from src.strategy.application.screen_formula import build_formula_engine
from src.strategy.application.screen_run_prepare import range_read_scope
from src.strategy.application.screener import screen


@pytest.mark.parametrize("source,factors", [
    ("M:=MA(CLOSE,5); PICK:CLOSE>10;", ["M"]),
    ("E:=EMA(CLOSE,5); PICK:CLOSE>10;", ["E"]),
    ("F:=FILTER(CLOSE>0,7); PICK:F;", ["F"]),
])
def test_new_formula_entire_range_matches_daily_screen_with_corporate_action(tmp_path, source, factors):
    dates = pd.bdate_range("2026-02-02", periods=150).strftime("%Y-%m-%d").tolist()
    codes = ["000001", "000002"]
    formula = build_formula_engine({"slug": "new-formula", "name": "New formula", "code": source,
                                    "manifest": {"schema_version": 1, "entry_timing": "next_open",
                                                 "min_bars": 30, "factors": factors,
                                                 "output": {"signal": "PICK"}}})
    with MarketStore(tmp_path / "market.db") as store:
        store.upsert_instruments({"code": code, "name": "fixture", "market": "sz",
                                  "board": "main", "instrument_type": "STOCK", "list_date": "2015-01-01"}
                                 for code in codes)
        store.conn.executemany("INSERT INTO quotes_daily(trade_date,code,open,high,low,close,volume,amount,source,fetched_at) "
                               "VALUES(?,?,?,?,?,?,?,?,?,?)",
                               [(day, code, 20., 21., 19., 20., 1e6, 2e7, "fixture", day)
                                for day in dates for code in codes])
        store.conn.commit()
        store.rebuild_calendar()
        for code in codes:
            store.upsert_adjust_factors(code, pd.DataFrame({"date": [dates[0], dates[-10]],
                                                           "hfq_factor": [1., 2.]}), source="fixture")
        options = dict(codes=codes, health_check=False, live_overlay=False, skip_universe_safety=True)
        days = dates[-21:]
        expected = [screen(store, formula, trade_date=day, **options) for day in days]
        with range_read_scope(store, formula, days, None, codes=codes):
            actual = [screen(store, formula, trade_date=day, **options) for day in days]
        for daily, ranged in zip(expected, actual):
            assert daily.trade_date == ranged.trade_date
            assert daily.picks == ranged.picks
            assert daily.watch_picks == ranged.watch_picks
            assert daily.universe_size == ranged.universe_size
            assert daily.universe_funnel == ranged.universe_funnel
            assert daily.data_snapshot == ranged.data_snapshot
