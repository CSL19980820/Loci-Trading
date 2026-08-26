r"""AI 运行事件的 SSE 跟随流。

从 `assistant.py` 拆出来:那个文件是「助手 API 的全部端点」,而这条流有自己的
一套并发约束(线程池令牌、SQLite 连接不得横跨 await),混在一起两头都读不清,
而且会把 assistant.py 顶过 600 行门禁。
"""
from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator, Callable
from typing import Any

from fastapi import APIRouter, Query, Request
from fastapi.concurrency import run_in_threadpool
from fastapi.responses import StreamingResponse

from src.ai.domain.assistant import AssistantError
from src.ai.infrastructure.assistant_store_lifecycle import TERMINAL_EVENT_TYPES


def register_stream_route(
    router: APIRouter,
    *,
    store: Callable[[], Any],
    sse_event: Callable[[dict[str, Any]], str],
    fail: Callable[..., Exception],
) -> None:
    """把 SSE 端点挂上 router。依赖由 assistant.py 注入,保持闭包语义不变。"""
    @router.get("/api/ai/runs/{run_id}/events/stream")
    def stream_events(
        run_id: str,
        request: Request,
        after: str = Query(default=""),
        limit: int = Query(default=200, ge=1, le=500),
    ) -> StreamingResponse:
        """重放并跟随已持久化的运行事件，不改变 JSON 轮询接口。"""
        cursor = after.strip() or request.headers.get("last-event-id", "").strip()
        with store() as db:
            if db.get_run(run_id) is None:
                raise fail(AssistantError("AI 运行不存在"), missing=True)

        def poll_once(cursor_value: str) -> dict[str, Any]:
            """一轮 DB 取数。**必须整块在线程里跑完再回来 yield**——

            生成器里边持库边 yield 的话,SQLite 连接会横跨 await 点,
            而 `store()` 是短开短关的单连接语义。
            """
            with store() as db:
                events, next_cursor = db.poll_events_cursor(
                    run_id, after=cursor_value, limit=limit
                )
                run = db.get_run(run_id)
                status_value = str(run["status"]) if run is not None else ""
                terminal_row = (
                    db.has_terminal_event(run_id)
                    if status_value in {"completed", "failed", "cancelled", "waiting_user"}
                    else False
                )
            return {
                "events": events,
                "cursor": next_cursor,
                "gone": run is None,
                "status": status_value,
                "terminal_row": terminal_row,
            }

        async def stream() -> AsyncIterator[str]:
            """异步生成器 + `run_in_threadpool`。

            这里**曾经是同步生成器 + `time.sleep(0.25)`**。Starlette 对同步迭代器
            走 `iterate_in_threadpool`,每次 `next()` 都占一个 AnyIO 线程池令牌,
            而 sleep 正好落在 `next()` 内部——于是每条流几乎全程占着一个令牌。
            该线程池默认只有 **40** 个令牌,且被全仓所有 `def` 端点共用
            (本仓端点 100% 是 `def`)。实测 45 条并发流会让无关端点 `/api/health`
            的时延从 2ms 劣化到 31ms(18 倍)。

            改成异步之后,等待期间不占任何线程,只有真正读库的那一小段才借线程。
            """
            terminal_empty_polls = 0
            current = cursor
            while True:
                if await request.is_disconnected():
                    # 客户端已经走了就别再轮询——旧实现只有等到终态才收手。
                    return
                snapshot = await run_in_threadpool(poll_once, current)
                current = snapshot["cursor"]
                events = snapshot["events"]
                terminal_event = False
                for event in events:
                    yield sse_event(event)
                    terminal_event = (
                        terminal_event or event["event_type"] in TERMINAL_EVENT_TYPES
                    )
                if terminal_event:
                    return
                if snapshot["gone"]:
                    return
                run_status = snapshot["status"]
                # completed 但 done 尚未落库(例如标题 LLM 插队的历史竞态):继续等,勿提前关流
                if run_status in {"completed", "failed", "cancelled", "waiting_user"} and not events:
                    if not snapshot["terminal_row"]:
                        terminal_empty_polls = 0
                    else:
                        terminal_empty_polls += 1
                        if terminal_empty_polls >= 4:
                            return
                else:
                    terminal_empty_polls = 0
                yield ": keepalive\n\n"
                await asyncio.sleep(0.25)

        return StreamingResponse(
            stream(),
            media_type="text/event-stream",
            headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
        )
