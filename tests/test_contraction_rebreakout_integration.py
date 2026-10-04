"""隔离数据库中的目录、真实样本选股、回测信号与评分持久化契约。"""
from __future__ import annotations

import pandas as pd
import pytest

from src.backtest.application.engine import BacktestConfig
from src.backtest.application.runner import prepare_backtest_context
from src.ledger import PalaceStore
from src.market import MarketStore
from src.ops import OpsStore
from src.strategy import describe_all, get
from src.strategy.application.persist import persist_screen_candidates
from src.strategy.application.screen_run_prepare import range_read_scope
from src.strategy.application.screener import screen
from tests.test_contraction_rebreakout import FIELDS, mango_example


SLUG = "contraction-rebreakout-v1"
CODES = ["300413", "301001", "300002", "600001", "000001", "688001"]


@pytest.fixture
def market_fixture(tmp_path):
    """300413 使用真实 35 日样本；其它代码为同形态隔离边界夹具。"""
    panels = mango_example()
    dates = list(panels["close"].index)
    path = tmp_path / "market.db"
    with MarketStore(path) as store:
        store.upsert_instruments({
            "code": code, "name": "芒果超媒" if code == "300413" else f"隔离样本{code}",
            "market": "sz" if code.startswith(("00", "30")) else "sh",
            "board": "chi_next" if code.startswith("30") else "star" if code.startswith("688") else "main",
            "instrument_type": "STOCK", "list_date": "2010-01-01",
        } for code in CODES)
        rows = []
        multipliers = {"300413": 1., "301001": 1.2, "300002": .9,
                       "600001": 3., "000001": 3., "688001": 3.}
        for day in dates:
            for code in CODES:
                values = [panels[field].at[day, "300413"] for field in FIELDS]
                if day == dates[-1]:
                    values[-1] *= multipliers[code]
                open_, high, low, close, volume = values
                rows.append((day, code, open_, high, low, close, volume, close * volume, "fixture", day))
        store.conn.executemany(
            "INSERT INTO quotes_daily(trade_date,code,open,high,low,close,volume,amount,source,fetched_at) "
            "VALUES(?,?,?,?,?,?,?,?,?,?)", rows,
        )
        store.conn.commit()
        store.rebuild_calendar()
        for code in CODES:
            store.upsert_adjust_factors(code, pd.DataFrame({"date": [dates[0]], "hfq_factor": [1.]}), source="fixture")
    return path, dates


def test_catalog_uses_formula_history_and_shared_universe_without_creating_jobs(tmp_path):
    engine = get(SLUG)
    info = next(row for row in describe_all() if row["slug"] == SLUG)
    assert info["name"] == "缩量回调后二次突破"
    assert info["source_kind"] == "builtin" and info["entry_timing"] == "next_open"
    assert info["min_bars"] == 31 and engine.screen_top_n == 2
    assert engine.screen_rank_factor == "score"
    assert info["default_universe"] is None
    assert engine.screen_managed_job is False
    with OpsStore(tmp_path / "ops.db") as store:
        store.ensure_managed_screen_jobs()
        assert store.get_job_by_name(f"screen:{SLUG}") is None


@pytest.mark.parametrize("adjust", ["none", "qfq", "hfq"])
def test_actual_mango_sample_passes_screen_when_shared_pool_selects_chinext(market_fixture, adjust):
    path, dates = market_fixture
    with MarketStore(path) as store:
        result = screen(store, SLUG, trade_date=dates[-1], adjust=adjust,
                        universe={"boards": ["chi_next"], "min_list_days": 0},
                        health_check=False, live_overlay=False)
    assert [pick["code"] for pick in result.picks] == ["301001", "300413"]
    mango = next(pick for pick in result.picks if pick["code"] == "300413")
    assert mango["name"] == "芒果超媒"
    assert mango["factors"]["score"] == 72.4752
    assert mango["factors"]["候选排名"] == 2.
    assert mango["factors"]["条件候选"] and mango["factors"]["每日前二"]
    assert result.universe["boards"] == ["chi_next"]
    assert result.universe["min_list_days"] == 0


