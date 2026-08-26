"""实时行情路由及与日线共享的粘性/并发门闸状态。"""
from __future__ import annotations

from concurrent.futures import Future, ThreadPoolExecutor, as_completed
import os
import threading
import time
from typing import Any, Callable, Sequence

from src.market.infrastructure.adapters.base import AdapterError
from src.market.infrastructure.adapters.registry import (
    enabled_adapter_ids,
    get_adapter,
    lane_route_policy,
)
from src.market.infrastructure.adapters.types import LANE_HIST_DAILY, LANE_SPOT_BATCH
from src.shared.observability import span as observation_span

STICKY_TTL_SEC = 600.0
#: hist_daily 并发同步时，门闩被占满则排队等待的上限（秒）
ADAPTER_CLAIM_WAIT_SEC = 120.0
ADAPTER_CLAIM_POLL_SEC = 0.05

#: 每个 (lane, 来源) 允许的在途外部请求数；默认单飞。
DEFAULT_ADAPTER_CONCURRENCY = 1
#: hist_daily 例外：全市场同步要跑五千多只票，单飞会把 ``sync_quotes`` 的
#: workers 全堵在一条连接上（实测单轮 40 分钟以上）。这条线放小并发，让
#: 逐票请求真的并行；上限仍由同步侧的 ``_RateLimiter`` 兜住来源礼貌。
ADAPTER_LANE_CONCURRENCY: dict[str, int] = {LANE_HIST_DAILY: 4}

#: (lane, 来源) 级覆盖。名额是**按源**定的，不该一刀切：HTTP 源怕被判爬虫，
#: 通达信是二进制长连接、每线程各一条，能吃更高的并发。
#:
#: **但别贪。** 曾把这里设成 24 跑全量回填（19 分钟拉 1683 万根），当天就被
#: TDX 服务端在协议层拒了：TCP 照样 0.01s 连上，握手却直接返回空
#: （``head_buf is not 0x10 : b''``），38 台无一幸免。8 路配上 38 台服务器池
#: 的分散起点，全市场增量仍有 20+ 票/秒，够快且不惹事。
ADAPTER_SOURCE_CONCURRENCY: dict[tuple[str, str], int] = {
    (LANE_HIST_DAILY, "tdx"): 8,
    (LANE_SPOT_BATCH, "tdx"): 8,
}
#: 各 lane 的**权威源**：只要它还在启用名单里，就永远排在合并优先序第一位。
#:
#: 「首位」和「权威」不是一回事。注册表顺序只决定初始排序，粘性赢家
#: （``peek_sticky``）会把上一轮命中的源提到最前——通达信偶尔抖一次、腾讯
#: 顶上并被钉住 600 秒，接下来这 600 秒里冲突日就按腾讯的值落库，而腾讯的
#: ``amount`` 是 ``close × volume`` 合成的假值。要「以通达信为准」，就得让
#: 权威源免疫粘性重排。
#:
#: 用户在运维「数据源」页手选 provider 仍然优先——那是明确的人工决定，
#: 不该被这张表推翻。
AUTHORITATIVE_BY_LANE: dict[str, str] = {
    LANE_HIST_DAILY: "tdx",
    LANE_SPOT_BATCH: "tdx",
}
#: 环境变量覆盖，形如 ``hist_daily=sina,spot_batch=""``（空值 = 该 lane 无权威源）。
_AUTHORITY_ENV = "LOCI_LANE_AUTHORITY"


def _authority_overrides() -> dict[str, str]:
    raw = str(os.environ.get(_AUTHORITY_ENV) or "").strip()
    if not raw:
        return {}
    out: dict[str, str] = {}
    for item in raw.split(","):
        lane, _, adapter_id = item.strip().partition("=")
        if lane.strip():
            out[lane.strip()] = adapter_id.strip()
    return out


def lane_authority(lane: str) -> str:
    """该 lane 的权威源 id；没有就返回空串。"""
    override = _authority_overrides()
    if lane in override:
        return override[lane]
    return AUTHORITATIVE_BY_LANE.get(lane, "")


def authoritative_order(lane: str, ids: list[str]) -> list[str]:
    """把权威源提到最前；它不在启用名单里就按粘性排。"""
    authority = lane_authority(lane)
    if authority and authority in ids:
        return [authority] + [aid for aid in ids if aid != authority]
    pinned = peek_sticky(lane)
    if pinned and pinned in ids:
        return [pinned] + [aid for aid in ids if aid != pinned]
    return list(ids)


def pin_authority(lane: str, order: list[str]) -> bool:
    """本轮排序是否由权威源领衔（领衔时调用方应跳过钉粘性）。"""
    authority = lane_authority(lane)
    return bool(authority) and bool(order) and order[0] == authority


#: 环境变量覆盖，形如 ``hist_daily:tdx=32,hist_daily:sina=6``。
_CONCURRENCY_ENV = "LOCI_ADAPTER_CONCURRENCY"

