"""实时行情 / 实时信号的 SSE 端点。

并发范式**逐行照抄** ``src/ai/api/assistant_stream.py``（全仓唯一被实测验证过的
SSE 实现）：``async def`` 生成器 + ``Last-Event-ID`` + ``: keepalive`` +
``request.is_disconnected()`` + ``await asyncio.sleep(...)``。

**为什么这里连 ``run_in_threadpool`` 都尽量不用**：那份文件记着一次事故——
同步生成器走 Starlette 的 ``iterate_in_threadpool``，每次 ``next()`` 占一个 AnyIO
线程池令牌，sleep 又正好落在 ``next()`` 里，于是每条流几乎全程占着令牌；池子
默认只有 40 个且被全仓 ``def`` 端点共用，实测 45 条并发流把 ``/api/health`` 从
2ms 拖到 31ms。**把 ``Subscription.wait()`` 包进 ``run_in_threadpool`` 会原样
复刻这个事故**——它是阻塞的 Condition 等待，一样全程占令牌。所以推流侧改成
读 ``hub.latest()``（纯内存 dict 读）+ ``asyncio.sleep``，等待期间零线程占用；
只有**真的要算指标**（信号引擎跑 pandas）时才借一小段线程。

**大屏对行情库是纯读路径**：这三个端点不写 ``market.db``、不需要写鉴权。

**唯一的写：ops.db 的 ``signal_journal``。** 算出信号之后顺手落一条日志（用户
需求 5：历史面板 + 7 天 / 80 条保留策略）。它写的是**运维库**，不是行情库，
与上面那条铁律不冲突——详见 ``application/realtime_signals.py`` 的模块 docstring
第 1 条。写入点放在这里而不是引擎里，是为了让引擎保持纯函数（进快照、出信号
列表），也让「谁负责落库」只有一处答案。

落库失败**永远不阻断推流**：日志坏了顶多丢复盘能力，不能把大屏一起带走。
"""
from __future__ import annotations

import asyncio
from collections import OrderedDict
from collections.abc import AsyncIterator
import json
import logging
import threading
import time
from typing import Any, Callable

from fastapi import APIRouter, HTTPException, Query, Request
from fastapi.concurrency import run_in_threadpool
from fastapi.responses import StreamingResponse

from src.market.application.live_hub import Snapshot, get_live_hub
from src.market.application.realtime_signals import get_signal_engine
from src.market.application.watchlist import ALL_PRESETS, MAX_PRESET_CODES
from src.shared.tenancy import current_tenant

logger = logging.getLogger(__name__)

#: 轮询共享快照的间隔。与 assistant_stream 的 0.25s 对齐。
POLL_SECONDS = 0.25
#: 无新帧时的注释心跳间隔；只是防中间层掐连接，不是数据。
HEARTBEAT_SECONDS = 15.0
#: 信号结果按 (feed key, seq) 缓存的条数。
_SIGNAL_CACHE_MAX = 32

_SIGNAL_LOCK = threading.Lock()
_SIGNAL_CACHE: "OrderedDict[tuple[str, int], list[dict[str, Any]]]" = OrderedDict()


def _sse(event: str, data: dict[str, Any], *, event_id: int | None = None) -> str:
    head = f"id: {event_id}\n" if event_id is not None else ""
    body = json.dumps(data, ensure_ascii=False, default=str)
    return f"{head}event: {event}\ndata: {body}\n\n"


def _parse_codes(raw: str) -> list[str]:
    items = [part.strip() for part in str(raw or "").split(",") if part.strip()]
    return items[:MAX_PRESET_CODES]


def _cursor(request: Request, after: int) -> int:
    """``after`` 优先，其次 ``Last-Event-ID``（断线重连时浏览器自动带上）。"""
    if after > 0:
        return int(after)
    raw = request.headers.get("last-event-id", "").strip()
    try:
        return max(0, int(raw))
    except ValueError:
        return 0


def _contract_row(row: dict[str, Any]) -> dict[str, Any]:
    """补齐对外契约里的 ``code`` 字段。

    适配器内部把标的标识叫 ``symbol``；对外 SSE 契约（前端与文档）用 ``code``。
    在 API 层补而不是改适配器：``symbol`` 是行情域的既有词汇，全仓上百处在用，
    为一个传输层字段名去改它得不偿失。两个键都留着，老消费者不受影响。
    """
    if "code" in row or "symbol" not in row:
        return row
    return {**row, "code": row["symbol"]}


def _quote_payload(preset: str, snapshot: Snapshot) -> dict[str, Any]:
    rows = [_contract_row(row) for row in snapshot.rows]
    return {
        "seq": snapshot.seq,
        "preset": preset,
        "as_of": snapshot.as_of,
        "source": snapshot.source,
        "count": len(rows),
        "rows": rows,
        "session": snapshot.session,
    }


