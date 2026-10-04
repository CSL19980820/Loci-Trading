"""Input equivalence, real truncation audits and task/version boundaries."""
from dataclasses import replace
import sqlite3
from types import SimpleNamespace
import textwrap

import pandas as pd
import numpy as np
import pytest

from src.strategy.application.audit import audit_truncation
from src.strategy.application.compute_runtime import (
    computation_scope, compute_result, range_compute_end, truncate_panels, _SCOPE,
)
from src.strategy.application.execution_profile import ExecutionProfile
from src.strategy.domain.base import SignalResult


class Engine:
    entry_timing = "next_open"
    slug = "test-runtime"
    calls = 0
    profile = ExecutionProfile(pure=True, causal=True, origin="sensitive")

    def required_fields(self):
        return ("close",)

    def min_bars(self):
        return 1

    def execution_profile(self, params=None):
        return self.profile

    def compute(self, panels, params=None):
        self.calls += 1
        close = panels["close"]
        return SignalResult(close > (params or {}).get("threshold", 0), {"value": close.cumsum()})


def panels(width=3):
    return {"close": pd.DataFrame([[float(i + j) for j in range(width)] for i in range(10)],
                                 index=[f"2026-09-{i + 1:02}" for i in range(10)],
                                 columns=[str(j) for j in range(width)])}


def store():
    return SimpleNamespace(conn=sqlite3.connect(":memory:"))


def test_one_shot_execution_does_not_hash_or_populate_reuse_cache(monkeypatch):
    from src.strategy.application import compute_runtime as runtime

    engine, market, data = Engine(), store(), panels()
    day = data["close"].index[-1]

    def forbidden(*args, **kwargs):
        raise AssertionError("one-shot computation must not fingerprint inputs")

    monkeypatch.setattr(runtime, "_input_digest", forbidden)
    try:
        with computation_scope(market):
            first = compute_result(engine, data, dates=[day], reuse=False)
            first.factors["value"].iloc[0, 0] = -999
            second = compute_result(engine, data, dates=[day], reuse=False)
            assert engine.calls == 2
            assert second.factors["value"].iloc[0, 0] != -999
            assert list(second.signals.index) == [day]
            assert not _SCOPE.get().results and _SCOPE.get().bytes_used == 0
    finally:
        market.conn.close()


def test_full_pool_month_prime_fits_budget_and_keeps_earliest_causal_row():
    class Wide(Engine):
        def compute(self, panels, params=None):
            self.calls += 1
            close = panels["close"]
            return SignalResult(close > 0, {str(n): close * (n + 1) for n in range(13)})

    dates = pd.date_range("2026-08-01", periods=40).strftime("%Y-%m-%d")
    close = pd.DataFrame(np.ones((40, 3044)), index=dates,
                         columns=[f"{n:06}" for n in range(3044)])
    data, engine = {"close": close}, Wide()
    with computation_scope(store(), max_bytes=64_000_000):
        compute_result(engine, data, dates=list(dates))
        scope = _SCOPE.get()
        assert len(scope.results) == 80 and len(scope.result_refs) == 40
        assert 0 < scope.bytes_used < 64_000_000
        actual = compute_result(engine, truncate_panels(data, dates[2]), dates=list(dates[:3]))
        assert engine.calls == 1
        pd.testing.assert_frame_equal(actual.factors["12"], close.iloc[:3] * 13)
        scope.max_bytes = scope.results[next(iter(scope.results))][1] * 2
        compute_result(engine, {"close": close * 2}, dates=[dates[-1]])
        assert scope.bytes_used <= scope.max_bytes
        assert all(count > 0 for count, _size in scope.result_refs.values())


def test_range_causal_outputs_are_reused_but_audit_runs_real_truncation():
    engine = Engine()
    data = panels()
    day = data["close"].index[-2]
    with computation_scope(store()):
        compute_result(engine, data, dates=[day])
        truncated = truncate_panels(data, day)
        compute_result(engine, truncated, dates=[day])
        assert engine.calls == 1
        compute_result(engine, truncated, dates=[day], audit=True)
        assert engine.calls == 2
        compute_result(engine, truncated, dates=[day], audit=True)
        assert engine.calls == 2


