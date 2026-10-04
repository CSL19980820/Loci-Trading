"""Explanation keeps price semantics without rebuilding a wide row per stock."""
from dataclasses import asdict

import numpy as np
import pandas as pd
from pandas.core.indexing import _iLocIndexer
import pytest

from src.strategy.application import screener
from src.strategy.application.execution_profile import ExecutionProfile
from src.strategy.domain.base import SignalResult


def _old_pct_chg(panel, trade_date, code):
    close = screener._cell(panel, trade_date, code)
    if panel is None or close is None or trade_date not in panel.index:
        return None
    try:
        idx = int(panel.index.get_loc(trade_date))
    except (KeyError, TypeError, ValueError):
        return None
    if idx <= 0 or code not in panel.columns:
        return None
    prev = panel.iloc[idx - 1][code]
    if pd.isna(prev) or float(prev) == 0:
        return None
    return round((close / float(prev) - 1.0) * 100.0, 2)


class ExplanationEngine:
    slug = name = "explanation-fixture"
    entry_timing = "next_open"
    adjust = "none"
    screen_rank_factor = "integer"

    def default_params(self):
        return {}

    def required_fields(self):
        return ("close", "open")

    def min_bars(self):
        return 1

    def execution_profile(self, params=None):
        return ExecutionProfile(pure=True, causal=True)

    def compute(self, panels, params=None):
        close = panels["close"]
        numbers = np.arange(len(close.columns))
        integer = pd.DataFrame(np.tile(numbers, (len(close), 1)), index=close.index, columns=close.columns)
        boolean = integer.mod(2).eq(0)
        return SignalResult(
            integer.lt(2000),
            {"float": close * 1.234567, "integer": integer, "numpy-bool": boolean,
             "python-bool": boolean.astype(object)},
            integer.ge(1900) & integer.lt(3000),
        )


class ExplanationStore:
    def __init__(self, panels):
        self.panels = panels

    def trading_days(self, start=None, end=None):
        return [day for day in self.panels["close"].index
                if (start is None or day >= start) and (end is None or day <= end)]

    def list_instruments(self, **kwargs):
        return [{"code": code, "name": "样本", "instrument_type": "STOCK", "status": "normal",
                 "list_date": "2010-01-01"} for code in self.panels["close"].columns]

    def data_snapshot(self, **kwargs):
        return {"market_revision": "fixture"}

    def market_revision(self):
        return "fixture"

    def load_panel(self, fields, **kwargs):
        return {name: self.panels[name] for name in fields}


def _wide_chunked_close():
    index = pd.Index(["2024-01-02", "2024-01-03", "2024-01-04"], name="trade_date")
    columns = pd.Index([f"{600000 + number:06}" for number in range(5000)], name="code")
    chunks = []
    for offset in range(0, len(columns), 64):
        part = columns[offset:offset + 64]
        numbers = np.arange(offset, offset + len(part)) / 1000
        chunks.append(pd.DataFrame(np.stack([10 + numbers, 10.1234567 + numbers, 11.9876543 + numbers]),
                                   index=index, columns=part))
    close = pd.concat(chunks, axis=1)
    close.iloc[1, 0] = 0
    close.iloc[1, 1] = np.nan
    close.iloc[2, 3] = np.nan
    close.iloc[1, 4], close.iloc[2, 4] = 1e-7, 2e-7
    return close


def test_wide_multiblock_screen_explanation_matches_old_results_and_reads_previous_row_once(monkeypatch):
    close = _wide_chunked_close()
    assert close.shape == (3, 5000) and close._mgr.nblocks > 1
    store = ExplanationStore({"close": close, "open": close * .99})
    arguments = {"trade_date": close.index[-1], "codes": list(close.columns),
                 "health_check": False, "live_overlay": False, "adjust": "none"}
    row_reads = []
    original_axis = _iLocIndexer._getitem_axis

    def counted(indexer, key, axis):
        if indexer.obj is close and axis == 0 and isinstance(key, (int, np.integer)):
            row_reads.append(key)
        return original_axis(indexer, key, axis)

    monkeypatch.setattr(_iLocIndexer, "_getitem_axis", counted)
    with monkeypatch.context() as old:
        old.setattr(screener, "_pct_chg", lambda current, previous, code:
                    _old_pct_chg(close, arguments["trade_date"], code))
        expected = screener.screen(store, ExplanationEngine(), **arguments)
    assert len(expected.picks) == 2000 and len(expected.watch_picks) == 1000
    assert len(row_reads) > 2000
    row_reads.clear()
    actual = screener.screen(store, ExplanationEngine(), **arguments)
    assert row_reads == [1]
    expected_data, actual_data = asdict(expected), asdict(actual)
    expected_data.pop("elapsed_seconds")
    actual_data.pop("elapsed_seconds")
    assert actual_data == expected_data
    assert actual.picks[0]["code"] == "601999"  # descending integer rank stays unchanged
    assert isinstance(actual.picks[0]["factors"]["integer"], float)
    assert isinstance(actual.picks[0]["factors"]["python-bool"], bool)
    by_code = {item["code"]: item for item in actual.picks}
    assert by_code["600000"]["pct_chg"] is None
    assert by_code["600001"]["pct_chg"] is None
    assert by_code["600003"]["close"] is None and by_code["600003"]["pct_chg"] is None
    assert by_code["600004"]["pct_chg"] == -100.0


@pytest.mark.parametrize("target,code", [
    ("2024-01-02", "600002"), ("2024-01-03", "600002"), ("2024-01-04", "600002"),
    ("2024-01-06", "600002"), ("2024-01-04", "missing"),
])
def test_cached_previous_row_preserves_first_day_missing_code_holiday_and_raw_rounding(target, code):
    panel = _wide_chunked_close()
    actual = screener._pct_chg(screener._cell(panel, target, code),
                               screener._previous_close_row(panel, target), code)
    assert actual == _old_pct_chg(panel, target, code)


def test_no_close_panel_keeps_missing_explanation():
    assert screener._previous_close_row(None, "2024-01-04") is None
    assert screener._pct_chg(None, None, "600000") is None


def test_holiday_screen_explains_the_same_last_session_and_keeps_formal_watch_order():
    close = _wide_chunked_close().iloc[:, :3]
    store = ExplanationStore({"close": close, "open": close * .99})
    arguments = {"codes": list(close.columns), "health_check": False,
                 "live_overlay": False, "adjust": "none"}
    session = screener.screen(store, ExplanationEngine(), trade_date="2024-01-04", **arguments)
    holiday = screener.screen(store, ExplanationEngine(), trade_date="2024-01-06", **arguments)
    assert holiday.trade_date == "2024-01-04"
    assert holiday.picks == session.picks and holiday.watch_picks == session.watch_picks
