"""盘口情报 provider 路由：first-healthy-wins，不跨来源拼接数据。"""
from __future__ import annotations

from collections.abc import Iterable, Sequence
import threading
import time
from typing import Any

from src.market.domain.tape import TapeAttempt, TapeProvenance, TapeRequest, TapeResult
from src.market.infrastructure.adapters.types import TAPE_LANES
from src.market.infrastructure.tape.base import provider_id_of, supports_lane
from src.market.infrastructure.tape.registry import providers_for_lane
from src.shared.observability import span as observation_span


DEFAULT_FAILURE_COOLDOWN_SECONDS = 30.0
_COOLDOWN_UNTIL: dict[tuple[str, str], float] = {}
_COOLDOWN_LOCK = threading.RLock()


def clear_provider_cooldown(
    provider_id: str | None = None,
    *,
    lane: str | None = None,
) -> None:
    """清理进程内失败冷却；供测试和运维热恢复使用。"""
    with _COOLDOWN_LOCK:
        if provider_id is None and lane is None:
            _COOLDOWN_UNTIL.clear()
            return
        for key in list(_COOLDOWN_UNTIL):
            if provider_id is not None and key[0] != provider_id:
                continue
            if lane is not None and key[1] != lane:
                continue
            _COOLDOWN_UNTIL.pop(key, None)


reset_provider_circuit = clear_provider_cooldown


def _in_cooldown(provider_id: str, lane: str) -> bool:
    with _COOLDOWN_LOCK:
        until = _COOLDOWN_UNTIL.get((provider_id, lane), 0.0)
        if until <= time.monotonic():
            _COOLDOWN_UNTIL.pop((provider_id, lane), None)
            return False
        return True


def _trip_cooldown(provider_id: str, lane: str, seconds: float) -> None:
    if seconds <= 0:
        return
    with _COOLDOWN_LOCK:
        _COOLDOWN_UNTIL[(provider_id, lane)] = time.monotonic() + seconds


def _provider_available(provider: Any, request: TapeRequest) -> tuple[bool, str]:
    checker = getattr(provider, "is_available", None)
    if not callable(checker):
        return True, ""
    try:
        available = checker(request)
    except TypeError:
        try:
            available = checker()
        except Exception as exc:
            return False, f"{type(exc).__name__}: {exc}"
    except Exception as exc:
        return False, f"{type(exc).__name__}: {exc}"
    if isinstance(available, tuple):
        ok = bool(available[0]) if available else False
        reason = str(available[1] or "") if len(available) > 1 else ""
        return ok, reason
    if isinstance(available, dict):
        return bool(available.get("available")), str(available.get("reason") or "")
    return bool(available), ""


def _coerce_result(
    raw: Any,
    *,
    provider_id: str,
    request: TapeRequest,
) -> TapeResult:
    if isinstance(raw, TapeResult):
        return raw
    return TapeResult(
        data=raw,
        provenance=TapeProvenance(
            provider_id=provider_id,
            lane=request.lane,
            requested_date=request.requested_date,
            as_of_date=request.as_of_date,
        ),
    )


def _finalize(
    result: TapeResult | None,
    *,
    provider_id: str | None,
    request: TapeRequest,
    attempts: Sequence[TapeAttempt],
    warnings: Iterable[str] = (),
    degraded: bool | None = None,
    error: str | None = None,
) -> TapeResult:
    current = result.provenance if result is not None else TapeProvenance()
    merged_warnings = tuple(
        dict.fromkeys(
            str(item).strip()
            for item in (*current.warnings, *warnings)
            if str(item).strip()
        )
    )
    final_degraded = (
        current.degraded
        if degraded is None and result is not None
        else bool(degraded)
    )
    final_error = error if error is not None else (result.error if result else None)
    provenance = TapeProvenance(
        provider_id=provider_id,
        lane=current.lane or request.lane,
        requested_date=current.requested_date or request.requested_date,
        as_of_date=current.as_of_date or request.as_of_date,
        fetched_at=current.fetched_at,
        degraded=final_degraded,
        stale=current.stale,
        from_cache=current.from_cache,
        attempts=tuple(attempts),
        warnings=merged_warnings,
    )
    return TapeResult(
        data=result.data if result is not None else None,
        provenance=provenance,
        error=final_error,
    )


