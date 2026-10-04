"""尾盘退役精确归属、成对备份、跨库回滚与幂等验证。"""
import json
from pathlib import Path
import sqlite3

import pytest

from scripts import retire_tail_micro_right_data as retirement

SLUG = retirement.RETIRED_SLUG
OTHER = "yangshi-tail-v1"


@pytest.fixture
def data_root(tmp_path):
    with sqlite3.connect(tmp_path / "palace.db") as db:
        db.executescript("""
            CREATE TABLE candidate_reviews(id TEXT PRIMARY KEY,code TEXT,strategy_slug TEXT,rule_version TEXT);
            CREATE TABLE reviews(id TEXT PRIMARY KEY,entity_type TEXT,entity_id TEXT,strategy_tag TEXT);
            CREATE TABLE plans(id TEXT PRIMARY KEY,code TEXT,rule_version TEXT,source TEXT);
            CREATE TABLE ai_judgments(id TEXT PRIMARY KEY,strategy_tag TEXT);
            CREATE TABLE trades(id TEXT PRIMARY KEY,code TEXT,source TEXT);
            CREATE TABLE positions(id TEXT PRIMARY KEY,code TEXT);
        """)
        db.executemany("INSERT INTO candidate_reviews VALUES(?,?,?,?)", [
            ("target", "600001", SLUG, "other-label"),
            ("legacy", "600001", "", "尾盘微右侧（15:30）"),
            ("other", "600001", OTHER, SLUG),
            ("reference", "600001", "manual", "参考尾盘微右侧的自选"),
        ])
        db.executemany("INSERT INTO reviews VALUES(?,?,?,?)", [
            ("linked", "candidate", "target", "arbitrary"),
            ("linked-legacy", "candidate", "legacy", "arbitrary"),
            ("other-linked", "candidate", "other", SLUG),
            ("target-standalone", "candidate", "missing", SLUG),
            ("linked-plan", "plan", "target-plan", "arbitrary"),
            ("other-plan", "plan", "kept-plan", SLUG),
            ("label-only", "candidate", "missing-other", "尾盘微右侧"),
        ])
        db.executemany("INSERT INTO plans VALUES(?,?,?,?)", [
            ("target-plan", "600001", SLUG, "strategy"),
            ("kept-plan", "600001", OTHER, "manual"),
            ("label-plan", "600001", "尾盘微右侧", "manual"),
        ])
        db.executemany("INSERT INTO ai_judgments VALUES(?,?)", [("target-ai", SLUG), ("other-ai", OTHER)])
        db.execute("INSERT INTO trades VALUES('manual-trade','600001','manual')")
        db.execute("INSERT INTO positions VALUES('manual-position','600001')")
    with sqlite3.connect(tmp_path / "ops.db") as db:
        db.executescript("""
            CREATE TABLE jobs(id TEXT PRIMARY KEY,name TEXT,kind TEXT,config_json TEXT);
            CREATE TABLE job_runs(id TEXT PRIMARY KEY,job_id TEXT,job_name TEXT,kind TEXT,result_json TEXT,status TEXT);
            CREATE TABLE strategy_docs(slug TEXT PRIMARY KEY);
            CREATE TABLE strategy_versions(id TEXT PRIMARY KEY,slug TEXT);
            CREATE TABLE strategy_backtests(slug TEXT,version TEXT,PRIMARY KEY(slug,version));
            CREATE TABLE meta(key TEXT PRIMARY KEY,value TEXT);
            CREATE TABLE research_jobs(namespace TEXT,id TEXT,payload TEXT,PRIMARY KEY(namespace,id));
            CREATE TABLE user_notes(id TEXT PRIMARY KEY,note TEXT);
        """)
        db.executemany("INSERT INTO jobs VALUES(?,?,?,?)", [
            ("managed", retirement.MANAGED_NAME, "screen", json.dumps({"strategy": SLUG})),
            ("custom", "my tail task", "screen", json.dumps({"strategy": SLUG})),
            ("other", "other task", "screen", json.dumps({"strategy": OTHER})),
            ("misnamed", retirement.MANAGED_NAME, "screen", json.dumps({"strategy": OTHER})),
            ("text-reference", "notes", "sync", json.dumps({"note": SLUG})),
        ])
        db.executemany("INSERT INTO job_runs VALUES(?,?,?,?,?,?)", [
            ("linked", "managed", "old", "screen", "{}", "done"),
            ("linked-custom", "custom", "my tail task", "screen", "{}", "done"),
            ("orphan-named", "missing", retirement.MANAGED_NAME, "screen", "{}", "done"),
            ("orphan-result", "missing", "old", "screen", json.dumps({"strategy": SLUG}), "done"),
            ("other", "other", "other task", "screen", json.dumps({"strategy": OTHER}), "done"),
            ("conflicting-name", "misnamed", retirement.MANAGED_NAME, "screen", json.dumps({"strategy": OTHER}), "done"),
            ("empty-foreign-run", "misnamed", retirement.MANAGED_NAME, "screen", "{}", "done"),
            ("foreign-history", "managed", retirement.MANAGED_NAME, "screen", json.dumps({"strategy": OTHER}), "done"),
            ("note-reference", "text-reference", "notes", "sync", json.dumps({"note": SLUG}), "done"),
        ])
        for slug in (SLUG, OTHER):
            db.execute("INSERT INTO strategy_docs VALUES(?)", (slug,))
            db.execute("INSERT INTO strategy_versions VALUES(?,?)", (slug + "-v1", slug))
            db.execute("INSERT INTO strategy_backtests VALUES(?,?)", (slug, "v1"))
            db.execute("INSERT INTO meta VALUES(?,?)", ("screen_job_opt_out:" + slug, "1"))
            db.execute("INSERT INTO research_jobs VALUES(?,?,?)", ("backtest_jobs.json", slug,
                       json.dumps({"request": {"strategy": slug}})))
        db.execute("INSERT INTO user_notes VALUES('original','preserve original')")
    external = tmp_path / "research_runs" / "RB-001"
    external.mkdir(parents=True)
    (external / "run_card.json").write_text(json.dumps({"strategy_slug": SLUG}), encoding="utf-8")
    return tmp_path


