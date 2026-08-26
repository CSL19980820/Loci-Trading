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
        ("CA-TAIL", "2026-07-31", "301263", "泰恩康", "精选", "qianlong-tail-v1", "qianlong-tail-v1@2026-07-31", "job:screen"),
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
    assert {r["id"] for r in doomed} == {"CA-OLD", "CA-V2", "CA-SKILL", "CA-TAIL"}
    deleted = mod.apply_delete(con)
    con.commit()
    assert deleted == 4
    left = {r[0] for r in con.execute("SELECT id FROM candidate_reviews")}
    assert left == {"CA-KEEP-V3"}
    con.close()


def _seed_deleted_1450(db: Path) -> None:
    """14:50 两档已连代码删除：精选 / 观察 / 跟踪行都不能再出现。"""
    con = sqlite3.connect(db)
    con.execute(
        """
        CREATE TABLE position_tracking (
            id TEXT PRIMARY KEY,
            strategy_tag TEXT,
            pool_id TEXT,
            code TEXT,
            name TEXT,
            signal_date TEXT,
            status TEXT
        )
        """
    )
    con.executemany(
        "INSERT INTO candidate_reviews VALUES (?,?,?,?,?,?,?,?)",
        [
            ("CA-S1450-PICK", "2026-08-21", "002045", "国光电器", "精选", "sanyuan-tail-1450", "sanyuan-tail-1450@2026-08-21", "job:screen"),
            ("CA-S1450-WATCH", "2026-08-19", "300035", "中科电气", "观察", "sanyuan-tail-1450", "sanyuan-tail-1450@2026-08-19", "job:screen"),
            ("CA-Y1450-PICK", "2026-08-21", "301098", "金埔园林", "精选", "yangshi-tail-1450", "yangshi-tail-1450@2026-08-21", "job:screen"),
            ("CA-QF1450-POOL", "2026-08-18", "003032", "传智教育", "精选", "qianfu-close", "qianfu-1450@2026-08-18", "job:screen"),
            ("CA-KEEP-WATCH", "2026-08-24", "600519", "贵州茅台", "观察", "sanyuan-tail-v1", "sanyuan-tail-v1@2026-08-24", "job:screen"),
        ],
    )
    con.executemany(
        "INSERT INTO position_tracking VALUES (?,?,?,?,?,?,?)",
        [
            ("PT-S1450", "sanyuan-tail-1450", "sanyuan-tail-1450@2026-08-21", "002045", "国光电器", "2026-08-21", "active"),
            ("PT-Y1450", "yangshi-tail-1450", "yangshi-tail-1450@2026-08-17", "002200", "交投生态", "2026-08-17", "expired"),
            ("PT-QF1450", "qianfu-1450", "qianfu-1450@2026-08-18", "003032", "传智教育", "2026-08-18", "active"),
            ("PT-KEEP", "sanyuan-tail-v1", "sanyuan-tail-v1@2026-08-24", "600519", "贵州茅台", "2026-08-24", "active"),
            ("PT-QFCLOSE-POOL", "qianfu-close", "qianfu-1450@2026-08-18", "301520", "万邦医药", "2026-08-18", "active"),
        ],
    )
    con.commit()
    con.close()


def test_deleted_1450_strategies_are_purged_regardless_of_decision(tmp_path: Path) -> None:
    mod = _load_cleanup()
    db = tmp_path / "palace.db"
    _seed(db)
    _seed_deleted_1450(db)
    con = sqlite3.connect(db)
    con.row_factory = sqlite3.Row
    doomed = mod.preview_deleted_strategies(con)
    assert {r["id"] for r in doomed["candidate_reviews"]} == {
        "CA-S1450-PICK",
        "CA-S1450-WATCH",
        "CA-Y1450-PICK",
    }
    assert {r["id"] for r in doomed["position_tracking"]} == {
        "PT-S1450",
        "PT-Y1450",
        "PT-QF1450",
    }
    purged = mod.delete_deleted_strategies(con)
    con.commit()
    assert purged == {"candidate_reviews": 3, "position_tracking": 3}
    left = {r[0] for r in con.execute("SELECT id FROM candidate_reviews")}
    # 归档对照版的重复精选由 apply_delete 管；本用例只盯 14:50 档。
    assert "CA-S1450-PICK" not in left
    assert "CA-S1450-WATCH" not in left
    assert "CA-Y1450-PICK" not in left
    # 自带别的 slug 的行，不因为批次 pool_id 带 1450 就被误删。
    assert "CA-QF1450-POOL" in left
    assert "CA-KEEP-WATCH" in left
    tracks = {r[0] for r in con.execute("SELECT id FROM position_tracking")}
    assert tracks == {"PT-KEEP", "PT-QFCLOSE-POOL"}
    con.close()


def test_purge_tolerates_tables_removed_by_later_migrations(tmp_path: Path) -> None:
    """palace 表会随功能下线消失（如 position_tracking），清理不能因此报错。"""
    mod = _load_cleanup()
    db = tmp_path / "palace.db"
    _seed(db)
    con = sqlite3.connect(db)
    con.row_factory = sqlite3.Row
    doomed = mod.preview_deleted_strategies(con)
    # 只建了 candidate_reviews；position_tracking 不存在时直接缺席。
    assert set(doomed) == {"candidate_reviews"}
    assert mod.delete_deleted_strategies(con) == {"candidate_reviews": 0}
    con.commit()
    con.close()
