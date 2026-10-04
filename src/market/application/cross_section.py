"""全市场实时截面：保留来源的一次批量读取，进程内合并重复请求。

本模块不写数据库；报价时间来自上游，缓存命中不刷新报价时间。失败由调用方
决定如何展示过期状态，不把旧截面伪装为新的采集结果。
"""
from __future__ import annotations

from collections import OrderedDict
from contextlib import closing
import copy
from pathlib import Path
import sqlite3
import threading
import time
from typing import Any

from src.market.infrastructure.adapters.base import AdapterError
from src.market.infrastructure.adapters.registry import enabled_adapter_ids
from src.market.infrastructure.adapters.router import fetch_live_quotes_routed
from src.market.infrastructure.adapters.types import LANE_SPOT_BATCH
from src.shared.paths import market_db

_TTL_SECONDS = 15.0
_lock = threading.Lock()
_cache: OrderedDict[tuple[str, tuple[str, ...]], tuple[float, list[dict[str, Any]]]] = OrderedDict()


def clear_cross_section_cache() -> None:
    with _lock:
        _cache.clear()


def _instruments(path: Path) -> list[dict[str, Any]]:
    with closing(sqlite3.connect(path.resolve().as_uri() + "?mode=ro", uri=True, timeout=2)) as conn:
        conn.row_factory = sqlite3.Row
        rows = conn.execute("SELECT code,name,board,industry FROM instruments "
                            "WHERE instrument_type='STOCK' AND COALESCE(status,'') <> 'delisted' ORDER BY code").fetchall()
        return [dict(row) for row in rows]


def fetch_cross_section(*, db_path: Path | str | None = None) -> list[dict[str, Any]]:
    """按当前启用来源取数，最多一轮并发采集；不足的截面不冒充全市场。"""
    path = Path(db_path or market_db()).resolve()
    providers = tuple(enabled_adapter_ids(LANE_SPOT_BATCH))
    if not providers:
        raise AdapterError("现价来源均已关闭")
    key = (str(path), providers)
    if not _lock.acquire(timeout=2):
        raise AdapterError("全市场截面正在刷新，请稍后重试")
    try:
        cached = _cache.get(key)
        if cached and time.monotonic() - cached[0] < _TTL_SECONDS:
            return copy.deepcopy(cached[1])
        instruments = _instruments(path)
        if not instruments:
            raise AdapterError("证券名录为空，请先同步交易所列表")
        if len(instruments) > 15000:
            raise AdapterError("证券名录超过截面读取上限")
        codes = [row["code"] for row in instruments]
        quotes, source = fetch_live_quotes_routed(codes, adapter_ids=providers)
        metadata = {row["code"]: row for row in instruments}
        indexed = {str(row.get("code") or ""): row for row in quotes if row.get("price", 0) > 0}
        if len(indexed.keys() & metadata.keys()) < len(codes) * 0.90:
            raise AdapterError(f"全市场截面不完整：有效 {len(indexed)} / 请求 {len(codes)}，不生成误导性排行")
        result = []
        for code in codes:
            quote = indexed.get(code)
            if quote is None:
                continue
            row = {**metadata[code], **quote, "source": source}
            # 上游无换手率、量比和涨速就不添加这些字段，不能填 0 伪装事实。
            result.append(row)
        _cache[key] = (time.monotonic(), result)
        _cache.move_to_end(key)
        while len(_cache) > 4:
            _cache.popitem(last=False)
        return copy.deepcopy(result)
    finally:
        _lock.release()
