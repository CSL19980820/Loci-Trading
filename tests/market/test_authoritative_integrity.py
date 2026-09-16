"""主源失效不能污染已有真值，恢复后同日必须能重试。"""
from datetime import date
from concurrent.futures import Future
from itertools import count
from types import SimpleNamespace
from unittest.mock import patch

import pandas as pd
import pytest

from src.market import MarketStore
from src.market.infrastructure import sync, tdx_daily, tencent
from src.market.infrastructure.adapters import AdapterError
from src.ops.application.jobs.context import JobContext
from src.ops.application.jobs.sync import _finalize_today_with_authoritative, execute_sync


def frame(amount=1020.0):
    return pd.DataFrame([dict(date=date.today().isoformat(), open=10, high=12,
                              low=9, close=11, volume=100, amount=amount)])


@pytest.mark.parametrize("incoming", ["tencent", "tencent_spot", "tdx_spot", "sina"])
def test_fallback_cannot_replace_finalized_authority(tmp_path, incoming):
    with MarketStore(tmp_path / "market.db") as store:
        store.conn.create_function("time", -1, lambda *_: "16:00:00")
        store.upsert_quotes("600519", frame(), source="tdx", receipt_id="authority")
        before = tuple(store.conn.execute("SELECT * FROM quotes_daily").fetchone())
        written = store.upsert_quotes("600519", frame(1100), source=incoming, receipt_id="fallback")
        assert written == 0
        assert tuple(store.conn.execute("SELECT * FROM quotes_daily").fetchone()) == before
        assert store.upsert_quotes("600519", frame(1040), source="tdx") == 1
        assert store.conn.execute("SELECT amount FROM quotes_daily").fetchone()[0] == 1040


def test_batch_spot_protects_authority_and_still_inserts_missing_code(tmp_path):
    with MarketStore(tmp_path / "market.db") as store:
        store.conn.create_function("time", -1, lambda *_: "16:00:00")
        store.upsert_quotes("600519", frame(), source="tdx")
        bars = [dict(frame().iloc[0], code=code) for code in ("600519", "600000")]
        assert store.upsert_quote_bars(bars, source="tencent_spot") == 1
        assert [tuple(r) for r in store.conn.execute(
            "SELECT code,source FROM quotes_daily ORDER BY code"
        )] == [("600000", "tencent_spot"), ("600519", "tdx")]


def test_intraday_tdx_bar_is_still_provisional_and_can_be_refreshed(tmp_path):
    with MarketStore(tmp_path / "market.db") as store:
        store.conn.create_function("time", -1, lambda *_: "14:00:00")
        store.upsert_quotes("600519", frame(), source="tdx")
        assert store.upsert_quotes("600519", frame(1040), source="tencent_spot") == 1
        assert store.conn.execute("SELECT amount FROM quotes_daily").fetchone()[0] == 1040


def test_spot_receipts_count_only_rows_actually_written(tmp_path):
    with MarketStore(tmp_path / "market.db") as store:
        store.conn.create_function("time", -1, lambda *_: "16:00:00")
        store.upsert_quotes("600519", frame(), source="tdx")
        receipts = [dict(code=code, lane="spot_batch", selected_source="tencent")
                    for code in ("600519", "600000")]
        bars = [dict(frame().iloc[0], code=r["code"]) for r in receipts]
        assert store.persist_quote_bar_receipts(receipts, bars, source="tencent_spot") == 1
        assert receipts[0]["coverage"]["rows_written"] == 0
        assert receipts[1]["coverage"]["rows_written"] == 1


def test_tencent_history_does_not_invent_amount():
    rows = tencent._parse_daily_rows([["2026-09-11", "10", "11", "12", "9", "100"]])
    flash = tencent._parse_flashdata("260911 10 11 12 9 100")
    assert rows["amount"].isna().all()
    assert flash["amount"].isna().all()
    assert rows.iloc[0]["volume"] == 10000


def test_non_authority_watermark_is_retried_same_day():
    today = date.today().isoformat()
    mark = dict(source="tencent", status="ok", last_synced_at=today)
    assert not sync._watermark_is_fresh(mark, today)
    assert sync._watermark_is_fresh({**mark, "source": "tdx"}, today)


def test_authoritative_sync_bypasses_fresh_watermark_and_locks_route(tmp_path):
    db = tmp_path / "market.db"
    today = date.today().isoformat()
    with MarketStore(db) as store:
        store.set_watermark("600519", source="tdx", last_trade_date=today)
    with patch("src.market.infrastructure.adapters.fetch_daily_routed", return_value=(frame(), "tdx")) as fetch:
        report = sync.sync_quotes(lambda: MarketStore(db), ["600519"],
                                  authoritative_only=True, with_factors=False,
                                  with_today_spot=False, workers=1, min_interval=0)
    assert report.succeeded == 1
    assert fetch.call_args.kwargs["adapter_ids"] == ["tdx"]
    assert fetch.call_args.kwargs["cross_check"] is False
    with MarketStore(db) as store:
        assert store.conn.execute("SELECT amount,source FROM quotes_daily").fetchone()[:] == (1020, "tdx")


