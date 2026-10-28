"""收盘后选股必须读正式日 K；手动、定时和关闭刷新时均不能用盘中快照。"""
from datetime import date, datetime
from zoneinfo import ZoneInfo

import pandas as pd
import pytest

from src.market import MarketStore
from src.market.application import screen_live, screen_spot
from src.market.infrastructure import sync_spot
from src.shared.tenancy import tenant_scope
from src.strategy.application import persist, screen_run, screen_run_prepare, screener
from src.strategy.application.screener import screen
from src.strategy.domain.base import StrategyError


DAY = "2026-10-20"
SLUG = "yangshi-tail-v1"
CODES = ("002173", "002246")
SH = ZoneInfo("Asia/Shanghai")
OLD_PRICES = {"002173": 16.43, "002246": 24.98}
CLOSE_PRICES = {"002173": 16.49, "002246": 25.06}


def forbidden(*_args, **_kwargs):
    raise AssertionError("收盘后选股不得补刷 spot")


@pytest.fixture
def clock(monkeypatch):
    def set_clock(stamp="2026-10-20T15:03:00+08:00"):
        current = datetime.fromisoformat(stamp)

        class Clock(datetime):
            @classmethod
            def now(cls, tz=None):
                return current.astimezone(tz) if tz else current.replace(tzinfo=None)

        class Day(date):
            @classmethod
            def today(cls):
                return current.astimezone(SH).date()

        monkeypatch.setattr(screen_spot, "datetime", Clock)
        monkeypatch.setattr(screen_live, "datetime", Clock)
        monkeypatch.setattr(screen_run_prepare, "date", Day)
        monkeypatch.setattr(screener, "date", Day)

    set_clock()
    monkeypatch.setattr(sync_spot, "apply_today_spot", forbidden)
    return set_clock


def receipt(store, code, *, lane="hist_daily", fetched_at="2026-10-20T07:11:38+00:00",
            quote_fetched_at="2026-10-20 07:11:39", **fields):
    key = f"{code}:{lane}:{fetched_at}"
    values = {"code": code, "lane": lane, "selected_source": "tdx", "state": "selected",
              "unresolved": 0, "fetched_at": fetched_at, **fields}
    store.conn.execute(
        "INSERT OR REPLACE INTO source_route_receipts("
        "receipt_id,code,lane,selected_source,state,unresolved,fetched_at,generated_at)"
        " VALUES(?,?,?,?,?,?,?,?)",
        (key, *(values[k] for k in ("code", "lane", "selected_source", "state",
                                    "unresolved", "fetched_at")), fetched_at),
    )
    # 定稿认定看 attempts 里有无真实命中，不能只看回执的 state 推导值。
    store.conn.execute(
        "INSERT OR REPLACE INTO source_route_attempts(receipt_id,attempt_no,source_id,state)"
        " VALUES(?,1,?,?)",
        (key, values["selected_source"], "selected"),
    )
    store.conn.execute(
        "UPDATE quotes_daily SET receipt_id=?, fetched_at=? WHERE code=? AND trade_date=?",
        (key, quote_fetched_at, code, DAY),
    )
    store.conn.commit()


def finalize(store, codes=CODES):
    for code in codes:
        receipt(store, code)
        store.conn.execute(
            "UPDATE quotes_daily SET close=? WHERE code=? AND trade_date=?",
            (CLOSE_PRICES[code], code, DAY),
        )
    store.conn.commit()


