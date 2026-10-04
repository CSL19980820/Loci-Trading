"""用隔离行情仓验证指标目录、复权、区间选股与回测共用链路。"""
from __future__ import annotations

import pandas as pd
import pytest

from src.backtest.application.engine import BacktestConfig
from src.backtest.application.runner import prepare_backtest_context
from src.market import MarketStore
from src.market.application.screen_live import overlay_live_day
from src.ops import OpsStore
from src.strategy import describe_all, get
from src.strategy.application.price_constraints import attach_raw_limit_close
from src.strategy.application.screen_run_prepare import range_read_scope
from src.strategy.application.screener import screen


SLUG = "impulse-inside-breakout-v1"
CODES = ["000001", "300001", "000002", "300002", "688001", "301001", "301002"]


@pytest.fixture
def market_fixture(tmp_path):
    dates = pd.bdate_range("2025-01-02", periods=215).strftime("%Y-%m-%d").tolist()
    path = tmp_path / "market.db"
    with MarketStore(path) as store:
        store.upsert_instruments(
            {"code": code, "name": f"样本{code}", "market": "sz" if code[0] in "03" else "sh",
             "board": "chi_next" if code.startswith("30") else "star" if code.startswith("688") else "main",
             "instrument_type": "STOCK", "list_date": "2010-01-01"}
            for code in CODES
        )
        rows = []
        pattern = {
            195: (10.0, 10.9, 9.9, 10.8, 3000.0),
            196: (10.3, 10.7, 10.1, 10.4, 800.0),
            197: (10.6, 10.8, 10.2, 10.5, 1100.0),
            198: (10.5, 10.8, 10.3, 10.6, 900.0),
            199: (10.6, 11.05, 10.5, 11.0, 1800.0),
        }
        for position, day in enumerate(dates):
            for code in CODES:
                values = pattern.get(position, (9.9, 10.1, 9.8, 10.0, 1000.0))
                if position == 199 and code in ("000002", "300002", "301002"):
                    limit = 11.66 if code == "000002" else 12.72
                    values = (10.6, limit, 10.5, limit, 1800.0)
                open_, high, low, close, volume = values
                rows.append((day, code, open_, high, low, close, volume, close * volume, "fixture", day))
        store.conn.executemany(
            "INSERT INTO quotes_daily(trade_date,code,open,high,low,close,volume,amount,source,fetched_at) "
            "VALUES(?,?,?,?,?,?,?,?,?,?)", rows,
        )
        store.conn.commit()
        store.rebuild_calendar()
        for code in CODES:
            store.upsert_adjust_factors(
                code, pd.DataFrame({"date": [dates[0], dates[205]], "hfq_factor": [2.0, 4.0]}),
                source="fixture",
            )
    return path, dates


def test_registered_catalog_and_manual_indicator_does_not_create_a_job(tmp_path):
    engine = get(SLUG)
    info = next(item for item in describe_all() if item["slug"] == SLUG)
    assert info["name"] == "大阳三日缩量突破"
    assert info["source_kind"] == "builtin" and info["entry_timing"] == "next_open"
    assert info["min_bars"] == 180
    assert info["backtest_metrics"] is None
    assert info["backtest_config"]["hold_days"] == 3
    assert info["backtest_config"]["mode"] == "trade"
    assert "universe" not in info["backtest_config"]
    archived = next(row for row in info["version_history"] if row["version"] == "v1.3")
    assert archived["status"] == "archived"
    assert archived["backtest_metrics"]["trades"] > 0
    assert archived["backtest_config"]["universe"]["boards"] == ["chi_next"]
    assert info["version"] == "v1.4" and info["strategy_revision"].endswith(":5")
    assert engine.screen_top_n == 2 and engine.screen_rank_factor == "score"
    assert engine.screen_managed_job is False
    assert getattr(engine, "default_universe", None) is None
    with OpsStore(tmp_path / "ops.db") as store:
        store.ensure_managed_screen_jobs()
        assert store.get_job_by_name(f"screen:{SLUG}") is None


@pytest.mark.parametrize("adjust", ["none", "qfq", "hfq"])
def test_store_screen_and_backtest_use_same_signals_and_raw_limits(market_fixture, adjust):
    path, dates = market_fixture
    day = dates[199]
    with MarketStore(path) as store:
        selected = screen(store, SLUG, trade_date=day, codes=CODES, adjust=adjust,
                          health_check=False, live_overlay=False)
        assert [pick["code"] for pick in selected.picks] == ["000001", "300001"]
        assert selected.picks[0]["factors"]["涨停价"] == 11.66
        assert selected.picks[1]["factors"]["涨停价"] == 12.72
        assert selected.universe["boards"] == ["main", "chi_next", "star"]
        context = prepare_backtest_context(
            store, SLUG, start=day, end=day, codes=CODES, adjust=adjust,
            config=BacktestConfig(hold_days=1, valuation_end=dates[-1]),
        )
        signals = context["signals"].loc[day]
        assert signals.index[signals].tolist() == [pick["code"] for pick in selected.picks]
        assert context["execution_adjust"] == "none"
        for field in ("open", "high", "low", "close"):
            raw = context["panels"][f"__raw_{field}"]
            pd.testing.assert_frame_equal(raw, context["execution_panels"][field])
        if adjust != "none":
            assert not context["panels"]["close"].equals(context["panels"]["__raw_close"])


