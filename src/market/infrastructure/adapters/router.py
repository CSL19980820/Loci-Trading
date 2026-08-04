"""选路：探测 / 测速 / 竞速粘性。

日常同步走 ``fetch_daily_routed``：先试粘性赢家，失败再并行竞速并钉住。
"""
from __future__ import annotations

from concurrent.futures import Future, ThreadPoolExecutor, as_completed
import threading
import time
import inspect
from typing import Sequence

import pandas as pd

from src.market.infrastructure.adapters.base import AdapterError, MarketAdapter
from src.market.infrastructure.adapters.registry import (
    adapters_for_lane,
    enabled_adapter_ids,
    get_adapter,
    lane_route_policy,
)
from src.market.infrastructure.adapters.types import (
    LANE_CAPITAL_FLOW,
    LANE_HIST_DAILY,
    LANE_SPOT_BATCH,
    ProbeResult,
    SpeedTestResult,
)
from src.market.infrastructure.adapters.aux_router import (
    fetch_adjust_factors_routed,
    fetch_capital_flow_routed,
    fetch_instruments_routed,
    fetch_minute_routed,
)

#: 粘性赢家存活时间（秒）。过期后下一次取数重新竞速。
STICKY_TTL_SEC = 600.0

_sticky_lock = threading.Lock()
#: lane -> (adapter_id, expires_monotonic)
_sticky: dict[str, tuple[str, float]] = {}

_adapter_gate_lock = threading.Lock()
_adapter_gates: dict[tuple[str, str], threading.Lock] = {}


def _try_claim_adapter(lane: str, adapter_id: str) -> threading.Lock | None:
    """同一 lane/源最多保留一个未结束的外部请求，避免慢源线程堆积。"""
    key = (lane, adapter_id)
    with _adapter_gate_lock:
        gate = _adapter_gates.setdefault(key, threading.Lock())
    return gate if gate.acquire(blocking=False) else None


def _release_gate_if_cancelled(
    future: Future[object], gate: threading.Lock
) -> None:
    """释放尚未启动就被线程池取消的请求 gate。"""
    if future.cancelled():
        gate.release()


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
    code: str = "600519",
) -> list[ProbeResult]:
    """并行探测该 lane 下各 adapter。返回顺序与参与列表一致。"""
    adapters = _resolve_adapters(lane, adapter_ids)
    if not adapters:
        return []

    def probe_adapter(adapter: MarketAdapter) -> ProbeResult:
        # 第三方/旧自定义适配器可能仍是 probe(lane)；保留该扩展契约。
        if "code" not in inspect.signature(adapter.probe).parameters:
            return adapter.probe(lane)
        return adapter.probe(lane, code=code)

    results: dict[str, ProbeResult] = {}
    workers = max(1, min(max_workers, len(adapters)))
    with ThreadPoolExecutor(max_workers=workers) as pool:
        futures = {pool.submit(probe_adapter, adapter): adapter for adapter in adapters}
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
    pool = ThreadPoolExecutor(max_workers=workers)
    try:
        futures = {}
        for adapter in adapters:
            gate = _try_claim_adapter(LANE_HIST_DAILY, adapter.meta.id)
            if gate is None:
                errors.append(f"{adapter.meta.id}: 请求进行中")
                continue
            try:
                future = pool.submit(
                    _fetch_daily_claimed,
                    adapter,
                    gate,
                    code,
                    instrument_type,
                )
            except Exception:
                gate.release()
                raise
            future.add_done_callback(
                lambda completed, claimed=gate: _release_gate_if_cancelled(
                    completed, claimed
                )
            )
            futures[future] = adapter
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
    finally:
        # 已启动的网络请求无法强制中断，但不能让慢源拖住最快成功结果。
        pool.shutdown(wait=False, cancel_futures=True)


