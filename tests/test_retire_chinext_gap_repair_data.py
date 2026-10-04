"""退役脚本在真实隔离 SQLite 文件上的精确范围、备份和回滚验证。"""
from __future__ import annotations

import json
import sqlite3
from pathlib import Path

import pytest

from scripts import retire_chinext_gap_repair_data as retirement


@pytest.fixture
def palace_db(tmp_path):
    path = tmp_path / "palace.db"
    with sqlite3.connect(path) as connection:
        connection.executescript("""
            CREATE TABLE candidate_reviews(id TEXT PRIMARY KEY, code TEXT, strategy_slug TEXT, rule_version TEXT);
            CREATE TABLE reviews(id TEXT PRIMARY KEY, entity_type TEXT, entity_id TEXT, strategy_tag TEXT);
            CREATE TABLE plans(id TEXT PRIMARY KEY, code TEXT, rule_version TEXT, source TEXT);
            CREATE TABLE user_notes(id TEXT PRIMARY KEY, note TEXT);
        """)
        connection.executemany("INSERT INTO candidate_reviews VALUES (?, ?, ?, ?)", [
            ("old-slug", "300972", retirement.RETIRED_SLUG, "未知旧展示"),
            ("old-name", "300972", "", "创业板跳空修复（15:30）"),
            ("old-rule-slug", "300972", "", retirement.RETIRED_SLUG),
            ("yangshi", "300972", "yangshi-tail-v1", "杨氏尾盘选股（15:30）"),
            ("qianlong", "300972", "qianlong-close-v3", "潜龙"),
            ("reference", "300972", "manual", "参考创业板跳空修复（15:30）的自选规则"),
            ("other-slug-old-tag", "300972", "yangshi-tail-v1", "创业板跳空修复（15:30）"),
        ])
        connection.executemany("INSERT INTO reviews VALUES (?, ?, ?, ?)", [
            ("linked-old", "candidate", "old-slug", "任意标签"),
            ("linked-name", "candidate", "old-name", retirement.RETIRED_SLUG),
            ("linked-active", "candidate", "yangshi", "杨氏"),
            ("same-id-plan", "plan", "old-slug", retirement.RETIRED_SLUG),
            ("standalone", "candidate", "missing-id", "创业板跳空修复"),
        ])
        connection.executemany("INSERT INTO plans VALUES (?, ?, ?, ?)", [
            ("manual-old", "300972", retirement.RETIRED_SLUG, "manual"),
            ("manual-active", "300972", "杨氏", "manual"),
        ])
        connection.execute("INSERT INTO user_notes VALUES ('original', '保留原始用户资料')")
    return path


def _ids(path, table):
    with sqlite3.connect(path) as connection:
        return {row[0] for row in connection.execute(f"SELECT id FROM {table}")}


def test_default_dry_run_reports_exact_counts_without_writes(palace_db):
    original = palace_db.read_bytes()
    report = retirement.retire_data(palace_db)
    assert report["mode"] == "dry-run" and report["status"] == "ok"
    assert report["matched"] == {"candidate_reviews": 3, "linked_candidate_reviews": 2}
    assert report["retained_for_review"] == {"plans": 1, "independent_reviews": 2}
    assert report["backup_path"] is None
    assert report["deleted"] == {"candidate_reviews": 0, "linked_candidate_reviews": 0}
    assert palace_db.read_bytes() == original
    assert not (palace_db.parent / "backups").exists()


def test_apply_preserves_other_strategies_manual_records_and_has_readable_backup(palace_db):
    report = retirement.retire_data(palace_db, apply=True)
    assert report["status"] == "ok", report
    assert report["deleted"] == report["matched"]
    assert _ids(palace_db, "candidate_reviews") == {"yangshi", "qianlong", "reference", "other-slug-old-tag"}
    assert _ids(palace_db, "reviews") == {"linked-active", "same-id-plan", "standalone"}
    assert _ids(palace_db, "plans") == {"manual-old", "manual-active"}
    assert _ids(palace_db, "user_notes") == {"original"}
    backup = Path(report["backup_path"])
    assert backup.parent == palace_db.parent / "backups"
    assert "before-retire-chinext-gap-repair-v1" in backup.name
    assert _ids(backup, "candidate_reviews") == {
        "old-slug", "old-name", "old-rule-slug", "yangshi", "qianlong", "reference", "other-slug-old-tag",
    }
    assert _ids(backup, "reviews") == {"linked-old", "linked-name", "linked-active", "same-id-plan", "standalone"}
    with sqlite3.connect(backup) as connection:
        assert connection.execute("PRAGMA quick_check").fetchone()[0] == "ok"
    second = retirement.retire_data(palace_db, apply=True)
    assert second["status"] == "ok"
    assert second["matched"] == second["deleted"] == {"candidate_reviews": 0, "linked_candidate_reviews": 0}
    assert second["backup_path"] is None
    assert list(backup.parent.glob("*.db")) == [backup]