def test_explicit_main_and_star_codes_are_evaluated_from_the_unified_pool(market_fixture):
    path, dates = market_fixture
    with MarketStore(path) as store:
        result = screen(store, SLUG, trade_date=dates[199], codes=["000001", "000002", "688001"],
                        health_check=False, live_overlay=False)
    assert [pick["code"] for pick in result.picks] == ["000001", "688001"]
    assert result.universe["boards"] == ["main", "chi_next", "star"]


def test_range_screen_keeps_raw_ohlc_and_matches_independent_dates(market_fixture):
    path, dates = market_fixture
    days = dates[199:202]
    engine = get(SLUG)
    options = dict(codes=CODES, health_check=False, live_overlay=False)
    with MarketStore(path) as store:
        expected = [screen(store, engine, trade_date=day, **options) for day in days]
        with range_read_scope(store, engine, days, None, codes=CODES):
            actual = [screen(store, engine, trade_date=day, **options) for day in days]
    assert expected[0].picks
    for daily, ranged in zip(expected, actual):
        assert daily.picks == ranged.picks
        assert daily.watch_picks == ranged.watch_picks


def test_ranked_cap_is_shared_by_screen_backtest_and_persisted_scores(market_fixture, tmp_path):
    from src.ledger import PalaceStore
    from src.strategy.application.persist import persist_screen_candidates

    path, dates = market_fixture
    day = dates[199]
    with MarketStore(path) as store:
        # Higher-volume main-board shapes compete across the complete resolved pool.
        volumes = {"000001": 4000, "000002": 4000, "300001": 2800,
                   "300002": 2400, "301001": 2000, "301002": 1800}
        for code, volume in volumes.items():
            store.conn.execute(
                "UPDATE quotes_daily SET open=10.6,high=11.05,low=10.5,close=11.0,volume=?,amount=? "
                "WHERE trade_date=? AND code=?", (volume, volume * 11, day, code),
            )
        store.conn.commit()
        selected = screen(store, SLUG, trade_date=day, codes=CODES, health_check=False, live_overlay=False)
        assert [pick["code"] for pick in selected.picks] == ["000001", "000002"]
        assert selected.picks[0]["factors"]["score"] == selected.picks[1]["factors"]["score"]
        context = prepare_backtest_context(
            store, SLUG, start=day, end=day, codes=CODES,
            config=BacktestConfig(hold_days=1, valuation_end=dates[-1]),
        )
        row = context["signals"].loc[day]
        assert set(row.index[row]) == {pick["code"] for pick in selected.picks}
    ledger_path = tmp_path / "palace.db"
    persisted = persist_screen_candidates(selected, palace_db=str(ledger_path), source="api:screen_backfill")
    assert persisted["written"] == 2 and not persisted["failed"]
    with PalaceStore(ledger_path) as ledger:
        rows = ledger.conn.execute("SELECT code,score,strategy_revision FROM candidate_reviews").fetchall()
    assert {row[0]: row[1] for row in rows} == {
        pick["code"]: pick["factors"]["score"] for pick in selected.picks
    }
    assert all(row[2] == selected.strategy_revision for row in rows)


def test_reviewed_builtin_daily_path_only_computes_target_and_keeps_data_rules(market_fixture, monkeypatch):
    from src.strategy.application import audit, compute_runtime, screener

    path, dates = market_fixture
    calls, progress = [], []
    original = screener.compute_result

    def tracked(engine, panels, params=None, **options):
        calls.append(options)
        return original(engine, panels, params, **options)

    def forbidden(*args, **kwargs):
        raise AssertionError("daily builtin screening must not repeat version validation")

    monkeypatch.setattr(screener, "compute_result", tracked)
    monkeypatch.setattr(audit, "audit_truncation", forbidden)
    monkeypatch.setattr(compute_runtime, "_input_digest", forbidden)
    with MarketStore(path) as store:
        result = screen(store, SLUG, trade_date=dates[199], codes=CODES,
                        health_check=False, live_overlay=False,
                        on_progress=lambda phase, *_: progress.append(phase))
    assert calls == [{"dates": [dates[199]], "reuse": False}]
    assert result.data_snapshot["strategy_validation"] == "release-tested"
    assert "audit" not in progress
    assert [pick["code"] for pick in result.picks] == ["000001", "300001"]
    assert all(pick["factors"]["距涨停至少2分钱"] for pick in result.picks)


@pytest.mark.parametrize("adjust", ["none", "qfq", "hfq"])
def test_raw_ohlc_attachment_and_live_overlay_preserve_real_prices(market_fixture, adjust):
    path, dates = market_fixture
    with MarketStore(path) as store:
        panels = store.load_panel(fields=("open", "high", "low", "close"), codes=CODES,
                                  start=dates[0], end=dates[-1], adjust=adjust, min_bars=1)
        attach_raw_limit_close(store, panels, enabled=True, include_ohlc=True,
                               adjust=adjust, codes=CODES, start=dates[0], end=dates[-1], min_bars=1)
        expected = store.load_panel(fields=("open", "high", "low", "close"), codes=CODES,
                                    start=dates[0], end=dates[-1], adjust="none", min_bars=1)
        for field in expected:
            pd.testing.assert_frame_equal(panels[f"__raw_{field}"], expected[field])
            if adjust == "none":
                assert panels[f"__raw_{field}"] is panels[field]
        bar = {"open": 12.0, "high": 12.5, "low": 11.9, "close": 12.3}
        overlaid = overlay_live_day(panels, {"000001": bar}, "2026-01-02")
        for field, value in bar.items():
            assert overlaid[f"__raw_{field}"].at["2026-01-02", "000001"] == value
        assert "2026-01-02" not in panels["__raw_close"].index
