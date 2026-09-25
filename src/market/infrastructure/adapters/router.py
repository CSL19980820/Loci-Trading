"""选路：探测 / 测速 / 多源协作合并与粘性。

日常同步走 ``fetch_daily_routed``：各启用源排队取数、全部结束后互补合并，
再把合并主源钉成粘性赢家。粘性只提高合并优先序，不再「谁快谁赢、取消其余」。
"""
from __future__ import annotations

from src.shared.clock import utc_now

from concurrent.futures import ThreadPoolExecutor, as_completed
import os
from typing import Any, Sequence

import pandas as pd

from src.market.infrastructure.adapters import circuit
from src.market.infrastructure.adapters.base import AdapterError, MarketAdapter
from src.market.infrastructure.adapters.registry import (
    enabled_adapter_ids,
    get_adapter,
    lane_disabled_provider_ids,
    lane_route_policy,
)
from src.market.infrastructure.adapters.types import (
    LANE_HIST_DAILY,
    LANE_SPOT_BATCH,
)
# 别名形式是 PEP 484 的显式再导出标记：这些名字本模块不用，只为兼容旧导入路径。
from src.market.infrastructure.adapters.aux_router import (
    fetch_adjust_factors_routed as fetch_adjust_factors_routed,
    fetch_capital_flow_routed as fetch_capital_flow_routed,
    fetch_instruments_routed as fetch_instruments_routed,
    fetch_minute_routed as fetch_minute_routed,
)
from src.market.infrastructure.adapters import router_live as _live_router
from src.market.infrastructure.adapters.router_live import (
    ADAPTER_CLAIM_WAIT_SEC,
    STICKY_TTL_SEC,
    _claim_adapter,
    authoritative_order,
    clear_sticky,
    peek_sticky,
    pin_authority,
    pin_sticky,
)
from src.shared.observability import (
    metric as observation_metric,
    span as observation_span,
)


def _record_receipt(
    receipt: list[dict[str, Any]] | None,
    *,
    source_id: str,
    state: str,
    rows: int | None = None,
    fields: Sequence[str] = (),
    error: str = "",
) -> None:
    observation_metric(
        "loci.market.provider.attempts",
        labels={"component": "market", "operation": "route", "status": state},
    )
    if receipt is None:
        return
    receipt.append(
        {
            "source_id": source_id,
            "state": state,
            "checked_at": utc_now(),
            "rows": rows,
            "fields": [str(field) for field in fields],
            "error": str(error)[:500],
        }
    )


# 兼容既有测试与第三方扩展对 router 私有竞速钩子的 monkeypatch；实际实现
# 保持在 router_live，粘性和 gate 状态也由它统一维护。
_LIVE_QUOTE_PREFERRED: tuple[str, ...] = _live_router._LIVE_QUOTE_PREFERRED


def _race_live_quotes(*args: Any, **kwargs: Any) -> tuple[list[dict], str]:
    return _live_router._race_live_quotes(*args, **kwargs)


from src.market.infrastructure.adapters.router_shared import _resolve_adapters


# 别名形式是 PEP 484 的显式再导出标记：这些名字本模块不用，只为兼容旧导入路径。
from src.market.infrastructure.adapters.router_probe import (
    probe_lane as probe_lane,
    speedtest_daily as speedtest_daily,
)



def _fetch_daily_queued(
    adapter: MarketAdapter,
    code: str,
    instrument_type: str,
    claim_wait_sec: float,
    recent_bars: int | None = None,
) -> tuple[str, pd.DataFrame | None, str, str]:
    """排队领取本源门闩后拉取；不取消、不抢赢。

    第四个返回值是结果类别：``ok`` / ``empty`` / ``failed`` / ``gate_timeout``。
    「源答了但没这只票」（empty）与「源打不通」（failed）必须分开——熔断只认后者。
    """
    aid = adapter.meta.id
    gate = _claim_adapter(LANE_HIST_DAILY, aid, timeout=claim_wait_sec)
    if gate is None:
        return aid, None, "等待来源空闲超时", "gate_timeout"
    try:
        with observation_span(
            "market.provider.fetch",
            source_id=aid,
            labels={"component": "market", "operation": "fetch", "lane": LANE_HIST_DAILY},
        ):
            frame = (
                adapter.fetch_daily(code, instrument_type=instrument_type)
                if recent_bars is None
                else adapter.fetch_daily_window(
                    code, instrument_type=instrument_type, bars=recent_bars
                )
            )
        if frame is None or frame.empty:
            return aid, None, "空数据", "empty"
        return aid, frame, "", "ok"
    except Exception as exc:
        return aid, None, f"{type(exc).__name__}: {exc}", "failed"
    finally:
        gate.release()


