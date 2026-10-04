"""Independent batching retains the exact ordinary whole-pool input semantics."""
from __future__ import annotations

from dataclasses import replace

import numpy as np
import pandas as pd
import pytest

from src.market import MarketStore
from src.strategy.application.audit import LookAheadError
from src.strategy.application.compute_runtime import project_result
from src.strategy.application.execution_profile import ExecutionProfile
from src.strategy.application.independent_screen import (
    IndependentRequest, prepare_independent_day, prepare_independent_range,
    _result_size, _share_projection_axes,
)
from src.strategy.application.screen_formula import build_formula_engine
from src.strategy.domain.base import SignalResult, StrategyError


class IndependentProbe:
    slug = "independent-probe"
    entry_timing = "next_open"
    calls = 0
    max_columns = 0

    def required_fields(self):
        return ("close", "volume")

    def min_bars(self):
        return 3

    def execution_profile(self, params=None):
        return ExecutionProfile(pure=True, causal=True, column_mode="independent", origin="sensitive")

    def compute(self, panels, params=None):
        self.calls += 1
        close = panels["close"]
        self.max_columns = max(self.max_columns, len(close.columns))
        ema = close.ewm(span=5, adjust=False).mean()
        mean = close.rolling(3).mean()
        bars = pd.DataFrame(np.repeat(np.arange(len(close))[:, None], len(close.columns), axis=1),
                            index=close.index, columns=close.columns)
        return SignalResult(close > ema, {"ema": ema, "mean": mean, "axis_bars": bars},
                            (close <= ema) & panels["volume"].gt(0))


class FutureProbe(IndependentProbe):
    def compute(self, panels, params=None):
        result = super().compute(panels, params)
        result.factors["future"] = panels["close"].apply(lambda col: col.max()) * pd.DataFrame(
            1.0, index=panels["close"].index, columns=panels["close"].columns)
        return result


class TwoFactorProbe(IndependentProbe):
    def min_bars(self):
        return 1

    def compute(self, panels, params=None):
        self.max_columns = max(self.max_columns, len(panels["close"].columns))
        return SignalResult(panels["close"] > 0,
                            {"price": panels["close"].copy(), "activity": panels["volume"].copy()})


class VolumeProbe(IndependentProbe):
    def required_fields(self):
        return ("volume",)

    def compute(self, panels, params=None):
        vol = panels["volume"]
        return SignalResult(vol > vol.shift(1), {"ema": vol.ewm(span=3).mean()})


class MetadataProbe(IndependentProbe):
    def execution_profile(self, params=None):
        return replace(super().execution_profile(params),
                       metadata_fields=("__basis", "__signal_calendar__"))

    def compute(self, panels, params=None):
        result = super().compute(panels, params)
        result.factors["basis"] = panels["__basis"]
        return result


class MutatingProbe(IndependentProbe):
    def __init__(self, store):
        self.store = store
        self.changed = False

    def compute(self, panels, params=None):
        result = super().compute(panels, params)
        if not self.changed:
            self.changed = True
            self.store.conn.execute("UPDATE quotes_daily SET close=close+0.1")
            self.store.conn.commit()
        return result


@pytest.fixture
def market(tmp_path):
    with MarketStore(tmp_path / "independent.db") as store:
        days = pd.bdate_range("2024-01-02", periods=30).strftime("%Y-%m-%d").tolist()
        for position, day in enumerate(days):
            for number in range(5):
                if number == 1 and position % 3 == 1:
                    continue
                if number == 2 and position < 15:
                    continue
                if number == 3 and position != 20:
                    continue
                # Fifth stock's quote exists but its required field is always null.
                close = None if number == 4 else 10 + position * 0.13 + number
                store.conn.execute(
                    "INSERT INTO quotes_daily(trade_date,code,open,high,low,close,volume,fetched_at) "
                    "VALUES(?,?,?,?,?,?,?,?)",
                    (day, f"30000{number}", close, close, close, close, 100 + position, day),
                )
        for code in ["300000", "300001", "300002"]:
            for position, factor in [(0, 1.0), (19, 1.4), (25, 1.7)]:
                store.conn.execute(
                    "INSERT INTO adjust_factors(code,trade_date,hfq_factor,fetched_at) VALUES(?,?,?,?)",
                    (code, days[position], factor, days[position]),
                )
        store.conn.commit()
        yield store, days