def test_explicit_other_board_codes_compete_in_the_unified_pool(market_fixture):
    path, dates = market_fixture
    with MarketStore(path) as store:
        result = screen(store, SLUG, trade_date=dates[-1], codes=["600001", "000001", "688001"],
                        health_check=False, live_overlay=False)
    assert [pick["code"] for pick in result.picks] == ["000001", "600001"]
    assert result.universe["boards"] == ["main", "chi_next", "star"]


def test_screen_backtest_and_persistence_share_the_same_ranked_two_and_scores(market_fixture, tmp_path):
    path, dates = market_fixture
    with MarketStore(path) as store:
        selected = screen(store, SLUG, trade_date=dates[-1], codes=CODES,
                          health_check=False, live_overlay=False)
        context = prepare_backtest_context(
            store, SLUG, start=dates[-1], end=dates[-1], codes=CODES,
            config=BacktestConfig(hold_days=5, valuation_end=dates[-1]),
        )
        row = context["signals"].loc[dates[-1]]
        assert set(row.index[row]) == {pick["code"] for pick in selected.picks}
        assert context["execution_adjust"] == "none"
    path = tmp_path / "palace.db"
    persisted = persist_screen_candidates(selected, palace_db=str(path), source="api:screen_backfill")
    assert persisted["written"] == 2 and not persisted["failed"]
    with PalaceStore(path) as store:
        rows = store.conn.execute("SELECT code,score,strategy_revision FROM candidate_reviews").fetchall()
    assert {row[0]: row[1] for row in rows} == {
        pick["code"]: pick["factors"]["score"] for pick in selected.picks
    }
    assert all(row[2] == selected.strategy_revision for row in rows)


def test_range_screen_matches_daily_calls_and_retains_actual_sample_scores(market_fixture):
    path, dates = market_fixture
    days = dates[-3:]
    engine = get(SLUG)
    options = {"codes": CODES, "health_check": False, "live_overlay": False}
    with MarketStore(path) as store:
        expected = [screen(store, engine, trade_date=day, **options) for day in days]
        with range_read_scope(store, engine, days, None, codes=CODES):
            actual = [screen(store, engine, trade_date=day, **options) for day in days]
    assert expected[-1].picks
    for daily, ranged in zip(expected, actual, strict=True):
        assert daily.picks == ranged.picks
        assert daily.watch_picks == ranged.watch_picks


@pytest.mark.parametrize("adjust", ["qfq", "hfq"])
def test_screen_and_backtest_prepare_raw_close_separately_from_adjusted_prices(market_fixture, adjust):
    path, dates = market_fixture
    with MarketStore(path) as store:
        # Introduce a historical factor change without altering the actual raw quotes.
        for code in CODES:
            store.upsert_adjust_factors(
                code, pd.DataFrame({"date": [dates[0], dates[-1]], "hfq_factor": [1., 2.]}), source="fixture",
            )
        selected = screen(store, SLUG, trade_date=dates[-1], codes=CODES, adjust=adjust,
                          health_check=False, live_overlay=False)
        context = prepare_backtest_context(
            store, SLUG, start=dates[-1], end=dates[-1], codes=CODES, adjust=adjust,
            config=BacktestConfig(hold_days=3, valuation_end=dates[-1]),
        )
        assert "__raw_close" in context["panels"]
        raw = context["panels"]["__raw_close"]
        pd.testing.assert_frame_equal(raw, context["execution_panels"]["close"])
        assert not context["panels"]["close"].equals(raw)
        result = get(SLUG).compute(context["panels"])
        assert result.factors["涨停价"].at[dates[-1], "300413"] == 22.51
        assert {pick["code"] for pick in selected.picks} == set(result.picks_on(dates[-1], rank_by="score"))
