"""市场来源回执的冷归档。

权威行情仍然留在 SQLite；超过在线回执窗口的 ``selected`` 回执先写成
Parquet/Zstd，再核对文件中的行数和主键摘要，最后才从 SQLite 删除。归档是
审计/离线研究材料，不是第二套可写行情真相；热路径只在 SQLite 查不到回执时
按 receipt_id 只读回查归档。
"""
from __future__ import annotations

from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import sqlite3
from typing import Any, Iterable, Mapping, Sequence
from uuid import uuid4


_IN_CHUNK = 900
_RECEIPT_TABLE = "receipts"
_ATTEMPT_TABLE = "attempts"


def default_archive_root(db_path: Path) -> Path:
    return db_path.parent / "archives" / "market-provenance"


def _sql_string(value: str) -> str:
    return "'" + str(value).replace("'", "''") + "'"


def _parquet_glob(root: Path, table: str) -> str:
    return str(root / table / "**" / "*.parquet").replace("\\", "/")


def _files(root: Path, table: str) -> list[Path]:
    return sorted((root / table).glob("**/*.parquet")) if (root / table).is_dir() else []


def _key_digest(values: Iterable[str]) -> str:
    body = "\n".join(sorted(str(value) for value in values)).encode("utf-8")
    return hashlib.sha256(body).hexdigest()


