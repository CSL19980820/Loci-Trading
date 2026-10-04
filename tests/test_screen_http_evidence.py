"""选股 HTTP 完成结果始终瘦身，不依赖候选入库循环。"""
from contextlib import nullcontext
from copy import deepcopy
import json
from types import SimpleNamespace

from fastapi import FastAPI
from fastapi.testclient import TestClient
import pytest

import src.strategy as strategy_api
from src.shared.evidence_compact import compact_job_result, RECEIPT_SOURCE
from src.strategy.api import router as strategy_router
from src.strategy.api import screen_today_router
from src.strategy.application import persist
from src.strategy.application.screen_run import _result_body
from src.strategy.application.screener import ScreenResult


def _result(pick_count):
    return ScreenResult(
        strategy_slug="qianlong-close-v3", strategy_revision="revision-1",
        trade_date="2026-09-11", entry_timing="next_open", universe_size=180,
        params={"window": 20}, effective_params={"window": 20},
        picks=[{"code": str(300001 + i), "close": 10.5, "factors": {"score": 99 - i}}
               for i in range(pick_count)],
        watch_picks=[{"code": "301001", "factors": {"risk": 1.2}}] if pick_count else [],
        data_snapshot={
            "market_revision": "market-1",
            "source_evidence": {
                "sources": [{"source_id": "tdx", "rows": 180, "codes": 180}],
                "field_coverage": {"close": {"rows": 180, "ratio": 1.0}},
                "receipts": [{"receipt_id": str(i), "state": "failed" if i >= 120 else "ok"}
                             for i in range(180)],
                "attempts": [{"receipt_id": str(i // 2), "state": "failed" if i % 2 else "ok"}
                             for i in range(360)],
                "observed_codes": [str(300001 + i) for i in range(180)],
            },
        },
    )


def _assert_compact(body):
    snapshot = body["data_snapshot"]
    evidence = snapshot["source_evidence"]
    assert evidence["receipts_total"] == 180
    assert evidence["receipts_failed"] == 60
    assert evidence["receipts_source"] == RECEIPT_SOURCE
    assert len(evidence["receipts"]) == 50
    assert all(item["state"] == "failed" for item in evidence["receipts"])
    assert len(evidence["attempts"]) == 50 and evidence["attempts_total"] == 360
    assert len(evidence["observed_codes"]) == 50 and evidence["observed_codes_total"] == 180
    assert snapshot["market_revision"] == "market-1"
    assert evidence["sources"] == [{"source_id": "tdx", "rows": 180, "codes": 180}]
    assert evidence["field_coverage"] == {"close": {"rows": 180, "ratio": 1.0}}
    serialized = json.dumps(body, sort_keys=True)
    assert compact_job_result(body) == 0
    assert json.dumps(body, sort_keys=True) == serialized


@pytest.mark.parametrize("endpoint", ["sync", "today"])
@pytest.mark.parametrize("record,pick_count", [(False, 2), (True, 0), (True, 2)])
def test_http_screen_compacts_with_no_record_zero_candidates_and_prior_persistence(
        monkeypatch, endpoint, record, pick_count):
    result = _result(pick_count)
    picks, watches = deepcopy(result.picks), deepcopy(result.watch_picks)
    store = SimpleNamespace(list_instruments=lambda **_kwargs: [])
    writes = []

    def run_screen(*_args, **_kwargs):
        assert len(result.data_snapshot["source_evidence"]["receipts"]) == 180
        return result

    def record_result(current, **_kwargs):
        writes.append(len(current.picks))
        # 既有入库循环只在有候选时压缩，HTTP 再压一次也不能覆盖真实总数。
        if current.picks:
            compact_job_result(current.data_snapshot)
        return {"written": len(current.picks)}

    monkeypatch.setattr(strategy_api, "screen", run_screen)
    monkeypatch.setattr(strategy_api, "get", lambda _slug: SimpleNamespace(requires_full_history=True))
    monkeypatch.setattr(persist, "persist_screen_candidates", record_result)
    monkeypatch.setattr(strategy_router, "market_store", lambda _path: nullcontext(store))
    monkeypatch.setattr(strategy_router, "effective_screen_universe", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(screen_today_router, "market_hot_store", lambda _path: nullcontext(store))
    monkeypatch.setattr(screen_today_router, "should_sync_today", lambda _path: False)
    app = FastAPI()
    app.include_router(strategy_router.build_strategy_router(write_dependency=lambda: None))
    with TestClient(app) as client:
        params = {"strategy": result.strategy_slug, "date": result.trade_date,
                  "record_candidates": record}
        response = (client.post("/api/strategies/screen", json=params) if endpoint == "sync"
                    else client.get("/api/screen/today", params=params))
    assert response.status_code == 200
    body = response.json()
    assert body["picks"] == picks and body["watch_picks"] == watches
    assert body["strategy_revision"] == "revision-1"
    assert body["params"] == body["effective_params"] == {"window": 20}
    assert writes == ([pick_count] if record else [])
    assert body.get("recorded") == ({"written": pick_count} if record else None)
    _assert_compact(body)


@pytest.mark.parametrize("recorded,pick_count", [(None, 2), ({"written": 0}, 0), ({"written": 2}, 2)])
def test_background_completed_result_compacts_and_keeps_candidate_contract(recorded, pick_count):
    result = _result(pick_count)
    body = _result_body(result, recorded)
    assert body["recorded"] == recorded
    assert body["picks"] == result.picks and body["watch_picks"] == result.watch_picks
    assert body["universe_size"] == 180 and body["entry_timing"] == "next_open"
    _assert_compact(body)