def ids(path, table, column="id"):
    with sqlite3.connect(path) as db:
        return {row[0] for row in db.execute(f"SELECT {column} FROM {table}")}


def test_dry_run_does_not_write_and_reports_external_runs(data_root):
    before = {name: (data_root / name).read_bytes() for name in ("palace.db", "ops.db")}
    report = retirement.retire_data(data_root=data_root)
    assert report["status"] == "ok" and report["can_apply"], report
    assert report["matched"] == {
        "reviews": 4, "candidate_reviews": 2, "plans": 1, "ai_judgments": 1,
        "job_runs": 4, "jobs": 2, "strategy_docs": 1, "strategy_versions": 1,
        "strategy_backtests": 1, "meta": 1, "research_jobs": 1,
    }
    assert all(value == 0 for value in report["deleted"].values())
    assert report["retained_for_review"]["legacy_label_plans"] == 1
    assert report["external_research_runs"]["matched_manifests"] == [str(data_root / "research_runs/RB-001/run_card.json")]
    assert not (data_root / "backups").exists()
    assert all((data_root / name).read_bytes() == content for name, content in before.items())


def test_apply_keeps_other_strategy_same_stock_and_manual_positions_and_is_idempotent(data_root):
    report = retirement.retire_data(data_root=data_root, apply=True)
    assert report["status"] == "ok", report
    assert report["deleted"] == report["matched"]
    assert ids(data_root / "palace.db", "candidate_reviews") == {"other", "reference"}
    assert ids(data_root / "palace.db", "reviews") == {"other-linked", "other-plan", "label-only"}
    assert ids(data_root / "palace.db", "trades") == {"manual-trade"}
    assert ids(data_root / "palace.db", "positions") == {"manual-position"}
    assert ids(data_root / "ops.db", "jobs") == {"other", "misnamed", "text-reference"}
    assert ids(data_root / "ops.db", "job_runs") == {
        "other", "conflicting-name", "empty-foreign-run", "foreign-history", "note-reference",
    }
    assert ids(data_root / "ops.db", "strategy_docs", "slug") == {OTHER}
    assert (data_root / "research_runs/RB-001/run_card.json").is_file()
    assert set(report["backups"]) == {"main", "ops"}
    assert ids(report["backups"]["main"], "candidate_reviews") == {"target", "legacy", "other", "reference"}
    assert ids(report["backups"]["ops"], "jobs") == {"managed", "custom", "other", "misnamed", "text-reference"}
    second = retirement.retire_data(data_root=data_root, apply=True)
    assert second["status"] == "ok" and not any(second["matched"].values())
    assert second["backups"] == {}
    assert len(list((data_root / "backups").glob("*.db"))) == 2


