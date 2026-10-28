"""Regression coverage for the scheduled candidate outcome query."""
from __future__ import annotations

import sqlite3

from psycopg._queries import _query2pg

from src.ledger.infrastructure.candidates_query import CandidateQueryMixin
from src.shared.postgres import translate_sql


class _PostgresCheckedConnection:
    def __init__(self, conn: sqlite3.Connection) -> None:
        self.conn = conn

    def execute(self, sql: str, params: tuple):
        # Use the actual psycopg placeholder parser before running the same
        # query on SQLite. Literal percent signs alongside parameters fail here.
        _query2pg(translate_sql(sql).encode(), "utf-8")
        return self.conn.execute(sql, params)


def test_outcome_query_accepts_postgres_parameters_and_excludes_history():
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    conn.execute(
        """CREATE TABLE candidate_reviews (
            id TEXT, occurred_on TEXT, pool_id TEXT, code TEXT, name TEXT,
            score REAL, decision TEXT, tier TEXT, strategy_slug TEXT,
            rule_version TEXT, source TEXT, created_at TEXT
        )"""
    )
    conn.executemany(
        "INSERT INTO candidate_reviews VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        [
            ("old", "2026-10-27", "pool", "A", "A", 1, "精选", "core", "s", "s", "job:screen", "2026-10-27 15:30"),
            ("new", "2026-10-27", "pool", "A", "A", 2, "精选", "core", "s", "s", "job:screen", "2026-10-27 15:31"),
            ("backfill", "2026-10-27", "pool", "B", "B", 1, "精选", "core", "s", "s", "api:screen_backfill", "2026-10-27 15:30"),
            ("history", "2026-10-27", "pool", "C", "C", 1, "精选", "core", "s", "s", "job:screen:history", "2026-10-27 15:30"),
            ("manual", "2026-10-26", "pool", "D", "D", 1, "精选", "core", "s", "s", "manual", "2026-10-27 15:30"),
        ],
    )
    query = CandidateQueryMixin()
    query.conn = _PostgresCheckedConnection(conn)

    assert [row["id"] for row in query.candidate_outcome_rows(limit=10)] == ["new", "manual"]
    assert [row["id"] for row in query.candidate_outcome_rows(limit=1)] == ["new"]
