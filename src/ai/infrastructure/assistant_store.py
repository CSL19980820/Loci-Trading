"""AI 会话在 ops.db 的可清理持久化。

实现拆分（同目录，沿用同一套 `assistant_store_*` 命名）：
- `assistant_store_util` — 脱敏 / JSON / 哈希 / 时钟等共享小工具
- `assistant_store_schema` — 六张表的建表 DDL 常量
- `assistant_store_lifecycle` — run 生命周期 mixin（取消 / HITL 等待 / 中断恢复 / 收口）
- `assistant_store_profile` — 画像与双仓记忆 mixin（含自己的 schema 补建）
- `assistant_store_grants` — ExecutionGrant mixin（签发 / 消费 / 收口）

本文件是门面：连接与事务，以及会话 / 消息 / run / 事件 / 用量的直接读写。
"""
from __future__ import annotations

from contextlib import contextmanager
from datetime import date
from pathlib import Path
import sqlite3
from typing import Any, Iterator
from uuid import uuid4

from src.ai.domain.assistant import AssistantError
from src.ai.infrastructure.assistant_store_grants import AssistantStoreGrantsMixin
from src.ai.infrastructure.assistant_store_lifecycle import AssistantStoreLifecycleMixin
from src.ai.infrastructure.assistant_store_profile import AssistantStoreProfileMixin
from src.ai.infrastructure.assistant_store_schema import ASSISTANT_SCHEMA_DDL
from src.ai.infrastructure.assistant_store_util import _dump, _hash, _load, _now, redact


