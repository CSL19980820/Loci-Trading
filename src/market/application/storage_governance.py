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
from src.market.infrastructure.history_floor import trade_date_floor
from src.shared.sqlite_retention import delete_in_batches, table_exists
from src.shared.postgres import CompatConnection


MiB = 1024 * 1024
GiB = 1024 * MiB


@dataclass(frozen=True)
class StoragePolicy:
    """默认是服务端 40G 小盘的保守值；参数可由 CLI/宿主脚本显式覆盖。"""

    history_floor: str = ""
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
    incremental_vacuum_pages: int = 8_192
    max_incremental_batches: int = 128


DEFAULT_POLICY = StoragePolicy()

# 旧部署把普通日 K 的地板用于稀疏因子；只移除读回后精确识别的这条历史规则。
_LEGACY_FACTOR_FLOOR_TRIGGER = (
    "CREATE TRIGGER adjust_factors_floor BEFORE INSERT ON adjust_factors "
    "WHEN NEW.trade_date < '2023-01-01' BEGIN SELECT RAISE(IGNORE); END"
)


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
        for name in ("page_count", "page_size", "freelist_count", "journal_mode", "auto_vacuum"):
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


def _retire_legacy_factor_floor(conn: sqlite3.Connection, *, dry_run: bool) -> dict[str, Any]:
    result: dict[str, Any] = {
        "name": "adjust_factors_floor", "present": False, "recognized": False, "removed": False,
    }
    if not dry_run:
        # 判定和 DROP 使用同一写事务，防止读回后触发器被另一个连接替换。
        conn.execute("BEGIN IMMEDIATE")
    try:
        row = conn.execute(
            "SELECT sql FROM sqlite_master WHERE type = 'trigger' "
            "AND name = ? AND tbl_name = ?", ("adjust_factors_floor", "adjust_factors"),
        ).fetchone()
        if row is not None:
            result["present"] = True
            actual = " ".join(str(row[0]).strip().rstrip(";").split()).casefold()
            expected = " ".join(_LEGACY_FACTOR_FLOOR_TRIGGER.split()).casefold()
            result["recognized"] = actual == expected
            if not result["recognized"]:
                result["error"] = "adjust_factors_floor 与已知旧定义不同；保留该触发器并停止维护，请人工核查"
            elif not dry_run:
                conn.execute("DROP TRIGGER adjust_factors_floor")
                result["removed"] = True
        if not dry_run:
            conn.commit()
    except Exception:
        if not dry_run:
            conn.rollback()
        raise
    return result


def _delete_orphan_attempts(conn: sqlite3.Connection, *, batch_size: int) -> int:
    if not table_exists(conn, "source_route_attempts"):
        return 0
    total = 0
    size = max(1, int(batch_size))
    after: tuple[str, int] | None = None
    for _ in range(4000):
        # attempts 的复合主键支持范围查找。每批从上批末尾继续，避免为删除
        # 数百万孤儿而反复扫描仍有回执的同一批保留行。
        boundary = "AND (a.receipt_id, a.attempt_no) > (?, ?) " if after else ""
        rows = conn.execute(
            "SELECT a.receipt_id, a.attempt_no FROM source_route_attempts a "
            "WHERE NOT EXISTS (SELECT 1 FROM source_route_receipts r "
            "WHERE r.receipt_id = a.receipt_id) " + boundary
            + "ORDER BY a.receipt_id, a.attempt_no LIMIT ?",
            (*after, size) if after else (size,),
        ).fetchall()
        if not rows:
            break
        last = (str(rows[-1][0]), int(rows[-1][1]))
        conn.execute("BEGIN IMMEDIATE")
        try:
            # 相同主键范围一次删除，在写锁内再次核对回执仍不存在。
            # 这既避免逐行执行，也不依赖旧 SQLite 对复合键 IN 的优化。
            lower = "AND (receipt_id, attempt_no) > (?, ?) " if after else ""
            cursor = conn.execute(
                "DELETE FROM source_route_attempts WHERE (receipt_id, attempt_no) <= (?, ?) "
                + lower + "AND NOT EXISTS (SELECT 1 FROM source_route_receipts r "
                "WHERE r.receipt_id = source_route_attempts.receipt_id)",
                (*last, *after) if after else last,
            )
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        total += int(cursor.rowcount or 0)
        after = last
        if len(rows) < size:
            break
    return total


