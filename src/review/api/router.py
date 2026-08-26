"""复盘 / 胜率 HTTP。

## 为什么这里有缓存

这几个同步端点每次请求都从零全量重算。实测口径：80 只票 / 720 交易日 / 720 条候选
（缓存行为由 `tests/review/test_review_router_cache.py` 兜着：写候选/写预案/行情换版本都必须换键，候选**等长改判**也必须换键——那条专门挡住把逐行摘要简化成 COUNT(*)。下面的耗时数字仍是手工基准，改动请重新实测）。

| 端点 | 单次耗时 |
|---|---|
| /api/winrate/summary | 720ms |
| /api/review/plans | 499ms |
| /api/review/candidates | 214ms |
| /api/winrate/trend | 5ms |

所以只给前三个加缓存：trend 本来就是几毫秒的 SQL，加缓存只会多一次指纹扫描。

缓存键 = 端点 + 参数 + ``palace.review_read_fingerprint()`` + ``market.market_revision()``。
两个版本号都只读聚合/一行 meta（合计约 2ms），候选池或行情一写就换键，**不引入隐式
陈数据**——这也是不用 TTL 的原因：TTL 窗口内新落的候选看不到。

## 2026-08：实盘项下线

``/api/review/equity|trips|positions|drift`` 连同其底层能力（资金曲线、往返归因、
持仓回放、回测-实盘偏离）一并删除——它们读真实成交 / 持仓，而复盘已改为只基于
「候选池 + 行情」算纸上收益。对应的实测行与缓存 scope 已从上表和名单里摘掉。
**缓存层本身保留**：candidates / plans / winrate_summary 三个 scope 仍在用它。
"""
from __future__ import annotations

import threading
from collections import OrderedDict
from typing import Any, Callable, Literal

from fastapi import APIRouter, Query

from src.shared.api_deps import market_store, missing_dependency, palace_store

#: 进程内结果缓存：键带候选池/行情版本号，装满按 LRU 淘汰。
#: 不做 TTL——过期时间只会制造「刚落的候选要等几秒才出现」这种解释不清的窗口。
_CACHE_LIMIT = 64
_CACHE_LOCK = threading.Lock()
_CACHE: OrderedDict[tuple, Any] = OrderedDict()
_MISS = object()


def clear_review_cache() -> None:
    """清空进程内复盘缓存。测试用；生产靠版本号换键，不需要手动清。"""
    with _CACHE_LOCK:
        _CACHE.clear()


def _cache_get(key: tuple) -> Any:
    with _CACHE_LOCK:
        if key not in _CACHE:
            return _MISS
        _CACHE.move_to_end(key)
        return _CACHE[key]


def _cache_put(key: tuple, value: Any) -> None:
    with _CACHE_LOCK:
        _CACHE[key] = value
        _CACHE.move_to_end(key)
        while len(_CACHE) > _CACHE_LIMIT:
            _CACHE.popitem(last=False)


def build_review_router(
    *,
    market_db: str | None = None,
    palace_db: str | None = None,
) -> APIRouter:
    router = APIRouter()

    def _market():
        return market_store(market_db)

    def _palace():
        return palace_store(palace_db)

    def _cached(scope: str, params: tuple, compute: Callable[[Any, Any], Any]) -> Any:
        """按「候选池读模型指纹 + 行情版本号」缓存端点结果。

        两个版本号都在打开的连接上现算：候选池 / 预案 / 复盘一写指纹就变，行情一
        同步 revision 就变，缓存立刻失效。命中时仍会开一次库读版本号（约 2ms），
        换来的是省掉几百毫秒的全量重算。

        ``review_read_fingerprint()`` 必须是逐行摘要而不是 COUNT(*)：候选**等长
        改判**（行数不变、裁决变了）也得换键，否则这里会发陈数据。

        返回的是缓存里的同一个对象，调用方（FastAPI 的 JSON 编码）只读不改。
        """
        with _palace() as palace, _market() as market:
            key = (scope, palace_db, market_db, params,
                   palace.review_read_fingerprint(), market.market_revision())
            hit = _cache_get(key)
            if hit is not _MISS:
                return hit
            value = compute(palace, market)
            _cache_put(key, value)
            return value

    @router.get("/api/review/candidates", tags=["review"])
    def review_candidates(
        limit: int = Query(default=300, ge=1, le=2000),
        benchmark: str | None = Query(default="000300", pattern=r"^\d{6}$"),
        window_days: int | None = Query(
            default=None,
            ge=1,
            le=60,
            description="仅保留近 N 个交易日选出的候选（盘面近选跟踪用 5）",
        ),
        selected_only: bool = Query(
            default=False,
            description="仅精选；盘面近选跟踪传 true",
        ),
        as_of: str | None = Query(
            default=None,
            pattern=r"^\d{4}-\d{2}-\d{2}$",
            description="观察日（交易日）；默认取行情日历末日",
        ),
    ) -> dict[str, Any]:
        try:
            from src.review import evaluate_candidates, filter_recent_outcomes, summarize_candidates
        except ImportError as exc:
            raise missing_dependency(exc) from exc

        def compute(palace, market):
            outcomes = evaluate_candidates(palace, market, limit=limit, benchmark=benchmark)
            if window_days is not None:
                calendar = market.trading_days()
                anchor = as_of or (calendar[-1] if calendar else "")
                outcomes = filter_recent_outcomes(
                    outcomes,
                    calendar,
                    as_of=anchor,
                    window_days=window_days,
                    selected_only=selected_only,
                )
            elif selected_only:
                outcomes = [row for row in outcomes if row.selected]
            return dict(
                outcomes=[outcome.to_dict() for outcome in outcomes],
                summary=summarize_candidates(outcomes),
            )

        params = (limit, benchmark, window_days, selected_only, as_of)
        return _cached("candidates", params, compute)

    @router.get("/api/review/plans", tags=["review"])
    def review_plans() -> list[dict[str, Any]]:
        try:
            from src.review import evaluate_plans
        except ImportError as exc:
            raise missing_dependency(exc) from exc
        return _cached("plans", (), lambda palace, market: evaluate_plans(palace, market))

    @router.get("/api/winrate/summary", tags=["review"])
    def winrate_summary() -> list[dict[str, Any]]:
        """各战法胜率：精选候选 T+5 优先，手工复盘兜底。"""
        try:
            from src.review import strategy_winrate_summary
        except ImportError as exc:
            raise missing_dependency(exc) from exc
        compute = lambda palace, market: strategy_winrate_summary(palace, market)
        return _cached("winrate_summary", (), compute)

    @router.get("/api/winrate/trend", tags=["review"])
    def winrate_trend(
        granularity: Literal["month", "week"] = Query(default="month"),
        tags: str | None = Query(default=None, max_length=500),
    ) -> list[dict[str, Any]]:
        """按时间粒度分战法统计胜率趋势。tags 用逗号分隔多个战法名。不缓存：实测 5ms。"""
        tag_list = [t.strip() for t in tags.split(",") if t.strip()] if tags else None
        with _palace() as palace:
            return palace.winrate_trend(strategy_tags=tag_list, granularity=granularity)

    return router
