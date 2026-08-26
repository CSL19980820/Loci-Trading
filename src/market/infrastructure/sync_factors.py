"""复权因子刷新：过期判定 + 逐票重拉。

从 ``sync.py`` 拆出来纯粹是体量原因（同步编排贴着 600 行上限）。
因子变动极稀疏——只在除权除息日新增一行——所以真正的优化不在并发，
而在「先用一条 GROUP BY 查出过期票清单，只对这批发请求」，
过期判定见 ``sync_prefetch.SyncPrefetch.factor_age``。
"""
from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
import logging
import threading
from typing import Any, Callable, Sequence

import pandas as pd

from src.market.infrastructure.sources import QuoteSource
from src.market.infrastructure.store import MarketStore, normalize_code
from src.market.infrastructure.sync_engine import RateLimiter as _RateLimiter
from src.market.infrastructure.sync_prefetch import SyncPrefetch

logger = logging.getLogger(__name__)

_FACTOR_STALE_DAYS = 3


def _factor_fetched_at(
    store: MarketStore, code: str, prefetch: SyncPrefetch | None = None
) -> str:
    if prefetch is not None and prefetch.loaded:
        return prefetch.factor_age.get(normalize_code(code), "")
    row = store.conn.execute(
        "SELECT MAX(fetched_at) FROM adjust_factors WHERE code = ?",
        (normalize_code(code),),
    ).fetchone()
    return str(row[0] or "") if row else ""


def _factor_is_fresh(latest: str, stale_days: int) -> bool:
    """因子时间戳是否还在保鲜期内。"""
    if not latest:
        return False
    try:
        fetched = datetime.fromisoformat(latest.replace("Z", "+00:00"))
    except ValueError:
        return False
    if fetched.tzinfo is not None:
        fetched = fetched.astimezone(timezone.utc).replace(tzinfo=None)
    age = (datetime.now(timezone.utc).replace(tzinfo=None) - fetched).total_seconds()
    return age <= stale_days * 86400


def _refresh_factors_if_stale(
    store: MarketStore,
    code: str,
    *,
    sources: Sequence[QuoteSource] | None,
    limiter: Any,
    stale_days: int = _FACTOR_STALE_DAYS,
    prefetch: SyncPrefetch | None = None,
) -> bool:
    """因子缺失或过旧时重拉；成功刷新返回 True。"""
    if _factor_is_fresh(_factor_fetched_at(store, code, prefetch), stale_days):
        return False
    got = _fetch_factors_for_sync(code, sources=sources, limiter=limiter)
    if got is None:
        return False
    factors, factor_src = got
    store.upsert_adjust_factors(code, factors, source=factor_src)
    return True


def refresh_adjust_factors(
    store_factory: Callable[[], MarketStore],
    codes: Sequence[str],
    *,
    sources: Sequence[QuoteSource] | None = None,
    instrument_types: dict[str, str] | None = None,
    workers: int = 4,
    min_interval: float = 0.15,
    stale_days: int = _FACTOR_STALE_DAYS,
    progress: Callable[[int, int, str], None] | None = None,
) -> int:
    """只刷新复权因子（日终 today_refresh 用），不重拉历史日 K。"""
    types = instrument_types or {}
    limiter = _RateLimiter(min_interval)
    refreshed = 0
    lock = threading.Lock()
    total = len(codes)

    def worker(index_and_code: tuple[int, str]) -> None:
        nonlocal refreshed
        index, raw_code = index_and_code
        code = normalize_code(raw_code)
        if types.get(code, "STOCK") != "STOCK":
            return
        store = store_factory()
        try:
            if _refresh_factors_if_stale(
                store, code, sources=sources, limiter=limiter, stale_days=stale_days
            ):
                with lock:
                    refreshed += 1
        except Exception as exc:
            logger.debug("刷新 %s 复权因子失败：%s", code, exc)
        finally:
            store.close()
            if progress:
                with lock:
                    progress(index + 1, total, code)

    with ThreadPoolExecutor(max_workers=max(1, workers)) as pool:
        futures = [pool.submit(worker, item) for item in enumerate(codes)]
        for future in as_completed(futures):
            future.result()
    return refreshed


def _fetch_factors_for_sync(
    code: str,
    *,
    sources: Sequence[QuoteSource] | None,
    limiter: Any,
) -> tuple[pd.DataFrame, str] | None:
    if sources is not None:
        for source in sources:
            try:
                limiter.wait()
                factors = source.fetch_adjust_factors(code)
                if factors is not None and not factors.empty:
                    return factors, source.name
            except Exception as exc:
                logger.debug("取 %s 复权因子失败（%s）：%s", code, source.name, exc)
        return None

    from src.market.infrastructure.adapters import AdapterError, fetch_adjust_factors_routed

    try:
        limiter.wait()
        return fetch_adjust_factors_routed(code)
    except AdapterError as exc:
        logger.debug("取 %s 复权因子失败：%s", code, exc)
        return None