def _incremental_reclaim(path: Path, policy: StoragePolicy) -> dict[str, Any]:
    """仅收缩已显式迁移到 INCREMENTAL 的库，限制每批写入与单轮工作量。"""
    size_before = _file_bytes(path)
    conn = sqlite3.connect(path, timeout=5.0)
    conn.execute("PRAGMA busy_timeout=5000")
    batches = 0
    reason = ""
    try:
        if int(conn.execute("PRAGMA auto_vacuum").fetchone()[0]) != 2:
            raise RuntimeError("行情库尚未启用 incremental auto_vacuum")
        pages_before = int(conn.execute("PRAGMA page_count").fetchone()[0])
        free_before = int(conn.execute("PRAGMA freelist_count").fetchone()[0])
        page_size = int(conn.execute("PRAGMA page_size").fetchone()[0])
        pages_after, free_after = pages_before, free_before
        for _ in range(max(1, int(policy.max_incremental_batches))):
            if not free_after:
                break
            count = min(free_after, max(1, int(policy.incremental_vacuum_pages)))
            # 页搬移还会更新父页及 WAL；按批次保留余量，不复制整个数据库。
            required = max(64 * MiB, count * page_size * 4)
            if shutil.disk_usage(path.parent).free < required:
                reason = f"可用空间不足增量回收批次余量 {required / MiB:.0f} MiB"
                break
            checkpoint = conn.execute("PRAGMA wal_checkpoint(TRUNCATE)").fetchone()
            if checkpoint and int(checkpoint[0]):
                reason = "WAL checkpoint 等待读连接释放，暂停增量回收"
                break
            # 此 PRAGMA 每步回收一页，必须消费全部返回行，不能只 execute。
            conn.execute(f"PRAGMA incremental_vacuum({count})").fetchall()
            batches += 1
            current_pages = int(conn.execute("PRAGMA page_count").fetchone()[0])
            free_after = int(conn.execute("PRAGMA freelist_count").fetchone()[0])
            if current_pages >= pages_after:
                reason = "增量回收未减少页数，暂停并保留剩余空闲页"
                break
            pages_after = current_pages
        checkpoint = conn.execute("PRAGMA wal_checkpoint(TRUNCATE)").fetchone()
        if checkpoint and int(checkpoint[0]):
            reason = "WAL checkpoint 等待读连接释放，文件收缩将在后续 checkpoint 生效"
        elif free_after and not reason:
            reason = f"达到增量回收批次上限，剩余 {free_after:,} 个空闲页留待下轮"
    finally:
        conn.close()
    size_after = _file_bytes(path)
    return {
        "mode": "incremental",
        "vacuumed": pages_after < pages_before,
        "batches": batches,
        "pages_reclaimed": max(0, pages_before - pages_after),
        "freelist_pages_before": free_before,
        "freelist_pages_after": free_after,
        "size_before_mb": round(size_before / 1e6, 1),
        "size_after_mb": round(size_after / 1e6, 1),
        "freed_mb": round(max(0, size_before - size_after) / 1e6, 1),
        "skipped_reason": reason,
    }


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
    warnings: list[str] = []
    remaining: dict[str, int] = {}
    archive_batches: list[dict[str, Any]] = []
    vacuum_report: dict[str, Any] = {"vacuumed": False, "skipped_reason": "未执行"}
    page_count = 0
    freelist_pages = 0
    auto_vacuum = 0
    factor_floor_trigger: dict[str, Any] = {}

    conn = (
        sqlite3.connect(f"file:{path}?mode=ro", uri=True, timeout=120.0)
        if dry_run
        else sqlite3.connect(path, timeout=120.0)
    )
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA busy_timeout=120000")
    try:
        factor_floor_trigger = _retire_legacy_factor_floor(conn, dry_run=dry_run)
        if factor_floor_trigger.get("error"):
            raise RuntimeError(str(factor_floor_trigger["error"]))
        for table in ("quotes_daily", "adjust_factors"):
            floor = policy.history_floor or trade_date_floor()
            where = "trade_date < ?"
            params = (floor,)
            if table == "adjust_factors":
                # 累计因子是稀疏事件，行情截断日之前的最后已知值仍是后续复权
                # 的锚点。仅删除另有更晚、且仍早于截断日的因子，绝不取未来值。
                where += (
                    " AND EXISTS (SELECT 1 FROM adjust_factors AS newer "
                    "WHERE newer.code = adjust_factors.code "
                    "AND newer.trade_date > adjust_factors.trade_date "
                    "AND newer.trade_date < ?)"
                )
                params = (floor, floor)
            count = _count(conn, table, where, params)
            if count and not dry_run:
                if table == "adjust_factors":
                    # 因子表 WITHOUT ROWID；按真实复合主键分批，不能使用 rowid。
                    deleted[table] = delete_in_batches(
                        conn, table, params=params, batch=policy.batch_size,
                        key="(code, trade_date)",
                        subquery=("SELECT code, trade_date FROM adjust_factors WHERE "
                                  + where + f" LIMIT {max(1, int(policy.batch_size))}"),
                    )
                else:
                    deleted[table] = delete_in_batches(
                        conn, table, where=where, params=params, batch=policy.batch_size,
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
                    remaining["selected_receipts"] = _count(
                        conn, "source_route_receipts",
                        "state = 'selected' AND julianday(generated_at) < julianday(?)",
                        (cutoff,),
                    )
                    if remaining["selected_receipts"]:
                        # 批次预算用尽不代表已提交的归档失败，也不应永久阻止
                        # 回收本轮已释放的空间；剩余工作明确留给后续轮次。
                        warnings.append(
                            f"selected 回执仍有 {remaining['selected_receipts']} 条待归档，"
                            "本轮已达到归档批次上限"
                        )
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
            auto_vacuum = int(conn.execute("PRAGMA auto_vacuum").fetchone()[0] or 0)
            conn.execute("PRAGMA wal_checkpoint(TRUNCATE)").fetchall()
            # 日维护只需有界统计，避免每轮完整扫描数百万行的所有索引。
            conn.execute("PRAGMA analysis_limit=1000")
            conn.execute("ANALYZE")
            integrity = str(conn.execute("PRAGMA quick_check(1)").fetchone()[0])
            if integrity != "ok":
                errors.append(f"SQLite quick_check: {integrity}"[:500])
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
            # 完整 VACUUM 的临时库和回滚/WAL 最多共需原库两倍额外空间。
            required = int(policy.vacuum_reserve_bytes) + int(size * 2)
            fragmentation_threshold = max(262_144, page_count // 10)
            if auto_vacuum == 2:
                try:
                    vacuum_report = _incremental_reclaim(path, policy)
                except Exception as exc:
                    errors.append(f"incremental VACUUM: {type(exc).__name__}: {exc}"[:400])
                    vacuum_report = {"mode": "incremental", "vacuumed": False, "error": str(exc)[:300]}
            elif freelist_pages < fragmentation_threshold:
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
                        f"磁盘空闲 {free / GiB:.2f} GiB，不足临时空间及保留余量共 {required / GiB:.2f} GiB 的 VACUUM 闸门"
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
            "history_floor": policy.history_floor or trade_date_floor(),
            "selected_before": cutoff,
            "skipped_before": skipped_cutoff,
            "intel_before": intel_cutoff,
        },
        "before": before,
        "deleted": deleted,
        "factor_floor_trigger": factor_floor_trigger,
        "archive_batches": archive_batches,
        "archive_cleanup": archive_cleanup,
        "sqlite_pages": {"page_count": page_count, "freelist_pages": freelist_pages,
                         "auto_vacuum": auto_vacuum},
        "vacuum": vacuum_report,
        "integrity": integrity,
        "errors": errors,
        "warnings": warnings,
        "remaining": remaining,
        "completed": not errors and not any(remaining.values()) and integrity == "ok",
        "after": after,
    }


