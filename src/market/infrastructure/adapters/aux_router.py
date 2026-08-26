"""非实时行情线路的顺序回退路由。"""
from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor, TimeoutError as FuturesTimeout
from typing import Sequence

import pandas as pd

from src.market.infrastructure.adapters.base import AdapterError
from src.market.infrastructure.adapters.registry import enabled_adapter_ids, get_adapter
from src.market.infrastructure.adapters.types import (
    LANE_ADJUST_FACTOR,
    LANE_CAPITAL_FLOW,
    LANE_INSTRUMENTS,
    LANE_MINUTE,
)

#: 单源拉证券列表墙钟超时；避免 bootstrap 永久卡在 instruments。
INSTRUMENTS_FETCH_TIMEOUT_SEC = 90.0


def fetch_instruments_routed(
    *,
    adapter_ids: Sequence[str] | None = None,
    timeout_sec: float = INSTRUMENTS_FETCH_TIMEOUT_SEC,
) -> tuple[pd.DataFrame, str]:
    """证券列表：按启用顺序试，首个非空即返回。单源超时后换下一个。"""
    ids = (
        list(adapter_ids)
        if adapter_ids is not None
        else enabled_adapter_ids(LANE_INSTRUMENTS)
    )
    if not ids:
        raise AdapterError("没有启用的 instruments 适配器")
    wait_sec = max(1.0, float(timeout_sec))
    errors: list[str] = []
    for aid in ids:
        # 不能用 with：退出上下文会 shutdown(wait=True)，重新堵在挂死的源上，
        # 超时形同虚设。超时后放弃线程、立刻换下一个源。
        pool = ThreadPoolExecutor(max_workers=1)
        try:
            future = pool.submit(get_adapter(aid).fetch_instruments)
            try:
                frame = future.result(timeout=wait_sec)
            except FuturesTimeout:
                errors.append(f"{aid}: 超时>{wait_sec:.0f}s")
                continue
            if frame is not None and not frame.empty:
                return frame, aid
            errors.append(f"{aid}: 空表")
        except Exception as exc:
            errors.append(f"{aid}: {type(exc).__name__}: {exc}")
        finally:
            pool.shutdown(wait=False, cancel_futures=True)
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


def fetch_minute_routed(
    code: str,
    *,
    period: str = "1",
    days: int = 1,
    trade_date: str | None = None,
    adapter_ids: Sequence[str] | None = None,
) -> tuple[pd.DataFrame, str]:
    """分钟线：按当前 lane 策略顺序尝试，成功即返回（不写库）。"""
    ids = (
        list(adapter_ids)
        if adapter_ids is not None
        else enabled_adapter_ids(LANE_MINUTE)
    )
    if not ids:
        raise AdapterError(f"没有启用的 minute_bars 适配器（code={code}）")
    errors: list[str] = []
    for adapter_id in ids:
        try:
            frame = get_adapter(adapter_id).fetch_minute(
                code, period=period, days=days, trade_date=trade_date
            )
            if frame is not None and not frame.empty:
                return frame, adapter_id
            errors.append(f"{adapter_id}: 空数据")
        except Exception as exc:
            errors.append(f"{adapter_id}: {type(exc).__name__}: {exc}")
    raise AdapterError(f"{code} 分钟线全部失败 -> " + " | ".join(errors[-4:]))


def fetch_capital_flow_routed(
    code: str,
    *,
    adapter_ids: Sequence[str] | None = None,
) -> tuple[pd.DataFrame, str]:
    """资金流：按当前 lane 策略顺序尝试，成功即返回。"""
    ids = (
        list(adapter_ids)
        if adapter_ids is not None
        else enabled_adapter_ids(LANE_CAPITAL_FLOW)
    )
    if not ids:
        raise AdapterError(f"没有启用的 capital_flow 适配器（code={code}）")
    errors: list[str] = []
    for adapter_id in ids:
        try:
            frame = get_adapter(adapter_id).fetch_capital_flow(code)
            if frame is not None and not frame.empty:
                return frame, adapter_id
            errors.append(f"{adapter_id}: 空数据")
        except Exception as exc:
            errors.append(f"{adapter_id}: {type(exc).__name__}: {exc}")
    raise AdapterError(f"{code} 资金流全部失败 -> " + " | ".join(errors[-4:]))