@pytest.fixture
def market(tmp_path):
    with MarketStore(tmp_path / "market.db") as store:
        store.upsert_instruments([
            {"code": code, "name": name, "market": "sz", "board": "main",
             "instrument_type": "STOCK", "list_date": "2000-01-01"}
            for code, name in zip(CODES, ("创新医疗", "北化股份"))
        ])
        days = pd.bdate_range(end=DAY, periods=61).strftime("%Y-%m-%d")
        rows = []
        for code, previous in zip(CODES, (15.65, 23.87)):
            for day in days:
                close = OLD_PRICES[code] if day == DAY else previous
                rows.append((day, code, previous, max(previous, close) + 0.1,
                             previous - 0.1, close, 1_000_000., 100_000_000.,
                             20_000_000., 0.05, "tdx", "2026-10-20 06:34:25"))
        store.conn.executemany(
            "INSERT INTO quotes_daily(trade_date,code,open,high,low,close,volume,amount,"
            "outstanding_share,turnover,source,fetched_at) VALUES(?,?,?,?,?,?,?,?,?,?,?,?)", rows,
        )
        store.conn.commit()
        store.rebuild_calendar()
        for code in CODES:
            receipt(store, code, lane="spot_batch", fetched_at="2026-10-20T06:34:25+00:00",
                    quote_fetched_at="2026-10-20 06:34:25")
        yield store


@pytest.mark.parametrize("force_refresh,codes", [(False, CODES), (True, CODES), (False, [])])
def test_complete_coverage_and_tdx_label_do_not_prove_close(market, clock, force_refresh, codes):
    assert screen_spot.measure_day_coverage(market, DAY)["ratio"] == 1
    with pytest.raises(screen_spot.ScreenSpotError, match="日终行情尚未定稿.*0/2"):
        screen_spot.ensure_today_quotes_for_screen(
            market, codes, trade_date=DAY, force_refresh=force_refresh,
        )


@pytest.mark.parametrize("bad", [
    {"lane": "spot_batch"},
    {"fetched_at": "2026-10-20T14:59:59+08:00"},
    {"quote_fetched_at": "2026-10-20 06:34:25"},
    {"state": "failed"},
    {"unresolved": 1},
    {"selected_source": "other"},
])
def test_partial_or_unconfirmed_finalization_is_blocked(market, clock, bad):
    finalize(market)
    receipt(market, CODES[0], **bad)
    with pytest.raises(screen_spot.ScreenSpotError, match="日终行情尚未定稿.*1/2"):
        screen_spot.ensure_closed_day_finalized(market, DAY)


def test_missing_row_or_receipt_cannot_be_hidden_by_coverage(market, clock):
    finalize(market)
    market.conn.execute("UPDATE quotes_daily SET receipt_id=NULL WHERE code=? AND trade_date=?",
                        (CODES[0], DAY))
    market.conn.commit()
    with pytest.raises(screen_spot.ScreenSpotError, match="1/2"):
        screen_spot.ensure_closed_day_finalized(market, DAY)
    market.conn.execute("DELETE FROM quotes_daily WHERE code=? AND trade_date=?", (CODES[0], DAY))
    market.conn.commit()
    with pytest.raises(screen_spot.ScreenSpotError, match="1/2"):
        screen_spot.ensure_closed_day_finalized(market, DAY)


def test_legacy_skipped_label_on_successful_fetch_still_proves_finalization(market, clock):
    """历史缺陷把「主源命中 + 后备源未请求」的成功回执写成了 skipped。

    那条回执的 attempts 里仍有真实 selected 命中，收盘定稿必须放行；否则盘中每轮
    增量同步重写行情 receipt 后，前一交易日的选股会被永久阻断。
    """
    finalize(market)
    market.conn.execute(
        "UPDATE source_route_receipts SET state='skipped' WHERE lane='hist_daily'"
    )
    market.conn.commit()
    assert screen_spot.ensure_closed_day_finalized(market, DAY)["finalized"] == 2


def test_receipt_without_selected_attempt_is_not_finalization_proof(market, clock):
    finalize(market)
    receipt_id = market.conn.execute(
        "SELECT receipt_id FROM quotes_daily WHERE code=? AND trade_date=?", (CODES[0], DAY)
    ).fetchone()[0]
    market.conn.execute("DELETE FROM source_route_attempts WHERE receipt_id=?", (receipt_id,))
    market.conn.execute("UPDATE source_route_receipts SET state='skipped' WHERE receipt_id=?",
                        (receipt_id,))
    market.conn.commit()
    with pytest.raises(screen_spot.ScreenSpotError, match="1/2"):
        screen_spot.ensure_closed_day_finalized(market, DAY)