def _fetch_daily_claimed(
    adapter: MarketAdapter,
    gate: threading.Lock,
    code: str,
    instrument_type: str,
) -> pd.DataFrame:
    try:
        return adapter.fetch_daily(code, instrument_type=instrument_type)
    finally:
        gate.release()


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
    ids = list(adapter_ids) if adapter_ids is not None else enabled_adapter_ids(LANE_HIST_DAILY)
    if not ids:
        raise AdapterError(f"没有启用的 hist_daily 适配器（code={code}）")

    policy = lane_route_policy(LANE_HIST_DAILY) if adapter_ids is None else None
    preferred = policy.get("provider_id") if policy else None
    if policy and policy["mode"] == "manual" and policy["fallback"] and preferred in ids:
        gate = _try_claim_adapter(LANE_HIST_DAILY, preferred)
        try:
            if gate is None:
                raise AdapterError(f"{preferred}: 请求进行中")
            frame = get_adapter(preferred).fetch_daily(code, instrument_type=instrument_type)
            if frame is not None and not frame.empty:
                pin_sticky(LANE_HIST_DAILY, preferred, ttl_sec=sticky_ttl_sec)
                return frame, preferred
        except Exception:
            pass
        finally:
            if gate is not None:
                gate.release()
        # 手选源不可用才允许其他源竞速；下次仍先探手选源，不被 fallback sticky 覆盖。
        fallback_ids = [adapter_id for adapter_id in ids if adapter_id != preferred]
        if not fallback_ids:
            raise AdapterError(f"手选 hist_daily 适配器失败且无回退源（code={code}）")
        frame, winner = fetch_daily_best(
            code,
            instrument_type=instrument_type,
            adapter_ids=fallback_ids,
            max_workers=max_workers,
        )
        pin_sticky(LANE_HIST_DAILY, winner, ttl_sec=sticky_ttl_sec)
        return frame, winner

    pinned = peek_sticky(LANE_HIST_DAILY)
    if pinned and pinned in ids:
        gate = _try_claim_adapter(LANE_HIST_DAILY, pinned)
        if gate is not None:
            try:
                frame = get_adapter(pinned).fetch_daily(
                    code, instrument_type=instrument_type
                )
                if frame is not None and not frame.empty:
                    return frame, pinned
            except Exception:
                clear_sticky(LANE_HIST_DAILY)
            finally:
                gate.release()

    frame, winner = fetch_daily_best(
        code,
        instrument_type=instrument_type,
        adapter_ids=ids,
        max_workers=max_workers,
    )
    pin_sticky(LANE_HIST_DAILY, winner, ttl_sec=sticky_ttl_sec)
    return frame, winner


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
        gate = _try_claim_adapter(LANE_SPOT_BATCH, aid)
        if gate is None:
            errors.append(f"{aid}: 请求进行中")
            if pinned == aid:
                clear_sticky(LANE_SPOT_BATCH)
            continue
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
        finally:
            gate.release()

    raise AdapterError("现价全部失败 -> " + " | ".join(errors[-4:]))


#: 顶栏/托盘 live 优先走按代码直连的源；东财全市场现价表慢且易 SSL 超时。
_LIVE_QUOTE_PREFERRED: tuple[str, ...] = ("sina", "tencent")


def _race_live_quotes(
    adapter_ids: Sequence[str],
    codes: list[str],
    *,
    instrument_types: dict[str, str] | None,
    batch_size: int,
) -> tuple[list[dict], str]:
    """并行拉 live，第一个非空结果胜出。"""
    if not adapter_ids:
        raise AdapterError("没有可竞速的 live 适配器")
    errors: list[str] = []
    workers = max(1, min(4, len(adapter_ids)))
    pool = ThreadPoolExecutor(max_workers=workers)
    try:
        futures = {}
        for aid in adapter_ids:
            gate = _try_claim_adapter(LANE_SPOT_BATCH, aid)
            if gate is None:
                errors.append(f"{aid}: 请求进行中")
                continue
            try:
                future = pool.submit(
                    _fetch_live_claimed,
                    aid,
                    gate,
                    codes,
                    instrument_types,
                    batch_size,
                )
            except Exception:
                gate.release()
                raise
            future.add_done_callback(
                lambda completed, claimed=gate: _release_gate_if_cancelled(
                    completed, claimed
                )
            )
            futures[future] = aid
        for future in as_completed(futures):
            aid = futures[future]
            try:
                rows = future.result()
                if rows:
                    for pending in futures:
                        if pending is not future and not pending.done():
                            pending.cancel()
                    return rows, aid
                errors.append(f"{aid}: 空数据")
            except Exception as exc:
                errors.append(f"{aid}: {type(exc).__name__}: {exc}")
        raise AdapterError("live 竞速失败 -> " + " | ".join(errors[-4:]))
    finally:
        # 已启动的适配器请求无法强制中断，但不能让慢源阻塞已完成的快源。
        pool.shutdown(wait=False, cancel_futures=True)