#: 交叉校验抽样：非抽中的票只打主源。多源协作合并是正确性手段，
#: 但对每票每天都跑，成本是「启用源数」倍的全量请求——实测这正是
#: 全市场同步 57 分钟里最大的一块。抽样保留信号，成本降一个量级。
CROSS_CHECK_SAMPLE_EVERY = 50
#: 环境变量覆盖；``0`` 或负数关闭抽样（全部只打主源）。
_CROSS_CHECK_ENV = "LOCI_CROSS_CHECK_EVERY"
#: 交叉校验这条路径的墙钟预算。抽中的票要等所有源跑完，而最慢的源（证券宝
#: 实测 1.7~30s/票）会把整轮同步顶住：40 只票里抽中 1 只，那一只就吃掉
#: 全部墙钟。超预算就用已经拿到的源合并，不足的记在回执里，不再干等。
CROSS_CHECK_BUDGET_SEC = 8.0


def cross_check_every() -> int:
    raw = str(os.environ.get(_CROSS_CHECK_ENV) or "").strip()
    if not raw:
        return CROSS_CHECK_SAMPLE_EVERY
    try:
        return int(raw)
    except ValueError:
        return CROSS_CHECK_SAMPLE_EVERY


def should_cross_check(code: str, *, every: int | None = None) -> bool:
    """这只票本轮要不要做多源交叉校验。

    按代码取模而不是随机：同一只票的判定在多次同步间稳定，回执可复现，
    不会今天说校验过、明天说没有。
    """
    step = cross_check_every() if every is None else int(every)
    if step <= 0:
        return False
    if step == 1:
        return True
    digits = "".join(ch for ch in str(code) if ch.isdigit())
    if not digits:
        return True
    return int(digits) % step == 0

def _fetch_daily_primary(
    code: str,
    adapters: list[MarketAdapter],
    *,
    instrument_type: str,
    claim_wait_sec: float,
    recent_bars: int | None,
    receipt: list[dict[str, Any]] | None,
    errors: list[str],
) -> tuple[pd.DataFrame, str]:
    """按优先序试到第一个成功就返回；不并发、不合并。

    主源是通达信二进制（单票 p50 约 28ms），一次命中就够；退化到这条路径
    的代价远小于「每票都等最慢的源跑完」。未尝试的源在回执里明确记 skipped，
    不能让人误读成「校验过且一致」。
    """
    for position, adapter in enumerate(adapters):
        aid = adapter.meta.id
        _record_receipt(receipt, source_id=aid, state="attempted")
        try:
            source_id, frame, error, kind = _fetch_daily_queued(
                adapter, code, instrument_type, max(0.0, claim_wait_sec), recent_bars
            )
        except Exception as exc:
            errors.append(f"{aid}: {type(exc).__name__}: {exc}")
            circuit.record_failure(LANE_HIST_DAILY, aid)
            _record_receipt(
                receipt,
                source_id=aid,
                state="failed",
                error=f"{type(exc).__name__}: {exc}",
            )
            continue
        if kind != "ok" or frame is None or frame.empty:
            message = error or "空数据"
            errors.append(f"{source_id}: {message}")
            if kind == "empty":
                state = "empty"
            else:
                circuit.record_failure(LANE_HIST_DAILY, source_id)
                state = "skipped" if kind == "gate_timeout" else "failed"
            _record_receipt(receipt, source_id=source_id, state=state, error=message)
            continue
        circuit.record_success(LANE_HIST_DAILY, source_id)
        _record_receipt(
            receipt,
            source_id=source_id,
            state="selected",
            rows=int(len(frame)),
            fields=frame.columns,
        )
        for other in adapters[position + 1 :]:
            _record_receipt(
                receipt,
                source_id=other.meta.id,
                state="skipped",
                error="主源命中，本轮未抽中交叉校验，该源未请求",
            )
        return frame, source_id
    raise AdapterError(
        f"{code} 全部 hist_daily 适配器失败 -> " + " | ".join(errors[-6:])
    )