def test_authority_outage_is_failed_and_does_not_write_quotes(tmp_path):
    db = tmp_path / "market.db"
    with patch("src.market.infrastructure.adapters.fetch_daily_routed", side_effect=AdapterError("TDX unavailable")):
        report = sync.sync_quotes(lambda: MarketStore(db), ["600519"],
                                  authoritative_only=True, with_factors=False,
                                  with_today_spot=False, workers=1, min_interval=0)
    assert report.failed == 1
    assert report.succeeded == 0
    with MarketStore(db) as store:
        assert store.conn.execute("SELECT COUNT(*) FROM quotes_daily").fetchone()[0] == 0
        assert store.watermark("600519")["status"] == "failed"


def test_eod_does_not_claim_failed_finalization_is_ok():
    report = SimpleNamespace(failed=1, succeeded=0, skipped=0, rows_written=0, elapsed_seconds=0)
    with patch("src.market.sync_quotes", return_value=report) as fetch:
        result = _finalize_today_with_authoritative({}, JobContext(market_db=":memory:"),
                                                   codes=["600519"], types={}, progress=None)
    assert result["status"] == "failed"
    assert result["failed"] == 1
    assert fetch.call_args.kwargs["authoritative_only"] is True


def test_eod_exposes_finalization_failure_to_job_runner(tmp_path):
    db = tmp_path / "market.db"
    with MarketStore(db) as store:
        store.upsert_instruments([dict(code="600519", name="sample", instrument_type="STOCK")])
    failed = SimpleNamespace(failed=1, succeeded=0, skipped=0, rows_written=0, elapsed_seconds=0)
    with (
        patch("src.market.sync_quotes", return_value=failed),
        patch("src.market.apply_today_spot", return_value=0),
        patch("src.market.backfill_missing_turnover", return_value={}),
        patch("src.market.mirror_recent_to_hot", return_value=dict(mode="skip", quotes=0, end="")),
    ):
        result = execute_sync(dict(mode="today_refresh", with_factors=False), JobContext(market_db=db))
    assert result["failed"] == 1
    assert result["finalize"]["status"] == "failed"


def test_handshake_only_server_is_disconnected_and_not_selected():
    disconnected = []

    class Api:
        def __init__(self, **kwargs):
            pass

        def connect(self, host, port, **kwargs):
            self.host = host
            return self

        def get_security_bars(self, *args):
            if self.host == "bad":
                raise ValueError("truncated K line body")
            return [{"close": 10}]

        def disconnect(self):
            disconnected.append(self.host)

    tdx_daily.reset_servers()
    try:
        with patch.object(tdx_daily, "_HOST_SEQUENCE", count()):
            api, errors = tdx_daily._try_hosts([("bad", 7709), ("good", 7709)], Api, budget=2)
        assert api.host == "good"
        assert disconnected == ["bad"]
        assert "truncated K line body" in errors[0]
    finally:
        tdx_daily.reset_servers()


def test_server_probe_timeout_keeps_completed_successes():
    future = Future()
    future.set_result(0.01)

    def completed(*_args, **_kwargs):
        yield future
        raise TimeoutError("another host stalled")

    pool = SimpleNamespace(submit=lambda *_: future, shutdown=lambda **_: None)
    with (
        patch.object(tdx_daily, "_servers", return_value=[("good", 7709)]),
        patch.object(tdx_daily, "ThreadPoolExecutor", return_value=pool),
        patch.object(tdx_daily, "as_completed", side_effect=completed),
    ):
        assert tdx_daily.rank_servers(use_cache=False) == [("good", 7709)]


def test_connections_rotate_even_when_thread_ids_are_aligned():
    class Api:
        def __init__(self, **_kwargs):
            pass

        def connect(self, host, _port, **_kwargs):
            self.host = host

        def get_security_bars(self, *_args):
            return [{"close": 10}]

        def disconnect(self):
            pass

    hosts = [(str(i), 7709) for i in range(8)]
    try:
        with patch.object(tdx_daily, "_HOST_SEQUENCE", count()), patch.object(
            tdx_daily.threading, "get_ident", return_value=16
        ):
            selected = [tdx_daily._try_hosts(hosts, Api, budget=1)[0].host for _ in range(8)]
        assert selected == [str(i) for i in range(8)]
    finally:
        tdx_daily.reset_servers()