def _status_payload(hub: Any, preset: str, codes: list[str]) -> dict[str, Any]:
    """``hello`` / ``heartbeat`` 的载荷：**没有行情时唯一说得出真相的那一帧**。

    连上就先发一次 ``hello``：不然在上游挂掉的那几个小时里，前端连「现在是不是
    开着盘」都不知道——它只能等第一帧，而第一帧永远不来。之后每 15s 的心跳把
    ``: keepalive`` 注释换成同一形状的数据帧，链路活着但数据源没喂上来时，
    界面才有底气说「数据源无更新」而不是继续假装实时。
    """
    try:
        return dict(hub.feed_status(preset, codes or None))
    except Exception as exc:  # pragma: no cover - 自述失败不许带走推流
        logger.warning("feed 自述失败（%s）：%s", preset, exc)
        return {"preset": preset, "session": {}, "stale_ms": -1, "source_error": str(exc)}


def journal_signals(signals: list[dict[str, Any]]) -> int:
    """把本轮新信号落进 ops.db 的 ``signal_journal``，返回真正新增的条数。

    **保留策略（7 天 / 每租户 80 条）由 ``append_signal_journal`` 顺带执行**，这里
    不需要也不应该再管一遍；两个阈值是 ``store_signals`` 的模块常量。

    去重有两道，各管各的：引擎的内存去抖管「同一天别刷屏」，这里的确定性主键管
    「进程重启后别重复落一行」。内存那道一重启就没了，所以两道都不能省。

    租户从 ``current_tenant()`` 取。调用点在 ``run_in_threadpool`` 里，anyio 会复制
    Context，所以租户是跟得过来的（裸 ``threading.Thread`` 就不行，见 tenancy）。
    """
    if not signals:
        return 0
    from src.ops import OpsStore

    with OpsStore() as store:
        result = store.append_signal_journal(signals, tenant=current_tenant())
    return int(result.get("inserted") or 0)


def _evaluate_once(
    engine: Any,
    key: str,
    snapshot: Snapshot,
    journal: Callable[[list[dict[str, Any]]], Any] | None = None,
) -> list[dict[str, Any]]:
    """同一 (feed, seq) 只算一次，N 个订阅者共享结果。

    不共享的话，引擎的去抖会让**第一个**客户端吃掉信号、其余客户端永远收不到。
    锁在这里是必要的串行点，且整个调用已经在 ``run_in_threadpool`` 的线程里。

    落库也只发生在**算的那一次**（缓存命中就直接返回），所以 N 个订阅者不会把同
    一帧信号写 N 遍——哪怕写了，确定性主键也会把它们压回一行。
    """
    cache_key = (key, snapshot.seq)
    with _SIGNAL_LOCK:
        hit = _SIGNAL_CACHE.get(cache_key)
        if hit is not None:
            return hit
        # 信号引擎按 `code` 过滤行；hub 的行来自适配器，键是 `symbol`。
        # 不补这一步，evaluate 会拿到空列表，信号流永远静默（且不报错）。
        signals = engine.evaluate([_contract_row(row) for row in snapshot.rows])
        _SIGNAL_CACHE[cache_key] = signals
        while len(_SIGNAL_CACHE) > _SIGNAL_CACHE_MAX:
            _SIGNAL_CACHE.popitem(last=False)
    write = journal_signals if journal is None else journal
    try:
        write(signals)
    except Exception as exc:
        # 日志落不下去不许影响推流：大屏是主线，历史是副产品。
        logger.warning("信号日志落库失败（本轮 %d 条，仅记日志）：%s", len(signals), exc)
    return signals