def _requests(days, *, start=0, codes=None, adjust="qfq", min_bars=3):
    return [IndependentRequest(day, days[start], day,
                               codes or [f"30000{number}" for number in range(5)],
                               min_bars, adjust) for day in days[9:]]


def _expected(store, engine, request):
    panels = store.load_panel(fields=engine.required_fields(), codes=list(request.codes),
                              start=request.start, end=request.end,
                              min_bars=request.min_bars, adjust=request.adjust)
    for name, value in request.metadata.items():
        panels[name] = value
    reference = panels[engine.required_fields()[0]]
    return project_result(engine.compute(panels), list(reference.index[-3:])), panels


def _same(actual, expected):
    pd.testing.assert_frame_equal(actual.signals, expected.signals, check_exact=True)
    assert actual.factors.keys() == expected.factors.keys()
    for name in expected.factors:
        pd.testing.assert_frame_equal(actual.factors[name], expected.factors[name], check_exact=True)
    if expected.watch_signals is None:
        assert actual.watch_signals is None
    else:
        pd.testing.assert_frame_equal(actual.watch_signals, expected.watch_signals, check_exact=True)


@pytest.mark.parametrize("adjust", ["none", "qfq", "hfq"])
def test_21_day_batch_equals_whole_pool_all_factors_and_inputs(market, adjust):
    store, days = market
    engine = IndependentProbe()
    requests = _requests(days, adjust=adjust)
    out = prepare_independent_range(store, engine, requests, chunk_size=2)
    assert engine.max_columns <= 2
    for request in requests:
        expected, panels = _expected(store, IndependentProbe(), request)
        _same(out[request.day].result, expected)
        for name in engine.required_fields():
            pd.testing.assert_frame_equal(out[request.day].raw_panels[name], panels[name].iloc[-3:])
        pd.testing.assert_index_equal(out[request.day].columns, panels["close"].columns)


def test_global_axis_includes_stock_removed_by_minbars(market):
    store, days = market
    # Only excluded stock quotes on day20. Its date remains part of all formulas.
    store.conn.execute("DELETE FROM quotes_daily WHERE trade_date=? AND code!='300003'", (days[20],))
    store.conn.commit()
    request = IndependentRequest(days[21], days[0], days[21], ("300000", "300003"), 3, "none")
    actual = prepare_independent_day(store, IndependentProbe(), request, chunk_size=1)
    expected, panels = _expected(store, IndependentProbe(), request)
    assert days[20] in panels["close"].index
    assert "300003" not in actual.columns
    _same(actual.result, expected)


def test_qfq_anchor_uses_global_last_quote_even_when_chunk_suspended(market):
    store, days = market
    store.conn.execute("DELETE FROM quotes_daily WHERE code='300001' AND trade_date>=?", (days[24],))
    store.conn.commit()
    request = _requests(days, codes=["300000", "300001"])[-1]
    actual = prepare_independent_day(store, IndependentProbe(), request, chunk_size=1)
    expected, panels = _expected(store, IndependentProbe(), request)
    _same(actual.result, expected)
    pd.testing.assert_frame_equal(actual.raw_panels["close"], panels["close"].iloc[-3:])


def test_changed_daily_origins_universes_and_reverse_requests(market):
    store, days = market
    requests = [IndependentRequest(day, days[i % 4], day,
                                   ("300000", "300001", "300002") if i % 2 else ("300000", "300003"),
                                   3, "none") for i, day in enumerate(days[9:])]
    out = prepare_independent_range(store, IndependentProbe(), list(reversed(requests)), chunk_size=1)
    for request in requests:
        expected, _ = _expected(store, IndependentProbe(), request)
        _same(out[request.day].result, expected)