def test_coupled_new_pool_and_sensitive_origin_reprime_without_skipping_real_audit():
    class Ranked(Engine):
        def compute(self, panels, params=None):
            self.calls += 1
            close = panels["close"]
            rank = close.rank(axis=1, ascending=False)
            return SignalResult(rank == 1, {"rank": rank, "sum": close.cumsum()})

    engine, market = Ranked(), store()
    full = panels(2)
    dates = list(full["close"].index)
    old_full = {"close": full["close"][["0"]]}
    first = truncate_panels(old_full, dates[6])
    try:
        with computation_scope(market, dates[6:]):
            assert range_compute_end(engine, first, {}) == dates[-1]
            compute_result(engine, old_full, {}, dates=dates[4:])
            old_result = compute_result(engine, first, {}, dates=dates[4:7])
            assert engine.calls == 1 and range_compute_end(engine, first, {}) is None

            new_pool = truncate_panels(full, dates[7])
            assert range_compute_end(engine, new_pool, {}) == dates[-1]
            compute_result(engine, full, {}, dates=dates[4:])
            current = compute_result(engine, new_pool, {}, dates=dates[5:8])
            assert engine.calls == 2 and range_compute_end(engine, new_pool, {}) is None
            expected = Ranked().compute(new_pool)
            pd.testing.assert_frame_equal(current.signals, expected.signals.iloc[-3:], check_exact=True)
            for name in expected.factors:
                pd.testing.assert_frame_equal(current.factors[name], expected.factors[name].iloc[-3:], check_exact=True)
            assert old_result.signals.iloc[-1].to_dict() == {"0": True}
            assert current.signals.iloc[-1].to_dict() == {"0": False, "1": True}

            report = audit_truncation(engine, new_pool, params={}, baseline=current)
            assert not report.failed and engine.calls == 4
            changed_origin = {"close": new_pool["close"].iloc[1:]}
            assert range_compute_end(engine, changed_origin, {}) == dates[-1]
            compute_result(engine, changed_origin, {}, dates=dates[5:8])
            assert engine.calls == 5
            expected_origin = Ranked().compute(changed_origin)
            actual_origin = compute_result(engine, changed_origin, {}, dates=dates[5:8])
            assert engine.calls == 5
            for name in expected_origin.factors:
                pd.testing.assert_frame_equal(actual_origin.factors[name], expected_origin.factors[name].iloc[-3:],
                                              check_exact=True)
    finally:
        market.conn.close()


def test_engine_can_decline_range_prime_without_changing_daily_results_or_audits():
    engine, market = Engine(), store()
    engine.range_prime_enabled = False
    full = panels()
    dates = list(full["close"].index)
    try:
        with computation_scope(market, dates[6:]):
            for position in (6, 7):
                daily = {"close": full["close"].iloc[position - 5:position + 1]}
                assert range_compute_end(engine, daily, {}) is None
                actual = compute_result(engine, daily)
                expected = Engine().compute(daily)
                pd.testing.assert_frame_equal(actual.signals, expected.signals.iloc[-3:], check_exact=True)
                pd.testing.assert_frame_equal(actual.factors["value"], expected.factors["value"].iloc[-3:],
                                              check_exact=True)
                assert not audit_truncation(engine, daily, baseline=actual).failed
                calls = engine.calls
                compute_result(engine, daily)
                assert engine.calls == calls
            assert not _SCOPE.get().primed_layouts
            # Declining one optimization must not consume its normal layout slot.
            engine.range_prime_enabled = True
            assert range_compute_end(engine, daily, {}) == dates[-1]
            assert range_compute_end(engine, daily, {}) is None
    finally:
        market.conn.close()


def test_pure_projection_dispatch_keeps_causal_hits_separate_from_real_audit_inputs():
    class Projected(Engine):
        def __init__(self):
            self.input_lengths = []

        def compute(self, panels, params=None):
            pytest.fail("Projection-capable pure engines must not build the full output first.")

        def compute_projection(self, panels, params, requested):
            self.calls += 1
            close = panels["close"]
            self.input_lengths.append(len(close))
            return SignalResult(close.loc[requested] > 0,
                                {"value": close.cumsum().loc[requested]})

    engine, data, market = Projected(), panels(), store()
    day = data["close"].index[-2]
    truncated = truncate_panels(data, day)
    try:
        with computation_scope(market):
            expected = compute_result(engine, data, dates=[day])
            cached = compute_result(engine, truncated, dates=[day])
            assert engine.calls == 1 and engine.input_lengths == [10]
            pd.testing.assert_frame_equal(cached.factors["value"], expected.factors["value"], check_exact=True)
            audited = compute_result(engine, truncated, dates=[day], audit=True)
            assert engine.calls == 2 and engine.input_lengths == [10, 9]
            pd.testing.assert_frame_equal(audited.signals, expected.signals, check_exact=True)
            pd.testing.assert_frame_equal(audited.factors["value"], expected.factors["value"], check_exact=True)
            compute_result(engine, truncated, dates=[day], audit=True)
            assert engine.calls == 2
    finally:
        market.conn.close()


