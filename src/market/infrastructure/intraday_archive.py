"""盘中留存带：按天分目录的加密 Parquet 快照。

**这是本仓唯一一处「丢了就永远拿不回来」的缓存。** 集合竞价、盘口异动、全市场
截面、人气榜、千股千评、板块资金排名——AkShare 侧没有任何参数能取到过去某一天
（东财 ``trends2`` 的 ``ndays`` 上限是 5），不每天自己落盘就永久没有历史。
详见 `docs/research/_scratch_2026-08-qb-akshare-surface.md` §4 与 ADR-014。

## 为什么按天分目录而不是一张 SQLite 表

过期删除退化成 ``rmtree``：实测删 30 天 **0.011 秒**，零碎片、无 2× 磁盘峰值。
换成 SQLite ``DELETE + VACUUM`` 会踩两个实测过的静默陷阱：``journal_mode=WAL``
排在 ``auto_vacuum`` 之前会让后者静默变 0；``PRAGMA incremental_vacuum`` 不
``fetchall()`` 等于没执行。行存还会把同一份数据放大 5.6~5.7 倍。

## 存原始，不存归一

``pipeline.normalize`` 对选填列缺席是静默丢列、对无法解析的值是静默变 NaN。快照的
价值在于「当时上游到底返回了什么」，归一会把证据抹掉。所以这里直接落上游 DataFrame。

## manifest 是明文

它本身就是排障入口与**列漂移基线**（AkShare 近 12 个月 76 个接口被动过且删接口不写
changelog）。里面只有列名、行数、抓取时刻与摘要，没有行情值。
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from src.market.infrastructure.intraday_keyring import KeyMaterial, load_or_create_key

#: 目录名必须严格是交易日，过期删除靠它做第一道闸门。
DAY_DIR_PATTERN = re.compile(r"^\d{4}-\d{2}-\d{2}$")

#: manifest 契约版本。加字段不升版；改字段含义必须升。
MANIFEST_CONTRACT = "loci-intraday-manifest-v1"

MANIFEST_NAME = "manifest.json"

#: 数据集名允许的字符。它会拼进文件名，必须挡住路径穿越。
DATASET_PATTERN = re.compile(r"^[a-z0-9][a-z0-9_]{0,62}$")


class IntradayArchiveError(RuntimeError):
    """留存带写入或读取失败。"""


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def validate_trade_date(value: str) -> str:
    text = str(value).strip()
    if not DAY_DIR_PATTERN.match(text):
        raise IntradayArchiveError(f"交易日必须是 YYYY-MM-DD：{value!r}")
    return text


def validate_dataset(name: str) -> str:
    # 不做 lower() 归一：``SpotClose`` 与 ``spotclose`` 归一后是同一个文件名，
    # 两条采集定义会静默互相覆盖。宁可拒绝，也不要让它们撞在一起。
    text = str(name).strip()
    if not DATASET_PATTERN.match(text):
        raise IntradayArchiveError(f"数据集名非法（只允许小写字母数字下划线）：{name!r}")
    return text


@dataclass(frozen=True)
class SnapshotRecord:
    """一份落盘快照在 manifest 里的登记项。"""

    dataset: str
    file: str
    rows: int
    columns: list[str]
    captured_at: str
    source: str
    encrypted: bool
    bytes: int

    def to_dict(self) -> dict[str, Any]:
        return {
            "dataset": self.dataset,
            "file": self.file,
            "rows": int(self.rows),
            "columns": list(self.columns),
            "captured_at": self.captured_at,
            "source": self.source,
            "encrypted": bool(self.encrypted),
            "bytes": int(self.bytes),
        }


def intraday_root(data_dir: Path | str) -> Path:
    """留存带根目录。与三库物理隔离，整目录可删。"""
    return Path(data_dir) / "intraday"


def day_dir(data_dir: Path | str, trade_date: str) -> Path:
    return intraday_root(data_dir) / validate_trade_date(trade_date)


def _duck(key: KeyMaterial):
    import duckdb

    con = duckdb.connect()
    if key.encrypted:
        con.execute(f"PRAGMA add_parquet_key('loci', '{key.base64_key()}')")
    return con


def _encryption_clause(key: KeyMaterial) -> str:
    return ", ENCRYPTION_CONFIG {footer_key: 'loci'}" if key.encrypted else ""


def write_snapshot(
    data_dir: Path | str,
    *,
    trade_date: str,
    dataset: str,
    frame: Any,
    source: str,
    key: KeyMaterial | None = None,
    captured_at: str | None = None,
) -> SnapshotRecord:
    """把一份上游 DataFrame 原样落成当日的加密 Parquet，并登记进 manifest。

    同一天同一 dataset 反复写是**覆盖**语义：盘中多次采样应当在 ``dataset`` 里带上
    时点（如 ``spot_1450``），否则后一次会盖掉前一次。
    """
    dataset = validate_dataset(dataset)
    target_dir = day_dir(data_dir, trade_date)
    target_dir.mkdir(parents=True, exist_ok=True)
    material = key or load_or_create_key(intraday_root(data_dir))
    suffix = ".parquet.enc" if material.encrypted else ".parquet"
    path = target_dir / f"{dataset}{suffix}"
    if frame is None or len(frame) == 0:
        raise IntradayArchiveError(f"{dataset} 快照为空，不落盘（空表会被下游读成「当天没有」）")
    columns = [str(c) for c in frame.columns]
    con = _duck(material)
    try:
        con.register("snapshot_frame", frame)
        posix = path.as_posix()
        con.execute(
            f"COPY snapshot_frame TO '{posix}' "
            f"(FORMAT parquet, COMPRESSION zstd{_encryption_clause(material)})"
        )
    except Exception as exc:
        raise IntradayArchiveError(f"{dataset} 落盘失败：{type(exc).__name__}: {exc}") from exc
    finally:
        con.close()
    record = SnapshotRecord(
        dataset=dataset,
        file=path.name,
        rows=int(len(frame)),
        columns=columns,
        captured_at=captured_at or _utc_now(),
        source=str(source),
        encrypted=material.encrypted,
        bytes=path.stat().st_size,
    )
    _upsert_manifest(target_dir, trade_date, record, material)
    return record


def _upsert_manifest(
    target_dir: Path,
    trade_date: str,
    record: SnapshotRecord,
    key: KeyMaterial,
) -> None:
    path = target_dir / MANIFEST_NAME
    body: dict[str, Any] = {
        "contract_version": MANIFEST_CONTRACT,
        "trade_date": validate_trade_date(trade_date),
        "files": [],
    }
    if path.exists():
        try:
            body = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            pass
    body.setdefault("contract_version", MANIFEST_CONTRACT)
    body["trade_date"] = validate_trade_date(trade_date)
    body["protection"] = key.protection
    try:
        import akshare

        body["akshare_version"] = str(getattr(akshare, "__version__", ""))
    except Exception:
        body.setdefault("akshare_version", "")
    files = [item for item in body.get("files", []) if item.get("dataset") != record.dataset]
    files.append(record.to_dict())
    body["files"] = sorted(files, key=lambda item: str(item.get("dataset")))
    body["updated_at"] = _utc_now()
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(body, ensure_ascii=False, indent=1), encoding="utf-8")
    tmp.replace(path)


def read_manifest(data_dir: Path | str, trade_date: str) -> dict[str, Any]:
    path = day_dir(data_dir, trade_date) / MANIFEST_NAME
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise IntradayArchiveError(f"manifest 损坏：{path}（{exc}）") from exc


def read_snapshot(
    data_dir: Path | str,
    *,
    trade_date: str,
    dataset: str,
    key: KeyMaterial | None = None,
    columns: list[str] | None = None,
) -> Any:
    """读回某天某个快照。无密钥或密钥不对时 DuckDB **硬失败**，不会返回空表。"""
    dataset = validate_dataset(dataset)
    target_dir = day_dir(data_dir, trade_date)
    material = key or load_or_create_key(intraday_root(data_dir))
    candidates = [target_dir / f"{dataset}.parquet.enc", target_dir / f"{dataset}.parquet"]
    path = next((item for item in candidates if item.exists()), None)
    if path is None:
        raise IntradayArchiveError(f"没有 {trade_date} 的 {dataset} 快照")
    projection = ", ".join(f'"{c}"' for c in columns) if columns else "*"
    clause = ""
    if path.suffix == ".enc":
        if not material.encrypted:
            raise IntradayArchiveError(f"{path.name} 是密文，但本机没有可用 DEK")
        clause = ", encryption_config = {footer_key: 'loci'}"
    con = _duck(material)
    try:
        return con.execute(
            f"SELECT {projection} FROM read_parquet('{path.as_posix()}'{clause})"
        ).fetch_df()
    except Exception as exc:
        raise IntradayArchiveError(f"读取 {path.name} 失败：{type(exc).__name__}: {exc}") from exc
    finally:
        con.close()


def list_days(data_dir: Path | str) -> list[str]:
    """留存带里已有的交易日，升序。只认严格的 YYYY-MM-DD 目录。"""
    root = intraday_root(data_dir)
    if not root.exists():
        return []
    return sorted(
        item.name for item in root.iterdir() if item.is_dir() and DAY_DIR_PATTERN.match(item.name)
    )


def describe(data_dir: Path | str) -> dict[str, Any]:
    """留存带现状：天数、区间、总体积、每个数据集的覆盖天数。"""
    root = intraday_root(data_dir)
    days = list_days(data_dir)
    total = 0
    by_dataset: dict[str, int] = {}
    for day in days:
        for item in (root / day).iterdir():
            if item.is_file():
                total += item.stat().st_size
        for entry in read_manifest(data_dir, day).get("files", []):
            name = str(entry.get("dataset") or "")
            if name:
                by_dataset[name] = by_dataset.get(name, 0) + 1
    return {
        "root": str(root),
        "days": len(days),
        "first_day": days[0] if days else None,
        "last_day": days[-1] if days else None,
        "total_mb": round(total / 1e6, 2),
        "datasets": dict(sorted(by_dataset.items())),
    }


__all__ = [
    "DATASET_PATTERN",
    "DAY_DIR_PATTERN",
    "MANIFEST_CONTRACT",
    "MANIFEST_NAME",
    "IntradayArchiveError",
    "SnapshotRecord",
    "day_dir",
    "describe",
    "intraday_root",
    "list_days",
    "read_manifest",
    "read_snapshot",
    "validate_dataset",
    "validate_trade_date",
    "write_snapshot",
]