def test_each_chunk_reads_numeric_history_once_for_21_days(market):
    store, days = market
    queries = []
    progress = []
    store.conn.set_trace_callback(queries.append)
    engine = IndependentProbe()
    prepare_independent_range(store, engine, _requests(days, adjust="none"), chunk_size=2,
                              on_progress=progress.append)
    store.conn.set_trace_callback(None)
    numeric = [query for query in queries if query.startswith("SELECT trade_date, code, close, volume ")]
    assert len(numeric) == 3
    assert progress == ["计算批次 1/3 · 2只 · 21日", "计算批次 2/3 · 2只 · 21日", "计算批次 3/3 · 1只 · 21日"]
    # Exact baseline is passed into guard; it is not computed for a second time.
    assert engine.calls < 3 * len(_requests(days)) * 3


def test_budget_shrinks_batches_and_rejects_unbounded_projection(market):
    store, days = market
    engine = IndependentProbe()
    prepare_independent_range(store, engine, _requests(days, adjust="none"), max_panel_cells=90)
    assert engine.max_columns == 1
    with pytest.raises(StrategyError, match="单股票历史"):
        prepare_independent_range(store, engine, _requests(days), max_panel_cells=89)
    with pytest.raises(StrategyError, match="投影结果"):
        prepare_independent_range(store, engine, _requests(days), max_result_bytes=1)


@pytest.mark.parametrize("profile", [ExecutionProfile(),
    ExecutionProfile(pure=True, causal=True, column_mode="coupled", origin="finite"),
    ExecutionProfile(pure=True, causal=True, column_mode="independent", origin="unknown")])
def test_unknown_or_coupled_engine_is_not_admitted(market, profile):
    store, days = market
    engine = IndependentProbe()
    engine.execution_profile = lambda params=None: profile
    with pytest.raises(StrategyError, match="列独立"):
        prepare_independent_day(store, engine, _requests(days)[-1])


def test_true_truncation_still_blocks_factor_only_future_read(market):
    store, days = market
    with pytest.raises(LookAheadError) as failure:
        prepare_independent_range(store, FutureProbe(), _requests(days, adjust="none"), chunk_size=1)
    assert any(item.check == "truncation" and item.severity == "block"
               for item in failure.value.report.findings)


def test_empty_codes_empty_survivors_and_request_validation(market):
    store, days = market
    request = _requests(days)[-1]
    for empty in [replace(request, codes=()), replace(request, min_bars=1000)]:
        out = prepare_independent_day(store, IndependentProbe(), empty)
        assert out.result.signals.empty and not len(out.columns)
    with pytest.raises(StrategyError, match="日期重复"):
        prepare_independent_range(store, IndependentProbe(), [request, request])
    with pytest.raises(StrategyError, match="越界"):
        prepare_independent_day(store, IndependentProbe(), replace(request, start=days[-1], end=days[0]))


@pytest.mark.parametrize("formula", ["EMA(CLOSE,5)", "BARSCOUNT(CLOSE)", "FILTER(CLOSE>0,3)"])
def test_real_dsl_uses_original_global_empty_rows(market, formula):
    store, days = market
    store.conn.execute("DELETE FROM quotes_daily WHERE trade_date=? AND code!='300003'", (days[20],))
    store.conn.commit()
    engine = build_formula_engine({
        "slug": "independent-dsl", "name": "independent-dsl",
        "code": f"VALUE:={formula}; PICK:" + ("VALUE;" if formula.startswith("FILTER") else "VALUE>0;"),
        "manifest": {"schema_version": 1, "entry_timing": "next_open", "min_bars": 5,
                     "factors": ["VALUE"], "output": {"signal": "PICK"}},
    })
    requests = _requests(days, codes=["300000", "300001", "300003"], adjust="none", min_bars=5)
    actual = prepare_independent_range(store, engine, requests, chunk_size=1)
    for request in requests:
        expected, _ = _expected(store, engine, request)
        _same(actual[request.day].result, expected)