def route_tape(
    request: TapeRequest,
    *,
    providers: Sequence[Any] | None = None,
    config: dict[str, Any] | None = None,
    failure_cooldown_seconds: float = DEFAULT_FAILURE_COOLDOWN_SECONDS,
) -> TapeResult:
    """按配置顺序取第一份健康结果；失败/缺数都软降级。"""
    ordered = list(providers) if providers is not None else providers_for_lane(
        request.lane, config=config
    )
    attempts: list[TapeAttempt] = []
    degraded_candidate: tuple[str, TapeResult] | None = None

    for provider in ordered:
        provider_id = provider_id_of(provider)
        if not provider_id:
            continue
        if _in_cooldown(provider_id, request.lane):
            attempts.append(
                TapeAttempt(
                    provider_id=provider_id,
                    lane=request.lane,
                    status="cooldown",
                    error="failure_cooldown",
                )
            )
            continue

        started = time.perf_counter()
        available, reason = _provider_available(provider, request)
        if not available:
            elapsed_ms = (time.perf_counter() - started) * 1000.0
            message = reason or "provider_unavailable"
            attempts.append(
                TapeAttempt(
                    provider_id=provider_id,
                    lane=request.lane,
                    status="unavailable",
                    error=message,
                    elapsed_ms=elapsed_ms,
                )
            )
            _trip_cooldown(provider_id, request.lane, failure_cooldown_seconds)
            continue

        try:
            with observation_span(
                "market.provider.fetch",
                source_id=provider_id,
                labels={"component": "market", "operation": "fetch", "lane": request.lane},
            ):
                raw = provider.fetch(request)
            result = _coerce_result(raw, provider_id=provider_id, request=request)
        except Exception as exc:
            elapsed_ms = (time.perf_counter() - started) * 1000.0
            message = f"{type(exc).__name__}: {exc}"
            attempts.append(
                TapeAttempt(
                    provider_id=provider_id,
                    lane=request.lane,
                    status="failed",
                    error=message,
                    elapsed_ms=elapsed_ms,
                )
            )
            _trip_cooldown(provider_id, request.lane, failure_cooldown_seconds)
            continue

        elapsed_ms = (time.perf_counter() - started) * 1000.0
        healthy = result.data is not None and not result.provenance.degraded
        attempts.append(
            TapeAttempt(
                provider_id=provider_id,
                lane=request.lane,
                ok=healthy,
                status="succeeded" if healthy else "degraded",
                elapsed_ms=elapsed_ms,
                error=result.error if not healthy else None,
            )
        )
        if healthy:
            return _finalize(
                result,
                provider_id=provider_id,
                request=request,
                attempts=attempts,
            )
        degraded_candidate = (provider_id, result)
        # 带数据的显式降级（例如本地行业题材）是稳定 fallback，不应因
        # 质量标记被冷却；无数据的失败候选仍需短暂避让。
        if result.data is None:
            _trip_cooldown(provider_id, request.lane, failure_cooldown_seconds)

    if degraded_candidate is not None:
        provider_id, result = degraded_candidate
        return _finalize(
            result,
            provider_id=provider_id,
            request=request,
            attempts=attempts,
            warnings=("all_providers_degraded",),
            degraded=True,
        )
    return _finalize(
        None,
        provider_id=None,
        request=request,
        attempts=attempts,
        warnings=("no_provider_available",),
        degraded=True,
        error="tape providers unavailable",
    )


def tape_readiness(
    *,
    required_lanes: Sequence[str] = TAPE_LANES,
    trade_date: str | None = None,
    store: Any | None = None,
    providers: Sequence[Any] | None = None,
    config: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """探测必需 lane 是否至少有一条可用线路。

    这是健康元数据，不参与 ``route_tape`` 的闸门决策；即使全空，也返回
    结构化的未就绪结果，让上层继续走 fail-closed 的正常扫描路径。
    """
    lanes: dict[str, dict[str, Any]] = {}
    missing: list[str] = []
    context = {"market_store": store} if store is not None else None
    for lane in required_lanes:
        request = TapeRequest(
            lane=str(lane),
            requested_date=str(trade_date or ""),
            context=context,
            cache=True,
            cache_max_age_minutes=5,
        )
        candidates = (
            list(providers)
            if providers is not None
            else providers_for_lane(str(lane), config=config)
        )
        checks: list[dict[str, Any]] = []
        for provider in candidates:
            provider_id = provider_id_of(provider)
            if not provider_id or not supports_lane(provider, str(lane)):
                continue
            available, reason = _provider_available(provider, request)
            checks.append(
                {
                    "provider_id": provider_id,
                    "available": available,
                    "reason": reason,
                    "degraded": bool(available and reason),
                }
            )
        available_ids = [item["provider_id"] for item in checks if item["available"]]
        if not available_ids:
            missing.append(str(lane))
        lanes[str(lane)] = {
            "available": bool(available_ids),
            "provider_id": available_ids[0] if available_ids else None,
            "provider_ids": available_ids,
            "checks": checks,
            "gaps": [
                {
                    "provider_id": item["provider_id"],
                    "reason": item["reason"],
                }
                for item in checks
                if not item["available"] or item["reason"]
            ],
        }
    return {
        "ready": not missing,
        "required_lanes": [str(lane) for lane in required_lanes],
        "missing_lanes": missing,
        "lanes": lanes,
    }


fetch_tape = route_tape


__all__ = [
    "DEFAULT_FAILURE_COOLDOWN_SECONDS",
    "clear_provider_cooldown",
    "fetch_tape",
    "reset_provider_circuit",
    "route_tape",
    "tape_readiness",
]