def test_three_exact_audit_rows_hash_the_complete_input_only_once_per_request(monkeypatch):
    from src.strategy.application import compute_runtime

    original = compute_runtime._input_digest
    digests = []
    def tracked(*args, **kwargs):
        digests.append(kwargs["causal"])
        return original(*args, **kwargs)
    monkeypatch.setattr(compute_runtime, "_input_digest", tracked)
    engine, data, market = Engine(), panels(), store()
    requested = list(data["close"].index[-3:])
    try:
        with computation_scope(market):
            actual = compute_result(engine, data, dates=requested, audit=True)
            assert digests == [False] and engine.calls == 1
            assert list(actual.signals.index) == requested
            compute_result(engine, data, dates=requested, audit=True)
            assert digests == [False, False] and engine.calls == 1
    finally:
        market.conn.close()


@pytest.mark.parametrize("change", ["price", "params", "columns", "axis_name", "origin", "metadata"])
def test_actual_input_boundaries_never_reuse_incompatible_result(change):
    engine = Engine()
    if change == "metadata":
        engine.profile = replace(engine.profile, metadata_fields=("__names",))
    data = panels()
    data["__names"] = {"0": "old"}
    day = data["close"].index[-1]
    with computation_scope(store()):
        compute_result(engine, data, dates=[day])
        altered = {**data, "close": data["close"].copy()}
        params = None
        if change == "price":
            altered["close"] *= 0.5  # per-target qfq anchor
        elif change == "params":
            params = {"threshold": 10}
        elif change == "columns":
            altered["close"] = altered["close"].iloc[:, :-1]
        elif change == "axis_name":
            altered["close"].index.name = "different"
        elif change == "origin":
            altered["close"] = altered["close"].iloc[1:]
        else:
            altered["__names"] = {"0": "new"}
        compute_result(engine, altered, params, dates=[day])
        assert engine.calls == 2


def test_revision_transaction_budget_scope_and_returned_copy():
    engine, data, market = Engine(), panels(), store()
    with computation_scope(market):
        result = compute_result(engine, data)
        result.factors["value"].iloc[-1, 0] = -999
        assert compute_result(engine, data).factors["value"].iloc[-1, 0] != -999
        cached = compute_result(engine, data)
        cached.factors["value"].columns.name = "caller-change"
        assert compute_result(engine, data).factors["value"].columns.name is None
        assert engine.calls == 1
        market.conn.execute("CREATE TABLE changes(value)")
        market.conn.execute("INSERT INTO changes VALUES(0)")
        market.conn.commit()
        compute_result(engine, data)
        assert engine.calls == 2
        market.conn.execute("INSERT INTO changes VALUES(1)")
        compute_result(engine, data)
        compute_result(engine, data)
        assert engine.calls == 4
        market.conn.rollback()
    assert _SCOPE.get() is None
    with computation_scope(market, max_bytes=1):
        compute_result(engine, data)
        compute_result(engine, data)
        assert _SCOPE.get().bytes_used == 0
    assert engine.calls == 6


def test_factor_only_future_read_is_blocked_on_full_cross_section():
    class FutureFactor(Engine):
        def compute(self, panels, params=None):
            close = panels["close"]
            factor = close.copy()
            factor.iloc[:, -1] = close.iloc[-1, -1]
            return SignalResult(close > -1, {"future": factor})
    with computation_scope(store()):
        report = audit_truncation(FutureFactor(), panels(260))
        assert report.failed and report.findings[0].detail[0]["factor"] == "future"


def test_coupled_rank_keeps_complete_universe_and_causal_calendar_is_truncated(monkeypatch):
    class Ranked(Engine):
        def compute(self, panels, params=None):
            close = panels["close"]
            rank = close.rank(axis=1, ascending=False)
            return SignalResult(rank == 1, {"rank": rank})
    data = panels(260)
    data["__signal_calendar__"] = pd.Index(data["close"].index)
    cut = truncate_panels(data, "2026-09-07")
    assert len(cut["__signal_calendar__"]) == 7
    from src.strategy.application import audit
    original = audit.inspect.getsource
    monkeypatch.setattr(audit.inspect, "getsource", lambda value: textwrap.dedent(original(value)))
    with computation_scope(store()):
        assert not audit.guard_strategy(Ranked(), data).failed