def test_no_close_field_counts_minbars_on_first_required_field(market):
    store, days = market
    requests = _requests(days, adjust="none")
    engine = VolumeProbe()
    actual = prepare_independent_range(store, engine, requests, chunk_size=1)
    for request in requests:
        expected, panels = _expected(store, engine, request)
        _same(actual[request.day].result, expected)
        pd.testing.assert_index_equal(actual[request.day].columns, panels["volume"].columns)
    assert "300004" in actual[days[-1]].columns


def test_metadata_axis_and_original_calendar_are_passed_per_day(market):
    store, days = market
    basis = pd.DataFrame(3.0, index=pd.Index(days, name="trade_date"),
                         columns=pd.Index(["300000", "300001"], name="code"))
    request = IndependentRequest(days[-1], days[0], days[-1], basis.columns, 3, "none",
                                 {"__basis": basis, "__signal_calendar__": pd.Index(days)})
    actual = prepare_independent_day(store, MetadataProbe(), request, chunk_size=1)
    expected, _ = _expected(store, MetadataProbe(), request)
    _same(actual.result, expected)


def test_database_change_during_read_is_not_published(market):
    store, days = market
    with pytest.raises(StrategyError, match="发生变化"):
        prepare_independent_range(store, MutatingProbe(store), _requests(days, adjust="none"), chunk_size=1)


def test_requested_holiday_key_preserves_actual_input_end_fallback(market):
    store, days = market
    request = replace(_requests(days, adjust="none")[-1], day="2099-01-01")
    actual = prepare_independent_day(store, IndependentProbe(), request)
    expected, _ = _expected(store, IndependentProbe(), request)
    assert actual.result.signals.index[-1] == days[-1]
    _same(actual.result, expected)


def test_working_arrays_budget_reduces_batch_without_changing_results(market):
    store, days = market
    engine = IndependentProbe()
    engine.working_frames = lambda: 200
    request = _requests(days, adjust="none")[-1]
    actual = prepare_independent_day(
        store, engine, request, max_working_bytes=len(days) * 200 * 8,
    )
    assert engine.max_columns == 1
    expected, _ = _expected(store, IndependentProbe(), request)
    _same(actual.result, expected)
    with pytest.raises(StrategyError, match="内存预算"):
        prepare_independent_day(store, engine, request, max_working_bytes=1)


def test_normal_21_day_5500_stock_projection_fits_32mb_with_shared_axes():
    columns = [f"{300000 + i:06}" for i in range(5500)]
    calendar = pd.bdate_range("2026-09-01", periods=23).strftime("%Y-%m-%d").tolist()
    used = old_count = 0
    daily_parts = []
    for position in range(2, 23):
        rows = calendar[position - 2:position + 1]
        def frame(value, dtype=float):
            return pd.DataFrame(np.full((3, 5500), value, dtype=dtype),
                                index=pd.Index(rows, name="trade_date"),
                                columns=pd.Index(columns.copy(), name="code"))
        result = SignalResult(frame(True, bool), {"price": frame(1.0), "activity": frame(100.0)})
        raw = {"close": frame(1.0), "volume": frame(100.0)}
        frames = [result.signals, *result.factors.values(), *raw.values()]
        old_count += 512 + sum(value.to_numpy(copy=False).nbytes
                              + value.index.memory_usage(deep=True)
                              + value.columns.memory_usage(deep=True) for value in frames)
        _share_projection_axes(result, raw)
        assert all(value.index is result.signals.index and value.columns is result.signals.columns
                   for value in frames)
        assert not np.shares_memory(raw["close"].to_numpy(), result.factors["price"].to_numpy())
        used += _result_size(result, raw)
        daily_parts.append((result, raw))
        raw["close"].iloc[0, 0] = -99
        assert result.factors["price"].iloc[0, 0] == 1
    assert old_count > 32_000_000
    assert 11_000_000 < used < 32_000_000
    assert len(daily_parts) == 21


