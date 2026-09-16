"""把经校验的历史时点行情交给战法，不替换执行日线或复用最终收盘信号。"""
from __future__ import annotations

from typing import Any

import pandas as pd

from src.backtest.infrastructure.signal_dataset import load_signal_dataset, snapshot_rows


def compute_asof_signals(
    engine: Any, panels: dict[str, pd.DataFrame], params: dict[str, Any],
    *, dataset_id: str, start: str, end: str,
) -> tuple[pd.DataFrame, dict[str, Any]]:
    payload, digest = load_signal_dataset(dataset_id)
    coverage = payload["coverage"]
    if payload.get("strategy") != engine.slug or payload["params"] != params:
        raise ValueError("历史快照数据集与战法或参数不匹配，需使用对应参数的数据集")
    if start < coverage["start"] or end > coverage["end"]:
        raise ValueError(f"历史快照覆盖区间为 {coverage['start']} 至 {coverage['end']}")
    if not set(map(str, panels["close"].columns)).issubset(coverage["codes"]):
        raise ValueError("历史快照未覆盖请求股票池")
    compute = getattr(engine, "compute_asof", None)
    if not callable(compute):
        raise ValueError("该战法尚不支持历史时点快照回放")
    snapshots = snapshot_rows(payload)
    output = compute(panels, snapshots, start=start, end=end, params=params)
    return output.signals, {
        "id": dataset_id, "sha256": digest, "schema": payload["schema"],
        "time": coverage["time"], "coverage_start": coverage["start"],
        "coverage_end": coverage["end"], "rows": len(snapshots),
        "confirmed_suspensions": sum(row is None for row in snapshots.values()),
        "source_evidence": payload.get("source_evidence", {}),
    }
