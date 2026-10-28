"""候选池列表轻量读取与按 ID 查看完整证据的回归。"""
from __future__ import annotations

import json
import sqlite3
from datetime import date, timedelta

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from psycopg._queries import _query2pg

from src.ledger import PalaceStore
from src.ledger.api.router import build_ledger_router
from src.ledger.infrastructure.candidates_query import CandidateQueryMixin
from src.shared.postgres import translate_sql


def _pool_dates_store(*, days=30, pools=5, candidates=20):
    """构造可复现的内存账本，不访问本地或远程真实数据库。"""
    store = CandidateQueryMixin()
    store.conn = sqlite3.connect(":memory:")
    store.conn.row_factory = sqlite3.Row
    store.conn.execute(
        """CREATE TABLE candidate_reviews (
            id TEXT PRIMARY KEY, occurred_on TEXT NOT NULL, pool_id TEXT NOT NULL,
            code TEXT NOT NULL, name TEXT NOT NULL, score REAL, decision TEXT NOT NULL,
            timing TEXT NOT NULL, reason TEXT NOT NULL, rule_version TEXT NOT NULL,
            strategy_slug TEXT NOT NULL, strategy_revision TEXT NOT NULL,
            effective_params_json TEXT NOT NULL, evidence_json TEXT NOT NULL,
            tier TEXT NOT NULL, source TEXT NOT NULL, created_at TEXT NOT NULL
        )"""
    )
    store.conn.execute(
        "CREATE UNIQUE INDEX idx_candidates_day_pool_code "
        "ON candidate_reviews(occurred_on, pool_id, code)"
    )
    evidence = json.dumps({"trace": "x" * 4096})
    rows = []
    for day_index in range(days):
        day = (date(2026, 10, 1) + timedelta(days=day_index)).isoformat()
        for pool_index in range(pools):
            for candidate_index in range(candidates):
                rows.append((
                    f"{day_index:03d}-{pool_index:02d}-{candidate_index:03d}", day,
                    f"pool-{pool_index:02d}", f"{candidate_index:06d}", "测试标的",
                    None if candidate_index % 7 == 0 else (candidate_index * 7 + pool_index) % 101 + 0.125,
                    ("selected", "观察", "剔除", "买入")[candidate_index % 4],
                    "", "测试理由", "测试战法", "fixture", "", "{}", evidence,
                    "core", "manual", f"{day}T15:30:{candidate_index % 60:02d}",
                ))
    store.conn.executemany(
        "INSERT INTO candidate_reviews VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        rows,
    )
    return store


def test_pool_dates_summarizes_normalized_decisions_and_null_scores():
    store = _pool_dates_store(days=1, pools=2, candidates=4)
    try:
        assert store.pool_dates_payload() == [
            {"date": "2026-10-01", "pool_id": "pool-00", "total": 4,
             "selected": 2, "filtered": 2, "scored": 3, "avg_score": 14.12},
            {"date": "2026-10-01", "pool_id": "pool-01", "total": 4,
             "selected": 2, "filtered": 2, "scored": 3, "avg_score": 15.12},
        ]
    finally:
        store.conn.close()


def test_pool_dates_uses_one_query_for_multiple_dates_and_pools():
    store = _pool_dates_store(days=3, pools=3, candidates=4)
    queries = []
    try:
        store.conn.set_trace_callback(queries.append)
        result = store.pool_dates_payload()
        assert len(result) == 9
        assert len(queries) == 1
        assert "evidence_json" not in queries[0]
    finally:
        store.conn.close()