def fetch_daily_best(
    code: str,
    *,
    instrument_type: str = "STOCK",
    adapter_ids: Sequence[str] | None = None,
    max_workers: int = 4,
    receipt: list[dict[str, Any]] | None = None,
    claim_wait_sec: float = ADAPTER_CLAIM_WAIT_SEC,
    recent_bars: int | None = None,
    cross_check: bool = True,
) -> tuple[pd.DataFrame, str]:
    """拉取 hist_daily。

    ``cross_check=True``（默认）走协作合并：各源排队取数，全部结束后互补合并。
    冲突日按 ``adapter_ids`` 优先序，缺失日/空字段由后方源补齐。

    ``cross_check=False`` 只打主源，第一个成功即返回。日常同步的绝大多数票走
    这条：协作合并对每票都跑，单票成本是「启用源数」倍，而最慢的源（证券宝
    实测 1.7~30s/票）会把整票拖到和它一样慢。抽样策略见 ``should_cross_check``。

    ``recent_bars``：只要最近这么多根，用于日常增量；``None`` 为全历史。
    """
    from src.market.infrastructure.adapters.daily_merge import merge_daily_frames

    resolved = _resolve_adapters(LANE_HIST_DAILY, adapter_ids)
    if not resolved:
        raise AdapterError(f"没有可用的 hist_daily 适配器（code={code}）")

    preferred = [adapter.meta.id for adapter in resolved]
    errors: list[str] = []
    adapters: list[MarketAdapter] = []
    # 扶摇是通达信备源；抽样交叉校验也不应在 TDX 成功时消耗其远端请求。
    hithink_fallback = (
        next((adapter for adapter in resolved if adapter.meta.id == "hithink"), None)
        if cross_check and preferred[0] == "tdx"
        else None
    )
    for adapter in resolved:
        if adapter is hithink_fallback:
            continue
        if circuit.acquire(LANE_HIST_DAILY, adapter.meta.id):
            adapters.append(adapter)
            continue
        cooldown = circuit.cooldown_remaining(LANE_HIST_DAILY, adapter.meta.id)
        message = f"来源连续失败已熔断，{int(cooldown)}s 后自动重试"
        errors.append(f"{adapter.meta.id}: {message}")
        _record_receipt(
            receipt, source_id=adapter.meta.id, state="skipped", error=message
        )
    if not adapters and hithink_fallback is None:
        raise AdapterError(
            f"{code} 所有 hist_daily 来源都在熔断冷却中 -> " + " | ".join(errors[-6:])
        )

    if not cross_check:
        return _fetch_daily_primary(
            code,
            adapters,
            instrument_type=instrument_type,
            claim_wait_sec=claim_wait_sec,
            recent_bars=recent_bars,
            receipt=receipt,
            errors=errors,
        )
    workers = max(1, min(max_workers, len(adapters)))
    successes: list[tuple[str, pd.DataFrame]] = []

    pool = ThreadPoolExecutor(max_workers=workers)
    try:
        futures = {
            pool.submit(
                _fetch_daily_queued,
                adapter,
                code,
                instrument_type,
                max(0.0, claim_wait_sec),
                recent_bars,
            ): adapter
            for adapter in adapters
        }
        for future in as_completed(futures):
            adapter = futures[future]
            aid = adapter.meta.id
            _record_receipt(receipt, source_id=aid, state="attempted")
            try:
                source_id, frame, error, kind = future.result()
            except Exception as exc:
                errors.append(f"{aid}: {type(exc).__name__}: {exc}")
                circuit.record_failure(LANE_HIST_DAILY, aid)
                _record_receipt(
                    receipt,
                    source_id=aid,
                    state="failed",
                    error=f"{type(exc).__name__}: {exc}",
                )
                continue
            if kind != "ok" or frame is None or frame.empty:
                message = error or "空数据"
                errors.append(f"{source_id}: {message}")
                if kind == "gate_timeout":
                    circuit.record_failure(LANE_HIST_DAILY, source_id)
                    state = "skipped"
                elif kind == "empty":
                    state = "empty"
                else:
                    circuit.record_failure(LANE_HIST_DAILY, source_id)
                    state = "failed"
                _record_receipt(receipt, source_id=source_id, state=state, error=message)
                continue
            circuit.record_success(LANE_HIST_DAILY, source_id)
            successes.append((source_id, frame))
    finally:
        pool.shutdown(wait=True, cancel_futures=False)

    if hithink_fallback is not None:
        aid = hithink_fallback.meta.id
        if any(source_id == "tdx" for source_id, _frame in successes):
            _record_receipt(
                receipt, source_id=aid, state="skipped", error="通达信命中，扶摇备源未请求"
            )
        elif not circuit.acquire(LANE_HIST_DAILY, aid):
            cooldown = circuit.cooldown_remaining(LANE_HIST_DAILY, aid)
            message = f"来源连续失败已熔断，{int(cooldown)}s 后自动重试"
            errors.append(f"{aid}: {message}")
            _record_receipt(
                receipt,
                source_id=aid,
                state="skipped",
                error=message,
            )
        else:
            _record_receipt(receipt, source_id=aid, state="attempted")
            source_id, frame, error, kind = _fetch_daily_queued(
                hithink_fallback,
                code,
                instrument_type,
                max(0.0, claim_wait_sec),
                recent_bars,
            )
            if kind == "ok" and frame is not None and not frame.empty:
                circuit.record_success(LANE_HIST_DAILY, aid)
                successes.append((source_id, frame))
            else:
                if kind != "empty":
                    circuit.record_failure(LANE_HIST_DAILY, aid)
                errors.append(f"{aid}: {error or '空数据'}")
                _record_receipt(
                    receipt,
                    source_id=aid,
                    state="empty" if kind == "empty" else "failed",
                    error=error or "空数据",
                )

    if not successes:
        raise AdapterError(
            f"{code} 全部 hist_daily 适配器失败 -> " + " | ".join(errors[-6:])
        )

    try:
        merged, primary, contributed = merge_daily_frames(
            successes,
            preferred_order=preferred,
            estimated_fields={
                adapter.meta.id: adapter.meta.estimated_fields
                for adapter in adapters
                if adapter.meta.estimated_fields
            },
        )
    except ValueError as exc:
        raise AdapterError(f"{code} 多源合并失败：{exc}") from exc

    for source_id, frame in successes:
        rows = int(contributed.get(source_id, 0))
        _record_receipt(
            receipt,
            source_id=source_id,
            state="selected" if source_id == primary else "succeeded",
            rows=rows if rows else int(len(frame)),
            fields=frame.columns,
            error="" if source_id == primary else "协作合并：校验/补齐用",
        )
    return merged, primary


