"""改判不许改写候选的首次写入时刻。

「盘后真选」的判据是 `created_at` 的日历日等于 `occurred_on`。改判时刷新
`created_at`，会让隔日修正过的候选被重判成回填，从当日真选口径里整条消失
——复盘看到的当日选票数会比实际少。
"""
from __future__ import annotations

from pathlib import Path

import pytest

from src.ledger import PalaceStore


@pytest.fixture()
def store(tmp_path: Path):
    palace = PalaceStore(tmp_path / "palace.db")
    try:
        yield palace
    finally:
        palace.close()


def _created_at(store: PalaceStore, candidate_id: str) -> str:
    return str(
        store.conn.execute(
            "SELECT created_at FROM candidate_reviews WHERE id = ?", (candidate_id,)
        ).fetchone()[0]
    )


def _record(store: PalaceStore, **overrides) -> str:
    payload = {
        "occurred_on": "2026-08-07",
        "code": "600519",
        "name": "贵州茅台",
        "score": 88.0,
        "decision": "精选",
        "reason": "首次写入",
    }
    payload.update(overrides)
    return store.record_candidate(**payload)


def test_rejudging_keeps_the_original_write_instant(store: PalaceStore) -> None:
    candidate_id = _record(store)
    store.conn.execute(
        "UPDATE candidate_reviews SET created_at = ? WHERE id = ?",
        ("2026-08-07T15:31:00+08:00", candidate_id),
    )
    store.conn.commit()

    again = _record(store, decision="观察", reason="隔日改判")

    assert again == candidate_id
    assert _created_at(store, candidate_id) == "2026-08-07T15:31:00+08:00"


def test_rejudged_candidate_stays_in_the_same_day_live_pool(store: PalaceStore) -> None:
    candidate_id = _record(store, source="api:screen")
    store.conn.execute(
        "UPDATE candidate_reviews SET created_at = ? WHERE id = ?",
        ("2026-08-07T15:31:00+08:00", candidate_id),
    )
    store.conn.commit()
    _record(store, source="api:screen", decision="观察", reason="隔日改判")

    live = store.conn.execute(
        "SELECT COUNT(*) FROM candidate_reviews"
        " WHERE substr(REPLACE(IFNULL(created_at, ''), 'T', ' '), 1, 10) = occurred_on"
    ).fetchone()[0]

    assert live == 1


def test_the_rejudged_content_is_still_written(store: PalaceStore) -> None:
    candidate_id = _record(store)
    _record(store, decision="观察", reason="隔日改判")

    row = store.conn.execute(
        "SELECT decision, reason FROM candidate_reviews WHERE id = ?", (candidate_id,)
    ).fetchone()
    assert str(row[0]) == "观察"
    assert str(row[1]) == "隔日改判"