def test_pool_dates_filters_before_deduplication_and_preserves_order():
    store = _pool_dates_store(days=2, pools=2, candidates=3)
    try:
        # 模拟尚未建立唯一索引的历史库，验证同时间按 ID 决胜及过滤顺序。
        store.conn.execute("DROP INDEX idx_candidates_day_pool_code")
        for candidate_id, score, decision, source, created in (
            ("v-a", 99, "buy", "manual", "2026-10-02T16:00:00"),
            ("v-b", 70, "reject", "manual", "2026-10-02T16:00:00"),
            ("z-backfill", 999, "精选", "api:screen_backfill", "2026-10-02T18:00:00"),
            ("z-history", 999, "精选", "job:screen:history", "2026-10-02T19:00:00"),
            ("z-stale", 999, "精选", "api:screen", "2026-10-03T20:00:00"),
        ):
            store.conn.execute(
                """INSERT INTO candidate_reviews
                   SELECT ?, occurred_on, pool_id, code, name, ?, ?, timing, reason,
                          rule_version, strategy_slug, strategy_revision, effective_params_json,
                          evidence_json, tier, ?, ?
                   FROM candidate_reviews WHERE id = ?""",
                (candidate_id, score, decision, source, created, "001-00-000"),
            )
        store.conn.execute(
            "UPDATE candidate_reviews SET score = NULL WHERE occurred_on = ? AND pool_id = ?",
            ("2026-10-02", "pool-01"),
        )
        store.conn.execute(
            """INSERT INTO candidate_reviews
               SELECT 'hidden-pool', occurred_on, 'hidden', code, name, score, decision, timing, reason,
                      rule_version, strategy_slug, strategy_revision, effective_params_json,
                      evidence_json, tier, 'job:screen:history', created_at
               FROM candidate_reviews WHERE id = '001-00-000'"""
        )
        assert store.pool_dates_payload() == [
            {"date": "2026-10-02", "pool_id": "pool-00", "total": 3,
             "selected": 0, "filtered": 3, "scored": 3, "avg_score": 30.42},
            {"date": "2026-10-02", "pool_id": "pool-01", "total": 3,
             "selected": 1, "filtered": 2, "scored": 0, "avg_score": None},
            {"date": "2026-10-01", "pool_id": "pool-00", "total": 3,
             "selected": 1, "filtered": 2, "scored": 2, "avg_score": 10.62},
            {"date": "2026-10-01", "pool_id": "pool-01", "total": 3,
             "selected": 1, "filtered": 2, "scored": 2, "avg_score": 11.62},
        ]
    finally:
        store.conn.close()


def test_pool_dates_preserves_legacy_date_normalization():
    store = _pool_dates_store(days=1, pools=1, candidates=4)
    try:
        for candidate_id, day in (("compact", "20261001"), ("empty", "")):
            store.conn.execute(
                """INSERT INTO candidate_reviews
                   SELECT ?, ?, pool_id, code, name, score, decision, timing, reason,
                          rule_version, strategy_slug, strategy_revision, effective_params_json,
                          evidence_json, tier, source, created_at
                   FROM candidate_reviews WHERE id = '000-00-001'""",
                (candidate_id, day),
            )
        assert store.pool_dates_payload() == [
            {"date": "20261001", "pool_id": "pool-00", "total": 4,
             "selected": 2, "filtered": 2, "scored": 3, "avg_score": 14.12},
            {"date": "2026-10-01", "pool_id": "pool-00", "total": 4,
             "selected": 2, "filtered": 2, "scored": 3, "avg_score": 14.12},
            {"date": "", "pool_id": "pool-00", "total": 1,
             "selected": 0, "filtered": 1, "scored": 1, "avg_score": 7.12},
        ]
    finally:
        store.conn.close()


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


def test_candidate_page_query_uses_postgres_safe_parameters(candidate_db):
    path, ids = candidate_db

    class PostgresCheckedConnection:
        def __init__(self, conn):
            self.conn = conn

        def execute(self, sql, params=None):
            if params is not None:
                _query2pg(translate_sql(sql).encode(), "utf-8")
            return self.conn.execute(sql, params or ())

    with PalaceStore(path) as store:
        sqlite_conn = store.conn
        store.conn = PostgresCheckedConnection(sqlite_conn)
        try:
            rows = store.candidates_list_payload(slim=True)
            filtered = store.candidates_list_payload(
                strategy="fixture-gap", decision="观察", start="2026-09-28",
                end="2026-09-28", include_backfill=True, slim=True,
            )
            daily = store.candidates_payload("2026-09-29")
            history = store.candidates_by_strategy("fixture-gap")
        finally:
            store.conn = sqlite_conn

    assert {row["id"] for row in rows} == {ids[key] for key in ("live", "lower", "other", "manual")}
    assert [row["id"] for row in filtered] == [ids["backfill"]]
    assert {row["id"] for row in daily} == {ids[key] for key in ("live", "lower", "other")}
    assert {row["id"] for row in history} == {ids["live"], ids["lower"]}