def fetch_daily_routed(
    code: str,
    *,
    instrument_type: str = "STOCK",
    adapter_ids: Sequence[str] | None = None,
    max_workers: int = 4,
    sticky_ttl_sec: float = STICKY_TTL_SEC,
    receipt: list[dict[str, Any]] | None = None,
    recent_bars: int | None = None,
    cross_check: bool | None = None,
) -> tuple[pd.DataFrame, str]:
    """日常同步入口：命中后钉住主源。

    ``cross_check`` 为 None 时按 ``should_cross_check(code)`` 抽样决定——多数票
    只打主源，抽中的票才做多源协作合并。粘性赢家只提高优先序。
    ``adapter_ids`` 为 None 时读 ``lane_providers`` 启用名单。
    启用源全灭且用户关掉了其他日 K 源时，把关掉的源当最后回退（不钉粘性），
    避免必需线路只剩单源时一次握手超时就整票失败。
    """
    effective_cross_check = (
        should_cross_check(code) if cross_check is None else bool(cross_check)
    )
    ids = list(adapter_ids) if adapter_ids is not None else enabled_adapter_ids(LANE_HIST_DAILY)
    if not ids:
        raise AdapterError(f"没有启用的 hist_daily 适配器（code={code}）")

    policy = lane_route_policy(LANE_HIST_DAILY) if adapter_ids is None else None
    preferred = policy.get("provider_id") if policy else None
    locked_single = False
    if policy and policy["mode"] == "manual" and preferred in ids:
        if not policy.get("fallback"):
            order = [preferred]
            locked_single = True
        else:
            order = [preferred] + [aid for aid in ids if aid != preferred]
    else:
        order = authoritative_order(LANE_HIST_DAILY, ids)

    if pin_authority(LANE_HIST_DAILY, order):
        # 权威源在位时不钉粘性：粘性的作用是「谁刚成功就先问谁」，
        # 但权威源本来就排第一，再钉一次只会在它某次失败后把别人钉到它前面。
        sticky_ttl_sec = 0.0

    try:
        frame, winner = fetch_daily_best(
            code,
            instrument_type=instrument_type,
            adapter_ids=order,
            max_workers=max_workers,
            receipt=receipt,
            recent_bars=recent_bars,
            cross_check=effective_cross_check,
        )
    except AdapterError as exc:
        if adapter_ids is not None:
            raise
        # 手选无回退：其余源根本没跑过，错误必须写清，不能让人以为整条线路挂了。
        if locked_single:
            raise AdapterError(
                f"{exc}（历史日 K 已手动锁定「{preferred}」且未开失败回退，"
                "其余数据源未尝试；可在运维「数据源」页打开失败回退或改回自动）"
            ) from exc
        parked = lane_disabled_provider_ids(LANE_HIST_DAILY)
        if not parked:
            raise
        # 关开关 = 日常协同合并不用它们，不是「必需日 K 单源抖动就整票失败」。
        for aid in parked:
            try:
                frame, winner = fetch_daily_best(
                    code,
                    instrument_type=instrument_type,
                    adapter_ids=[aid],
                    max_workers=1,
                    receipt=receipt,
                    recent_bars=recent_bars,
                )
            except AdapterError:
                continue
            _record_receipt(
                receipt,
                source_id=winner,
                state="emergency",
                rows=int(len(frame)),
                fields=frame.columns,
                error="启用源失败后回退到已关闭来源",
            )
            return frame, winner
        raise AdapterError(
            f"{exc}（历史日 K 只剩 {len(ids)} 个启用源；"
            f"{'、'.join(parked)} 已关闭，最后回退仍失败）"
        ) from exc
    # 手选无回退时始终钉住手选源；其余钉合并主源。
    pin_id = preferred if (policy and policy["mode"] == "manual" and preferred) else winner
    if pin_id:
        pin_sticky(LANE_HIST_DAILY, pin_id, ttl_sec=sticky_ttl_sec)
    return frame, winner


