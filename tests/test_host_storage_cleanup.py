from __future__ import annotations

import os
from pathlib import Path

import pytest

from tools.host_storage_cleanup import DAY, cleanup


NOW = 1_800_000_000


@pytest.fixture
def app(tmp_path):
    root = tmp_path / "loci"
    (root / "data").mkdir(parents=True)
    return root


def put(root: Path, relative: str, *, days: int = 8) -> Path:
    path = root / relative
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(b"test-only")
    os.utime(path, (NOW - days * DAY, NOW - days * DAY))
    return path


def test_dry_run_and_execute_obey_backup_allowlist(app):
    expired = [put(app, relative) for relative in (
        "backups/run/market.db", "data/backups/rollback.sql",
        "data/maintenance-backups/old.tar.gz", "data/maintenance_backups/old.db",
        "data/market.db.bak-20261001", "data/palace.db.bak",
    )]
    protected = [put(app, relative, days=60) for relative in (
        "data/market.db", "data/market_hot.db", "data/palace.db", "data/ops.db",
        "data/.palace_ai_master_key", ".env", "data/unrecognized.bak",
        "data/cache/report.json", "data/tenants/tenant/palace.db.bak",
    )]
    protected.append(put(app, "data/backups/recent.db", days=1))
    preview = cleanup(app, dry_run=True, now=NOW)
    assert preview["eligible_files"] == len(expired)
    assert preview["deleted_files"] == 0
    assert all(path.exists() for path in expired + protected)
    report = cleanup(app, now=NOW)
    assert report["errors"] == []
    assert report["deleted_files"] == len(expired)
    assert report["deleted_bytes"] == len(expired) * len(b"test-only")
    assert all(not path.exists() for path in expired)
    assert all(path.exists() for path in protected)
    assert cleanup(app, now=NOW)["deleted_files"] == 0


def test_automatic_backup_count_age_and_matching_manifest(app):
    oldest = put(app, "backups/storage/market-consistent-20260901-034000.db.gz", days=20)
    older = put(app, "backups/storage/market-consistent-20261001-034000.db.gz", days=6)
    older_manifest = put(app, "backups/storage/market-consistent-20261001-034000.json", days=6)
    newest = put(app, "backups/storage/market-consistent-20261007-034000.db.gz", days=1)
    newest_manifest = put(app, "backups/storage/market-consistent-20261007-034000.json", days=1)
    unfinished_gzip = put(app, "backups/storage/market-consistent-20261008-034000.db.gz", days=0)
    orphan = put(app, "backups/storage/market-consistent-20260801-034000.json", days=30)
    partial = put(app, "backups/storage/.market-consistent-20261003-034000.db", days=3)
    active_partial = put(app, "backups/storage/.market-consistent-20261008-034000.db", days=0)
    report = cleanup(app, now=NOW)
    assert report["deleted_files"] == 5
    assert all(not path.exists() for path in (oldest, older, older_manifest, orphan, partial))
    assert all(path.exists() for path in (newest, newest_manifest, active_partial, unfinished_gzip))
    # Even the sole newest backup has a maximum age, including its manifest.
    assert cleanup(app, now=NOW + 15 * DAY)["deleted_files"] == 4


def test_explicit_purge_deletes_recent_backups_but_no_live_files(app):
    backup = put(app, "data/backups/today/palace.db", days=0)
    active = put(app, "data/palace.db", days=60)
    result = cleanup(app, now=NOW, purge_backups=True)
    assert result["deleted_files"] == 1
    assert not backup.exists()
    assert active.exists()


def test_deletion_budget_reports_partial_and_next_run_continues(app):
    for index in range(3):
        put(app, f"backups/{index}.db")
    result = cleanup(app, now=NOW, max_files=2)
    assert result["deleted_files"] == 2
    assert result["budget_exhausted"] is True
    assert cleanup(app, now=NOW)["deleted_files"] == 1


def test_rejects_root_or_data_outside_app(app, tmp_path):
    with pytest.raises(ValueError, match="child"):
        cleanup(app, data_root=tmp_path)
    with pytest.raises(ValueError, match="child"):
        cleanup(app, data_root=app)
    with pytest.raises(ValueError, match="positive"):
        cleanup(app, max_scan=0)


def test_never_follows_directory_or_file_symlinks(app, tmp_path):
    external = put(tmp_path, "external/palace.db")
    target = app / "backups"
    target.mkdir()
    try:
        (target / "linked").symlink_to(external.parent, target_is_directory=True)
        (target / "linked.db").symlink_to(external)
        (app / "data" / "backups").symlink_to(external.parent, target_is_directory=True)
    except OSError as exc:
        pytest.skip(f"host does not permit symlink creation: {exc}")
    result = cleanup(app, now=NOW, purge_backups=True)
    assert result["deleted_files"] == 0
    assert external.exists()
    assert (target / "linked.db").is_symlink()
    assert result["skipped_unsafe"]
    with pytest.raises(ValueError, match="symlink"):
        cleanup(target / "linked", data_root=external.parent)
