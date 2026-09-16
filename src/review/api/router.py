"""复盘 / 胜率 HTTP。

## 为什么这里有缓存

这几个同步端点每次请求都从零全量重算。实测口径：80 只票 / 720 交易日 / 720 条候选
（缓存行为由 `tests/review/test_review_router_cache.py` 兜着：写候选/写预案/行情换版本都必须换键，候选**等长改判**也必须换键——那条专门挡住把逐行摘要简化成 COUNT(*)。下面的耗时数字仍是手工基准，改动请重新实测）。

|端点|单次耗时|
|---|---|
| /api/winrate/summary | 720ms |
| /api/review/plans | 499ms |
| /api/review/candidates | 214ms |
| /api/winrate/trend | 5ms（旧口径读 reviews）|

缓存键 = 端点 + 参数 + ``palace.review_read_fingerprint()`` + ``market.market_revision()``。
两个版本号都只读聚合/一行 meta（合计约 2ms），候选池或行情一写就换键，**不引入隐式
陈数据**——这也是不用 TTL 的原因：TTL 窗口内新落的候选看不到。

## 2026-09：winrate 三兄弟共用一次重算

``/api/winrate/trend`` 原先只读 ``reviews`` 表（手工复盘），而主表读候选 T+N。手工
复盘早已停用（线上 0 行），那张「分周期明细」于是永远空着。现在 trend 与 summary
同源，新增的 ``/api/winrate/samples`` 也一样——三者都从 ``candidate_outcomes`` 这个
共享缓存 scope 派生，一条请求链上 ``evaluate_candidates`` 只跑一次。代价是 trend 不
再是 5ms 的裸 SQL，所以它也进了缓存。

## 2026-08：实盘项下线

``/api/review/equity|trips|positions|drift`` 连同其底层能力（资金曲线、往返归因、
持仓回放、回测-实盘偏离）一并删除——它们读真实成交 / 持仓，而复盘已改为只基于
「候选池 + 行情」算纸上收益。对应的实测行与缓存 scope 已从上表和名单里摘掉。
"""
from __future__ import annotations

import threading
from collections import OrderedDict
from typing import Any, Callable, Literal

