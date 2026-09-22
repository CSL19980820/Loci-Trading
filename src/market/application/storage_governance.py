"""行情存储治理：容量报告、保留期清理与高峰操作闸门。

这层把原先散落在宿主脚本里的 SQL 规则收回应用侧，保证桌面、容器和定时任务
使用同一份保留口径。它不触碰 palace.db，也不自动删除用户手工备份。
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
import shutil
import sqlite3
from typing import Any

from src.market.application.provenance_archive import (
    archive_selected_batch,
    default_archive_root,
    prune_archive,
)
from src.market.application.reclaim import reclaim_market_db
from src.shared.sqlite_retention import delete_in_batches, table_exists


MiB = 1024 * 1024
GiB = 1024 * MiB


@dataclass(frozen=True)
class StoragePolicy:
    """默认是服务端 40G 小盘的保守值；参数可由 CLI/宿主脚本显式覆盖。"""

    history_floor: str = "2023-01-01"
    selected_keep_days: int = 14
    skipped_keep_days: int = 7
    intel_keep_days: int = 30
    archive_keep_days: int = 90
    batch_size: int = 20_000
    max_archive_batches: int = 20
    warning_free_bytes: int = 10 * GiB
    critical_free_bytes: int = 6 * GiB
    vacuum_reserve_bytes: int = 10 * GiB
    wal_warning_bytes: int = 512 * MiB


DEFAULT_POLICY = StoragePolicy()


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _file_bytes(path: Path) -> int:
    try:
        return path.stat().st_size
    except OSError:
        return 0


def _sidecar_bytes(path: Path) -> int:
    total = 0
    for suffix in ("", "-wal", "-shm"):
        total += _file_bytes(Path(str(path) + suffix))
    return total


def _directory_bytes(path: Path) -> int:
    if not path.is_dir():
        return 0
    total = 0
    for item in path.rglob("*"):
        try:
            if item.is_file():
                total += item.stat().st_size
        except OSError:
            continue
    return total


def _table_sizes(conn: sqlite3.Connection) -> list[dict[str, Any]]:
    try:
        rows = conn.execute(
            "SELECT name, SUM(pgsize) AS bytes, COUNT(*) AS pages "
            "FROM dbstat GROUP BY name ORDER BY bytes DESC"
        ).fetchall()
    except sqlite3.Error:
        return []
    return [
        {"name": str(row[0]), "bytes": int(row[1] or 0), "pages": int(row[2] or 0)}
        for row in rows
    ]


def _database_report(path: Path, *, include_tables: bool) -> dict[str, Any]:
    main_bytes = 0
    try:
        main_bytes = path.stat().st_size
    except OSError:
        pass
    result: dict[str, Any] = {
        "path": str(path),
        "exists": path.is_file(),
        "main_bytes": main_bytes,
        "bytes": _sidecar_bytes(path),
        "wal_bytes": _file_bytes(Path(str(path) + "-wal")),
        "tables": [],
    }
    if not path.is_file():
        return result
    try:
        conn = sqlite3.connect(f"file:{path}?mode=ro", uri=True, timeout=15)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA query_only=ON")
        for name in ("page_count", "page_size", "freelist_count", "journal_mode"):
            try:
                result[name] = conn.execute(f"PRAGMA {name}").fetchone()[0]
            except sqlite3.Error:
                result[name] = None
        if include_tables:
            result["tables"] = _table_sizes(conn)
        conn.close()
    except sqlite3.Error as exc:
        result["error"] = f"{type(exc).__name__}: {exc}"[:300]
    return result


def storage_report(
    db_path: Path | str,
    *,
    include_tables: bool = True,
    policy: StoragePolicy = DEFAULT_POLICY,
) -> dict[str, Any]:
    """返回当前磁盘、数据库边车、热点目录和 SQLite 页面的可审计快照。"""
    db = Path(db_path)
    root = db.parent
    usage = shutil.disk_usage(root)
    databases = {
        name: _database_report(root / name, include_tables=include_tables)
        for name in ("market.db", "market_hot.db", "ops.db", "palace.db")
    }
    directories = {
        name: _directory_bytes(root / name)
        for name in ("backups", "archives", "intraday", "research_runs", "skill_runs")
    }
    return {
        "contract_version": "loci-storage-report-v1",
        "generated_at": _now().isoformat(),
        "root": str(root),
        "disk": {
            "total_bytes": int(usage.total),
            "used_bytes": int(usage.used),
            "free_bytes": int(usage.free),
            "used_ratio": round(usage.used / usage.total, 6) if usage.total else 1.0,
        },
        "databases": databases,
        "directories": directories,
        "policy": {
            "history_floor": policy.history_floor,
            "selected_keep_days": int(policy.selected_keep_days),
            "skipped_keep_days": int(policy.skipped_keep_days),
            "intel_keep_days": int(policy.intel_keep_days),
            "archive_keep_days": int(policy.archive_keep_days),
            "warning_free_bytes": int(policy.warning_free_bytes),
            "critical_free_bytes": int(policy.critical_free_bytes),
        },
    }


def storage_check(
    db_path: Path | str,
    *,
    policy: StoragePolicy = DEFAULT_POLICY,
) -> dict[str, Any]:
    """轻量容量闸门；不扫描 dbstat，不写数据库。"""
    report = storage_report(db_path, include_tables=False, policy=policy)
    free = int(report["disk"]["free_bytes"])
    market = report["databases"]["market.db"]
    reasons: list[str] = []
    status = "ok"
    if free < int(policy.critical_free_bytes):
        status = "critical"
        reasons.append("磁盘可用空间低于 critical 阈值")
    elif free < int(policy.warning_free_bytes):
        status = "warning"
        reasons.append("磁盘可用空间低于 warning 阈值")
    if int(market.get("wal_bytes", 0) or 0) >= int(policy.wal_warning_bytes):
        if status == "ok":
            status = "warning"
        reasons.append("market.db WAL 超过阈值")
    report.update({"status": status, "reasons": reasons})
    return report


def _count(conn: sqlite3.Connection, table: str, where: str = "", params: tuple[Any, ...] = ()) -> int:
    if not table_exists(conn, table):
        return 0
    clause = f" WHERE {where}" if where else ""
    row = conn.execute(f"SELECT COUNT(*) FROM {table}{clause}", params).fetchone()
    return int(row[0] or 0) if row else 0


def _delete_orphan_attempts(conn: sqlite3.Connection, *, batch_size: int) -> int:
    if not table_exists(conn, "source_route_attempts"):
        return 0
    total = 0
    size = max(1, int(batch_size))
    for _ in range(4000):
        rows = conn.execute(
            "SELECT a.receipt_id, a.attempt_no FROM source_route_attempts a "
            "WHERE NOT EXISTS (SELECT 1 FROM source_route_receipts r "
            "WHERE r.receipt_id = a.receipt_id) LIMIT ?",
            (size,),
        ).fetchall()
        if not rows:
            break
        conn.execute("BEGIN IMMEDIATE")
        try:
            for receipt_id, attempt_no in rows:
                conn.execute(
                    "DELETE FROM source_route_attempts WHERE receipt_id = ? AND attempt_no = ?",
                    (receipt_id, attempt_no),
                )
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        total += len(rows)
        if len(rows) < size:
            break
    return total


def _count_floor(conn: sqlite3.Connection, table: str, floor: str) -> int:
    return _count(conn, table, "trade_date < ?", (floor,))


def run_storage_maintenance(
    db_path: Path | str,
    *,
    archive_root: Path | str | None = None,
    policy: StoragePolicy = DEFAULT_POLICY,
    vacuum: bool = True,
    dry_run: bool = False,
) -> dict[str, Any]:
    """执行一次有上限、可重跑的行情存储维护。

    关键顺序：旧 selected 回执归档并核验成功后才删除；VACUUM 只有在删除后仍
    能保留 ``vacuum_reserve_bytes`` 时才执行。磁盘不足不会用危险的强制压缩换取
    一次绿色任务。
    """
    path = Path(db_path)
    root = path.parent
    archive = Path(archive_root) if archive_root else default_archive_root(path)
    before = storage_report(path, include_tables=False, policy=policy)
    cutoff = (_now() - timedelta(days=max(0, int(policy.selected_keep_days)))).isoformat()
    skipped_cutoff = (
        _now() - timedelta(days=max(0, int(policy.skipped_keep_days)))
    ).isoformat()
    intel_cutoff = (_now() - timedelta(days=max(0, int(policy.intel_keep_days)))).date().isoformat()
    deleted: dict[str, int] = {}
    errors: list[str] = []
    archive_batches: list[dict[str, Any]] = []
    vacuum_report: dict[str, Any] = {"vacuumed": False, "skipped_reason": "未执行"}
    page_count = 0
    freelist_pages = 0

    conn = (
        sqlite3.connect(f"file:{path}?mode=ro", uri=True, timeout=120.0)
        if dry_run
        else sqlite3.connect(path, timeout=120.0)
    )
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA busy_timeout=120000")
    try:
        for table in ("quotes_daily", "adjust_factors"):
            count = _count_floor(conn, table, policy.history_floor)
            if count and not dry_run:
                deleted[table] = delete_in_batches(
                    conn, table, where="trade_date < ?", params=(policy.history_floor,),
                    batch=policy.batch_size,
                )
            else:
                deleted[table] = count

        if table_exists(conn, "source_route_receipts"):
            if dry_run:
                deleted["selected_receipts"] = _count(
                    conn, "source_route_receipts",
                    "state = 'selected' AND julianday(generated_at) < julianday(?)",
                    (cutoff,),
                )
                deleted["selected_attempts"] = 0
            else:
                for _ in range(max(1, int(policy.max_archive_batches))):
                    batch = archive_selected_batch(
                        conn, archive, cutoff=cutoff,
                        batch_size=policy.batch_size, dry_run=False,
                    )
                    if not batch.get("receipts"):
                        break
                    archive_batches.append(batch)
                if archive_batches and archive_batches[-1].get("receipts"):
                    # 达到上限时留下清晰的“还有下一批”证据，而不是假装清完。
                    remaining = _count(
                        conn, "source_route_receipts",
                        "state = 'selected' AND julianday(generated_at) < julianday(?)",
                        (cutoff,),
                    )
                    if remaining:
                        errors.append(f"selected 回执仍有 {remaining} 条待归档")
                deleted["selected_receipts"] = sum(
                    int(item.get("receipts", 0)) for item in archive_batches
                )
                deleted["selected_attempts"] = sum(
                    int(item.get("attempts", 0)) for item in archive_batches
                )

        deleted["skipped_receipts"] = (
            _count(conn, "source_route_receipts", "state = 'skipped' AND julianday(generated_at) < julianday(?)", (skipped_cutoff,))
            if dry_run else delete_in_batches(
                conn, "source_route_receipts",
                where="state = 'skipped' AND julianday(generated_at) < julianday(?)",
                params=(skipped_cutoff,), batch=policy.batch_size,
            )
        )
        deleted["orphan_attempts"] = 0 if dry_run else _delete_orphan_attempts(
            conn, batch_size=policy.batch_size
        )
        deleted["intel_snapshots"] = (
            _count(conn, "intel_snapshots", "trade_date < ?", (intel_cutoff,))
            if dry_run else delete_in_batches(
                conn, "intel_snapshots", where="trade_date < ?", params=(intel_cutoff,),
                batch=policy.batch_size,
            )
        )
        if not dry_run:
            page_count = int(conn.execute("PRAGMA page_count").fetchone()[0] or 0)
            freelist_pages = int(conn.execute("PRAGMA freelist_count").fetchone()[0] or 0)
            conn.execute("PRAGMA wal_checkpoint(TRUNCATE)").fetchall()
            conn.execute("ANALYZE")
            integrity = str(conn.execute("PRAGMA quick_check(1)").fetchone()[0])
        else:
            integrity = "not_run"
    except Exception as exc:  # keep the receipt useful; caller still gets non-zero on errors
        errors.append(f"{type(exc).__name__}: {exc}"[:500])
        integrity = "not_run"
    finally:
        conn.close()

    if not dry_run:
        try:
            archive_cleanup = prune_archive(archive, keep_days=policy.archive_keep_days)
        except Exception as exc:  # archive retention failure must not delete market rows
            archive_cleanup = {"error": f"{type(exc).__name__}: {exc}"[:300]}
            errors.append(str(archive_cleanup["error"]))
        if vacuum and integrity == "ok" and not errors:
            free = shutil.disk_usage(root).free
            size = path.stat().st_size if path.exists() else 0
            required = max(
                int(policy.vacuum_reserve_bytes), int(size * 1.1)
            )
            fragmentation_threshold = max(262_144, page_count // 10)
            if freelist_pages < fragmentation_threshold:
                vacuum_report = {
                    "vacuumed": False,
                    "skipped_reason": (
                        f"空闲页 {freelist_pages:,} 少于碎片阈值 {fragmentation_threshold:,}，无需重写"
                    ),
                }
            elif free >= required:
                try:
                    report = reclaim_market_db(path, vacuum=True, free_bytes=free)
                    vacuum_report = report.to_dict()
                except Exception as exc:
                    errors.append(f"VACUUM: {type(exc).__name__}: {exc}"[:400])
                    vacuum_report = {"vacuumed": False, "error": str(exc)[:300]}
            else:
                vacuum_report = {
                    "vacuumed": False,
                    "skipped_reason": (
                        f"磁盘空闲 {free / GiB:.2f} GiB，不足保留 {required / GiB:.2f} GiB 的 VACUUM 闸门"
                    ),
                }
        elif vacuum:
            vacuum_report = {
                "vacuumed": False,
                "skipped_reason": "维护存在错误或完整性检查未通过，跳过 VACUUM",
            }
    else:
        archive_cleanup = {"dry_run": True}

    after = storage_report(path, include_tables=False, policy=policy)
    return {
        "contract_version": "loci-storage-maintenance-v1",
        "generated_at": _now().isoformat(),
        "db_path": str(path),
        "archive_root": str(archive),
        "dry_run": bool(dry_run),
        "cutoffs": {
            "history_floor": policy.history_floor,
            "selected_before": cutoff,
            "skipped_before": skipped_cutoff,
            "intel_before": intel_cutoff,
        },
        "before": before,
        "deleted": deleted,
        "archive_batches": archive_batches,
        "archive_cleanup": archive_cleanup,
        "sqlite_pages": {"page_count": page_count, "freelist_pages": freelist_pages},
        "vacuum": vacuum_report,
        "integrity": integrity,
        "errors": errors,
        "after": after,
    }


def report_text(payload: dict[str, Any]) -> str:
    disk = payload.get("disk", {})
    return (
        f"磁盘 {int(disk.get('free_bytes', 0)) / GiB:.2f} GiB 可用 / "
        f"{int(disk.get('total_bytes', 0)) / GiB:.2f} GiB，总状态 {payload.get('status', 'ok')}"
    )


__all__ = [
    "DEFAULT_POLICY",
    "StoragePolicy",
    "report_text",
    "run_storage_maintenance",
    "storage_check",
    "storage_report",
]