class AssistantStore(
    AssistantStoreGrantsMixin,
    AssistantStoreLifecycleMixin,
    AssistantStoreProfileMixin,
):
    """会话、消息、运行事件、画像记忆及用量。每个线程使用自己的 Store 实例。"""

    def __init__(self, db_path: str | Path | None) -> None:
        if not db_path:
            raise AssistantError("未配置 ops.db，无法保存 AI 会话")
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self.conn = sqlite3.connect(self.db_path, timeout=15, check_same_thread=False)
        self.conn.row_factory = sqlite3.Row
        self.conn.execute("PRAGMA foreign_keys = ON")
        self.conn.execute("PRAGMA busy_timeout = 15000")
        self._init_schema()

    def close(self) -> None:
        self.conn.close()

    def __enter__(self) -> AssistantStore:
        return self

    def __exit__(self, exc_type: object, exc: object, tb: object) -> None:
        self.close()

    @contextmanager
    def _tx(self) -> Iterator[sqlite3.Cursor]:
        cursor = self.conn.cursor()
        try:
            cursor.execute("BEGIN IMMEDIATE")
            yield cursor
        except BaseException:
            self.conn.rollback()
            raise
        else:
            self.conn.commit()
        finally:
            cursor.close()

    def _init_schema(self) -> None:
        with self.conn:
            self.conn.executescript(ASSISTANT_SCHEMA_DDL)
            self._ensure_profile_schema(self.conn)

    def create_session(
        self, *, title: str = "", provider: str = "", model: str = "", metadata: dict[str, Any] | None = None
    ) -> str:
        session_id = f"AIS-{uuid4().hex[:16].upper()}"
        now = _now()
        with self._tx() as cur:
            cur.execute(
                "INSERT INTO ai_sessions(id,title,status,provider,model,metadata_json,created_at,updated_at)"
                " VALUES(?,?, 'idle', ?,?,?,?,?)",
                (session_id, title.strip()[:160], provider.strip(), model.strip(), _dump(redact(metadata)), now, now),
            )
        return session_id

    def get_session(self, session_id: str) -> dict[str, Any] | None:
        row = self.conn.execute("SELECT * FROM ai_sessions WHERE id = ?", (session_id,)).fetchone()
        return self._session(row) if row else None

    def list_sessions(
        self,
        *,
        limit: int = 50,
        include_archived: bool = False,
        archived_only: bool = False,
    ) -> list[dict[str, Any]]:
        if not 1 <= limit <= 500:
            raise AssistantError("limit 必须在 1-500 之间")
        if include_archived and archived_only:
            raise AssistantError("include_archived 与 archived_only 不能同时为真")
        sql = "SELECT * FROM ai_sessions"
        args: list[Any] = []
        if archived_only:
            sql += " WHERE status = 'archived'"
        elif not include_archived:
            sql += " WHERE status <> 'archived'"
        sql += " ORDER BY updated_at DESC, id DESC LIMIT ?"
        args.append(limit)
        return [self._session(row) for row in self.conn.execute(sql, args)]

    def update_session(self, session_id: str, **fields: Any) -> dict[str, Any]:
        allowed = {"title", "provider", "model", "metadata", "status", "last_error"}
        unknown = set(fields) - allowed
        if unknown:
            raise AssistantError(f"不支持的会话字段：{sorted(unknown)}")
        if not fields:
            session = self.get_session(session_id)
            if session is None:
                raise AssistantError("AI 会话不存在")
            return session
        assignments: list[str] = []
        values: list[Any] = []
        for name, value in fields.items():
            column = "metadata_json" if name == "metadata" else name
            assignments.append(f"{column} = ?")
            values.append(_dump(redact(value)) if name == "metadata" else value)
        assignments.append("updated_at = ?")
        values.extend([_now(), session_id])
        with self._tx() as cur:
            cur.execute(f"UPDATE ai_sessions SET {', '.join(assignments)} WHERE id = ?", values)
            if cur.rowcount != 1:
                raise AssistantError("AI 会话不存在")
        return self.get_session(session_id) or {}

    def archive_session(self, session_id: str) -> dict[str, Any]:
        with self._tx() as cur:
            self._ensure_session_inactive(cur, session_id)
            cur.execute(
                "UPDATE ai_sessions SET status = 'archived', updated_at = ? WHERE id = ?",
                (_now(), session_id),
            )
            if cur.rowcount != 1:
                raise AssistantError("AI 会话不存在")
        return self.get_session(session_id) or {}

    def unarchive_session(self, session_id: str) -> dict[str, Any]:
        with self._tx() as cur:
            row = cur.execute("SELECT status FROM ai_sessions WHERE id = ?", (session_id,)).fetchone()
            if row is None:
                raise AssistantError("AI 会话不存在")
            if str(row["status"]) != "archived":
                raise AssistantError("仅已归档会话可以恢复")
            cur.execute(
                "UPDATE ai_sessions SET status = 'idle', updated_at = ? WHERE id = ?",
                (_now(), session_id),
            )
        return self.get_session(session_id) or {}

    def delete_session(self, session_id: str) -> bool:
        """永久删除会话及级联消息/run/events；授权审计 grants 无 FK，予以保留。"""
        with self._tx() as cur:
            self._ensure_session_inactive(cur, session_id)
            cur.execute("DELETE FROM ai_sessions WHERE id = ?", (session_id,))
            return cur.rowcount == 1

    def batch_sessions(self, *, action: str, ids: list[str]) -> dict[str, Any]:
        """逐条容错的批量归档 / 恢复 / 删除。"""
        if action not in {"archive", "unarchive", "delete"}:
            raise AssistantError("批量动作必须是 archive、unarchive 或 delete")
        if not ids:
            raise AssistantError("ids 不能为空")
        if len(ids) > 100:
            raise AssistantError("单次批量最多 100 条")
        ok: list[str] = []
        failed: list[dict[str, str]] = []
        for session_id in ids:
            sid = str(session_id).strip()
            if not sid:
                failed.append({"id": session_id, "error": "空 id"})
                continue
            try:
                if action == "archive":
                    self.archive_session(sid)
                elif action == "unarchive":
                    self.unarchive_session(sid)
                else:
                    if not self.delete_session(sid):
                        raise AssistantError("AI 会话不存在")
                ok.append(sid)
            except AssistantError as exc:
                failed.append({"id": sid, "error": str(exc)})
        return {"ok": ok, "failed": failed}

    @staticmethod
    def _ensure_session_inactive(cur: sqlite3.Cursor, session_id: str) -> None:
        active = cur.execute(
            "SELECT 1 FROM ai_agent_runs"
            " WHERE session_id = ? AND status IN ('running', 'waiting_user') LIMIT 1",
            (session_id,),
        ).fetchone()
        if active is not None:
            raise AssistantError("AI 会话仍在运行或等待用户回复，请先取消后再归档或删除")

    def append_message(
        self, session_id: str, *, role: str, content: str = "", metadata: dict[str, Any] | None = None
    ) -> dict[str, Any]:
        if role not in {"user", "assistant", "system"}:
            raise AssistantError("消息角色必须为 user、assistant 或 system")
        message_id = f"AIM-{uuid4().hex[:16].upper()}"
        with self._tx() as cur:
            row = cur.execute("SELECT COALESCE(MAX(seq), 0) + 1 AS seq FROM ai_messages WHERE session_id = ?", (session_id,)).fetchone()
            if cur.execute("SELECT 1 FROM ai_sessions WHERE id = ?", (session_id,)).fetchone() is None:
                raise AssistantError("AI 会话不存在")
            cur.execute(
                "INSERT INTO ai_messages(id,session_id,seq,role,content,metadata_json,created_at) VALUES(?,?,?,?,?,?,?)",
                (message_id, session_id, int(row["seq"]), role, str(redact(content)), _dump(redact(metadata)), _now()),
            )
            cur.execute("UPDATE ai_sessions SET updated_at = ? WHERE id = ?", (_now(), session_id))
        return self.get_message(message_id) or {}

    def append_assistant_if_run_active(
        self,
        run_id: str,
        session_id: str,
        *,
        content: str = "",
        metadata: dict[str, Any] | None = None,
    ) -> dict[str, Any] | None:
        """仅当 run 仍为 running 且未取消时写入助手消息，避免取消后迟到写入插队到新一轮之后。"""
        message_id = f"AIM-{uuid4().hex[:16].upper()}"
        with self._tx() as cur:
            run = cur.execute(
                "SELECT status, cancel_requested, session_id FROM ai_agent_runs WHERE id = ?",
                (run_id,),
            ).fetchone()
            if run is None:
                return None
            if str(run["session_id"]) != session_id:
                return None
            if str(run["status"]) != "running" or bool(run["cancel_requested"]):
                return None
            if cur.execute("SELECT 1 FROM ai_sessions WHERE id = ?", (session_id,)).fetchone() is None:
                raise AssistantError("AI 会话不存在")
            row = cur.execute(
                "SELECT COALESCE(MAX(seq), 0) + 1 AS seq FROM ai_messages WHERE session_id = ?",
                (session_id,),
            ).fetchone()
            cur.execute(
                "INSERT INTO ai_messages(id,session_id,seq,role,content,metadata_json,created_at)"
                " VALUES(?,?,?,?,?,?,?)",
                (
                    message_id,
                    session_id,
                    int(row["seq"]),
                    "assistant",
                    str(redact(content)),
                    _dump(redact(metadata)),
                    _now(),
                ),
            )
            cur.execute("UPDATE ai_sessions SET updated_at = ? WHERE id = ?", (_now(), session_id))
        return self.get_message(message_id)

    def get_message(self, message_id: str) -> dict[str, Any] | None:
        row = self.conn.execute("SELECT * FROM ai_messages WHERE id = ?", (message_id,)).fetchone()
        return self._message(row) if row else None

    def list_messages(self, session_id: str, *, after_seq: int = 0, limit: int = 200) -> list[dict[str, Any]]:
        rows = self.conn.execute(
            "SELECT * FROM ai_messages WHERE session_id = ? AND seq > ? ORDER BY seq LIMIT ?",
            (session_id, max(0, after_seq), min(max(1, limit), 500)),
        )
        return [self._message(row) for row in rows]

    def create_run(
        self, session_id: str, *, provider: str = "", model: str = "", user_message: str = ""
    ) -> str:
        with self._tx() as cur:
            session = cur.execute("SELECT status FROM ai_sessions WHERE id = ?", (session_id,)).fetchone()
            self._ensure_session_startable(session)
            return self._insert_run(
                cur,
                session_id=session_id,
                provider=provider,
                model=model,
                user_message=user_message,
            )

    def begin_run(
        self,
        session_id: str,
        *,
        provider: str = "",
        model: str = "",
        user_message: str,
        metadata: dict[str, Any] | None = None,
    ) -> str:
        """原子写入用户消息并占用会话，避免并发请求启动多个 Agent。"""
        prompt = str(user_message).strip()
        meta = dict(metadata or {})
        images = meta.get("images") if isinstance(meta.get("images"), list) else []
        if not prompt and not images:
            raise AssistantError("消息不能为空")
        # 仅附图时正文占位，保证 hash / 标题链路有非空串
        stored_content = prompt or "（附图）"
        hash_message = prompt or f"（附图×{len(images)}）"
        with self._tx() as cur:
            session = cur.execute("SELECT status FROM ai_sessions WHERE id = ?", (session_id,)).fetchone()
            self._ensure_session_startable(session)
            next_seq = cur.execute(
                "SELECT COALESCE(MAX(seq), 0) + 1 AS seq FROM ai_messages WHERE session_id = ?",
                (session_id,),
            ).fetchone()
            cur.execute(
                "INSERT INTO ai_messages(id,session_id,seq,role,content,metadata_json,created_at) VALUES(?,?,?,?,?,?,?)",
                (
                    f"AIM-{uuid4().hex[:16].upper()}",
                    session_id,
                    int(next_seq["seq"]),
                    "user",
                    str(redact(stored_content)),
                    _dump(redact(meta)),
                    _now(),
                ),
            )
            return self._insert_run(
                cur,
                session_id=session_id,
                provider=provider,
                model=model,
                user_message=hash_message,
            )

    def get_run(self, run_id: str) -> dict[str, Any] | None:
        row = self.conn.execute("SELECT * FROM ai_agent_runs WHERE id = ?", (run_id,)).fetchone()
        return self._run(row) if row else None

    def get_active_run(self, session_id: str) -> dict[str, Any] | None:
        """返回会话最新一条占用中的 run：优先 running，否则 waiting_user。"""
        row = self.conn.execute(
            "SELECT * FROM ai_agent_runs"
            " WHERE session_id = ? AND status IN ('running', 'waiting_user')"
            " ORDER BY CASE status WHEN 'running' THEN 0 ELSE 1 END,"
            " started_at DESC, id DESC LIMIT 1",
            (session_id,),
        ).fetchone()
        return self._run(row) if row else None

    def latest_event_id(self, run_id: str) -> str:
        """最新事件 id，供前端续拉；无事件时返回空串。"""
        row = self.conn.execute(
            "SELECT id FROM ai_agent_events WHERE run_id = ? ORDER BY seq DESC LIMIT 1",
            (run_id,),
        ).fetchone()
        return str(row["id"]) if row else ""

    def append_event(self, run_id: str, event_type: str, payload: dict[str, Any] | None = None) -> dict[str, Any]:
        """写入一条事件并直接返回与 ``poll_events``/``_event`` 同形的 dict（事务内构造，无回读）。"""
        event_id = f"AIE-{uuid4().hex[:16].upper()}"
        created_at = _now()
        kind = event_type[:80]
        payload_json = _dump(redact(payload))
        with self._tx() as cur:
            row = cur.execute(
                "SELECT COALESCE(MAX(seq), 0) + 1 AS seq FROM ai_agent_events WHERE run_id = ?",
                (run_id,),
            ).fetchone()
            if cur.execute("SELECT 1 FROM ai_agent_runs WHERE id = ?", (run_id,)).fetchone() is None:
                raise AssistantError("AI 运行不存在")
            seq = int(row["seq"])
            cur.execute(
                "INSERT INTO ai_agent_events(id,run_id,seq,event_type,payload_json,created_at) VALUES(?,?,?,?,?,?)",
                (event_id, run_id, seq, kind, payload_json, created_at),
            )
        return {
            "id": event_id,
            "run_id": run_id,
            "seq": seq,
            "event_type": kind,
            "payload": _load(payload_json, {}),
            "created_at": created_at,
        }

    def poll_events(self, run_id: str, *, after_seq: int = 0, limit: int = 200) -> list[dict[str, Any]]:
        rows = self.conn.execute(
            "SELECT * FROM ai_agent_events WHERE run_id = ? AND seq > ? ORDER BY seq LIMIT ?",
            (run_id, max(0, after_seq), min(max(1, limit), 500)),
        )
        return [self._event(row) for row in rows]

    def poll_events_cursor(
        self, run_id: str, *, after: str = "", limit: int = 200,
    ) -> tuple[list[dict[str, Any]], str]:
        """用稳定事件 ID 续拉，供前端在轮询与 SSE 间无缝切换。"""
        after_seq = 0
        cursor = after.strip()
        if cursor:
            row = self.conn.execute(
                "SELECT seq FROM ai_agent_events WHERE run_id = ? AND id = ?",
                (run_id, cursor),
            ).fetchone()
            if row is not None:
                after_seq = int(row["seq"])
            elif cursor.isdigit():
                after_seq = int(cursor)
        events = self.poll_events(run_id, after_seq=after_seq, limit=limit)
        return events, str(events[-1]["id"]) if events else cursor

    def record_usage(self, *, provider: str, model: str, input_tokens: int, output_tokens: int) -> None:
        with self._tx() as cur:
            cur.execute(
                "INSERT INTO ai_usage_daily(day,provider,model,input_tokens,output_tokens,calls) VALUES(?,?,?,?,?,1)"
                " ON CONFLICT(day,provider,model) DO UPDATE SET input_tokens=input_tokens+excluded.input_tokens,"
                " output_tokens=output_tokens+excluded.output_tokens, calls=calls+1",
                (date.today().isoformat(), provider, model, max(0, input_tokens), max(0, output_tokens)),
            )

    def monthly_token_usage(self, *, on: date | None = None) -> int:
        """返回当前自然月已持久化的输入与输出 Token 总数。"""
        current = on or date.today()
        start = current.replace(day=1)
        end = date(start.year + 1, 1, 1) if start.month == 12 else date(start.year, start.month + 1, 1)
        row = self.conn.execute(
            "SELECT COALESCE(SUM(input_tokens + output_tokens), 0) AS total "
            "FROM ai_usage_daily WHERE day >= ? AND day < ?",
            (start.isoformat(), end.isoformat()),
        ).fetchone()
        return int(row["total"] if row else 0)

    def monthly_assistant_run_count(self, *, on: date | None = None) -> int:
        """自然月内助手 run 次数（含失败）；查询失败时抛错（硬拒绝语义）。"""
        current = on or date.today()
        start = current.replace(day=1)
        end = date(start.year + 1, 1, 1) if start.month == 12 else date(start.year, start.month + 1, 1)
        row = self.conn.execute(
            "SELECT COUNT(*) AS total FROM ai_agent_runs "
            "WHERE substr(started_at, 1, 10) >= ? AND substr(started_at, 1, 10) < ?",
            (start.isoformat(), end.isoformat()),
        ).fetchone()
        return int(row["total"] if row else 0)

    @staticmethod
    def _ensure_session_startable(session: sqlite3.Row | None) -> None:
        if session is None:
            raise AssistantError("AI 会话不存在")
        status = str(session["status"])
        if status == "archived":
            raise AssistantError("AI 会话不存在或已归档")
        if status == "running":
            raise AssistantError("当前 AI 会话已有运行，请先等待结束或中止")
        # waiting_user：允许用户回复；正常路径走 resume_waiting_run，勿 begin_run。

    @staticmethod
    def _insert_run(
        cur: sqlite3.Cursor,
        *,
        session_id: str,
        provider: str,
        model: str,
        user_message: str,
    ) -> str:
        run_id = f"AIR-{uuid4().hex[:16].upper()}"
        now = _now()
        cur.execute(
            "INSERT INTO ai_agent_runs(id,session_id,status,provider,model,user_message_hash,started_at)"
            " VALUES(?,?, 'running',?,?,?,?)",
            (run_id, session_id, provider, model, _hash(user_message), now),
        )
        assignments = ["status='running'", "last_error=''", "updated_at=?"]
        values: list[Any] = [now]
        if provider:
            assignments.append("provider=?")
            values.append(provider)
        if model:
            assignments.append("model=?")
            values.append(model)
        values.append(session_id)
        cur.execute(f"UPDATE ai_sessions SET {', '.join(assignments)} WHERE id=?", values)
        return run_id

    @staticmethod
    def _session(row: sqlite3.Row) -> dict[str, Any]:
        out = dict(row)
        out["metadata"] = _load(out.pop("metadata_json"), {})
        return out

    @staticmethod
    def _message(row: sqlite3.Row) -> dict[str, Any]:
        out = dict(row)
        out["metadata"] = _load(out.pop("metadata_json"), {})
        return out

    @staticmethod
    def _run(row: sqlite3.Row) -> dict[str, Any]:
        out = dict(row)
        out["cancel_requested"] = bool(out["cancel_requested"])
        out["result"] = _load(out.pop("result_json"), {})
        return out

    @staticmethod
    def _event(row: sqlite3.Row) -> dict[str, Any]:
        out = dict(row)
        out["payload"] = _load(out.pop("payload_json"), {})
        return out


AiSessionStore = AssistantStore
