"""Candidate-based review cache and manual-review period regressions."""
from __future__ import annotations

from types import SimpleNamespace

from src.ledger import PalaceStore
from src.shared.postgres import _CompatRow


def test_review_fingerprint_tracks_an_equal_length_candidate_change(tmp_path):
    with PalaceStore(tmp_path / "palace.db") as store:
        candidate_id = store.record_candidate(
            code="300001", name="测试标的", occurred_on="2026-10-27",
            pool_id="test@2026-10-27", decision="精选", reason="测试", score=None,
        )
        sqlite_conn = store.conn

        class PostgresStyleRows:
            def execute(self, sql):
                cursor = sqlite_conn.execute(sql)
                values = tuple(cursor.fetchone())
                names = tuple(col[0] for col in cursor.description)
                return SimpleNamespace(fetchone=lambda: _CompatRow(values, names))

        # PostgreSQL rows are mappings with positional access; iterating them
        # produces column names, not the values used for cache invalidation.
        store.conn = PostgresStyleRows()
        try:
            before = store.review_read_fingerprint()
            sqlite_conn.execute(
                "UPDATE candidate_reviews SET decision = ? WHERE id = ?",
                ("落选", candidate_id),
            )
            after = store.review_read_fingerprint()
        finally:
            store.conn = sqlite_conn

    assert before != after


def test_manual_review_periods_keep_calendar_week_across_year_boundary(tmp_path):
    with PalaceStore(tmp_path / "palace.db") as store:
        store.conn.executemany(
            """INSERT INTO reviews
               (id, reviewed_on, entity_type, entity_id, strategy_tag, outcome,
                return_pct, created_at) VALUES (?, ?, 'candidate', 'test', 'test', 'ok', ?, ?)""",
            [
                ("one", "2025-12-31", 1.0, "2025-12-31"),
                ("two", "2026-01-04", -1.0, "2026-01-04"),
                ("three", "2026-01-05", 2.0, "2026-01-05"),
            ],
        )
        monthly = store.winrate_trend(granularity="month")
        weekly = store.winrate_trend(granularity="week", strategy_tags=["test"])

    assert [(row["period"], row["total"], row["wins"]) for row in monthly] == [
        ("2025-12", 1, 1), ("2026-01", 2, 1),
    ]
    assert [(row["period"], row["total"], row["wins"]) for row in weekly] == [
        ("2025-12-29", 2, 1), ("2026-01-05", 1, 1),
    ]
