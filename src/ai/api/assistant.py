"""独立装配的全局助手 API；组合根决定是否挂载。"""
from __future__ import annotations

from collections.abc import Callable, Iterator
import json
from time import sleep
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, ConfigDict, Field

from src.ai.application.assistant_manager import AssistantManager
from src.ai.application.system_toolbus import build_system_toolbus
from src.ai.domain.assistant import AssistantError, AssistantUnavailableError
from src.ai.infrastructure.assistant_store import AssistantStore
from src.shared.paths import ops_db as default_ops_db


class _Model(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)


class AssistantSessionCreate(_Model):
    title: str = Field(default="", max_length=160)
    provider: str = Field(default="", max_length=80)
    model: str = Field(default="", max_length=160)
    metadata: dict[str, Any] = Field(default_factory=dict)


class AssistantSessionUpdate(_Model):
    title: str | None = Field(default=None, max_length=160)
    archived: bool | None = None


class AssistantRunCreate(_Model):
    message: str = Field(min_length=1, max_length=12_000)
    provider: str = Field(default="", max_length=80)
    model: str = Field(default="", max_length=160)


def build_assistant_router(
    *, write_dependency: Any, ops_db: str | None = None, palace_db: str | None = None,
    market_db: str | None = None, manager: AssistantManager | None = None,
    scheduler_reloader: Callable[[], None] | None = None,
) -> APIRouter:
    """返回未挂载 router。所有会话数据读取也沿用写鉴权，防止对话越权读取。"""
    router = APIRouter(tags=["ai-assistant"], dependencies=[Depends(write_dependency)])
    resolved_ops_db = str(ops_db or default_ops_db())
    active_manager = manager or AssistantManager(
        ops_db=resolved_ops_db,
        palace_db=palace_db,
        market_db=market_db,
        scheduler_reloader=scheduler_reloader,
    )

    def store() -> AssistantStore:
        return AssistantStore(resolved_ops_db)

    def fail(exc: AssistantError, *, missing: bool = False) -> HTTPException:
        status_code = 404 if missing else 503 if isinstance(exc, AssistantUnavailableError) else 422
        return HTTPException(status_code=status_code, detail=str(exc))

    def public_session(row: dict[str, Any]) -> dict[str, Any]:
        return {
            "id": row["id"],
            "title": row["title"],
            "status": "error" if row["status"] == "error" else row["status"],
            "provider": row["provider"],
            "model": row["model"],
            "updated_at": row["updated_at"],
        }

    def public_message(row: dict[str, Any]) -> dict[str, Any]:
        return {
            "id": row["id"],
            "role": row["role"],
            "content": row["content"],
            "created_at": row["created_at"],
        }

    def public_run(row: dict[str, Any]) -> dict[str, Any]:
        status_map = {"completed": "done", "failed": "error"}
        raw = str(row.get("status") or "")
        if raw in {"completed", "failed", "cancelled"}:
            status = status_map.get(raw, raw)
        elif raw == "waiting_user":
            status = "waiting_user"
        elif row.get("cancel_requested") and raw == "running":
            # 仅「仍在跑但已请求取消」对外报 cancelled；终态以 DB status 为准，避免 completed 被伪装。
            status = "cancelled"
        else:
            status = status_map.get(raw, raw)
        out: dict[str, Any] = {
            "id": row["id"],
            "session_id": row["session_id"],
            "status": status,
            "provider": row["provider"],
            "model": row["model"],
            "input_tokens": row["input_tokens"],
            "output_tokens": row["output_tokens"],
        }
        if "cursor" in row:
            out["cursor"] = row["cursor"]
        return out

    def enrich_run(db: AssistantStore, row: dict[str, Any]) -> dict[str, Any]:
        return {**row, "cursor": db.latest_event_id(str(row["id"]))}

    def public_event(row: dict[str, Any]) -> dict[str, Any]:
        return {"id": row["id"], "type": row["event_type"], "data": row["payload"]}

    def sse_event(row: dict[str, Any]) -> str:
        event = public_event(row)
        payload = json.dumps(event["data"], ensure_ascii=False, separators=(",", ":"))
        return f"id: {event['id']}\nevent: {event['type']}\ndata: {payload}\n\n"

    @router.get("/api/ai/sessions")
    def list_sessions(
        limit: int = Query(default=50, ge=1, le=500), include_archived: bool = False,
    ) -> list[dict[str, Any]]:
        with store() as db:
            return [public_session(row) for row in db.list_sessions(limit=limit, include_archived=include_archived)]

    @router.post("/api/ai/sessions", status_code=201)
    def create_session(payload: AssistantSessionCreate) -> dict[str, Any]:
        with store() as db:
            session_id = db.create_session(title=payload.title, provider=payload.provider, model=payload.model, metadata=payload.metadata)
            session = db.get_session(session_id)
            return public_session(session or {})

    @router.get("/api/ai/sessions/{session_id}")
    def get_session(session_id: str) -> dict[str, Any]:
        with store() as db:
            session = db.get_session(session_id)
            if session is None:
                raise fail(AssistantError("AI 会话不存在"), missing=True)
            detail = public_session(session)
            detail["messages"] = [public_message(row) for row in db.list_messages(session_id, limit=200)]
            active = db.get_active_run(session_id)
            detail["active_run"] = public_run(enrich_run(db, active)) if active is not None else None
            return detail

    @router.patch("/api/ai/sessions/{session_id}")
    def update_session(session_id: str, payload: AssistantSessionUpdate) -> dict[str, Any]:
        try:
            with store() as db:
                fields = payload.model_dump(exclude_none=True)
                archived = bool(fields.pop("archived", False))
                session = db.archive_session(session_id) if archived else db.update_session(session_id, **fields)
                return public_session(session)
        except AssistantError as exc:
            raise fail(exc, missing="不存在" in str(exc)) from exc

    @router.delete("/api/ai/sessions/{session_id}")
    def delete_session(session_id: str) -> dict[str, bool]:
        try:
            with store() as db:
                if not db.delete_session(session_id):
                    raise fail(AssistantError("AI 会话不存在"), missing=True)
        except AssistantError as exc:
            raise fail(exc, missing="不存在" in str(exc)) from exc
        return {"removed": True}

    @router.get("/api/ai/sessions/{session_id}/messages")
    def list_messages(
        session_id: str, after_seq: int = Query(default=0, ge=0), limit: int = Query(default=200, ge=1, le=500),
    ) -> list[dict[str, Any]]:
        with store() as db:
            if db.get_session(session_id) is None:
                raise fail(AssistantError("AI 会话不存在"), missing=True)
            return [public_message(row) for row in db.list_messages(session_id, after_seq=after_seq, limit=limit)]

    @router.post("/api/ai/sessions/{session_id}/messages", status_code=202)
    @router.post("/api/ai/sessions/{session_id}/runs", status_code=202, include_in_schema=False)
    def start_run(session_id: str, payload: AssistantRunCreate) -> dict[str, str]:
        try:
            return {"run_id": active_manager.start_run(session_id, message=payload.message, provider=payload.provider, model=payload.model)}
        except AssistantError as exc:
            raise fail(exc, missing="会话不存在" in str(exc)) from exc

    @router.get("/api/ai/runs/{run_id}")
    def get_run(run_id: str) -> dict[str, Any]:
        with store() as db:
            run = db.get_run(run_id)
            if run is None:
                raise fail(AssistantError("AI 运行不存在"), missing=True)
            return public_run(enrich_run(db, run))

    @router.get("/api/ai/runs/{run_id}/events")
    def poll_events(
        run_id: str, after: str = Query(default=""), limit: int = Query(default=200, ge=1, le=500),
    ) -> dict[str, Any]:
        with store() as db:
            if db.get_run(run_id) is None:
                raise fail(AssistantError("AI 运行不存在"), missing=True)
            events, cursor = db.poll_events_cursor(run_id, after=after, limit=limit)
            return {"events": [public_event(row) for row in events], "after": cursor}

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

        def stream() -> Iterator[str]:
            terminal_empty_polls = 0
            current = cursor
            with store() as db:
                while True:
                    events, current = db.poll_events_cursor(run_id, after=current, limit=limit)
                    terminal_event = False
                    for event in events:
                        yield sse_event(event)
                        terminal_event = terminal_event or event["event_type"] in {
                            "done", "error", "cancelled", "waiting_user",
                        }
                    if terminal_event:
                        return

                    run = db.get_run(run_id)
                    if run is None:
                        return
                    if run["status"] in {"completed", "failed", "cancelled", "waiting_user"} and not events:
                        terminal_empty_polls += 1
                        if terminal_empty_polls >= 4:
                            return
                    else:
                        terminal_empty_polls = 0
                    yield ": keepalive\n\n"
                    sleep(0.25)

        return StreamingResponse(
            stream(),
            media_type="text/event-stream",
            headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
        )

    @router.post("/api/ai/runs/{run_id}/cancel")
    def cancel_run(run_id: str) -> dict[str, Any]:
        if not active_manager.cancel_run(run_id):
            raise fail(AssistantError("AI 运行不存在或已结束"), missing=True)
        with store() as db:
            run = db.get_run(run_id)
            if run is None:
                return public_run(
                    {
                        "id": run_id,
                        "session_id": "",
                        "status": "cancelled",
                        "cancel_requested": True,
                        "provider": "",
                        "model": "",
                        "input_tokens": 0,
                        "output_tokens": 0,
                        "cursor": "",
                    }
                )
            return public_run(enrich_run(db, run))

    @router.get("/api/ai/tools")
    def tool_catalog() -> dict[str, Any]:
        from src.ops import OpsStore

        with OpsStore(resolved_ops_db) as ops:
            rows = ops.list_providers()
        providers = [
            {
                "name": str(row["name"]),
                "models": list(row.get("models") or []),
                "default_model": str(row.get("default_model") or ""),
                "is_active": bool(row.get("is_active")),
                "is_default": bool(row.get("is_default")),
            }
            for row in rows
            if row.get("is_active") and row.get("has_key")
        ]
        return {
            "provider_configured": bool(providers),
            "providers": providers,
            "tools": build_system_toolbus(
                palace_db=palace_db,
                market_db=market_db,
                ops_db=resolved_ops_db,
                scheduler_reloader=scheduler_reloader,
            ).catalog(),
        }

    return router