@pytest.mark.parametrize("stamp", ["2026-10-20T07:00:00+00:00", "2026-10-20T15:00:00+08:00"])
def test_all_finalized_at_close_pass_without_spot_even_when_forced(market, clock, stamp):
    for code in CODES:
        receipt(market, code, fetched_at=stamp, quote_fetched_at="2026-10-20 07:00:00")
    body = screen_spot.ensure_today_quotes_for_screen(market, CODES, trade_date=DAY, force_refresh=True)
    assert body["written"] == 0 and body["degraded"] is False
    assert body["eod_finalization"]["finalized"] == body["eod_finalization"]["required"] == 2


def test_intraday_and_historical_selection_keep_existing_behavior(market, clock):
    clock("2026-10-20T14:59:59+08:00")
    assert screen_spot.ensure_closed_day_finalized(market, DAY) is None
    assert screen_spot.ensure_today_quotes_for_screen(market, CODES, trade_date=DAY)["status"] == "skipped"
    clock()
    assert screen_spot.ensure_closed_day_finalized(market, "2026-10-19") is None
    assert screen_spot.ensure_today_quotes_for_screen(market, CODES, trade_date="2026-10-19")["status"] == "skipped"


def test_yangshi_rejects_old_intraday_winner_then_uses_final_close(market, clock):
    options = {"trade_date": DAY, "codes": list(CODES), "health_check": False,
               "skip_universe_safety": True, "live_overlay": False}
    clock("2026-10-20T14:59:59+08:00")
    assert [p["code"] for p in screen(market, SLUG, **options).picks] == ["002173"]
    clock("2026-10-20T15:00:00+08:00")
    with pytest.raises(StrategyError, match="日终行情尚未定稿"):
        screen(market, SLUG, **options)
    finalize(market, codes=CODES[:1])
    with pytest.raises(StrategyError, match="1/2"):
        screen(market, SLUG, **options)
    finalize(market, codes=CODES[1:])
    result = screen(market, SLUG, **options)
    assert [p["code"] for p in result.picks] == ["002246"]
    assert result.data_snapshot["eod_finalization"]["status"] == "finalized"


@pytest.mark.parametrize("now", ["2026-10-20T15:45:00+08:00", "2026-10-21T09:00:00+08:00"])
def test_latest_closed_day_stays_blocked_until_all_rows_are_finalized(market, clock, now):
    clock(now)
    with pytest.raises(screen_spot.ScreenSpotError, match="日终行情尚未定稿"):
        screen_spot.ensure_closed_day_finalized(market, DAY)
    finalize(market)
    assert screen_spot.ensure_closed_day_finalized(market, DAY)["closed_at"] == DAY + "T15:00:00+08:00"


def test_stale_hot_store_cannot_use_full_store_finalization(market, clock, tmp_path):
    from src.market import mirror_recent_to_hot

    options = {"trade_date": DAY, "codes": list(CODES), "health_check": False,
               "skip_universe_safety": True, "live_overlay": False}
    with MarketStore(tmp_path / "hot.db") as hot:
        mirror_recent_to_hot(market, hot)
        finalize(market)
        assert screen_spot.ensure_closed_day_finalized(market, DAY)["finalized"] == 2
        with pytest.raises(StrategyError, match="日终行情尚未定稿"):
            screen(hot, SLUG, **options)
        mirror_recent_to_hot(market, hot)
        assert [p["code"] for p in screen(hot, SLUG, **options).picks] == ["002246"]


