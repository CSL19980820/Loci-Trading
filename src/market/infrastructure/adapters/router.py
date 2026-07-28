"""选路：探测 / 测速 / 竞速粘性。

日常同步走 ``fetch_daily_routed``：先试粘性赢家，失败再并行竞速并钉住。
"""
from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor, as_completed
import threading
import time
from typing import Sequence

import pandas as pd

from src.market.infrastructure.adapters.base import AdapterError, MarketAdapter
from src.market.infrastructure.adapters.registry import (
    adapters_for_lane,
    enabled_adapter_ids,
    get_adapter,
)
from src.market.infrastructure.adapters.types import (
    LANE_ADJUST_FACTOR,
    LANE_HIST_DAILY,
    LANE_INSTRUMENTS,
    LANE_SPOT_BATCH,
    ProbeResult,
    SpeedTestResult,
)

#: 粘性赢家存活时间（秒）。过期后下一次取数重新竞速。
STICKY_TTL_SEC = 600.0

_sticky_lock = threading.Lock()
#: lane -> (adapter_id, expires_monotonic)
_sticky: dict[str, tuple[str, float]] = {}


def clear_sticky(lane: str | None = None) -> None:
    """测试 / 运维：清粘性。``None`` 清全部。"""
    with _sticky_lock:
        if lane is None:
            _sticky.clear()
        else:
            _sticky.pop(lane, None)


def peek_sticky(lane: str) -> str | None:
    """未过期的粘性赢家；过期则清除并返回 None。"""
    now = time.monotonic()
    with _sticky_lock:
        entry = _sticky.get(lane)
        if not entry:
            return None
        adapter_id, expires = entry
        if now >= expires:
            _sticky.pop(lane, None)
            return None
        return adapter_id


def pin_sticky(lane: str, adapter_id: str, *, ttl_sec: float = STICKY_TTL_SEC) -> None:
    with _sticky_lock:
        _sticky[lane] = (adapter_id, time.monotonic() + max(0.0, ttl_sec))


def _resolve_adapters(
    lane: str, adapter_ids: Sequence[str] | None
) -> list[MarketAdapter]:
    if adapter_ids is None:
        return adapters_for_lane(lane)
    out: list[MarketAdapter] = []
    for aid in adapter_ids:
        adapter = get_adapter(aid)
        if lane in adapter.meta.lanes:
            out.append(adapter)
    return out


def probe_lane(
    lane: str,
    *,
    adapter_ids: Sequence[str] | None = None,
    max_workers: int = 4,
) -> list[ProbeResult]:
    """并行探测该 lane 下各 adapter。返回顺序与参与列表一致。"""
    adapters = _resolve_adapters(lane, adapter_ids)
    if not adapters:
        return []

    results: dict[str, ProbeResult] = {}
    workers = max(1, min(max_workers, len(adapters)))
    with ThreadPoolExecutor(max_workers=workers) as pool:
        futures = {pool.submit(adapter.probe, lane): adapter for adapter in adapters}
        for future in as_completed(futures):
            adapter = futures[future]
            try:
                results[adapter.meta.id] = future.result()
            except Exception as exc:  # pragma: no cover - probe 自身应吞异常
                results[adapter.meta.id] = ProbeResult(
                    adapter_id=adapter.meta.id,
                    lane=lane,
                    ok=False,
                    error=f"{type(exc).__name__}: {exc}",
                )
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
) -> list[SpeedTestResult]:
    """对 hist_daily lane 各 adapter 拉全历史，记耗时与粗估吞吐。"""
    adapters = _resolve_adapters(LANE_HIST_DAILY, adapter_ids)
    if not adapters:
        return []

    def run_one(adapter: MarketAdapter) -> SpeedTestResult:
        started = time.perf_counter()
        try:
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
    with ThreadPoolExecutor(max_workers=workers) as pool:
        futures = {pool.submit(run_one, adapter): adapter for adapter in adapters}
        for future in as_completed(futures):
            adapter = futures[future]
            results[adapter.meta.id] = future.result()
    return [results[a.meta.id] for a in adapters if a.meta.id in results]


