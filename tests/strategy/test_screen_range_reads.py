"""区间后台入口必须实际复用面板，并保持逐日结果及预热边界。"""
from contextlib import nullcontext
from datetime import date, timedelta
from pathlib import Path
from unittest.mock import patch

import pandas as pd

from src.market import MarketStore
from src.strategy.application.screen_run import execute_screen_run, screen_run_snapshot
from src.strategy.application.screen_run_prepare import range_read_scope
from src.strategy.domain.base import SignalResult


class RangeEngine:
    slug = "range-read-contract"
    name = "区间读取契约"
    entry_timing = "next_open"
    adjust = "none"
    warmup_bars = 25

    def default_params(self) -> dict:
        return {}

    def required_fields(self) -> tuple[str, ...]:
        return ("close",)

    def min_bars(self) -> int:
        return 2

    def compute(self, panels: dict[str, pd.DataFrame], params: dict | None = None) -> SignalResult:
        close = panels["close"]
        change = close.diff()
        return SignalResult(signals=change.gt(0), factors={"change": change})


def test_background_range_reuses_quotes_without_changing_results(tmp_path: Path) -> None:
    path = tmp_path / "market.db"
    dates = [(date(2026, 1, 1) + timedelta(days=i)).isoformat() for i in range(50)]
    with MarketStore(path) as store:
        store.upsert_instruments([
            {"code": "000001", "name": "夹具甲", "market": "SZ", "instrument_type": "STOCK"},
            {"code": "600001", "name": "夹具乙", "market": "SH", "instrument_type": "STOCK"},
        ])
        store.conn.executemany(
            "INSERT INTO trading_calendar(trade_date,updated_at) VALUES(?, '')",
            [(day,) for day in dates],
        )
        store.conn.executemany(
            "INSERT INTO quotes_daily(trade_date,code,close,source,fetched_at) VALUES(?,?,?,'fixture','')",
            [(day, code, 10 + i * direction) for i, day in enumerate(dates)
             for code, direction in (("000001", .1), ("600001", -.1))],
        )
        store.conn.commit()
    opts = {"strategy": RangeEngine.slug, "start": dates[30], "end": dates[49],
            "codes": ["000001", "600001"], "record_candidates": False, "refresh_spot": False}
    payload_reads: list[str] = []

    def factory() -> MarketStore:
        store = MarketStore(path)
        store.conn.set_trace_callback(lambda sql: payload_reads.append(sql)
                                     if sql.upper().startswith("SELECT TRADE_DATE, CODE, CLOSE FROM QUOTES_DAILY") else None)
        return store

    with patch("src.strategy.get", return_value=RangeEngine()), patch(
        "src.strategy.application.screener.get", return_value=RangeEngine()
    ):
        with patch("src.strategy.application.screen_run.range_read_scope", return_value=nullcontext()):
            execute_screen_run(opts, market_factory=factory, palace_db=None)
        baseline = screen_run_snapshot(RangeEngine.slug)
        assert baseline["status"] == "done", baseline["error"]
        assert len(payload_reads) == 20
        payload_reads.clear()
        execute_screen_run(opts, market_factory=factory, palace_db=None)
        optimized = screen_run_snapshot(RangeEngine.slug)
    assert optimized["status"] == "done", optimized["error"]
    assert len(payload_reads) == 1
    for key in ("picks", "watch_picks", "universe_size", "data_snapshot", "params"):
        assert optimized["result"][key] == baseline["result"][key]
    assert optimized["result"]["picks"][0]["code"] == "000001"
    assert optimized["result"]["data_snapshot"]["start"] == dates[25]
    for before, after in zip(baseline["result"]["range"]["days"], optimized["result"]["range"]["days"], strict=True):
        assert (before["trade_date"], before["picks"], before["universe_size"]) == (after["trade_date"], after["picks"], after["universe_size"])


def test_explicit_small_universe_uses_bounded_sql(tmp_path: Path) -> None:
    with MarketStore(tmp_path / "small.db") as store:
        store.upsert_instruments([
            {"code": f"{code:06}", "name": "夹具", "market": "SZ", "instrument_type": "STOCK"}
            for code in range(1, 101)
        ])
        with patch("src.strategy.application.screen_run_prepare.panel_read_window", side_effect=AssertionError("must not preload the whole market")):
            with range_read_scope(store, RangeEngine(), ["2026-01-01", "2026-01-05"], None, codes=["000001"]):
                pass
            with range_read_scope(store, RangeEngine(), ["2026-01-01", "2026-01-05"], None, universe={"codes_include": ["000001"]}):
                pass