def test_backup_failure_prevents_all_deletions(palace_db, monkeypatch):
    def unavailable(*_args):
        raise OSError("备份目录不可写")

    monkeypatch.setattr(retirement, "_backup_locked_database", unavailable)
    report = retirement.retire_data(palace_db, apply=True)
    assert report["status"] == "error" and "备份目录不可写" in report["error"]
    assert report["deleted"] == {"candidate_reviews": 0, "linked_candidate_reviews": 0}
    assert "old-slug" in _ids(palace_db, "candidate_reviews")
    assert "linked-old" in _ids(palace_db, "reviews")


def test_nonempty_other_strategy_slug_wins_and_null_slug_uses_legacy_fallback(palace_db):
    with sqlite3.connect(palace_db) as connection:
        connection.execute(
            "INSERT INTO candidate_reviews VALUES ('legacy-null', '300972', NULL, ?)",
            (retirement.RETIRED_SLUG,),
        )
        connection.execute(
            "INSERT INTO reviews VALUES ('other-slug-review', 'candidate', 'other-slug-old-tag', ?)",
            (retirement.RETIRED_SLUG,),
        )
    report = retirement.retire_data(palace_db, apply=True)
    assert report["status"] == "ok", report
    assert report["deleted"] == {"candidate_reviews": 4, "linked_candidate_reviews": 2}
    assert "legacy-null" not in _ids(palace_db, "candidate_reviews")
    assert "other-slug-old-tag" in _ids(palace_db, "candidate_reviews")
    assert "other-slug-review" in _ids(palace_db, "reviews")


def test_transaction_failure_rolls_back_linked_reviews_and_candidates(palace_db):
    with sqlite3.connect(palace_db) as connection:
        connection.executescript("""
            CREATE TRIGGER prevent_candidate_delete BEFORE DELETE ON candidate_reviews
            BEGIN SELECT RAISE(ABORT, '模拟候选删除失败'); END;
        """)
    report = retirement.retire_data(palace_db, apply=True)
    assert report["status"] == "error" and "模拟候选删除失败" in report["error"]
    assert report["deleted"] == {"candidate_reviews": 0, "linked_candidate_reviews": 0}
    assert "old-slug" in _ids(palace_db, "candidate_reviews")
    assert "linked-old" in _ids(palace_db, "reviews")
    assert Path(report["backup_path"]).is_file()


def test_missing_optional_tables_and_old_rule_only_schema_are_supported(tmp_path):
    path = tmp_path / "legacy.db"
    with sqlite3.connect(path) as connection:
        connection.execute("CREATE TABLE candidate_reviews(id TEXT PRIMARY KEY, rule_version TEXT)")
        connection.executemany("INSERT INTO candidate_reviews VALUES (?, ?)", [
            ("old", "创业板跳空修复"), ("kept", "杨氏"),
        ])
    report = retirement.retire_data(path, apply=True)
    assert report["status"] == "ok", report
    assert report["deleted"] == {"candidate_reviews": 1, "linked_candidate_reviews": 0}
    assert report["schema"]["reviews"] == report["schema"]["plans"] == []
    assert _ids(path, "candidate_reviews") == {"kept"}


def test_missing_link_fields_fail_closed_instead_of_leaving_orphan_reviews(palace_db):
    with sqlite3.connect(palace_db) as connection:
        connection.execute("DROP TABLE reviews")
        connection.execute("CREATE TABLE reviews(id TEXT PRIMARY KEY, strategy_tag TEXT)")
        connection.execute("INSERT INTO reviews VALUES ('legacy-review', ?)", (retirement.RETIRED_SLUG,))
    report = retirement.retire_data(palace_db, apply=True)
    assert report["status"] == "error" and report["can_apply"] is False
    assert report["backup_path"] is None
    assert "old-slug" in _ids(palace_db, "candidate_reviews")
    assert _ids(palace_db, "reviews") == {"legacy-review"}


def test_backup_includes_committed_wal_data_without_checkpoint(palace_db):
    with sqlite3.connect(palace_db) as writer:
        assert writer.execute("PRAGMA journal_mode=WAL").fetchone()[0] == "wal"
        writer.execute("PRAGMA wal_autocheckpoint=0")
        writer.execute("INSERT INTO user_notes VALUES ('committed-wal', 'WAL 中的资料')")
        writer.commit()
        assert Path(str(palace_db) + "-wal").is_file()
        report = retirement.retire_data(palace_db, apply=True)
        assert report["status"] == "ok", report
        assert _ids(report["backup_path"], "user_notes") == {"original", "committed-wal"}


def test_cli_requires_explicit_database_and_emits_json_dry_run(palace_db, capsys):
    with pytest.raises(SystemExit) as failure:
        retirement.main([])
    assert failure.value.code == 2
    assert retirement.main(["--palace-db", str(palace_db)]) == 0
    report = json.loads(capsys.readouterr().out)
    assert report["mode"] == "dry-run"
    assert report["palace_db"] == str(palace_db.resolve())
    assert "old-slug" in _ids(palace_db, "candidate_reviews")


def test_missing_explicit_database_does_not_create_a_file(tmp_path):
    path = tmp_path / "not-present.db"
    report = retirement.retire_data(path, apply=True)
    assert report["status"] == "error"
    assert not path.exists()