def fetch_daily_best(
    code: str,
    *,
    instrument_type: str = "STOCK",
    adapter_ids: Sequence[str] | None = None,
    max_workers: int = 4,
) -> tuple[pd.DataFrame, str]:
    """并行试拉 hist_daily，返回 (归一日线, 最快成功的 adapter_id)。

    策略：所有候选同时 fetch；第一个成功完成的即胜出（其余 future 仍跑完
    但不采用）。若全部失败，抛出汇总错误。
    """
    adapters = _resolve_adapters(LANE_HIST_DAILY, adapter_ids)
    if not adapters:
        raise AdapterError(f"没有可用的 hist_daily 适配器（code={code}）")

    errors: list[str] = []
    workers = max(1, min(max_workers, len(adapters)))
    with ThreadPoolExecutor(max_workers=workers) as pool:
        futures = {
            pool.submit(
                adapter.fetch_daily, code, instrument_type=instrument_type
            ): adapter
            for adapter in adapters
        }
        for future in as_completed(futures):
            adapter = futures[future]
            try:
                frame = future.result()
                if frame is None or frame.empty:
                    errors.append(f"{adapter.meta.id}: 空数据")
                    continue
                # 取消尚未完成的任务（尽力而为；已在跑的不会真停）
                for pending in futures:
                    if pending is not future and not pending.done():
                        pending.cancel()
                return frame, adapter.meta.id
            except Exception as exc:
                errors.append(f"{adapter.meta.id}: {type(exc).__name__}: {exc}")

    raise AdapterError(
        f"{code} 全部 hist_daily 适配器失败 -> " + " | ".join(errors[-6:])
    )


def fetch_daily_routed(
    code: str,
    *,
    instrument_type: str = "STOCK",
    adapter_ids: Sequence[str] | None = None,
    max_workers: int = 4,
    sticky_ttl_sec: float = STICKY_TTL_SEC,
) -> tuple[pd.DataFrame, str]:
    """日常同步入口：粘性赢家优先，失败再竞速并钉住。

    ``adapter_ids`` 为 None 时读 ``lane_providers`` 启用名单。
    """
    ids = (
        list(adapter_ids)
        if adapter_ids is not None
        else enabled_adapter_ids(LANE_HIST_DAILY)
    )
    if not ids:
        raise AdapterError(f"没有启用的 hist_daily 适配器（code={code}）")

    pinned = peek_sticky(LANE_HIST_DAILY)
    if pinned and pinned in ids:
        try:
            frame = get_adapter(pinned).fetch_daily(
                code, instrument_type=instrument_type
            )
            if frame is not None and not frame.empty:
                return frame, pinned
        except Exception:
            clear_sticky(LANE_HIST_DAILY)

    frame, winner = fetch_daily_best(
        code,
        instrument_type=instrument_type,
        adapter_ids=ids,
        max_workers=max_workers,
    )
    pin_sticky(LANE_HIST_DAILY, winner, ttl_sec=sticky_ttl_sec)
    return frame, winner


def fetch_instruments_routed(
    *,
    adapter_ids: Sequence[str] | None = None,
) -> tuple[pd.DataFrame, str]:
    """证券列表：按启用顺序试，首个非空即返回。"""
    ids = (
        list(adapter_ids)
        if adapter_ids is not None
        else enabled_adapter_ids(LANE_INSTRUMENTS)
    )
    if not ids:
        raise AdapterError("没有启用的 instruments 适配器")
    errors: list[str] = []
    for aid in ids:
        try:
            frame = get_adapter(aid).fetch_instruments()
            if frame is not None and not frame.empty:
                return frame, aid
            errors.append(f"{aid}: 空表")
        except Exception as exc:
            errors.append(f"{aid}: {type(exc).__name__}: {exc}")
    raise AdapterError("证券列表全部失败 -> " + " | ".join(errors[-4:]))


