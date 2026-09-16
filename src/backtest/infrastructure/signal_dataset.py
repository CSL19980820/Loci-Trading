"""租户私有、带内容校验的历史时点行情输入；显式导入，不自动联网。"""
from __future__ import annotations

import hashlib
import json
import math
import os
import re
import tempfile
from datetime import date
from pathlib import Path
from typing import Any

from src.shared.paths import data_dir
from src.shared.tenancy import tenant_root

_ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9_-]{0,95}\Z")
_SHA = re.compile(r"[a-f0-9]{64}\Z")


def dataset_directory() -> Path:
    return tenant_root(data_dir()) / "backtest_datasets"


def canonical_payload(payload: dict[str, Any]) -> bytes:
    return json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False).encode("utf-8")


def load_signal_dataset(dataset_id: str) -> tuple[dict[str, Any], str]:
    if not _ID.fullmatch(dataset_id):
        raise ValueError("历史快照数据集ID无效")
    root = dataset_directory().resolve()
    path = (root / f"{dataset_id}.json").resolve()
    if path.parent != root:
        raise ValueError("历史快照数据集路径越界")
    if not path.is_file():
        raise ValueError(f"当前租户没有历史快照数据集：{dataset_id}")
    if path.stat().st_size > 50_000_000:
        raise ValueError("历史快照数据集超过读取上限")
    body = json.loads(path.read_text(encoding="utf-8"))
    return _validated_body(body, dataset_id)


def _validated_body(body: Any, dataset_id: str) -> tuple[dict[str, Any], str]:
    if not isinstance(body, dict):
        raise ValueError("历史快照数据集格式无效")
    payload, expected = body.get("payload"), body.get("sha256")
    if not isinstance(payload, dict) or not isinstance(expected, str):
        raise ValueError("历史快照数据集格式无效")
    digest = hashlib.sha256(canonical_payload(payload)).hexdigest()
    if digest != expected or not _SHA.fullmatch(expected):
        raise ValueError("历史快照数据集内容校验失败")
    if payload.get("schema") != "asof-ohlcv-v1" or payload.get("id") != dataset_id:
        raise ValueError("历史快照数据集版本或ID不匹配")
    coverage = payload.get("coverage", {})
    if (not isinstance(coverage, dict) or coverage.get("time") != "14:50" or coverage.get("volume_unit") != "shares"
            or not isinstance(coverage.get("codes"), list)):
        raise ValueError("历史快照数据集缺少14:50覆盖信息")
    if date.fromisoformat(coverage["start"]) > date.fromisoformat(coverage["end"]):
        raise ValueError("历史快照数据集日期范围无效")
    if not isinstance(payload.get("rows"), list) or not isinstance(payload.get("params"), dict):
        raise ValueError("历史快照数据集缺少行情或参数")
    return payload, digest


def import_signal_dataset(body: dict[str, Any]) -> dict[str, Any]:
    """显式导入当前租户；同ID同内容幂等，禁止覆盖不同输入。"""
    if not isinstance(body, dict) or not isinstance(body.get("payload"), dict):
        raise ValueError("历史快照数据集格式无效")
    dataset_id = str((body.get("payload") or {}).get("id", ""))
    if not _ID.fullmatch(dataset_id):
        raise ValueError("历史快照数据集ID无效")
    payload, digest = _validated_body(body, dataset_id)
    snapshot_rows(payload)
    content = canonical_payload({"payload": payload, "sha256": digest})
    if len(content) > 50_000_000:
        raise ValueError("历史快照数据集超过读取上限")
    root = dataset_directory().resolve()
    root.mkdir(parents=True, exist_ok=True)
    target = root / f"{dataset_id}.json"
    temporary: Path | None = None
    created = False
    try:
        with tempfile.NamedTemporaryFile(dir=root, prefix=".snapshot-", delete=False) as handle:
            temporary = Path(handle.name)
            handle.write(content)
            handle.flush()
            os.fsync(handle.fileno())
        try:
            os.link(temporary, target)
            created = True
        except FileExistsError:
            _, stored_digest = load_signal_dataset(dataset_id)
            if stored_digest != digest:
                raise ValueError("历史快照ID已存在，禁止覆盖不同输入") from None
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)
    return {"id": dataset_id, "sha256": digest, "created": created, "rows": len(payload["rows"])}


def snapshot_rows(payload: dict[str, Any]) -> dict[tuple[str, str], tuple[float, ...] | None]:
    result: dict[tuple[str, str], tuple[float, ...] | None] = {}
    coverage = payload["coverage"]
    codes = set(coverage["codes"])
    for row in payload["rows"]:
        day, code = str(row["date"]), str(row["code"])
        date.fromisoformat(day)
        if code not in codes or not coverage["start"] <= day <= coverage["end"]:
            raise ValueError("历史快照行超出声明覆盖范围")
        key = (day, code)
        if key in result:
            raise ValueError("历史快照包含重复股票日期")
        if row.get("status") == "confirmed_suspension":
            if not row.get("evidence"):
                raise ValueError("停牌快照必须保留独立证据")
            result[key] = None
            continue
        if row.get("status") != "observed" or not _SHA.fullmatch(str(row.get("source_sha256", ""))):
            raise ValueError("历史快照缺少实际行情来源指纹")
        values = row.get("ohlcv")
        if not isinstance(values, list) or len(values) != 5:
            raise ValueError("历史快照OHLCV字段不完整")
        if any(isinstance(v, bool) or not isinstance(v, (float, int)) for v in values):
            raise ValueError("历史快照OHLCV必须为数值")
        o, h, low, c, volume = map(float, values)
        if not all(math.isfinite(v) for v in (o, h, low, c, volume)) or min(o, h, low, c) <= 0 or volume < 0:
            raise ValueError("历史快照OHLCV数值无效")
        if h < max(o, low, c) or low > min(o, h, c):
            raise ValueError("历史快照最高最低价不自洽")
        result[key] = (o, h, low, c, volume)
    return result