def report_text(payload: dict[str, Any]) -> str:
    disk = payload.get("disk", {})
    return (
        f"磁盘 {int(disk.get('free_bytes', 0)) / GiB:.2f} GiB 可用 / "
        f"{int(disk.get('total_bytes', 0)) / GiB:.2f} GiB，总状态 {payload.get('status', 'ok')}"
    )


def run_postgres_retention(
    *,
    database_url: str | None = None,
    years: int = 3,
    receipt_days: int = 3,
) -> dict[str, Any]:
    """Apply the long price-history and short provenance-retention windows.

    Daily bars stay small enough to keep three years online.  Source-routing
    receipts are much wider and are generated repeatedly during the day, so
    only the recent audit window remains queryable.  A linked bar keeps its
    source label when its receipt expires; the now-unverifiable receipt id is
    cleared instead of leaving a dangling reference.
    """
    if years < 1:
        raise ValueError("保留年限必须至少为 1")
    if receipt_days < 1:
        raise ValueError("来源回执保留天数必须至少为 1")
    receipt_batch = 50_000
    with CompatConnection(database_url) as conn:
        conn.raw.execute("SET search_path TO market, public")
        conn.raw.commit()
        # The imported schema kept two indexes with no distinct query contract:
        # quotes_date_code duplicates the (trade_date, code) primary key, and
        # attempt lookups all start from receipt_id.  Dropping them is idempotent
        # and avoids paying their write-amplification cost forever.
        conn.raw.execute("DROP INDEX IF EXISTS market.quotes_date_code")
        conn.raw.execute("DROP INDEX IF EXISTS market.idx_source_attempts_source")
        conn.raw.commit()
        cutoff_row = conn.execute(
            "SELECT (CURRENT_DATE - (?::text || ' years')::interval)::date AS cutoff",
            (int(years),),
        ).fetchone()
        cutoff = str(cutoff_row["cutoff"])
        deleted_quotes = conn.execute(
            "DELETE FROM quotes_daily WHERE trade_date < ?", (cutoff,),
        ).rowcount
        deleted_factors = conn.execute(
            """DELETE FROM adjust_factors f
               WHERE f.trade_date < ?
                 AND EXISTS (
                   SELECT 1 FROM adjust_factors newer
                   WHERE newer.code=f.code AND newer.trade_date > f.trade_date
                     AND newer.trade_date < ?
                 )""",
            (cutoff, cutoff),
        ).rowcount
        deleted_calendar = conn.execute(
            "DELETE FROM trading_calendar WHERE trade_date < ?", (cutoff,),
        ).rowcount
        deleted_intel = conn.execute(
            "DELETE FROM intel_snapshots WHERE trade_date < ?", (cutoff,),
        ).rowcount
        receipt_cutoff_row = conn.execute(
            "SELECT (CURRENT_DATE - ?::int)::text AS cutoff",
            (int(receipt_days),),
        ).fetchone()
        receipt_cutoff = str(receipt_cutoff_row["cutoff"])

        detached_quotes = 0
        deleted_receipts = 0
        deleted_receipt_attempts = 0
        while True:
            rows = conn.execute(
                """SELECT receipt_id FROM source_route_receipts
                   WHERE substring(generated_at FROM 1 FOR 10) < ?
                   ORDER BY generated_at, receipt_id LIMIT ?""",
                (receipt_cutoff, receipt_batch),
            ).fetchall()
            receipt_ids = [str(row["receipt_id"]) for row in rows]
            if not receipt_ids:
                break
            try:
                detached = conn.raw.execute(
                    "UPDATE quotes_daily SET receipt_id=NULL "
                    "WHERE receipt_id = ANY(%s)",
                    (receipt_ids,),
                ).rowcount
                attempts = conn.raw.execute(
                    "DELETE FROM source_route_attempts "
                    "WHERE receipt_id = ANY(%s)",
                    (receipt_ids,),
                ).rowcount
                receipts = conn.raw.execute(
                    "DELETE FROM source_route_receipts "
                    "WHERE receipt_id = ANY(%s)",
                    (receipt_ids,),
                ).rowcount
                conn.commit()
            except Exception:
                conn.rollback()
                raise
            detached_quotes += max(0, int(detached or 0))
            deleted_receipt_attempts += max(0, int(attempts or 0))
            deleted_receipts += max(0, int(receipts or 0))
            if len(rows) < receipt_batch:
                break

        # A zero-fallback success needs one selected attempt for close
        # finalization.  Its attempted/skipped/cancelled rows add no evidence
        # beyond requested_sources_json.  Keep every attempt for failed and
        # fallback paths because source diagnosis depends on that detail.
        compacted_attempts = 0
        while True:
            removed = conn.execute(
                """DELETE FROM source_route_attempts
                   WHERE (receipt_id, attempt_no) IN (
                     SELECT a.receipt_id, a.attempt_no
                     FROM source_route_attempts a
                     JOIN source_route_receipts r USING (receipt_id)
                     WHERE a.state <> 'selected'
                       AND r.state = 'selected'
                       AND r.fallback_used = 0
                     LIMIT ?
                   )""",
                (receipt_batch,),
            ).rowcount
            conn.commit()
            compacted_attempts += max(0, int(removed or 0))
            if int(removed or 0) < receipt_batch:
                break

        total_row = conn.execute("SELECT COUNT(*) AS count FROM quotes_daily").fetchone()
        total = int(total_row["count"])
        last_row = conn.execute(
            "SELECT MAX(trade_date) AS last_date FROM quotes_daily"
        ).fetchone()
        last_date = str(last_row["last_date"] or "")
        tail_row = conn.execute(
            "SELECT COUNT(*) AS count FROM quotes_daily WHERE trade_date=?",
            (last_date,),
        ).fetchone() if last_date else {"count": 0}
        tail = int(
            tail_row["count"] if hasattr(tail_row, "keys") else tail_row[0]
        )
        conn.execute(
            """INSERT INTO meta(key,value,updated_at)
               VALUES('quotes_daily_rows_v2',?,CURRENT_TIMESTAMP::text)
               ON CONFLICT(key) DO UPDATE SET
                   value=excluded.value, updated_at=excluded.updated_at""",
            (f"{last_date}|{max(0, total-tail)}",),
        )
        conn.executemany(
            """INSERT INTO meta(key,value,updated_at)
               VALUES(?,?,CURRENT_TIMESTAMP::text)
               ON CONFLICT(key) DO UPDATE SET
                   value=excluded.value, updated_at=excluded.updated_at""",
            [
                ("postgres_receipt_retention_days", str(int(receipt_days))),
                ("postgres_receipt_retention_cutoff", receipt_cutoff),
            ],
        )
        conn.commit()
        return {
            "status": "ok",
            "cutoff": cutoff,
            "receipt_cutoff": receipt_cutoff,
            "deleted": {
                "quotes_daily": max(0, deleted_quotes),
                "adjust_factors": max(0, deleted_factors),
                "trading_calendar": max(0, deleted_calendar),
                "intel_snapshots": max(0, deleted_intel),
                "detached_quote_receipts": detached_quotes,
                "source_route_attempts": deleted_receipt_attempts,
                "source_route_receipts": deleted_receipts,
                "redundant_selected_receipt_attempts": compacted_attempts,
            },
            "quotes_daily_rows": total,
            "quotes_daily_last_date": last_date,
        }


__all__ = [
    "DEFAULT_POLICY",
    "StoragePolicy",
    "report_text",
    "run_postgres_retention",
    "run_storage_maintenance",
    "storage_check",
    "storage_report",
]
