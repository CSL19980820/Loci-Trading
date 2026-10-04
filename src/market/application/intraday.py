"""盘中留存编排：有来源、有时间的真实快照；单项失败如实记录。"""
from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path
from typing import Any

from src.market.infrastructure.intraday_archive import (
    IntradayArchiveError,
    describe,
    intraday_root,
    write_snapshot,
)
from src.market.infrastructure.intraday_keyring import KeyMaterial, load_or_create_key

#: 一个采集源：``name`` 决定落盘文件名，``fetch`` 返回上游原始 DataFrame。
Fetcher = Callable[[], Any]


@dataclass(frozen=True)
class CaptureSpec:
    """一条采集定义。``phase`` 只是给调度用的标签，本模块不解释它。"""

    dataset: str
    source: str
    fetch: Fetcher
    phase: str = "close"
    note: str = ""


@dataclass
class CaptureReport:
    trade_date: str
    captured: list[dict[str, Any]] = field(default_factory=list)
    failures: list[dict[str, str]] = field(default_factory=list)
    protection: str = ""

    @property
    def ok(self) -> bool:
        return bool(self.captured) and not self.failures

    def to_dict(self) -> dict[str, Any]:
        return {
            "contract_version": "loci-intraday-capture-v1",
            "trade_date": self.trade_date,
            "protection": self.protection,
            "captured": list(self.captured),
            "captured_count": len(self.captured),
            "failures": list(self.failures),
            "failure_count": len(self.failures),
        }


def capture_snapshots(
    data_dir: Path | str,
    specs: list[CaptureSpec],
    *,
    trade_date: str | None = None,
    key: KeyMaterial | None = None,
) -> CaptureReport:
    """按 ``specs`` 逐个采集并落盘。单项失败不影响其余项。"""
    day = trade_date or date.today().isoformat()
    material = key or load_or_create_key(intraday_root(data_dir))
    report = CaptureReport(trade_date=day, protection=material.protection)
    for spec in specs:
        try:
            frame = spec.fetch()
        except Exception as exc:
            report.failures.append(
                {"dataset": spec.dataset, "stage": "fetch", "error": f"{type(exc).__name__}: {exc}"}
            )
            continue
        try:
            record = write_snapshot(
                data_dir,
                trade_date=day,
                dataset=spec.dataset,
                frame=frame,
                source=str(getattr(frame, "attrs", {}).get("source") or spec.source),
                key=material,
            )
        except IntradayArchiveError as exc:
            report.failures.append({"dataset": spec.dataset, "stage": "write", "error": str(exc)})
            continue
        report.captured.append(record.to_dict())
    return report






def _fetch_spot() -> Any:
    """保留来源的当日实际截面，不补造专题字段。"""
    import pandas as pd
    from src.market.application.cross_section import fetch_cross_section
    rows = fetch_cross_section()
    frame = pd.DataFrame(rows)
    if frame.empty:
        raise RuntimeError("未获取到实际截面")
    frame.attrs["source"] = str(rows[0].get("source") or "unknown")
    return frame


def default_specs() -> list[CaptureSpec]:
    """只留存可由现有来源独立提供的截面，特色情报由悟道缓存负责。"""
    return [CaptureSpec(dataset="spot_close", source="market_snapshot", fetch=_fetch_spot,
                        phase="close", note="带真实来源与报价时间的市场快照，不含未提供的专题字段")]




def intraday_status(data_dir: Path | str) -> dict[str, Any]:
    """留存带现状 + 本机加密能力，供 CLI / 运维页展示。"""
    from src.market.infrastructure.intraday_keyring import dpapi_available

    body = dict(describe(data_dir))
    body["dpapi_available"] = dpapi_available()
    return body


__all__ = [
    "CaptureReport",
    "CaptureSpec",
    "capture_snapshots",
    "default_specs",
    "intraday_status",
]