from fastapi import APIRouter, HTTPException, Query

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
    ops_db: str | None = None,
) -> APIRouter:
    router = APIRouter()

    def _market():
        return market_store(market_db)

    def _palace():
        return palace_store(palace_db)

    def _cached_on(
        palace: Any,
        market: Any,
        scope: str,
        params: tuple,
        compute: Callable[[Any, Any], Any],
    ) -> Any:
        """在**已打开的连接上**按「候选池读模型指纹 + 行情版本号」缓存。

        拆出这一层是为了让 winrate 三兄弟（summary / trend / samples）共用一次
        ``evaluate_candidates``——它们都从同一批候选 T+N 结局派生，各自重算等于
        把 700ms 乘三。

        ``review_read_fingerprint()`` 必须是逐行摘要而不是 COUNT(*)：候选**等长
        改判**（行数不变、裁决变了）也得换键，否则这里会发陈数据。

        返回的是缓存里的同一个对象，调用方（FastAPI 的 JSON 编码）只读不改。
        """
        # 默认路径参数都是 None；缓存必须绑定实际连接的租户库，而不是这些参数。
        key = (scope, str(palace.db_path.resolve()), str(market.db_path.resolve()), params,
            palace.review_read_fingerprint(), market.market_revision())
        hit = _cache_get(key)
        if hit is not _MISS:
            return hit
        value = compute(palace, market)
        _cache_put(key, value)
        return value

    def _cached(scope: str, params: tuple, compute: Callable[[Any, Any], Any]) -> Any:
        """开连接 + 缓存。命中时仍读一次版本号（约 2ms），省掉几百毫秒的全量重算。"""
        with _palace() as palace, _market() as market:
            return _cached_on(palace, market, scope, params, compute)

    def _outcomes(
        palace: Any,
        market: Any,
        *,
        limit: int = 2000,
        benchmark: str | None = "000300",
    ) -> Any:
        """候选 T+N 结局：三个 winrate 端点共用的那一次重算。"""
        from src.review import evaluate_candidates

        return _cached_on(
            palace,
            market,
            "candidate_outcomes",
            (limit, benchmark),
            lambda p, m: evaluate_candidates(p, m, limit=limit, benchmark=benchmark),
        )

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
    def winrate_summary(
        current_only: bool = Query(default=False, description="仅当前工坊战法；保留无样本战法并返回目录名称"),
    ) -> list[dict[str, Any]]:
        """各战法胜率：精选候选 T+5 优先，手工复盘兜底。"""
        try:
            from src.review import build_winrate_summary
        except ImportError as exc:
            raise missing_dependency(exc) from exc

        def compute(palace, market):
            return build_winrate_summary(
                _outcomes(palace, market),
                palace.strategy_winrates(),
            )

        rows = _cached("winrate_summary", (), compute)
        if not current_only:
            return rows
        from src.strategy import describe_all
        from src.ops import OpsStore
        from src.review.application.workshop import enabled_workshop_catalog, workshop_winrates

        # 目录不进统计缓存：工坊改名/删除后，下次读取立刻反映，历史样本不删除。
        with OpsStore(ops_db) as store:
            catalog = enabled_workshop_catalog(describe_all(), store.list_jobs(enabled_only=True))
        return workshop_winrates(rows, catalog)

    @router.get("/api/winrate/trend", tags=["review"])
    def winrate_trend(
        granularity: Literal["month", "week"] = Query(default="month"),
        tags: str | None = Query(default=None, max_length=500),
    ) -> list[dict[str, Any]]:
        """分周期胜率，**与主表同口径**：精选候选 T+5 按选出日聚合。

        一条候选样本都没有时才回退手工 ``reviews``（返回行的 ``source`` 标明是哪一
        种）。两条路都可能为空——那种情况下页面上的「没有明细」才是真的没有样本，
        而不是像旧版那样口径挂错。
        """
        try:
            from src.review import winrate_periods
        except ImportError as exc:
            raise missing_dependency(exc) from exc

        tag_list = [t.strip() for t in tags.split(",") if t.strip()] if tags else None

        def compute(palace, market):
            rows = winrate_periods(
                _outcomes(palace, market),
                granularity=granularity,
                strategy_tags=tag_list,
            )
            if rows:
                return rows
            fallback = palace.winrate_trend(strategy_tags=tag_list, granularity=granularity)
            return [{**row, "avg_return": None, "source": "reviews"} for row in fallback]

        return _cached("winrate_trend", (granularity, tuple(tag_list or ())), compute)

    @router.get("/api/winrate/samples", tags=["review"])
    def winrate_samples(
        tag: str = Query(min_length=1, max_length=100, description="战法 slug"),
        horizon: int = Query(
            default=5,
            description="持有期；只认 evaluate_candidates 真算过的 1/3/5/10/20/60",
        ),
        limit: int = Query(default=300, ge=1, le=1000),
    ) -> dict[str, Any]:
        """某战法逐条样本：胜率的分母到底是哪几只票、哪天选出、各自涨跌多少。"""
        try:
            from src.review import HORIZONS
            from src.review import winrate_samples as build_samples
        except ImportError as exc:
            raise missing_dependency(exc) from exc

        if horizon not in HORIZONS:
            # Literal[int] 在 query 里不做 str→int 转换（pydantic v2 严格 literal），
            # 白名单只能在这里显式对 HORIZONS 校验，免得再抄一份持有期常量。
            raise HTTPException(status_code=422, detail=f"horizon 只支持 {list(HORIZONS)}")

        def compute(palace, market):
            return build_samples(
                _outcomes(palace, market),
                strategy_tag=tag,
                primary_horizon=horizon,
                limit=limit,
            )

        return _cached("winrate_samples", (tag, horizon, limit), compute)

    return router
