"""探测与测速：给运维「数据源」页用的一次性诊断，不在同步热路径上。

从 ``router.py`` 拆出来是体量原因（那边贴着 600 行上限）。这两个动作的共同点
是「可以慢、但绝不能挂死」：外部 SDK（如 baostock）没有超时参数，所以统一用
线程池 + 墙钟上限包一层，超时就记结果、不等它。
"""
from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor, wait
import inspect
import time
from typing import Any, Sequence

import pandas as pd

from src.market.infrastructure.adapters.base import MarketAdapter
from src.market.infrastructure.adapters.router_shared import _resolve_adapters
from src.shared.observability import span as observation_span
from src.market.infrastructure.adapters.types import (
    LANE_HIST_DAILY,
    ProbeResult,
    SpeedTestResult,
)

#: 单源探测墙钟上限。外部 SDK/套接字无超时（如 baostock）时，避免整页卡死。
PROBE_ADAPTER_TIMEOUT_SEC = 25.0
#: 单源全历史测速墙钟上限；测速比探测重，给得更宽，但同样不能无限等。
SPEEDTEST_TIMEOUT_SEC = 90.0


def probe_lane(
    lane: str,
    *,
    adapter_ids: Sequence[str] | None = None,
    max_workers: int = 4,
    code: str = "600519",
    timeout_sec: float = PROBE_ADAPTER_TIMEOUT_SEC,
) -> list[ProbeResult]:
    """并行探测该 lane 下各 adapter。返回顺序与参与列表一致。"""
    adapters = _resolve_adapters(lane, adapter_ids)
    if not adapters:
        return []

    def probe_adapter(adapter: MarketAdapter) -> ProbeResult:
        with observation_span(
            "market.provider.probe",
            source_id=adapter.meta.id,
            labels={"component": "market", "operation": "probe", "lane": lane},
        ):
            # 第三方/旧自定义适配器可能仍是 probe(lane)；保留该扩展契约。
            if "code" not in inspect.signature(adapter.probe).parameters:
                return adapter.probe(lane)
            return adapter.probe(lane, code=code)

    results: dict[str, ProbeResult] = {}
    workers = max(1, min(max_workers, len(adapters)))
    wait_sec = max(1.0, float(timeout_sec))
    # wait=False：超时后立刻返回，不让 ThreadPoolExecutor.__exit__ 再堵在挂死的 SDK 上。
    pool = ThreadPoolExecutor(max_workers=workers)
    try:
        futures = {pool.submit(probe_adapter, adapter): adapter for adapter in adapters}
        done, pending = wait(set(futures), timeout=wait_sec)
        for future in done:
            adapter = futures[future]
            try:
                results[adapter.meta.id] = future.result(timeout=0)
            except Exception as exc:  # pragma: no cover - probe 自身应吞异常
                results[adapter.meta.id] = ProbeResult(
                    adapter_id=adapter.meta.id,
                    lane=lane,
                    ok=False,
                    error=f"{type(exc).__name__}: {exc}",
                )
        for future in pending:
            adapter = futures[future]
            results[adapter.meta.id] = ProbeResult(
                adapter_id=adapter.meta.id,
                lane=lane,
                ok=False,
                error=f"探测超时（>{int(wait_sec)}s）",
            )
    finally:
        pool.shutdown(wait=False, cancel_futures=True)
    return [results[a.meta.id] for a in adapters if a.meta.id in results]


def _estimate_bytes(frame: pd.DataFrame) -> int:
    """粗估载荷字节：行数 × 列数 × 8（浮点近似），仅用于比吞吐。"""
    if frame is None or frame.empty:
        return 0
    return int(frame.shape[0] * frame.shape[1] * 8)


def speedtest_daily(
    code: str = "600519",
    *,
    instrument_type: str = "STOCK",
    adapter_ids: Sequence[str] | None = None,
    max_workers: int = 4,
    timeout_sec: float = SPEEDTEST_TIMEOUT_SEC,
) -> list[SpeedTestResult]:
    """对 hist_daily lane 各 adapter 拉全历史，记耗时与粗估吞吐。"""
    adapters = _resolve_adapters(LANE_HIST_DAILY, adapter_ids)
    if not adapters:
        return []

    def run_one(adapter: MarketAdapter) -> SpeedTestResult:
        started = time.perf_counter()
        try:
            with observation_span(
                "market.provider.fetch",
                source_id=adapter.meta.id,
                labels={"component": "market", "operation": "speedtest", "lane": LANE_HIST_DAILY},
            ):
                frame = adapter.fetch_daily(code, instrument_type=instrument_type)
            elapsed_ms = (time.perf_counter() - started) * 1000.0
            rows = int(len(frame)) if frame is not None else 0
            bytes_est = _estimate_bytes(frame)
            elapsed_s = max(elapsed_ms / 1000.0, 1e-9)
            mb_per_s = (bytes_est / (1024 * 1024)) / elapsed_s
            return SpeedTestResult(
                adapter_id=adapter.meta.id,
                code=code,
                ok=True,
                elapsed_ms=elapsed_ms,
                rows=rows,
                bytes_est=bytes_est,
                mb_per_s=mb_per_s,
            )
        except Exception as exc:
            elapsed_ms = (time.perf_counter() - started) * 1000.0
            return SpeedTestResult(
                adapter_id=adapter.meta.id,
                code=code,
                ok=False,
                elapsed_ms=elapsed_ms,
                error=f"{type(exc).__name__}: {exc}",
            )

    results: dict[str, SpeedTestResult] = {}
    workers = max(1, min(max_workers, len(adapters)))
    wait_sec = max(1.0, float(timeout_sec))
    # 与 probe_lane 同款：外部 SDK 可能没有超时，不能让运维页无限等下去。
    pool = ThreadPoolExecutor(max_workers=workers)
    try:
        futures = {pool.submit(run_one, adapter): adapter for adapter in adapters}
        done, pending = wait(set(futures), timeout=wait_sec)
        for future in done:
            adapter = futures[future]
            results[adapter.meta.id] = future.result(timeout=0)
        for future in pending:
            adapter = futures[future]
            results[adapter.meta.id] = SpeedTestResult(
                adapter_id=adapter.meta.id,
                code=code,
                ok=False,
                elapsed_ms=wait_sec * 1000.0,
                error=f"测速超时（>{int(wait_sec)}s）",
            )
    finally:
        pool.shutdown(wait=False, cancel_futures=True)
    return [results[a.meta.id] for a in adapters if a.meta.id in results]
