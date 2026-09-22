"""行情落库的不可重试故障识别与热库重建空间预检。"""
from __future__ import annotations

import errno
from pathlib import Path
import shutil
import sqlite3


_FATAL_SQLITE_CODES = {
    sqlite3.SQLITE_FULL,
    sqlite3.SQLITE_IOERR,
    sqlite3.SQLITE_CORRUPT,
    sqlite3.SQLITE_NOTADB,
    sqlite3.SQLITE_READONLY,
}
_FATAL_OS_CODES = {errno.ENOSPC, errno.EDQUOT, errno.EIO, errno.EROFS}
_FATAL_SQLITE_MESSAGES = {
    "database or disk is full",
    "disk i/o error",
    "database disk image is malformed",
    "file is not a database",
    "attempt to write a readonly database",
}
_REBUILD_RESERVE_BYTES = 512 * 1024 * 1024


def is_fatal_storage_error(error: BaseException) -> bool:
    """磁盘/数据库故障不能靠逐票重试恢复；锁竞争、坏数据仍走原兜底。

    扩展 SQLite 错误码的低 8 位是主错误码。无错误码时才匹配 SQLite
    异常的标准文案，不把网络异常中相同的文本误判为本机磁盘故障。
    """
    seen: set[int] = set()
    current: BaseException | None = error
    while current is not None and id(current) not in seen:
        seen.add(id(current))
        if isinstance(current, sqlite3.Error):
            code = getattr(current, "sqlite_errorcode", None)
            if isinstance(code, int):
                if (code & 0xFF) in _FATAL_SQLITE_CODES:
                    return True
            elif str(current).strip().lower() in _FATAL_SQLITE_MESSAGES:
                return True
        if isinstance(current, OSError) and current.errno in _FATAL_OS_CODES:
            return True
        current = current.__cause__ or (
            None if current.__suppress_context__ else current.__context__
        )
    return False


def require_rebuild_headroom(db_path: Path, *, database_bytes: int) -> None:
    """在修改热库前预留重写日志、增长和其他任务的空间。

    两倍当前逻辑库大小加 512 MiB 是保守预估，不是容量保证；初次建库
    或扩大历史窗口仍可能超过估算。此处不截断 WAL、不破坏重建事务。
    """
    required = 2 * max(0, database_bytes) + _REBUILD_RESERVE_BYTES
    free = shutil.disk_usage(db_path.parent).free
    if free < required:
        gib = 1024 ** 3
        raise OSError(
            errno.ENOSPC,
            f"行情热库重建已停止：磁盘可用 {free / gib:.2f} GiB，"
            f"本轮预估至少需要 {required / gib:.2f} GiB；"
            "请清理未使用的构建缓存或扩容后重试，原热库窗口未改动",
            str(db_path),
        )
