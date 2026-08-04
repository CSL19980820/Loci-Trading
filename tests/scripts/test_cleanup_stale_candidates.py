from __future__ import annotations

import importlib.util
import sqlite3
from pathlib import Path


def _load_cleanup():
    path = Path(__file__).resolve().parents[2] / "scripts" / "cleanup_stale_candidate_versions.py"
    spec = importlib.util.spec_from_file_location("cleanup_stale_candidate_versions", path)
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _seed(db: Path) -> None:
    con = sqlite3.connect(db)
    con.execute(
        """
        CREATE TABLE candidate_reviews (
            id TEXT PRIMARY KEY,
            occurred_on TEXT,
            code TEXT,
            name TEXT,
            decision TEXT,
            strategy_slug TEXT,
            pool_id TEXT,
            source TEXT
        )
        """
    )
    rows = [
        ("CA-KEEP-V3", "2026-07-31", "002123", "梦网科技", "精选", "qianlong-close-v3", "qianlong-close-v3@2026-07-31", "job:screen"),
        ("CA-OLD", "2026-07-31", "002123", "梦网科技", "精选", "qianlong-close", "qianlong-close@2026-07-31", "job:screen"),
        ("CA-V2", "2026-07-31", "002123", "梦网科技", "精选", "qianlong-close-v2", "qianlong-close-v2@2026-07-31", "api:screen_run"),
        ("CA-SKILL", "2026-07-29", "002555", "三七互娱", "精选", "", "POOL-2026-07-29-qianlong", "qianlong-skill"),
        ("CA-KEEP-TAIL", "2026-07-31", "301263", "泰恩康", "精选", "qianlong-tail-v1", "qianlong-tail-v1@2026-07-31", "job:screen"),
    ]
    con.executemany(
        "INSERT INTO candidate_reviews VALUES (?,?,?,?,?,?,?,?)",
        rows,
    )
    con.commit()
    con.close()


def test_cleanup_removes_archived_keeps_current(tmp_path: Path) -> None:
    mod = _load_cleanup()
    db = tmp_path / "palace.db"
    _seed(db)
    con = sqlite3.connect(db)
    con.row_factory = sqlite3.Row
    doomed = mod.preview(con)
    assert {r["id"] for r in doomed} == {"CA-OLD", "CA-V2", "CA-SKILL"}
    deleted = mod.apply_delete(con)
    con.commit()
    assert deleted == 3
    left = {r[0] for r in con.execute("SELECT id FROM candidate_reviews")}
    assert left == {"CA-KEEP-V3", "CA-KEEP-TAIL"}
    con.close()