def _fetch_live_claimed(
    adapter_id: str,
    gate: threading.Lock,
    codes: list[str],
    instrument_types: dict[str, str] | None,
    batch_size: int,
) -> list[dict]:
    try:
        return get_adapter(adapter_id).fetch_live_quotes(
            codes,
            instrument_types=instrument_types,
            batch_size=batch_size,
        )
    finally:
        gate.release()


def _fetch_live_quotes_in_configured_order(
    adapter_ids: Sequence[str],
    codes: list[str],
    *,
    instrument_types: dict[str, str] | None,
    batch_size: int,
) -> tuple[list[dict], str]:
    """按配置顺序拉 live；手选源及其回退链不能参与竞速。"""
    errors: list[str] = []
    for aid in adapter_ids:
        gate = _try_claim_adapter(LANE_SPOT_BATCH, aid)
        if gate is None:
            errors.append(f"{aid}: 请求进行中")
            continue
        try:
            rows = get_adapter(aid).fetch_live_quotes(
                codes,
                instrument_types=instrument_types,
                batch_size=batch_size,
            )
            if rows:
                return rows, aid
            errors.append(f"{aid}: 空数据")
        except Exception as exc:
            errors.append(f"{aid}: {type(exc).__name__}: {exc}")
        finally:
            gate.release()
    raise AdapterError("live 行情全部失败 -> " + " | ".join(errors[-4:]))


def fetch_live_quotes_routed(
    codes: Sequence[str],
    *,
    instrument_types: dict[str, str] | None = None,
    batch_size: int = 400,
    adapter_ids: Sequence[str] | None = None,
    sticky_ttl_sec: float = STICKY_TTL_SEC,
) -> tuple[list[dict], str]:
    """顶栏/托盘富行情：先竞速 sina/tencent，再回落东财等全市场源。

    东财 spot 要拉全表，冷启动常卡十几秒；托盘 urlopen 只有数秒超时，
    若仍按注册表顺序先试东财，会稳定显示「行情暂不可用」而行情板（库内）正常。
    """
    ids = (
        list(adapter_ids)
        if adapter_ids is not None
        else enabled_adapter_ids(LANE_SPOT_BATCH)
    )
    if not ids:
        raise AdapterError("没有启用的 spot_batch 适配器")

    code_list = list(codes)
    policy = lane_route_policy(LANE_SPOT_BATCH) if adapter_ids is None else None
    selected = policy.get("provider_id") if policy else None
    if policy and policy["mode"] == "manual" and selected in ids:
        rows, winner = _fetch_live_quotes_in_configured_order(
            ids,
            code_list,
            instrument_types=instrument_types,
            batch_size=batch_size,
        )
        pin_sticky(LANE_SPOT_BATCH, winner, ttl_sec=sticky_ttl_sec)
        return rows, winner

    preferred = [aid for aid in _LIVE_QUOTE_PREFERRED if aid in ids]
    others = [aid for aid in ids if aid not in preferred]
    pinned = peek_sticky(LANE_SPOT_BATCH)
    # 仅当粘性赢家本身是快源时前置；东财粘性不阻断 sina/tencent 竞速。
    if pinned and pinned in preferred:
        preferred = [pinned] + [aid for aid in preferred if aid != pinned]

    errors: list[str] = []
    if preferred:
        try:
            rows, winner = _race_live_quotes(
                preferred,
                code_list,
                instrument_types=instrument_types,
                batch_size=batch_size,
            )
            pin_sticky(LANE_SPOT_BATCH, winner, ttl_sec=sticky_ttl_sec)
            return rows, winner
        except AdapterError as exc:
            errors.append(str(exc))
            if pinned and pinned in preferred:
                clear_sticky(LANE_SPOT_BATCH)

    for aid in others:
        gate = _try_claim_adapter(LANE_SPOT_BATCH, aid)
        if gate is None:
            errors.append(f"{aid}: 请求进行中")
            continue
        try:
            rows = get_adapter(aid).fetch_live_quotes(
                code_list,
                instrument_types=instrument_types,
                batch_size=batch_size,
            )
            if rows:
                pin_sticky(LANE_SPOT_BATCH, aid, ttl_sec=sticky_ttl_sec)
                return rows, aid
            errors.append(f"{aid}: 空数据")
        except Exception as exc:
            errors.append(f"{aid}: {type(exc).__name__}: {exc}")
        finally:
            gate.release()

    raise AdapterError("live 行情全部失败 -> " + " | ".join(errors[-4:]))