def test_intraday_request_queued_past_close_reads_final_daily_bars(market, clock, monkeypatch):
    finalize(market)
    monkeypatch.setattr(screen_live, "fetch_live_spot_bars", forbidden)
    result = screen(market, SLUG, trade_date=DAY, codes=list(CODES), health_check=False,
                    skip_universe_safety=True, live_overlay=True)
    assert result.data_snapshot["live_overlay"] is False
    assert [p["code"] for p in result.picks] == ["002246"]


def test_unlisted_and_suspended_instruments_do_not_block_finalized_day(market, clock):
    market.upsert_instruments([
        {"code": "600001", "list_date": "2026-10-21"},
        {"code": "600002", "status": "suspended"},
    ])
    finalize(market)
    assert screen_spot.ensure_closed_day_finalized(market, DAY)["required"] == 2


def test_requested_today_cannot_fall_back_to_yesterday_when_entire_day_is_missing(market, clock, tmp_path):
    market.conn.execute("DELETE FROM quotes_daily WHERE trade_date=?", (DAY,))
    market.conn.execute("DELETE FROM trading_calendar WHERE trade_date=?", (DAY,))
    market.conn.commit()
    with pytest.raises(StrategyError, match="日终行情尚未定稿.*0/2"):
        screen(market, SLUG, trade_date=DAY, codes=list(CODES), health_check=False,
               skip_universe_safety=True, live_overlay=False)
    with tenant_scope("screen-close-missing-day"):
        try:
            screen_run.screen_run_try_begin(strategy=SLUG, trade_date=DAY)
            screen_run.execute_screen_run(
                {"strategy": SLUG, "date": DAY, "refresh_spot": False,
                 "skip_health_check": True, "record_candidates": False},
                market_factory=lambda: MarketStore(market.db_path),
                hot_db=str(tmp_path / "hot.db"), palace_db=str(tmp_path / "palace.db"),
            )
            state = screen_run.screen_run_snapshot(SLUG)
            assert state["status"] == "error" and "日终行情尚未定稿" in state["error"]
            assert state["result"] is None
        finally:
            screen_run._STATES.pop("screen-close-missing-day", None)


@pytest.mark.parametrize("entry", ["manual", "scheduled"])
@pytest.mark.parametrize("refresh", [False, True])
def test_manual_and_scheduled_gate_before_candidate_write(market, clock, monkeypatch, tmp_path, entry, refresh):
    from src.ops.application.jobs.context import JobContext, JobError
    from src.ops.application.jobs.screen import execute_screen

    written = []
    monkeypatch.setattr(persist, "persist_screen_candidates",
                        lambda result, **_kw: written.append(result) or {"written": len(result.picks)})
    options = {"strategy": SLUG, "date": DAY, "codes": list(CODES),
               "refresh_spot": refresh, "skip_health_check": True, "record_candidates": True}
    hot = str(tmp_path / "hot.db")
    palace = str(tmp_path / "palace.db")

    def run():
        if entry == "scheduled":
            return execute_screen(options, JobContext(
                market_db=str(market.db_path), market_hot_db=hot, palace_db=palace,
            ))
        with tenant_scope("screen-close-finalization"):
            screen_run._STATES.pop("screen-close-finalization", None)
            screen_run.screen_run_try_begin(strategy=SLUG, trade_date=DAY)
            screen_run.execute_screen_run(
                options, market_factory=lambda: MarketStore(market.db_path), hot_db=hot, palace_db=palace,
            )
            state = screen_run.screen_run_snapshot(SLUG)
        if state["status"] == "error":
            raise StrategyError(state["error"])
        assert state["status"] == "done"
        return state["result"]

    try:
        with pytest.raises((StrategyError, JobError), match="日终行情尚未定稿"):
            run()
        assert written == []
        finalize(market)
        body = run()
        assert [p["code"] for p in body["picks"]] == ["002246"]
        assert body["data_snapshot"]["eod_finalization"]["finalized"] == 2
        assert len(written) == 1
    finally:
        screen_run._STATES.pop("screen-close-finalization", None)