def test_shared_projection_axes_preserve_different_names_dtypes_and_stock_order():
    basis = pd.DataFrame(np.arange(6, dtype=float).reshape(3, 2),
                         index=pd.Index([0, 1, 2], dtype="int64", name="day"),
                         columns=pd.Index(["a", "b"], name="code"))
    renamed = basis.copy()
    renamed.index.name = "different"
    same_renamed = renamed.copy()
    different_dtype = basis.copy()
    different_dtype.index = pd.Index([0, 1, 2], dtype="int32", name="day")
    different_order = basis.loc[:, ["b", "a"]].copy()
    result = SignalResult(basis > 0, {"renamed": renamed, "same_renamed": same_renamed,
                                     "dtype": different_dtype, "order": different_order}, basis < 2)
    raw = {"close": basis.copy()}
    expected = {name: frame.copy(deep=True) for name, frame in result.factors.items()}
    _share_projection_axes(result, raw)
    assert raw["close"].index is result.signals.index
    assert result.watch_signals.columns is result.signals.columns
    assert result.factors["renamed"].index is result.factors["same_renamed"].index
    assert result.factors["renamed"].index is not result.signals.index
    assert result.factors["dtype"].index is not result.signals.index
    assert result.factors["order"].columns is not result.signals.columns
    for name, value in result.factors.items():
        pd.testing.assert_frame_equal(value, expected[name], check_exact=True)


def test_real_64_chunks_keep_two_factor_raw_values_and_shared_join_axes(tmp_path):
    codes = [f"{300000 + i:06}" for i in range(64)]
    days = pd.bdate_range("2026-09-01", periods=8).strftime("%Y-%m-%d").tolist()
    with MarketStore(tmp_path / "64-chunks.db") as store:
        store.upsert_instruments({"code": code, "name": "fixture", "market": "sz", "board": "chi_next",
                                  "instrument_type": "STOCK", "list_date": "2015-01-01"} for code in codes)
        store.conn.executemany(
            "INSERT INTO quotes_daily(trade_date,code,open,high,low,close,volume,source,fetched_at) "
            "VALUES(?,?,?,?,?,?,?,?,?)",
            [(day, code, float(position + 1), float(position + 1), float(position + 1),
              float(position + 1), float(position + 100), "fixture", day)
             for position, day in enumerate(days) for code in codes],
        )
        store.conn.commit()
        engine, progress = TwoFactorProbe(), []
        request = IndependentRequest(days[-1], days[0], days[-1], codes, 1, "none")
        actual = prepare_independent_day(store, engine, request, chunk_size=1,
                                         max_result_bytes=32_000_000, on_progress=progress.append)
        expected, panels = _expected(store, TwoFactorProbe(), request)
        _same(actual.result, expected)
        assert len(progress) == 64 and engine.max_columns == 1
        frames = [actual.result.signals, *actual.result.factors.values(), *actual.raw_panels.values()]
        assert all(frame.index is actual.result.signals.index and frame.columns is actual.result.signals.columns
                   for frame in frames)
        assert actual.columns is actual.result.signals.columns
        for name, frame in actual.raw_panels.items():
            pd.testing.assert_frame_equal(frame, panels[name].iloc[-3:], check_exact=True)
        assert not np.shares_memory(actual.raw_panels["close"].to_numpy(), actual.result.factors["price"].to_numpy())
        with pytest.raises(StrategyError, match="投影结果"):
            prepare_independent_day(store, TwoFactorProbe(), request, chunk_size=1, max_result_bytes=1)