_sticky_lock = threading.Lock()
_sticky: dict[str, tuple[str, float]] = {}
_adapter_gate_lock = threading.Lock()
_adapter_gates: dict[tuple[str, str], threading.BoundedSemaphore] = {}


def _env_overrides() -> dict[tuple[str, str], int]:
    raw = str(os.environ.get(_CONCURRENCY_ENV) or "").strip()
    if not raw:
        return {}
    out: dict[tuple[str, str], int] = {}
    for item in raw.split(","):
        spec, _, value = item.strip().partition("=")
        lane, _, adapter_id = spec.partition(":")
        try:
            out[(lane.strip(), adapter_id.strip())] = int(value)
        except ValueError:
            continue
    return out


def lane_concurrency(lane: str, adapter_id: str | None = None) -> int:
    """该 (lane, 来源) 的在途名额。来源级 > lane 级 > 全局默认。"""
    if adapter_id:
        override = _env_overrides().get((lane, adapter_id))
        if override:
            return max(1, int(override))
        pinned = ADAPTER_SOURCE_CONCURRENCY.get((lane, adapter_id))
        if pinned:
            return max(1, int(pinned))
    return max(1, int(ADAPTER_LANE_CONCURRENCY.get(lane, DEFAULT_ADAPTER_CONCURRENCY)))


def _adapter_gate(lane: str, adapter_id: str) -> threading.BoundedSemaphore:
    with _adapter_gate_lock:
        gate = _adapter_gates.get((lane, adapter_id))
        if gate is None:
            gate = threading.BoundedSemaphore(lane_concurrency(lane, adapter_id))
            _adapter_gates[(lane, adapter_id)] = gate
        return gate


def _try_claim_adapter(lane: str, adapter_id: str) -> threading.BoundedSemaphore | None:
    """非阻塞：占用该 lane/来源的一个在途名额，占满返回 ``None``。

    live 顶栏竞速仍用本函数（抢不到立刻换源）。
    hist_daily / spot_batch 日常同步走 ``_claim_adapter`` 排队等待。
    """
    gate = _adapter_gate(lane, adapter_id)
    return gate if gate.acquire(blocking=False) else None


def _claim_adapter(
    lane: str,
    adapter_id: str,
    *,
    timeout: float = ADAPTER_CLAIM_WAIT_SEC,
) -> threading.BoundedSemaphore | None:
    """阻塞领取门闩；超时返回 None（仍不超过该来源的在途名额）。"""
    gate = _adapter_gate(lane, adapter_id)
    if timeout <= 0:
        return gate if gate.acquire(blocking=False) else None
    return gate if gate.acquire(blocking=True, timeout=timeout) else None


def clear_adapter_gates() -> None:
    """测试用：清空门闩表（调用方须保证无进行中请求）。"""
    with _adapter_gate_lock:
        _adapter_gates.clear()


def _release_gate_if_cancelled(future: Future[object], gate: threading.BoundedSemaphore) -> None:
    """释放尚未启动就被线程池取消的请求 gate。"""
    if future.cancelled():
        gate.release()


def clear_sticky(lane: str | None = None) -> None:
    """测试/运维清除粘性赢家；None 表示全部 lane。"""
    with _sticky_lock:
        if lane is None:
            _sticky.clear()
        else:
            _sticky.pop(lane, None)


def peek_sticky(lane: str) -> str | None:
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


_LIVE_QUOTE_PREFERRED: tuple[str, ...] = ("sina", "tencent")


def _race_live_quotes(
    adapter_ids: Sequence[str],
    codes: list[str],
    *,
    instrument_types: dict[str, str] | None,
    batch_size: int,
) -> tuple[list[dict], str]:
    if not adapter_ids:
        raise AdapterError("没有可竞速的 live 适配器")
    errors: list[str] = []
    pool = ThreadPoolExecutor(max_workers=max(1, min(4, len(adapter_ids))))
    try:
        futures = {}
        for adapter_id in adapter_ids:
            gate = _try_claim_adapter(LANE_SPOT_BATCH, adapter_id)
            if gate is None:
                errors.append(f"{adapter_id}: 请求进行中")
                continue
            try:
                future = pool.submit(
                    _fetch_live_claimed, adapter_id, gate, codes, instrument_types, batch_size
                )
            except Exception:
                gate.release()
                raise
            future.add_done_callback(
                lambda completed, claimed=gate: _release_gate_if_cancelled(completed, claimed)
            )
            futures[future] = adapter_id
        for future in as_completed(futures):
            adapter_id = futures[future]
            try:
                rows = future.result()
                if rows:
                    for pending in futures:
                        if pending is not future and not pending.done():
                            pending.cancel()
                    return rows, adapter_id
                errors.append(f"{adapter_id}: 空数据")
            except Exception as exc:
                errors.append(f"{adapter_id}: {type(exc).__name__}: {exc}")
        raise AdapterError("live 竞速失败 -> " + " | ".join(errors[-4:]))
    finally:
        pool.shutdown(wait=False, cancel_futures=True)