def fetch_adjust_factors_routed(
    code: str,
    *,
    adapter_ids: Sequence[str] | None = None,
) -> tuple[pd.DataFrame, str]:
    """复权因子：按启用顺序试。"""
    ids = (
        list(adapter_ids)
        if adapter_ids is not None
        else enabled_adapter_ids(LANE_ADJUST_FACTOR)
    )
    if not ids:
        raise AdapterError(f"没有启用的 adjust_factor 适配器（code={code}）")
    errors: list[str] = []
    for aid in ids:
        try:
            frame = get_adapter(aid).fetch_adjust_factors(code)
            if frame is not None and not frame.empty:
                return frame, aid
            errors.append(f"{aid}: 空表")
        except Exception as exc:
            errors.append(f"{aid}: {type(exc).__name__}: {exc}")
    raise AdapterError(f"{code} 复权因子全部失败 -> " + " | ".join(errors[-4:]))


def fetch_spot_routed(
    codes: Sequence[str],
    *,
    instrument_types: dict[str, str] | None = None,
    batch_size: int = 400,
    adapter_ids: Sequence[str] | None = None,
    sticky_ttl_sec: float = STICKY_TTL_SEC,
) -> tuple[pd.DataFrame, str]:
    """批量现价：粘性赢家优先，失败再按启用顺序试。"""
    ids = (
        list(adapter_ids)
        if adapter_ids is not None
        else enabled_adapter_ids(LANE_SPOT_BATCH)
    )
    if not ids:
        raise AdapterError("没有启用的 spot_batch 适配器")

    pinned = peek_sticky(LANE_SPOT_BATCH)
    order = (
        [pinned] + [aid for aid in ids if aid != pinned]
        if pinned and pinned in ids
        else list(ids)
    )

    errors: list[str] = []
    for aid in order:
        try:
            frame = get_adapter(aid).fetch_spot(
                list(codes),
                instrument_types=instrument_types,
                batch_size=batch_size,
            )
            if frame is not None and not frame.empty:
                pin_sticky(LANE_SPOT_BATCH, aid, ttl_sec=sticky_ttl_sec)
                return frame, aid
            errors.append(f"{aid}: 空数据")
            if pinned == aid:
                clear_sticky(LANE_SPOT_BATCH)
        except Exception as exc:
            errors.append(f"{aid}: {type(exc).__name__}: {exc}")
            if pinned == aid:
                clear_sticky(LANE_SPOT_BATCH)

    raise AdapterError("现价全部失败 -> " + " | ".join(errors[-4:]))


def fetch_live_quotes_routed(
    codes: Sequence[str],
    *,
    instrument_types: dict[str, str] | None = None,
    batch_size: int = 400,
    adapter_ids: Sequence[str] | None = None,
    sticky_ttl_sec: float = STICKY_TTL_SEC,
) -> tuple[list[dict], str]:
    """顶栏/列表富行情：粘性赢家优先。"""
    ids = (
        list(adapter_ids)
        if adapter_ids is not None
        else enabled_adapter_ids(LANE_SPOT_BATCH)
    )
    if not ids:
        raise AdapterError("没有启用的 spot_batch 适配器")

    pinned = peek_sticky(LANE_SPOT_BATCH)
    order = (
        [pinned] + [aid for aid in ids if aid != pinned]
        if pinned and pinned in ids
        else list(ids)
    )

    errors: list[str] = []
    for aid in order:
        try:
            rows = get_adapter(aid).fetch_live_quotes(
                list(codes),
                instrument_types=instrument_types,
                batch_size=batch_size,
            )
            if rows:
                pin_sticky(LANE_SPOT_BATCH, aid, ttl_sec=sticky_ttl_sec)
                return rows, aid
            errors.append(f"{aid}: 空数据")
            if pinned == aid:
                clear_sticky(LANE_SPOT_BATCH)
        except Exception as exc:
            errors.append(f"{aid}: {type(exc).__name__}: {exc}")
            if pinned == aid:
                clear_sticky(LANE_SPOT_BATCH)

    raise AdapterError("live 行情全部失败 -> " + " | ".join(errors[-4:]))