def fetch_spot_routed(
    codes: Sequence[str],
    *,
    instrument_types: dict[str, str] | None = None,
    batch_size: int = 400,
    adapter_ids: Sequence[str] | None = None,
    sticky_ttl_sec: float = STICKY_TTL_SEC,
    claim_wait_sec: float = ADAPTER_CLAIM_WAIT_SEC,
    receipt: list[dict[str, Any]] | None = None,
) -> tuple[pd.DataFrame, str]:
    """批量现价：粘性赢家优先，失败再按启用顺序试；源忙时排队等待，不立刻报『请求进行中』。"""
    ids = (
        list(adapter_ids)
        if adapter_ids is not None
        else enabled_adapter_ids(LANE_SPOT_BATCH)
    )
    if not ids:
        raise AdapterError("没有启用的 spot_batch 适配器")

    pinned = peek_sticky(LANE_SPOT_BATCH)
    # 权威源（通达信）领衔；它不在启用名单里才退回粘性排序。
    order = authoritative_order(LANE_SPOT_BATCH, list(ids))

    errors: list[str] = []
    for aid in order:
        gate = _claim_adapter(LANE_SPOT_BATCH, aid, timeout=claim_wait_sec)
        if gate is None:
            errors.append(f"{aid}: 等待来源空闲超时")
            _record_receipt(
                receipt, source_id=aid, state="skipped", error="等待来源空闲超时"
            )
            if pinned == aid:
                clear_sticky(LANE_SPOT_BATCH)
            continue
        try:
            _record_receipt(receipt, source_id=aid, state="attempted")
            with observation_span(
                "market.provider.fetch",
                source_id=aid,
                labels={"component": "market", "operation": "fetch", "lane": LANE_SPOT_BATCH},
            ):
                frame = get_adapter(aid).fetch_spot(
                    list(codes),
                    instrument_types=instrument_types,
                    batch_size=batch_size,
                )
            if frame is not None and not frame.empty:
                _record_receipt(
                    receipt,
                    source_id=aid,
                    state="selected",
                    rows=int(len(frame)),
                    fields=frame.columns,
                )
                pin_sticky(LANE_SPOT_BATCH, aid, ttl_sec=sticky_ttl_sec)
                return frame, aid
            errors.append(f"{aid}: 空数据")
            _record_receipt(receipt, source_id=aid, state="empty", rows=0)
            if pinned == aid:
                clear_sticky(LANE_SPOT_BATCH)
        except Exception as exc:
            errors.append(f"{aid}: {type(exc).__name__}: {exc}")
            _record_receipt(
                receipt,
                source_id=aid,
                state="failed",
                error=f"{type(exc).__name__}: {exc}",
            )
            if pinned == aid:
                clear_sticky(LANE_SPOT_BATCH)
        finally:
            gate.release()

    raise AdapterError("当日现价暂时拉不到 -> " + " | ".join(errors[-4:]))


def fetch_live_quotes_routed(
    codes: Sequence[str],
    *,
    instrument_types: dict[str, str] | None = None,
    batch_size: int = 400,
    adapter_ids: Sequence[str] | None = None,
    sticky_ttl_sec: float = STICKY_TTL_SEC,
) -> tuple[list[dict], str]:
    """兼容 facade：实现和共享状态集中在 ``router_live``。"""
    return _live_router.fetch_live_quotes_routed(
        codes,
        instrument_types=instrument_types,
        batch_size=batch_size,
        adapter_ids=adapter_ids,
        sticky_ttl_sec=sticky_ttl_sec,
        _enabled_adapter_ids=enabled_adapter_ids,
        _lane_route_policy=lane_route_policy,
        _preferred_sources=_LIVE_QUOTE_PREFERRED,
        _race_live=_race_live_quotes,
    )
