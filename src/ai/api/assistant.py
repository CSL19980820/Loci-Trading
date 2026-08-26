"""独立装配的全局助手 API；组合根决定是否挂载。"""
from __future__ import annotations

from collections.abc import Callable
import json
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from pydantic import BaseModel, ConfigDict, Field, model_validator

from src.ai.application.assistant_manager import AssistantManager
from src.ai.application.assistant_rich_state import public_rich_fields
from src.ai.application.assistant_session_title import lock_manual_title
from src.ai.api.assistant_stream import register_stream_route
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


class AssistantSessionBatch(_Model):
    action: str = Field(pattern="^(archive|unarchive|delete)$")
    ids: list[str] = Field(min_length=1, max_length=100)


class AssistantProfileUpdate(_Model):
    about_user: str | None = Field(default=None, max_length=2000)
    response_style: str | None = Field(default=None, max_length=4000)
    rules: list[str] | None = None
    memory_enabled: bool | None = None
    auto_memory_enabled: bool | None = None
    auto_memory_min_turns: int | None = Field(default=None, ge=5, le=100)


class AssistantMemoryCreate(_Model):
    target: str = Field(pattern="^(user|memory)$")
    content: str = Field(min_length=1, max_length=4000)


class AssistantMemoryUpdate(_Model):
    target: str | None = Field(default=None, pattern="^(user|memory)$")
    content: str | None = Field(default=None, min_length=1, max_length=4000)


class AssistantMemoryDocument(_Model):
    target: str = Field(pattern="^(user|memory)$")
    content: str = Field(default="", max_length=4000)