def _atomic_json(path: Path, payload: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    staging = path.with_name(f".{path.name}.{uuid4().hex}.tmp")
    try:
        staging.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        staging.replace(path)
    finally:
        if staging.exists():
            staging.unlink(missing_ok=True)


def _write_parquet(path: Path, rows: Sequence[Mapping[str, Any]], columns: Sequence[str]) -> None:
    """通过已存在的 DuckDB 依赖写 Parquet；不引入 pyarrow。"""
    import duckdb
    import pandas as pd

    path.parent.mkdir(parents=True, exist_ok=True)
    frame = pd.DataFrame.from_records(rows, columns=list(columns))
    staging = path.with_name(f".{path.name}.{uuid4().hex}.tmp")
    db = duckdb.connect()
    try:
        db.register("archive_rows", frame)
        db.execute(
            "COPY archive_rows TO "
            + _sql_string(str(staging).replace("\\", "/"))
            + " (FORMAT PARQUET, COMPRESSION ZSTD)"
        )
        staging.replace(path)
    finally:
        db.close()
        if staging.exists():
            staging.unlink(missing_ok=True)


def _parquet_count_and_digest(path: Path, key: str) -> tuple[int, str]:
    import duckdb

    db = duckdb.connect()
    try:
        rows = db.execute(
            "SELECT " + key + " FROM read_parquet(" + _sql_string(str(path)) + ")"
        ).fetchall()
    finally:
        db.close()
    return len(rows), _key_digest(str(row[0]) for row in rows)


def _manifest_path(root: Path, batch_key: str) -> Path:
    return root / "manifests" / f"{batch_key}.json"


def _manifest_valid(root: Path, payload: Mapping[str, Any]) -> bool:
    try:
        receipt_path = root / str(payload["receipts_file"])
        attempt_name = str(payload.get("attempts_file") or "")
        attempt_path = root / attempt_name if attempt_name else None
        receipt_count, receipt_digest = _parquet_count_and_digest(
            receipt_path, "receipt_id"
        )
        if receipt_count != int(payload["receipt_count"]):
            return False
        if receipt_digest != str(payload["receipt_id_sha256"]):
            return False
        if int(payload.get("attempt_count", 0)):
            if attempt_path is None:
                return False
            attempt_count, attempt_digest = _parquet_count_and_digest(
                attempt_path, "receipt_id || ':' || CAST(attempt_no AS VARCHAR)"
            )
            return (
                attempt_count == int(payload["attempt_count"])
                and attempt_digest == str(payload["attempt_key_sha256"])
            )
        return True
    except (KeyError, OSError, TypeError, ValueError):
        return False


def _select_batch(
    conn: sqlite3.Connection, *, cutoff: str, batch_size: int
) -> list[sqlite3.Row]:
    return conn.execute(
        "SELECT * FROM source_route_receipts "
        "WHERE state = 'selected' AND julianday(generated_at) < julianday(?) "
        "ORDER BY generated_at, receipt_id LIMIT ?",
        (cutoff, max(1, int(batch_size))),
    ).fetchall()


def _attempt_rows(conn: sqlite3.Connection, receipt_ids: Sequence[str]) -> list[sqlite3.Row]:
    rows: list[sqlite3.Row] = []
    for offset in range(0, len(receipt_ids), _IN_CHUNK):
        chunk = list(receipt_ids[offset : offset + _IN_CHUNK])
        placeholders = ",".join("?" for _ in chunk)
        rows.extend(
            conn.execute(
                "SELECT * FROM source_route_attempts WHERE receipt_id IN ("
                + placeholders
                + ") ORDER BY receipt_id, attempt_no",
                chunk,
            ).fetchall()
        )
    return rows


def _delete_batch(conn: sqlite3.Connection, receipt_ids: Sequence[str]) -> tuple[int, int]:
    attempts_deleted = 0
    receipts_deleted = 0
    conn.execute("BEGIN IMMEDIATE")
    try:
        for offset in range(0, len(receipt_ids), _IN_CHUNK):
            chunk = list(receipt_ids[offset : offset + _IN_CHUNK])
            placeholders = ",".join("?" for _ in chunk)
            cursor = conn.execute(
                "DELETE FROM source_route_attempts WHERE receipt_id IN ("
                + placeholders
                + ")",
                chunk,
            )
            attempts_deleted += int(cursor.rowcount or 0)
            cursor = conn.execute(
                "DELETE FROM source_route_receipts WHERE receipt_id IN ("
                + placeholders
                + ") AND state = 'selected'",
                chunk,
            )
            receipts_deleted += int(cursor.rowcount or 0)
        if receipts_deleted != len(receipt_ids):
            raise RuntimeError(
                f"归档后删除回执数量不符：期望 {len(receipt_ids)}，实际 {receipts_deleted}"
            )
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    return receipts_deleted, attempts_deleted


def archive_selected_batch(
    conn: sqlite3.Connection,
    root: Path,
    *,
    cutoff: str,
    batch_size: int = 20_000,
    dry_run: bool = False,
) -> dict[str, Any]:
    """归档并删除一批旧 selected 回执；归档失败时绝不删除 SQLite 行。"""
    conn.row_factory = sqlite3.Row
    rows = _select_batch(conn, cutoff=cutoff, batch_size=batch_size)
    if not rows:
        return {"receipts": 0, "attempts": 0, "dry_run": bool(dry_run)}
    receipt_ids = [str(row["receipt_id"]) for row in rows]
    attempts = _attempt_rows(conn, receipt_ids)
    first = str(rows[0]["generated_at"] or "")[:10] or "unknown"
    last = str(rows[-1]["generated_at"] or "")[:10] or "unknown"
    batch_key = hashlib.sha256(
        (f"{receipt_ids[0]}:{receipt_ids[-1]}:{len(receipt_ids)}").encode("utf-8")
    ).hexdigest()[:24]
    manifest_path = _manifest_path(root, batch_key)
    root.mkdir(parents=True, exist_ok=True)

    if dry_run:
        return {
            "receipts": len(rows),
            "attempts": len(attempts),
            "first_generated_at": first,
            "last_generated_at": last,
            "dry_run": True,
        }

    manifest: dict[str, Any]
    if manifest_path.is_file():
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        if not _manifest_valid(root, manifest):
            raise RuntimeError(f"已有归档清单校验失败，拒绝删除：{manifest_path}")
    else:
        receipt_columns = [str(item[1]) for item in conn.execute(
            "PRAGMA table_info(source_route_receipts)"
        )]
        attempt_columns = [str(item[1]) for item in conn.execute(
            "PRAGMA table_info(source_route_attempts)"
        )]
        receipt_path = root / "receipts" / first[:4] / first[5:7] / f"{batch_key}.parquet"
        attempt_path = root / "attempts" / first[:4] / first[5:7] / f"{batch_key}.parquet"
        receipt_dicts = [{column: row[column] for column in receipt_columns} for row in rows]
        attempt_dicts = [{column: row[column] for column in attempt_columns} for row in attempts]
        _write_parquet(receipt_path, receipt_dicts, receipt_columns)
        _write_parquet(attempt_path, attempt_dicts, attempt_columns) if attempts else None
        receipt_count, receipt_digest = _parquet_count_and_digest(receipt_path, "receipt_id")
        attempt_count = attempt_digest = 0
        if attempts:
            attempt_count, attempt_digest = _parquet_count_and_digest(
                attempt_path, "receipt_id || ':' || CAST(attempt_no AS VARCHAR)"
            )
        if receipt_count != len(rows) or receipt_digest != _key_digest(receipt_ids):
            raise RuntimeError(f"回执归档校验失败：{receipt_path}")
        if attempt_count != len(attempts):
            raise RuntimeError(f"attempt 归档校验失败：{attempt_path}")
        manifest = {
            "contract_version": "market-provenance-archive-v1",
            "created_at": datetime.now(timezone.utc).isoformat(),
            "cutoff": cutoff,
            "first_generated_at": first,
            "last_generated_at": last,
            "receipt_count": receipt_count,
            "attempt_count": attempt_count,
            "receipt_id_sha256": receipt_digest,
            "attempt_key_sha256": attempt_digest,
            "receipts_file": str(receipt_path.relative_to(root)).replace("\\", "/"),
            "attempts_file": (
                str(attempt_path.relative_to(root)).replace("\\", "/") if attempts else ""
            ),
        }
        _atomic_json(manifest_path, manifest)
        if not _manifest_valid(root, manifest):
            raise RuntimeError(f"归档清单落盘后校验失败：{manifest_path}")

    deleted_receipts, deleted_attempts = _delete_batch(conn, receipt_ids)
    return {
        "receipts": deleted_receipts,
        "attempts": deleted_attempts,
        "archived_receipts": int(manifest.get("receipt_count", len(rows))),
        "archived_attempts": int(manifest.get("attempt_count", len(attempts))),
        "manifest": str(manifest_path),
        "first_generated_at": str(manifest.get("first_generated_at", first)),
        "last_generated_at": str(manifest.get("last_generated_at", last)),
        "dry_run": False,
    }


def query_archived_receipts(root: Path, receipt_ids: Sequence[str]) -> list[dict[str, Any]]:
    return _query_archive(root, _RECEIPT_TABLE, receipt_ids)


def query_archived_attempts(root: Path, receipt_ids: Sequence[str]) -> list[dict[str, Any]]:
    return _query_archive(root, _ATTEMPT_TABLE, receipt_ids)


def _query_archive(root: Path, table: str, receipt_ids: Sequence[str]) -> list[dict[str, Any]]:
    if not receipt_ids or not _files(root, table):
        return []
    import duckdb

    out: list[dict[str, Any]] = []
    db = duckdb.connect()
    try:
        parquet = _sql_string(_parquet_glob(root, table))
        for offset in range(0, len(receipt_ids), _IN_CHUNK):
            chunk = list(receipt_ids[offset : offset + _IN_CHUNK])
            placeholders = ",".join("?" for _ in chunk)
            rows = db.execute(
                "SELECT * FROM read_parquet(" + parquet + ") WHERE receipt_id IN ("
                + placeholders
                + ")",
                chunk,
            ).fetchdf()
            out.extend(rows.to_dict(orient="records"))
    finally:
        db.close()
    return out


def prune_archive(root: Path, *, keep_days: int = 90, now: datetime | None = None) -> dict[str, Any]:
    """按清单创建时间清理冷归档；不触碰 SQLite 和用户手工备份。"""
    cutoff = (now or datetime.now(timezone.utc)).timestamp() - max(0, int(keep_days)) * 86400
    manifests = sorted((root / "manifests").glob("*.json")) if (root / "manifests").is_dir() else []
    deleted = 0
    freed = 0
    for path in manifests:
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
            created = datetime.fromisoformat(str(payload["created_at"]).replace("Z", "+00:00"))
            if created.timestamp() >= cutoff:
                continue
            for key in ("receipts_file", "attempts_file"):
                relative = str(payload.get(key) or "")
                if not relative:
                    continue
                target = root / relative
                if target.is_file():
                    freed += target.stat().st_size
                    target.unlink()
            freed += path.stat().st_size
            path.unlink()
            deleted += 1
        except (OSError, KeyError, TypeError, ValueError, json.JSONDecodeError):
            continue
    return {"deleted_manifests": deleted, "freed_bytes": freed, "keep_days": int(keep_days)}


__all__ = [
    "archive_selected_batch",
    "default_archive_root",
    "prune_archive",
    "query_archived_attempts",
    "query_archived_receipts",
]
