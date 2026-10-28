#!/usr/bin/env python3
"""Bounded cleanup of Loci-owned backup files.

No database is opened and no Docker object is removed. The caller owns scheduling
and locking; this tool can also preview the exact policy with --dry-run.
"""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import re
import stat
import time


DAY = 86400
AUTO_NAME = re.compile(r"market-consistent-\d{8}-\d{6}\.db\.gz\Z")
LOOSE_BACKUP = re.compile(r"(?:market|market_hot|palace|ops|identity)\.db\.bak(?:[-.].+)?\Z")


def _checked_root(value: str | Path) -> Path:
    root = Path(os.path.abspath(value))
    if root == Path(root.anchor) or not root.is_dir():
        raise ValueError(f"expected an existing application directory: {root}")
    if any(part.is_symlink() for part in (root, *root.parents)):
        raise ValueError(f"symlink root or ancestor is not allowed: {root}")
    return root


def cleanup(
    app_root: str | Path,
    *,
    data_root: str | Path | None = None,
    dry_run: bool = False,
    purge_backups: bool = False,
    manual_days: int = 7,
    auto_days: int = 14,
    auto_keep: int = 1,
    max_files: int = 2000,
    max_scan: int = 20000,
    max_seconds: float = 10,
    now: float | None = None,
) -> dict:
    root = _checked_root(app_root)
    data = _checked_root(data_root or root / "data")
    if not data.is_relative_to(root) or data == root:
        raise ValueError("data root must be a child of the application root")
    if min(manual_days, auto_days, auto_keep) < 0:
        raise ValueError("retention values must be non-negative")
    if max_files < 1 or max_scan < 1 or max_seconds <= 0:
        raise ValueError("cleanup budgets must be positive")
    timestamp = time.time() if now is None else now
    deadline = time.monotonic() + max_seconds
    root_device = root.stat().st_dev
    report = {
        "contract_version": "loci-host-cleanup-v1",
        "observed_at": datetime.fromtimestamp(timestamp, timezone.utc).isoformat(),
        "dry_run": dry_run,
        "purge_backups": purge_backups,
        "policy": {"manual_days": manual_days, "auto_days": auto_days,
                   "auto_keep": auto_keep},
        "scanned_files": 0, "eligible_files": 0, "deleted_files": 0,
        "eligible_bytes": 0, "deleted_bytes": 0,
        "budget_exhausted": False, "skipped_unsafe": [], "errors": [], "files": [],
    }
    candidates: dict[Path, tuple[os.stat_result, str]] = {}

    def safe(path: Path) -> bool:
        if not path.is_relative_to(root):
            return False
        current = path
        while current != root:
            if current.is_symlink():
                return False
            current = current.parent
        try:
            return path.stat(follow_symlinks=False).st_dev == root_device
        except FileNotFoundError:
            return False

    def budget() -> bool:
        if report["scanned_files"] >= max_scan or time.monotonic() >= deadline:
            report["budget_exhausted"] = True
            return False
        return True

    def files(directory: Path, *, recursive: bool = True):
        if not directory.exists():
            return
        if not safe(directory):
            report["skipped_unsafe"].append(str(directory))
            return
        for parent, subdirs, names in os.walk(directory, followlinks=False):
            if not budget():
                return
            base = Path(parent)
            subdirs[:] = sorted(d for d in subdirs if recursive and safe(base / d))
            for name in sorted(names):
                if not budget():
                    return
                path = base / name
                report["scanned_files"] += 1
                if not safe(path):
                    report["skipped_unsafe"].append(str(path))
                    continue
                info = path.stat(follow_symlinks=False)
                if stat.S_ISREG(info.st_mode):
                    yield path, info

    def select(path: Path, info: os.stat_result, reason: str):
        candidates[path] = (info, reason)

    auto_dir = root / "backups" / "storage"
    auto_files = list(files(auto_dir, recursive=False))
    auto_info = dict(auto_files)
    valid_snapshots = []
    for path, info in auto_files:
        if not AUTO_NAME.fullmatch(path.name):
            continue
        manifest = path.with_name(path.name.removesuffix(".db.gz") + ".json")
        # A killed gzip may have created the newest .gz without completing its
        # manifest. Such a partial must not evict the last completed backup.
        if manifest in auto_info:
            valid_snapshots.append((path, info))
    snapshots = sorted(
        valid_snapshots,
        key=lambda item: (item[1].st_mtime, item[0].name), reverse=True,
    )
    retained = set()
    for index, (path, info) in enumerate(snapshots):
        manifest = path.with_name(path.name.removesuffix(".db.gz") + ".json")
        if purge_backups or index >= auto_keep or info.st_mtime < timestamp - auto_days * DAY:
            select(path, info, "automatic_backup_retention")
            for other in (manifest, Path(str(path) + ".json")):
                if other in auto_info:
                    select(other, auto_info[other], "automatic_backup_manifest")
        else:
            retained.update((path, manifest, Path(str(path) + ".json")))
    for path, info in auto_files:
        if path in retained or path in candidates:
            continue
        # A killed .backup/gzip must not leave a full SQLite copy forever.
        days = 1 if path.name.startswith(".market-consistent-") or AUTO_NAME.fullmatch(path.name) else auto_days
        if purge_backups or info.st_mtime < timestamp - days * DAY:
            select(path, info, "automatic_backup_orphan")

    backup_roots = (root / "backups", data / "backups",
                    data / "maintenance-backups", data / "maintenance_backups")
    for directory in backup_roots:
        for path, info in files(directory):
            if path.is_relative_to(auto_dir):
                continue
            if purge_backups or info.st_mtime < timestamp - manual_days * DAY:
                select(path, info, "manual_backup_retention")
    for path, info in files(data, recursive=False):
        if LOOSE_BACKUP.fullmatch(path.name) and (
            purge_backups or info.st_mtime < timestamp - manual_days * DAY
        ):
            select(path, info, "loose_database_backup")

    for path, (info, reason) in sorted(candidates.items(), key=lambda item: item[1][0].st_mtime):
        if report["eligible_files"] >= max_files or time.monotonic() >= deadline:
            report["budget_exhausted"] = True
            break
        try:
            if not safe(path):
                report["skipped_unsafe"].append(str(path))
                continue
            current = path.stat(follow_symlinks=False)
            if (current.st_dev, current.st_ino, current.st_size, current.st_mtime_ns) != (
                info.st_dev, info.st_ino, info.st_size, info.st_mtime_ns
            ):
                report["errors"].append(f"changed during cleanup: {path}")
                continue
            report["eligible_files"] += 1
            report["eligible_bytes"] += info.st_size
            if len(report["files"]) < 100:
                report["files"].append({"path": str(path), "bytes": info.st_size, "reason": reason})
            if not dry_run:
                path.unlink()
                if path.exists() or path.is_symlink():
                    raise OSError("file still exists after unlink")
                report["deleted_files"] += 1
                report["deleted_bytes"] += info.st_size
        except OSError as exc:
            report["errors"].append(f"{path}: {exc}")
    return report


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--app-root", default="/srv/qianlong-loci")
    parser.add_argument("--data-root")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--purge-backups", action="store_true",
                        help="explicitly remove even recent files in the backup allowlist")
    parser.add_argument("--manual-days", type=int, default=7)
    parser.add_argument("--auto-days", type=int, default=14)
    parser.add_argument("--auto-keep", type=int, default=1)
    parser.add_argument("--max-files", type=int, default=2000)
    parser.add_argument("--max-scan", type=int, default=20000)
    parser.add_argument("--max-seconds", type=float, default=10)
    try:
        report = cleanup(**vars(parser.parse_args()))
    except (ValueError, OSError) as exc:
        print(json.dumps({"error": str(exc)}, ensure_ascii=False))
        return 1
    print(json.dumps(report, ensure_ascii=False))
    return 1 if report["errors"] else 0


if __name__ == "__main__":
    raise SystemExit(main())
