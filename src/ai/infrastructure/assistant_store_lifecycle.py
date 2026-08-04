"""AI run 生命周期：取消、HITL 等待、中断恢复、结束。"""
from __future__ import annotations

from typing import Any
from uuid import uuid4

from src.ai.domain.assistant import AssistantError
from src.ai.infrastructure.assistant_store_util import _dump, _now, redact


class AssistantStoreLifecycleMixin:
    """依赖宿主提供 `_tx` / `get_run` / `append_event` / `conn`。"""

    def cancel_run(self, run_id: str) -> bool:
        with self._tx() as cur:  # type: ignore[attr-defined]
            cur.execute(
                "UPDATE ai_agent_runs SET cancel_requested = 1"
                " WHERE id = ? AND status IN ('running', 'waiting_user')",
                (run_id,),
            )
            changed = cur.rowcount == 1
            if changed:
                row = cur.execute(
                    "SELECT status, session_id FROM ai_agent_runs WHERE id = ?", (run_id,),
                ).fetchone()
                if row is not None and str(row["status"]) == "waiting_user":
                    now = _now()
                    cur.execute(
                        "UPDATE ai_agent_runs SET status='cancelled', finished_at=? WHERE id=?",
                        (now, run_id),
                    )
                    cur.execute(
                        "UPDATE ai_sessions SET status='idle', last_error='', updated_at=? WHERE id=?",
                        (now, str(row["session_id"])),
                    )
        if changed:
            self.append_event(  # type: ignore[attr-defined]
                run_id,
                "cancel_requested",
                {"message": "已标记取消；当前模型请求不能强杀，已启动后台任务会继续写入任务历史"},
            )
            run = self.get_run(run_id)  # type: ignore[attr-defined]
            if run is not None and run["status"] == "cancelled":
                self.append_event(run_id, "cancelled", {"cancelled": True})  # type: ignore[attr-defined]
        return changed

    def pause_run_waiting_user(
        self, run_id: str, *, ask: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """HITL 暂停：会话占用保留，前端可展示 ask 并等待用户回复。"""
        run = self.get_run(run_id)  # type: ignore[attr-defined]
        if run is None:
            raise AssistantError("AI 运行不存在")
        if run["status"] not in {"running", "waiting_user"}:
            raise AssistantError("AI 运行已结束，无法进入等待用户状态")
        now = _now()
        with self._tx() as cur:  # type: ignore[attr-defined]
            cur.execute(
                "UPDATE ai_agent_runs SET status='waiting_user', result_json=?, finished_at='' WHERE id=?",
                (_dump(redact({"pending_ask": ask or {}})), run_id),
            )
            cur.execute(
                "UPDATE ai_sessions SET status='waiting_user', last_error='', updated_at=? WHERE id=?",
                (now, run["session_id"]),
            )
        return self.get_run(run_id) or {}  # type: ignore[attr-defined]

    def resolve_waiting_session(self, session_id: str) -> int:
        """用户再次发消息前，把等待中的 run 收敛为 completed，释放会话占用。"""
        resolved = 0
        with self._tx() as cur:  # type: ignore[attr-defined]
            rows = cur.execute(
                "SELECT id FROM ai_agent_runs WHERE session_id = ? AND status = 'waiting_user'",
                (session_id,),
            ).fetchall()
            now = _now()
            for row in rows:
                run_id = str(row["id"])
                cur.execute(
                    "UPDATE ai_agent_runs SET status='completed', finished_at=? WHERE id=? AND status='waiting_user'",
                    (now, run_id),
                )
                if cur.rowcount != 1:
                    continue
                resolved += 1
                next_seq = cur.execute(
                    "SELECT COALESCE(MAX(seq), 0) + 1 AS seq FROM ai_agent_events WHERE run_id = ?",
                    (run_id,),
                ).fetchone()
                cur.execute(
                    "INSERT INTO ai_agent_events(id,run_id,seq,event_type,payload_json,created_at)"
                    " VALUES(?,?,?,?,?,?)",
                    (
                        f"AIE-{uuid4().hex[:16].upper()}",
                        run_id,
                        int(next_seq["seq"]),
                        "done",
                        _dump({"stopped_reason": "waiting_user_resolved"}),
                        now,
                    ),
                )
            if resolved:
                cur.execute(
                    "UPDATE ai_sessions SET status='idle', last_error='', updated_at=? WHERE id=? AND status='waiting_user'",
                    (now, session_id),
                )
        return resolved

    def recover_interrupted_runs(self) -> int:
        """进程内 worker 无法跨重启续跑，启动时把遗留 running 收敛为可见失败。

        waiting_user 保留：无后台 worker，用户仍可回复后开新 run。
        """
        message = "应用已重启，未完成的 AI 运行已中断"
        recovered = 0
        with self._tx() as cur:  # type: ignore[attr-defined]
            rows = cur.execute(
                "SELECT id, session_id FROM ai_agent_runs WHERE status = 'running'"
            ).fetchall()
            now = _now()
            for row in rows:
                run_id = str(row["id"])
                cur.execute(
                    "UPDATE ai_agent_runs SET status='failed', error_text=?, result_json=?, finished_at=?"
                    " WHERE id=? AND status = 'running'",
                    (message, _dump({"interrupted": True}), now, run_id),
                )
                if cur.rowcount != 1:
                    continue
                cur.execute(
                    "UPDATE ai_execution_grants SET status='interrupted', result_json=?"
                    " WHERE run_id=? AND status='consumed'",
                    (_dump({"interrupted": True, "message": message}), run_id),
                )
                recovered += 1
                cur.execute(
                    "UPDATE ai_sessions SET status='error', last_error=?, updated_at=?"
                    " WHERE id=? AND status = 'running'",
                    (message, now, str(row["session_id"])),
                )
                next_seq = cur.execute(
                    "SELECT COALESCE(MAX(seq), 0) + 1 AS seq FROM ai_agent_events WHERE run_id = ?",
                    (run_id,),
                ).fetchone()
                cur.execute(
                    "INSERT INTO ai_agent_events(id,run_id,seq,event_type,payload_json,created_at)"
                    " VALUES(?,?,?,?,?,?)",
                    (
                        f"AIE-{uuid4().hex[:16].upper()}",
                        run_id,
                        int(next_seq["seq"]),
                        "error",
                        _dump({"message": message, "interrupted": True}),
                        now,
                    ),
                )
        return recovered

    def finish_run(
        self, run_id: str, *, status: str, result: dict[str, Any] | None = None, error: str = "",
        input_tokens: int = 0, output_tokens: int = 0,
    ) -> dict[str, Any]:
        if status not in {"completed", "failed", "cancelled"}:
            raise AssistantError("AI 运行结束状态无效")
        run = self.get_run(run_id)  # type: ignore[attr-defined]
        if run is None:
            raise AssistantError("AI 运行不存在")
        session_status = "idle" if status in {"completed", "cancelled"} else "error"
        with self._tx() as cur:  # type: ignore[attr-defined]
            cur.execute(
                "UPDATE ai_agent_runs SET status=?, result_json=?, error_text=?,"
                " input_tokens=?, output_tokens=?, finished_at=?, cancel_requested=?"
                " WHERE id=? AND status IN ('running', 'waiting_user')",
                (
                    status,
                    _dump(redact(result)),
                    str(redact(error))[:4000],
                    max(0, input_tokens),
                    max(0, output_tokens),
                    _now(),
                    1 if status == "cancelled" else 0,
                    run_id,
                ),
            )
            if cur.rowcount == 1:
                cur.execute(
                    "UPDATE ai_sessions SET status=?, last_error=?, updated_at=? WHERE id=?",
                    (session_status, str(redact(error))[:4000], _now(), run["session_id"]),
                )
        return self.get_run(run_id) or {}  # type: ignore[attr-defined]