def _fetch_live_claimed(
    adapter_id: str,
    gate: threading.BoundedSemaphore,
    codes: list[str],
    instrument_types: dict[str, str] | None,
    batch_size: int,
) -> list[dict]:
    try:
        with observation_span(
            "market.provider.fetch",
            source_id=adapter_id,
            labels={"component": "market", "operation": "fetch", "lane": LANE_SPOT_BATCH},
        ):
            return get_adapter(adapter_id).fetch_live_quotes(
                codes, instrument_types=instrument_types, batch_size=batch_size
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
    """手选源及其显式回退链不参与竞速。"""
    errors: list[str] = []
    for adapter_id in adapter_ids:
        gate = _try_claim_adapter(LANE_SPOT_BATCH, adapter_id)
        if gate is None:
            errors.append(f"{adapter_id}: 请求进行中")
            continue
        try:
            with observation_span(
                "market.provider.fetch",
                source_id=adapter_id,
                labels={"component": "market", "operation": "fetch", "lane": LANE_SPOT_BATCH},
            ):
                rows = get_adapter(adapter_id).fetch_live_quotes(
                    codes, instrument_types=instrument_types, batch_size=batch_size
                )
            if rows:
                return rows, adapter_id
            errors.append(f"{adapter_id}: 空数据")
        except Exception as exc:
            errors.append(f"{adapter_id}: {type(exc).__name__}: {exc}")
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
    _enabled_adapter_ids: Callable[[str], Sequence[str]] | None = None,
    _lane_route_policy: Callable[[str], dict[str, Any]] | None = None,
    _preferred_sources: Sequence[str] | None = None,
    _race_live: Callable[..., tuple[list[dict], str]] | None = None,
) -> tuple[list[dict], str]:
    """顶栏/托盘富行情：先竞速新浪/腾讯，再回落全市场来源。"""
    enabled = _enabled_adapter_ids or enabled_adapter_ids
    route_policy = _lane_route_policy or lane_route_policy
    race_live = _race_live or _race_live_quotes
    ids = list(adapter_ids) if adapter_ids is not None else list(enabled(LANE_SPOT_BATCH))
    if not ids:
        raise AdapterError("没有启用的 spot_batch 适配器")
    code_list = list(codes)
    policy = route_policy(LANE_SPOT_BATCH) if adapter_ids is None else None
    selected = policy.get("provider_id") if policy else None
    if policy and policy["mode"] == "manual" and selected in ids:
        rows, winner = _fetch_live_quotes_in_configured_order(
            ids, code_list, instrument_types=instrument_types, batch_size=batch_size
        )
        pin_sticky(LANE_SPOT_BATCH, winner, ttl_sec=sticky_ttl_sec)
        return rows, winner

    preferred_sources = _preferred_sources or _LIVE_QUOTE_PREFERRED
    preferred = [adapter_id for adapter_id in preferred_sources if adapter_id in ids]
    others = [adapter_id for adapter_id in ids if adapter_id not in preferred]
    pinned = peek_sticky(LANE_SPOT_BATCH)
    if pinned and pinned in preferred:
        preferred = [pinned] + [adapter_id for adapter_id in preferred if adapter_id != pinned]

    errors: list[str] = []
    if preferred:
        try:
            rows, winner = race_live(
                preferred, code_list, instrument_types=instrument_types, batch_size=batch_size
            )
            pin_sticky(LANE_SPOT_BATCH, winner, ttl_sec=sticky_ttl_sec)
            return rows, winner
        except AdapterError as exc:
            errors.append(str(exc))
            if pinned and pinned in preferred:
                clear_sticky(LANE_SPOT_BATCH)

    for adapter_id in others:
        gate = _try_claim_adapter(LANE_SPOT_BATCH, adapter_id)
        if gate is None:
            errors.append(f"{adapter_id}: 请求进行中")
            continue
        try:
            with observation_span(
                "market.provider.fetch",
                source_id=adapter_id,
                labels={"component": "market", "operation": "fetch", "lane": LANE_SPOT_BATCH},
            ):
                rows = get_adapter(adapter_id).fetch_live_quotes(
                    code_list, instrument_types=instrument_types, batch_size=batch_size
                )
            if rows:
                pin_sticky(LANE_SPOT_BATCH, adapter_id, ttl_sec=sticky_ttl_sec)
                return rows, adapter_id
            errors.append(f"{adapter_id}: 空数据")
        except Exception as exc:
            errors.append(f"{adapter_id}: {type(exc).__name__}: {exc}")
        finally:
            gate.release()
    raise AdapterError("live 行情全部失败 -> " + " | ".join(errors[-4:]))