def test_known_prefixes_and_whitespace_are_exactly_normalized(data_root):
    target_keys = [" skill: " + SLUG.upper() + " ", " SCREEN:" + SLUG.upper() + " ", " " + SLUG.upper() + " "]
    with sqlite3.connect(data_root / "ops.db") as db:
        for index, key in enumerate(target_keys):
            job_id = f"prefixed-{index}"
            field = "strategy_slug" if index == 1 else "strategy"
            db.execute("INSERT INTO jobs VALUES(?,?,?,?)", (job_id, "custom task", "screen", json.dumps({field: key})))
            db.execute("INSERT INTO job_runs VALUES(?,?,?,?,?,?)", (job_id, job_id, "custom task", "screen",
                       "{}" if index == 0 else json.dumps({field: key}), "done"))
            db.execute("INSERT INTO research_jobs VALUES(?,?,?)", ("backtest_jobs.json", job_id,
                       json.dumps({"request": {field: key}})))
        for job_id, key in (("near-prefix", "skill:" + SLUG + "-other"),
                            ("retargeted-prefix", " skill: " + OTHER.upper() + " "),
                            ("double-prefix", "skill:screen:" + SLUG)):
            db.execute("INSERT INTO jobs VALUES(?,?,?,?)", (job_id, retirement.MANAGED_NAME, "screen",
                       json.dumps({"strategy": key})))
            db.execute("INSERT INTO job_runs VALUES(?,?,?,?,?,?)", (job_id, job_id, retirement.MANAGED_NAME,
                       "screen", "{}", "done"))
            db.execute("INSERT INTO research_jobs VALUES(?,?,?)", ("backtest_jobs.json", job_id,
                       json.dumps({"request": {"strategy": key}})))
    external = data_root / "research_runs/RB-002"
    external.mkdir()
    (external / "run_card.json").write_text(json.dumps({"strategy_slug": target_keys[0]}), encoding="utf-8")
    (data_root / "research_runs/backtest_jobs.json").write_text(json.dumps({"jobs": {
        "prefixed": {"request": {"strategy": target_keys[1]}},
        "foreign": {"request": {"strategy": "skill:" + OTHER}},
    }}), encoding="utf-8")
    report = retirement.retire_data(data_root=data_root, apply=True)
    assert report["status"] == "ok", report
    assert report["deleted"]["jobs"] == 5
    assert report["deleted"]["job_runs"] == 7
    assert report["deleted"]["research_jobs"] == 4
    for table in ("jobs", "job_runs", "research_jobs"):
        remaining = ids(data_root / "ops.db", table)
        assert not {"prefixed-0", "prefixed-1", "prefixed-2"} & remaining
        assert {"near-prefix", "retargeted-prefix", "double-prefix"} <= remaining
    assert str(external / "run_card.json") in report["external_research_runs"]["matched_manifests"]
    assert report["external_research_runs"]["legacy_research_job_ids"] == ["prefixed"]
    assert (external / "run_card.json").is_file()