def build_market_stream_router(
    *,
    write_dependency: Callable[..., Any],
    market_db: str | None = None,
    hub_factory: Callable[[], Any] | None = None,
    engine_factory: Callable[[], Any] | None = None,
    journal_writer: Callable[[list[dict[str, Any]]], Any] | None = None,
) -> APIRouter:
    """大屏推流路由。``write_dependency`` / ``market_db`` 只为对齐工厂签名——

    这三个端点对**行情库**是纯读路径，不需要写鉴权；唯一的写是 ops.db 的信号
    日志（见模块 docstring）。``*_factory`` / ``journal_writer`` 供测试注入。
    """
    _ = (write_dependency, market_db)
    router = APIRouter()
    _hub = hub_factory or get_live_hub
    _engine = engine_factory or get_signal_engine

    def _validate(preset: str) -> str:
        name = str(preset or "").strip().lower()
        if name not in ALL_PRESETS:
            raise HTTPException(
                status_code=422,
                detail=f"未知 preset：{preset!r}（可选 {', '.join(ALL_PRESETS)}）",
            )
        return name

    @router.get("/api/market/stream/quotes", tags=["market"])
    def stream_quotes(
        request: Request,
        preset: str = Query(default="index", max_length=32),
        codes: str = Query(default="", max_length=4000),
        top_n: int = Query(default=50, ge=1, le=MAX_PRESET_CODES),
        after: int = Query(default=0, ge=0),
        events: int = Query(default=0, ge=0, le=10000, description="发满 N 帧就收流；0=不限"),
    ) -> StreamingResponse:
        """共享快照推流。event: ``snapshot``；``id`` 是单调递增的 ``seq``。"""
        name = _validate(preset)
        wanted = _parse_codes(codes)
        start_at = _cursor(request, after)
        hub = _hub()

        async def stream() -> AsyncIterator[str]:
            subscription = hub.subscribe(name, wanted or None, top_n=top_n, after=start_at)
            cursor, sent, beat = start_at, 0, time.monotonic()
            try:
                # 先报到再等数据：会话相位与数据源现状不该等到第一帧才有。
                yield _sse("hello", _status_payload(hub, name, wanted))
                while True:
                    if await request.is_disconnected():
                        return
                    # 纯内存读：不借线程，等待期间不占任何 AnyIO 令牌。
                    snapshot = hub.latest(name, wanted or None)
                    if snapshot is not None and snapshot.seq > cursor:
                        cursor = snapshot.seq
                        yield _sse("snapshot", _quote_payload(name, snapshot), event_id=cursor)
                        sent += 1
                        beat = time.monotonic()
                        if events and sent >= events:
                            return
                    elif time.monotonic() - beat >= HEARTBEAT_SECONDS:
                        beat = time.monotonic()
                        yield _sse("heartbeat", _status_payload(hub, name, wanted))
                    await asyncio.sleep(POLL_SECONDS)
            finally:
                subscription.close()

        return StreamingResponse(
            stream(),
            media_type="text/event-stream",
            headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
        )

    @router.get("/api/market/stream/signals", tags=["market"])
    def stream_signals(
        request: Request,
        preset: str = Query(default="index", max_length=32),
        codes: str = Query(default="", max_length=4000),
        top_n: int = Query(default=50, ge=1, le=MAX_PRESET_CODES),
        after: int = Query(default=0, ge=0),
        events: int = Query(default=0, ge=0, le=10000, description="发满 N 帧就收流；0=不限"),
    ) -> StreamingResponse:
        """实时信号推流。event: ``signals``；每条信号都带 ``provisional: true``。"""
        name = _validate(preset)
        wanted = _parse_codes(codes)
        start_at = _cursor(request, after)
        hub, engine = _hub(), _engine()

        async def stream() -> AsyncIterator[str]:
            subscription = hub.subscribe(name, wanted or None, top_n=top_n, after=start_at)
            cursor, sent, beat = start_at, 0, time.monotonic()
            try:
                # 同行情流：先报到。信号栏空着的时候，用户要的是「为什么空」。
                yield _sse("hello", _status_payload(hub, name, wanted))
                while True:
                    if await request.is_disconnected():
                        return
                    snapshot = hub.latest(name, wanted or None)
                    if snapshot is None or snapshot.seq <= cursor:
                        if time.monotonic() - beat >= HEARTBEAT_SECONDS:
                            beat = time.monotonic()
                            yield _sse("heartbeat", _status_payload(hub, name, wanted))
                        await asyncio.sleep(POLL_SECONDS)
                        continue
                    cursor = snapshot.seq
                    # 只有「真的要算」时才借线程：pandas 指标是 CPU 活，不能占着事件
                    # 循环；顺带的信号落库（sqlite 写）同理，也必须在这条线程里。
                    signals = await run_in_threadpool(
                        _evaluate_once, engine, subscription.key, snapshot, journal_writer
                    )
                    beat = time.monotonic()
                    yield _sse(
                        "signals",
                        {
                            "seq": cursor,
                            "preset": name,
                            "as_of": snapshot.as_of,
                            "count": len(signals),
                            "provisional": True,
                            "signals": signals,
                        },
                        event_id=cursor,
                    )
                    sent += 1
                    if events and sent >= events:
                        return
                    await asyncio.sleep(POLL_SECONDS)
            finally:
                subscription.close()

        return StreamingResponse(
            stream(),
            media_type="text/event-stream",
            headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
        )

    @router.get("/api/market/stream/stats", tags=["market"])
    def stream_stats() -> dict[str, Any]:
        """采集器自述：订阅数 / tick 数 / 最近耗时 / 错误数 + 规则表。普通 JSON。"""
        payload = dict(_hub().stats())
        payload["signals"] = _engine().stats()
        payload["presets"] = list(ALL_PRESETS)
        payload["poll_seconds"] = POLL_SECONDS
        return payload

    return router


__all__ = ["build_market_stream_router", "journal_signals"]