class AssistantRunCreate(_Model):
    message: str = Field(default="", max_length=12_000)
    provider: str = Field(default="", max_length=80)
    model: str = Field(default="", max_length=160)
    thinking: str = Field(default="", max_length=16)
    images: list[str] = Field(default_factory=list, max_length=4)
    skill_slug: str = Field(default="", max_length=80)

    @model_validator(mode="after")
    def _require_text_or_images(self) -> AssistantRunCreate:
        if not self.message.strip() and not self.images:
            raise ValueError("消息不能为空")
        return self


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
        out: dict[str, Any] = {
            "id": row["id"],
            "role": row["role"],
            "content": row["content"],
            "created_at": row["created_at"],
        }
        # ADR-006：thinking / tool_receipts / artifacts / warnings 来自 metadata_json
        meta = row.get("metadata") if isinstance(row.get("metadata"), dict) else {}
        out.update(public_rich_fields(meta))
        # Hermes/OpenClaw：空终稿失败对外标 error，避免 sync 后伪装成普通 done
        if str(row.get("role") or "") == "assistant":
            stopped = str(meta.get("stopped_reason") or "")
            if stopped == "empty_completion" or stopped.startswith("llm_error"):
                out["status"] = "error"
        return out

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
        # HITL：waiting_user 时把 pending_ask 暴露给前端恢复 ConfirmCard 选项
        result = row.get("result") if isinstance(row.get("result"), dict) else {}
        pending_ask = result.get("pending_ask") if isinstance(result, dict) else None
        if isinstance(pending_ask, dict) and (
            pending_ask.get("prompt")
            or pending_ask.get("options")
            or pending_ask.get("questions")
        ):
            out["pending_ask"] = {
                "prompt": str(pending_ask.get("prompt") or "").strip(),
                "options": [
                    str(item)
                    for item in (pending_ask.get("options") or [])
                    if str(item).strip()
                ]
                if isinstance(pending_ask.get("options"), list)
                else [],
            }
            questions = pending_ask.get("questions")
            if isinstance(questions, list) and questions:
                cleaned_questions: list[dict[str, Any]] = []
                for item in questions[:8]:
                    if not isinstance(item, dict):
                        continue
                    qid = str(item.get("id") or "").strip()
                    qprompt = str(item.get("prompt") or "").strip()
                    if not qid or not qprompt:
                        continue
                    qrow: dict[str, Any] = {"id": qid, "prompt": qprompt}
                    qopts = item.get("options")
                    if isinstance(qopts, list):
                        cleaned_opts = [str(o).strip() for o in qopts if str(o).strip()]
                        if cleaned_opts:
                            qrow["options"] = cleaned_opts
                    if item.get("allow_free_text") is True:
                        qrow["allow_free_text"] = True
                    cleaned_questions.append(qrow)
                if cleaned_questions:
                    out["pending_ask"]["questions"] = cleaned_questions
            risk = str(pending_ask.get("risk") or "").strip()
            if risk:
                out["pending_ask"]["risk"] = risk
        return out

    def enrich_run(db: AssistantStore, row: dict[str, Any]) -> dict[str, Any]:
        return {**row, "cursor": db.latest_event_id(str(row["id"]))}

    def public_event(row: dict[str, Any]) -> dict[str, Any]:
        return {"id": row["id"], "type": row["event_type"], "data": row["payload"]}

    def sse_event(row: dict[str, Any]) -> str:
        event = public_event(row)
        payload = json.dumps(event["data"], ensure_ascii=False, separators=(",", ":"))
        return f"id: {event['id']}\nevent: {event['type']}\ndata: {payload}\n\n"

    def public_memory(row: dict[str, Any]) -> dict[str, Any]:
        return {
            "id": row["id"],
            "target": row["target"],
            "content": row["content"],
            "source": row["source"],
            "created_at": row["created_at"],
            "updated_at": row["updated_at"],
        }

    def public_profile(row: dict[str, Any]) -> dict[str, Any]:
        return {
            "about_user": row.get("about_user") or "",
            "response_style": row.get("response_style") or "",
            "rules": list(row.get("rules") or []),
            "memory_enabled": bool(row.get("memory_enabled", True)),
            "auto_memory_enabled": bool(row.get("auto_memory_enabled", True)),
            "auto_memory_min_turns": int(row.get("auto_memory_min_turns") or 20),
            "updated_at": row.get("updated_at") or "",
            "memory_usage": row.get("memory_usage") or {},
        }

    @router.get("/api/ai/sessions")
    def list_sessions(
        limit: int = Query(default=50, ge=1, le=500),
        include_archived: bool = False,
        archived_only: bool = False,
    ) -> list[dict[str, Any]]:
        try:
            with store() as db:
                return [
                    public_session(row)
                    for row in db.list_sessions(
                        limit=limit,
                        include_archived=include_archived,
                        archived_only=archived_only,
                    )
                ]
        except AssistantError as exc:
            raise fail(exc) from exc

    @router.post("/api/ai/sessions", status_code=201)
    def create_session(payload: AssistantSessionCreate) -> dict[str, Any]:
        with store() as db:
            session_id = db.create_session(title=payload.title, provider=payload.provider, model=payload.model, metadata=payload.metadata)
            session = db.get_session(session_id)
            return public_session(session or {})

    @router.post("/api/ai/sessions/batch")
    def batch_sessions(payload: AssistantSessionBatch) -> dict[str, Any]:
        try:
            with store() as db:
                return db.batch_sessions(action=payload.action, ids=payload.ids)
        except AssistantError as exc:
            raise fail(exc) from exc

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
                if "archived" in fields:
                    archived = bool(fields.pop("archived"))
                    session = db.archive_session(session_id) if archived else db.unarchive_session(session_id)
                    if "title" in fields:
                        session = lock_manual_title(db, session_id, str(fields["title"]))
                    elif fields:
                        session = db.update_session(session_id, **fields)
                elif "title" in fields:
                    session = lock_manual_title(db, session_id, str(fields["title"]))
                else:
                    session = db.update_session(session_id, **fields)
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

    @router.get("/api/ai/profile")
    def get_profile() -> dict[str, Any]:
        with store() as db:
            profile = db.get_profile()
            profile["memory_usage"] = {
                "user": db.memory_char_usage("user"),
                "memory": db.memory_char_usage("memory"),
            }
            return public_profile(profile)

    @router.put("/api/ai/profile")
    def put_profile(payload: AssistantProfileUpdate) -> dict[str, Any]:
        try:
            with store() as db:
                profile = db.update_profile(**payload.model_dump(exclude_none=True))
                profile["memory_usage"] = {
                    "user": db.memory_char_usage("user"),
                    "memory": db.memory_char_usage("memory"),
                }
                return public_profile(profile)
        except AssistantError as exc:
            raise fail(exc) from exc

    @router.post("/api/ai/profile/reset-defaults")
    def reset_profile_defaults() -> dict[str, Any]:
        """恢复产品默认规则与回答偏好；保留「关于你」；幂等写入 builtin 工作记忆。"""
        with store() as db:
            profile = db.reset_to_product_defaults(keep_about_user=True)
            profile["memory_usage"] = {
                "user": db.memory_char_usage("user"),
                "memory": db.memory_char_usage("memory"),
            }
            return public_profile(profile)

    @router.get("/api/ai/memories")
    def list_memories(target: str | None = Query(default=None)) -> list[dict[str, Any]]:
        try:
            with store() as db:
                return [public_memory(row) for row in db.list_memories(target=target)]
        except AssistantError as exc:
            raise fail(exc) from exc

    @router.put("/api/ai/memories/document")
    def put_memory_document(payload: AssistantMemoryDocument) -> dict[str, Any]:
        """整仓替换为一篇 Markdown 文档（设置页用）。"""
        try:
            with store() as db:
                result = db.set_memory_document(payload.target, payload.content, source="manual")
                item = result.get("item")
                return {
                    "target": result["target"],
                    "content": result["content"],
                    "usage": result["usage"],
                    "item": public_memory(item) if item else None,
                }
        except AssistantError as exc:
            raise fail(exc) from exc

    @router.post("/api/ai/memories", status_code=201)
    def create_memory(payload: AssistantMemoryCreate) -> dict[str, Any]:
        try:
            with store() as db:
                return public_memory(
                    db.add_memory(target=payload.target, content=payload.content, source="manual")
                )
        except AssistantError as exc:
            raise fail(exc) from exc

    @router.patch("/api/ai/memories/{memory_id}")
    def patch_memory(memory_id: str, payload: AssistantMemoryUpdate) -> dict[str, Any]:
        try:
            with store() as db:
                return public_memory(
                    db.update_memory(
                        memory_id,
                        content=payload.content,
                        target=payload.target,
                    )
                )
        except AssistantError as exc:
            raise fail(exc, missing="不存在" in str(exc)) from exc

    @router.delete("/api/ai/memories/{memory_id}")
    def remove_memory(memory_id: str) -> dict[str, bool]:
        try:
            with store() as db:
                if not db.delete_memory(memory_id):
                    raise fail(AssistantError("记忆不存在"), missing=True)
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

    @router.post("/api/ai/sessions/{session_id}/compact")
    def compact_session(session_id: str) -> dict[str, Any]:
        """手动压缩喂模上下文（Cursor /compact）；不删库内原文。"""
        try:
            return active_manager.compact_session(session_id)
        except AssistantError as exc:
            raise fail(exc, missing="会话不存在" in str(exc)) from exc

    @router.post("/api/ai/sessions/{session_id}/messages", status_code=202)
    @router.post("/api/ai/sessions/{session_id}/runs", status_code=202, include_in_schema=False)
    def start_run(session_id: str, payload: AssistantRunCreate) -> dict[str, str]:
        try:
            return {
                "run_id": active_manager.start_run(
                    session_id,
                    message=payload.message,
                    provider=payload.provider,
                    model=payload.model,
                    thinking=payload.thinking,
                    images=payload.images,
                    skill_slug=payload.skill_slug,
                )
            }
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

    register_stream_route(router, store=store, sse_event=sse_event, fail=fail)


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
                "model_catalog": [
                    {
                        "id": str(item.get("id") or ""),
                        "name": str(item.get("name") or item.get("id") or ""),
                        "context_window": item.get("context_window"),
                        "enabled": bool(item.get("enabled", True)),
                    }
                    for item in (row.get("model_catalog") or [])
                    if isinstance(item, dict) and str(item.get("id") or "").strip()
                ],
                "default_model": str(row.get("default_model") or ""),
                "is_active": bool(row.get("is_active")),
                "is_default": bool(row.get("is_default")),
            }
            for row in rows
            if row.get("is_active") and row.get("has_key")
        ]
        from src.ai.application.context_usage import estimate_tokens
        from src.ai.domain.assistant import assistant_system_prompt

        return {
            "provider_configured": bool(providers),
            "providers": providers,
            "system_prompt_tokens": estimate_tokens(assistant_system_prompt()),
            "tools": build_system_toolbus(
                palace_db=palace_db,
                market_db=market_db,
                ops_db=resolved_ops_db,
                scheduler_reloader=scheduler_reloader,
            ).catalog(),
        }

    return router