def test_partial_backups_are_private_before_database_copy(data_root, monkeypatch):
    original = Path.chmod
    private_backups = []

    def chmod(path, mode, *args, **kwargs):
        if path.name.endswith(".db.partial"):
            assert mode == 0o600 and path.stat().st_size == 0
            private_backups.append(path)
        return original(path, mode, *args, **kwargs)

    monkeypatch.setattr(Path, "chmod", chmod)
    report = retirement.retire_data(data_root=data_root, apply=True)
    assert report["status"] == "ok", report
    assert len(private_backups) == 2
    assert all(not path.exists() for path in private_backups)


def test_second_backup_failure_does_not_delete_either_database(data_root, monkeypatch):
    original = retirement._backup_locked_database
    calls = []

    def backup(path, expected):
        calls.append(path)
        if len(calls) == 2:
            raise OSError("second backup failed")
        return original(path, expected)

    monkeypatch.setattr(retirement, "_backup_locked_database", backup)
    report = retirement.retire_data(data_root=data_root, apply=True)
    assert report["status"] == "error" and "second backup failed" in report["error"]
    assert not any(report["deleted"].values())
    assert "target" in ids(data_root / "palace.db", "candidate_reviews")
    assert "managed" in ids(data_root / "ops.db", "jobs")


def test_delete_failure_rolls_back_both_databases(data_root):
    with sqlite3.connect(data_root / "ops.db") as db:
        db.executescript("CREATE TRIGGER stop_delete BEFORE DELETE ON jobs BEGIN SELECT RAISE(ABORT,'stop'); END;")
    report = retirement.retire_data(data_root=data_root, apply=True)
    assert report["status"] == "error" and "stop" in report["error"]
    assert "target" in ids(data_root / "palace.db", "candidate_reviews")
    assert "linked" in ids(data_root / "palace.db", "reviews")
    assert "linked" in ids(data_root / "ops.db", "job_runs")


def test_backup_preserves_committed_wal_and_active_runs_block_apply(data_root):
    with sqlite3.connect(data_root / "ops.db") as writer:
        writer.execute("PRAGMA journal_mode=WAL")
        writer.execute("PRAGMA wal_autocheckpoint=0")
        writer.execute("INSERT INTO user_notes VALUES('wal-only','committed WAL original')")
        writer.commit()
        report = retirement.retire_data(data_root=data_root, apply=True)
        assert report["status"] == "ok", report
        assert ids(report["backups"]["ops"], "user_notes") == {"original", "wal-only"}


def test_running_target_and_missing_schema_fail_closed(data_root):
    with sqlite3.connect(data_root / "ops.db") as db:
        db.execute("UPDATE job_runs SET status='running' WHERE id='linked'")
    report = retirement.retire_data(data_root=data_root, apply=True)
    assert report["status"] == "error" and report["active_target_runs"] == 1
    assert not report["backups"] and "target" in ids(data_root / "palace.db", "candidate_reviews")
    with sqlite3.connect(data_root / "palace.db") as db:
        db.execute("DROP TABLE reviews")
        db.execute("CREATE TABLE reviews(id TEXT PRIMARY KEY)")
    report = retirement.retire_data(data_root=data_root, apply=True)
    assert report["status"] == "error" and not report["can_apply"]


def test_explicit_paths_required_and_missing_files_not_created(tmp_path, data_root, capsys):
    with pytest.raises(SystemExit) as failure:
        retirement.main([])
    assert failure.value.code == 2
    assert retirement.main(["--data-root", str(data_root)]) == 0
    assert json.loads(capsys.readouterr().out)["mode"] == "dry-run"
    assert retirement.retire_data(data_root=tmp_path / "missing", apply=True)["status"] == "error"
    assert not (tmp_path / "missing").exists()
    assert retirement.retire_data(palace_db=data_root / "palace.db", ops_db=data_root / "ops.db")["status"] == "ok"
