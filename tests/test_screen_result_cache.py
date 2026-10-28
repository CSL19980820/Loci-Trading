"""Persistent screen results require exact market, code and parameter identity."""
from __future__ import annotations

import json
from types import SimpleNamespace

from src.strategy.application.screen_result_cache import (
    load_screen_result,
    save_screen_result,
)
from src.strategy.application.screener import ScreenResult


def _store(tmp_path, revision="rev-1"):
    store = SimpleNamespace(db_path=tmp_path / "market.db")
    store.revision = revision
    store.market_revision = lambda: store.revision
    return store


def _result(revision="rev-1"):
    return ScreenResult(
        strategy_slug="cache-test",
        strategy_revision="cache-test:v1",
        trade_date="2024-01-05",
        elapsed_seconds=9.0,
        universe_size=1,
        data_snapshot={"market_revision": revision, "start": "2024-01-03"},
    )


def _rw(store, *, codes=None, params=None):
    return {
        "params": params,
        "codes": codes,
        "universe": {"preset": "default_a_share"},
        "adjust": "hfq",
        "extra_bars": 20,
        "health_check": False,
        "skip_universe_safety": False,
    }


def test_screen_result_cache_round_trip_and_revision_invalidation(tmp_path):
    store = _store(tmp_path)
    engine = SimpleNamespace(slug="cache-test", strategy_revision="cache-test:v1")
    save_screen_result(
        store, engine, _result(), **_rw(store, codes=["600001"]),
    )
    loaded = load_screen_result(
        store, engine, "2024-01-05", **_rw(store, codes=["600001"]),
    )
    assert loaded is not None
    assert loaded.cache_hit
    assert loaded.picks == [] and loaded.universe_size == 1
    assert loaded.elapsed_seconds < 1
    health_checked = _rw(store, codes=["600001"]) | {"health_check": True}
    assert load_screen_result(
        store, engine, "2024-01-05", **health_checked,
    ) is not None

    store.revision = "rev-2"
    assert load_screen_result(
        store, engine, "2024-01-05", **_rw(store, codes=["600001"]),
    ) is None


def test_screen_result_cache_distinguishes_codes_and_params(tmp_path):
    store = _store(tmp_path)
    engine = SimpleNamespace(slug="cache-test", strategy_revision="cache-test:v1")
    save_screen_result(
        store, engine, _result(), **_rw(store, codes=["600001"], params={"mode": "a"}),
    )
    assert load_screen_result(
        store, engine, "2024-01-05",
        **_rw(store, codes=["600002"], params={"mode": "a"}),
    ) is None
    assert load_screen_result(
        store, engine, "2024-01-05",
        **_rw(store, codes=["600001"], params={"mode": "b"}),
    ) is None


def test_corrupt_screen_result_cache_is_a_safe_miss(tmp_path):
    store = _store(tmp_path)
    engine = SimpleNamespace(slug="cache-test", strategy_revision="cache-test:v1")
    save_screen_result(
        store, engine, _result(), **_rw(store, codes=["600001"]),
    )
    path = next((tmp_path / "cache" / "screen-results").glob("*.json"))
    path.write_text(json.dumps({"key": {}, "result": []}), encoding="utf-8")
    assert load_screen_result(
        store, engine, "2024-01-05", **_rw(store, codes=["600001"]),
    ) is None
