"""One physical hash pass must still certify every actual prefix and audit input."""
from types import SimpleNamespace
import sqlite3

import numpy as np
import pandas as pd
import pytest

from src.strategy.application import audit, compute_runtime as runtime
from src.strategy.application.execution_profile import ExecutionProfile


class Engine:
    slug = "prefix-identity"
    entry_timing = "next_open"
    def required_fields(self):
        return ("close", "volume")


def _panels():
    dates = pd.bdate_range("2026-01-01", periods=60).strftime("%Y-%m-%d")
    columns = pd.Index(["000001", "600001", "600002"], name="code")
    close = pd.DataFrame(np.arange(180, dtype=float).reshape(60, 3), index=dates, columns=columns)
    close.iloc[10, 0] = -0.0
    close.iloc[12:15, 1] = np.nan
    return {"close": close, "volume": close * 100, "__calendar": dates,
            "__signal_calendar__": dates, "__status": {"000001": {"name": "test"}}}


@pytest.mark.parametrize("layout", ["C", "F", "strided", "mixed"])
def test_streamed_prefix_keys_equal_each_independently_hashed_truncation(layout):
    panels = _panels()
    if layout in ("C", "F"):
        for name in ("close", "volume"):
            original = panels[name]
            panels[name] = pd.DataFrame(np.array(original, order=layout), index=original.index, columns=original.columns)
    elif layout == "strided":
        panels.update({name: panels[name].iloc[::2] for name in ("close", "volume")})
    else:
        panels["volume"]["000001"] = np.arange(len(panels["volume"]), dtype=np.int64)
    profile = ExecutionProfile(pure=True, causal=True, metadata_fields=("__signal_calendar__", "__status", "missing"))
    dates = list(panels["close"].index)
    requested = list(reversed(dates[-22:])) + ["1999-01-01", "2099-01-01"]
    engine = Engine()
    actual = runtime._causal_input_keys(engine, panels, {"period": 10}, profile, requested)
    expected = {day: runtime._input_key(engine, panels, {"period": 10}, profile, day, causal=True)
                for day in requested}
    assert actual == expected


def test_prefix_keys_still_change_with_inplace_data_dtype_axis_and_metadata_mutations():
    panels, engine = _panels(), Engine()
    profile = ExecutionProfile(pure=True, causal=True, metadata_fields=("__status",))
    dates = list(panels["close"].index[-3:])
    previous = runtime._causal_input_keys(engine, panels, {}, profile, dates)
    panels["close"].iloc[0, 0] = -10
    changed = runtime._causal_input_keys(engine, panels, {}, profile, dates)
    assert all(changed[day] != previous[day] for day in dates)
    for mutate in (
        lambda: panels["close"].rename_axis("different", inplace=True),
        lambda: panels["__status"]["000001"].update(name="changed"),
        lambda: panels.update(volume=panels["volume"].astype(np.float32)),
    ):
        previous = changed
        mutate()
        changed = runtime._causal_input_keys(engine, panels, {}, profile, dates)
        assert all(changed[day] != previous[day] for day in dates)


def test_multiple_dates_hash_the_numeric_content_once_per_field(monkeypatch):
    panels, engine = _panels(), Engine()
    bytes_read = []
    original = runtime.np.ascontiguousarray
    def tracked(array, *args, **kwargs):
        bytes_read.append(array.nbytes)
        return original(array, *args, **kwargs)
    monkeypatch.setattr(runtime.np, "ascontiguousarray", tracked)
    dates = list(panels["close"].index[-22:])
    assert all(runtime._causal_input_keys(engine, panels, {}, ExecutionProfile(), dates).values())
    assert sum(bytes_read) == panels["close"].to_numpy().nbytes + panels["volume"].to_numpy().nbytes


def test_non_temporal_metadata_is_serialized_once_per_call_and_inplace_changes_remain_visible(monkeypatch):
    panels, engine = _panels(), Engine()
    profile = ExecutionProfile(pure=True, causal=True, metadata_fields=("__status", "__signal_calendar__"))
    dates = list(panels["close"].index[-22:])
    expected = {day: runtime._input_key(engine, panels, {}, profile, day, causal=True) for day in dates}
    calls = []
    original = runtime.json.dumps

    def tracked(value, *args, **kwargs):
        if value is panels["__status"]:
            calls.append(value["000001"]["name"])
        return original(value, *args, **kwargs)

    monkeypatch.setattr(runtime.json, "dumps", tracked)
    actual = runtime._causal_input_keys(engine, panels, {}, profile, dates)
    assert actual == expected
    assert calls == ["test"]
    panels["__status"]["000001"]["name"] = "changed"
    changed = runtime._causal_input_keys(engine, panels, {}, profile, dates)
    assert calls == ["test", "changed"]
    assert all(changed[day] != actual[day] for day in dates)


def test_static_validation_reuses_exact_source_only_and_does_not_leak_findings(monkeypatch):
    source = {"code": "class Strategy:\n    def compute(self, panels):\n        return panels['close']\n"}
    calls = []
    original = audit.audit_source
    def validate(*args, **kwargs):
        calls.append((args, kwargs))
        return original(*args, **kwargs)
    monkeypatch.setattr(audit.inspect, "getsource", lambda _type: source["code"])
    monkeypatch.setattr(audit, "audit_source", validate)
    store = SimpleNamespace(conn=sqlite3.connect(":memory:"))
    engine = Engine()
    try:
        with runtime.computation_scope(store):
            first = audit.audit_engine_source(engine)
            first.findings.append(audit.AuditFinding("caller", "block", "mutable"))
            assert not audit.audit_engine_source(engine).failed
            assert len(calls) == 1
            engine.entry_timing = "open"
            assert audit.audit_engine_source(engine).failed
            assert len(calls) == 2
            source["code"] = "class Strategy:\n    def compute(self, panels):\n        return 1\n"
            assert not audit.audit_engine_source(engine).failed
            assert len(calls) == 3
        with runtime.computation_scope(store):
            audit.audit_engine_source(engine)
            assert len(calls) == 4
    finally:
        store.conn.close()
