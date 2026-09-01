"""行情库磁盘回收。

`DROP INDEX` 只把页归还给 SQLite 的库内空闲链，文件大小纹丝不动——下次写入会
复用这些页，但用户看到的 `market.db` 还是 5.7 GB。要真正把空间还给操作系统只有
`VACUUM`，而 `VACUUM` 需要**约等于当前库大小的额外磁盘**（把整库重写到临时文件
再换回），在 5.7 GB 的库上是分钟级操作且全程持写锁。

所以这件事必须是**显式命令**，不能塞进启动迁移里：否则用户某天双击 Loci，会看到
它卡住几分钟且磁盘暴涨一倍。

口径：本模块只做「量一量、清一清」，不改任何行情事实。
"""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
import sqlite3

#: `VACUUM` 需要的额外磁盘倍数（保守取 1.1×；官方文档口径是「约等于库大小」）。
VACUUM_HEADROOM_RATIO = 1.1

#: 权威库上确认无热路径消费者、可安全删除的索引。
#: `idx_quotes_receipt` 唯一的 `NOT EXISTS` 探测消费者只跑在热库
#: （`store_hot._purge_orphan_receipts`），schema v8 起权威库不再建它。
RECLAIMABLE_INDEXES = ("idx_quotes_receipt",)


@dataclass
class ReclaimReport:
    """一次回收的前后对照。所有体积单位为字节。"""

    db_path: str
    size_before: int
    size_after: int
    dropped_indexes: list[str] = field(default_factory=list)
    freelist_pages_before: int = 0
    vacuumed: bool = False
    skipped_reason: str = ""

    @property
    def freed(self) -> int:
        return max(0, self.size_before - self.size_after)

    def to_dict(self) -> dict[str, object]:
        return {
            "contract_version": "market-reclaim-v1",
            "db_path": self.db_path,
            "size_before_mb": round(self.size_before / 1e6, 1),
            "size_after_mb": round(self.size_after / 1e6, 1),
            "freed_mb": round(self.freed / 1e6, 1),
            "dropped_indexes": list(self.dropped_indexes),
            "freelist_pages_before": int(self.freelist_pages_before),
            "vacuumed": bool(self.vacuumed),
            "skipped_reason": self.skipped_reason,
        }


def _existing_indexes(conn: sqlite3.Connection, names: tuple[str, ...]) -> list[str]:
    rows = conn.execute(
        "SELECT name FROM sqlite_master WHERE type='index' AND name IN ("
        + ",".join("?" for _ in names)
        + ")",
        names,
    ).fetchall()
    return sorted(str(row[0]) for row in rows)


def _freelist_pages(conn: sqlite3.Connection) -> int:
    try:
        return int(conn.execute("PRAGMA freelist_count").fetchone()[0])
    except (sqlite3.Error, TypeError, IndexError):
        return 0


def reclaim_market_db(
    db_path: Path | str,
    *,
    vacuum: bool = True,
    free_bytes: int | None = None,
) -> ReclaimReport:
    """删掉可回收索引，并可选 `VACUUM` 把空间还给操作系统。

    `free_bytes` 是调用方测得的磁盘剩余空间；不足时**跳过 VACUUM 而不是失败**——
    索引已经删掉，页已经归还库内空闲链，下次写入照样复用，只是文件没缩小。
    半路失败的 VACUUM 比不做更糟。
    """
    path = Path(db_path)
    if not path.exists():
        raise FileNotFoundError(f"行情库不存在：{path}")
    size_before = path.stat().st_size
    conn = sqlite3.connect(path, timeout=60.0)
    try:
        conn.execute("PRAGMA busy_timeout=60000")
        dropped = _existing_indexes(conn, RECLAIMABLE_INDEXES)
        for name in dropped:
            conn.execute(f"DROP INDEX IF EXISTS {name}")
        conn.commit()
        freelist = _freelist_pages(conn)
        skipped = ""
        did_vacuum = False
        if not vacuum:
            skipped = "调用方要求不 VACUUM"
        elif free_bytes is not None and free_bytes < size_before * VACUUM_HEADROOM_RATIO:
            need = size_before * VACUUM_HEADROOM_RATIO
            skipped = (
                f"磁盘剩余 {free_bytes / 1e9:.1f} GB 不足 VACUUM 所需的约 "
                f"{need / 1e9:.1f} GB，已跳过（索引仍已删除）"
            )
        else:
            # VACUUM 不能在事务里跑。
            conn.isolation_level = None
            conn.execute("VACUUM")
            did_vacuum = True
    finally:
        conn.close()
    return ReclaimReport(
        db_path=str(path),
        size_before=size_before,
        size_after=path.stat().st_size,
        dropped_indexes=dropped,
        freelist_pages_before=freelist,
        vacuumed=did_vacuum,
        skipped_reason=skipped,
    )


__all__ = ["RECLAIMABLE_INDEXES", "ReclaimReport", "reclaim_market_db"]
