"""候选池列表轻量读取与按 ID 查看完整证据的回归。"""
from __future__ import annotations

import json
import sqlite3

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from src.ledger import PalaceStore
from src.ledger.api.router import build_ledger_router


@pytest.fixture
def candidate_db(tmp_path):
    path = tmp_path / "palace.db"
    with PalaceStore(path) as store:
        ids = {}

        def record(key, *, code, day, source, score=90, decision="精选", slug="fixture-gap", created=None):
            candidate_id = store.record_candidate(
                code=code,
                name=f"测试标的 {code}",
                occurred_on=day,
                pool_id=f"{slug}@{day}",
                decision=decision,
                reason=f"{key} 的候选理由",
                score=score,
                rule_version="测试修复战法" if slug == "fixture-gap" else "其他测试战法",
                strategy_slug=slug,
                strategy_revision="fixture-revision",
                effective_params={"period": 20},
                evidence={"fixture": key, "snapshot": "证据" * 20_000},
                source=source,
            )
            store.conn.execute(
                "UPDATE candidate_reviews SET created_at = ? WHERE id = ?",
                (created or f"{day} 15:30:00", candidate_id),
            )
            ids[key] = candidate_id

        record("live", code="300001", day="2026-09-29", source="api:screen", score=90)
        record("lower", code="300002", day="2026-09-29", source="job:screen", score=75)
        record("other", code="300003", day="2026-09-29", source="manual", score=None, slug="fixture-other")
        record("backfill", code="300001", day="2026-09-28", source="api:screen_backfill", decision="观察")
        record("history", code="300005", day="2026-09-27", source="job:screen:history")
        record("stale", code="300006", day="2026-09-26", source="api:screen", created="2026-09-29 16:00:00")
        record("manual", code="300007", day="2026-09-25", source="manual", created="2026-09-29 16:00:00")
        store.conn.commit()
    return path, ids


@pytest.fixture
def ledger_client(candidate_db):
    path, _ = candidate_db

    def get_store():
        with PalaceStore(path) as store:
            yield store

    app = FastAPI()
    app.include_router(build_ledger_router(write_dependency=lambda: None, get_store=get_store))
    with TestClient(app) as client:
        yield client


def test_default_list_preserves_complete_payload(candidate_db):
    path, ids = candidate_db
    with PalaceStore(path) as store:
        rows = store.candidates_list_payload(include_backfill=True)
    live = next(row for row in rows if row["id"] == ids["live"])
    assert live["strategy_revision"] == "fixture-revision"
    assert live["effective_params"] == {"period": 20}
    assert live["evidence"] == {"fixture": "live", "snapshot": "证据" * 20_000}
    assert live["source"] == "api:screen"
    assert live["created_at"] == "2026-09-29 15:30:00"


def test_slim_list_does_not_read_heavy_json_columns(candidate_db):
    path, _ = candidate_db
    denied_reads = []

    def deny_evidence(action, table, column, _database, _trigger):
        if action == sqlite3.SQLITE_READ and table == "candidate_reviews" and column in {
            "evidence_json", "effective_params_json",
        }:
            denied_reads.append(column)
            return sqlite3.SQLITE_DENY
        return sqlite3.SQLITE_OK

    with PalaceStore(path) as store:
        full = store.candidates_list_payload(include_backfill=True)
        # 如果轻量模式只在 Python/router 中删键，这里会因仍读取大列而失败。
        store.conn.set_authorizer(deny_evidence)
        try:
            slim = store.candidates_list_payload(include_backfill=True, slim=True)
        finally:
            store.conn.set_authorizer(None)
    assert denied_reads == []
    assert slim == [
        {key: value for key, value in row.items() if key not in {"evidence", "effective_params"}}
        for row in full
    ]


@pytest.mark.parametrize("slim", [False, True])
def test_historical_scope_keeps_live_and_manual_records(candidate_db, slim):
    path, ids = candidate_db
    with PalaceStore(path) as store:
        visible = store.candidates_list_payload(slim=slim)
        audit = store.candidates_list_payload(include_backfill=True, slim=slim)
    assert {row["id"] for row in visible} == {ids[key] for key in ("live", "lower", "other", "manual")}
    assert {row["id"] for row in audit} == set(ids.values())


def test_slim_filters_and_order_match_full_list(candidate_db):
    path, ids = candidate_db
    with PalaceStore(path) as store:
        options = {
            "strategy": "fixture-gap", "decision": "观察", "code": "300001",
            "start": "2026-09-28", "end": "2026-09-28", "include_backfill": True,
        }
        full = store.candidates_list_payload(**options)
        slim = store.candidates_list_payload(**options, slim=True)
        assert [row["id"] for row in slim] == [ids["backfill"]]
        assert slim[0]["reason"] == full[0]["reason"]
        assert store.candidates_list_payload(**{**options, "include_backfill": False}, slim=True) == []
        assert store.candidates_list_payload(**{**options, "start": "2026-09-29"}, slim=True) == []
        top = store.candidates_list_payload(include_backfill=True, slim=True, limit=3)
        assert [row["id"] for row in top] == [ids["live"], ids["lower"], ids["other"]]


def test_candidate_detail_uses_exact_id_and_preserves_historical_evidence(candidate_db):
    path, ids = candidate_db
    with PalaceStore(path) as store:
        detail = store.candidate_payload(ids["backfill"])
        assert detail is not None
        assert detail["id"] == ids["backfill"]
        # 同一股票还有较新的真选行；详情必须按 ID 返回这一条历史候选。
        assert detail["code"] == "300001"
        assert detail["date"] == "2026-09-28"
        assert detail["evidence"]["fixture"] == "backfill"
        assert detail["effective_params"] == {"period": 20}
        assert store.candidate_payload("CA-MISSING") is None


def test_http_slim_list_is_small_and_full_list_remains_available(ledger_client, candidate_db):
    _, ids = candidate_db
    query = {"strategy": "fixture-gap", "include_backfill": "true", "limit": 1000}
    full = ledger_client.get("/api/candidates/list", params=query)
    slim = ledger_client.get("/api/candidates/list", params={**query, "slim": "true"})
    assert full.status_code == slim.status_code == 200
    assert len(slim.content) < len(full.content) / 20
    assert [row["id"] for row in slim.json()] == [row["id"] for row in full.json()]
    assert all("evidence" not in row and "effective_params" not in row for row in slim.json())
    assert any(row["id"] == ids["backfill"] for row in slim.json())


def test_http_detail_loads_complete_backfill_and_returns_404(ledger_client, candidate_db):
    _, ids = candidate_db
    response = ledger_client.get(f"/api/candidates/{ids['backfill']}")
    assert response.status_code == 200
    payload = response.json()
    assert payload["id"] == ids["backfill"]
    assert payload["evidence"]["fixture"] == "backfill"
    assert payload["effective_params"] == {"period": 20}
    assert json.dumps(payload["evidence"], ensure_ascii=False).count("证据") == 20_000
    assert ledger_client.get("/api/candidates/CA-MISSING").status_code == 404


def test_http_static_list_route_and_default_history_scope(ledger_client, candidate_db):
    _, ids = candidate_db
    response = ledger_client.get("/api/candidates/list", params={"slim": "true"})
    assert response.status_code == 200
    assert {row["id"] for row in response.json()} == {ids[key] for key in ("live", "lower", "other", "manual")}
