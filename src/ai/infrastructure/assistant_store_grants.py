"""ExecutionGrant：助手写操作的一次性授权（签发 / 消费 / 收口）。

与 lifecycle / profile 同一套分工：本文件只管 `ai_execution_grants` 一张表，
连接与事务仍由宿主 `AssistantStore` 提供。grant 绑定本轮 run 与参数哈希，
实参不落库（只存脱敏副本），审计行**不随会话级联删除**。
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any
from uuid import uuid4

from src.ai.domain.assistant import AssistantError
from src.ai.infrastructure.assistant_store_util import _dump, _hash, _now, redact


class AssistantStoreGrantsMixin:
    """依赖宿主提供 `_tx` / `get_run`。"""

    def issue_grant(
        self, *, session_id: str, run_id: str, user_message: str, action: str, target: str,
        parameters: dict[str, Any], ttl_seconds: int = 120,
    ) -> dict[str, Any]:
        """签发只绑定本轮的短期 grant；实际参数仅存哈希和脱敏副本。"""
        if not 1 <= ttl_seconds <= 300:
            raise AssistantError("ExecutionGrant TTL 必须在 1-300 秒之间")
        run = self.get_run(run_id)
        if run is None or run["session_id"] != session_id or run["status"] != "running":
            raise AssistantError("ExecutionGrant 绑定的运行无效")
        message_hash = _hash(user_message)
        if run["user_message_hash"] != message_hash:
            raise AssistantError("ExecutionGrant 原始用户消息不匹配")
        now = datetime.now(timezone.utc)
        expires = now.timestamp() + ttl_seconds
        grant_id = f"AIG-{uuid4().hex[:16].upper()}"
        key = _hash({"grant": grant_id, "run": run_id, "action": action, "params": parameters})
        with self._tx() as cur:
            existing = cur.execute(
                "SELECT id, idempotency_key, expires_at, status FROM ai_execution_grants"
                " WHERE run_id=? AND action=? AND target=? AND params_hash=?",
                (run_id, action, target, _hash(parameters)),
            ).fetchone()
            if existing is not None:
                if str(existing["status"]) == "issued" and str(existing["expires_at"]) > _now():
                    return {"id": str(existing["id"]), "idempotency_key": str(existing["idempotency_key"]), "expires_at": str(existing["expires_at"])}
                raise AssistantError("相同动作已签发或执行，拒绝重复写入")
            cur.execute(
                "INSERT INTO ai_execution_grants(id,session_id,run_id,message_hash,action,target,params_hash,"
                "params_redacted_json,idempotency_key,status,expires_at,created_at) VALUES(?,?,?,?,?,?,?,?,?, 'issued',?,?)",
                (grant_id, session_id, run_id, message_hash, action, target, _hash(parameters),
                 _dump(redact(parameters)), key, datetime.fromtimestamp(expires, timezone.utc).isoformat(timespec="seconds"), _now()),
            )
        return {"id": grant_id, "idempotency_key": key, "expires_at": datetime.fromtimestamp(expires, timezone.utc).isoformat(timespec="seconds")}

    def consume_grant(
        self, *, grant_id: str, session_id: str, run_id: str, user_message: str,
        action: str, target: str, parameters: dict[str, Any],
    ) -> str:
        """原子地消费 grant，任何绑定不一致或重放均拒绝。"""
        with self._tx() as cur:
            row = cur.execute("SELECT * FROM ai_execution_grants WHERE id = ?", (grant_id,)).fetchone()
            if row is None:
                raise AssistantError("ExecutionGrant 不存在")
            run = cur.execute("SELECT cancel_requested FROM ai_agent_runs WHERE id = ?", (run_id,)).fetchone()
            valid = (
                run is not None and not bool(run["cancel_requested"]) and
                str(row["status"]) == "issued"
                and str(row["session_id"]) == session_id
                and str(row["run_id"]) == run_id
                and str(row["message_hash"]) == _hash(user_message)
                and str(row["action"]) == action
                and str(row["target"]) == target
                and str(row["params_hash"]) == _hash(parameters)
                and str(row["expires_at"]) > _now()
            )
            if not valid:
                raise AssistantError("ExecutionGrant 缺失、过期、已使用或与本会话参数不匹配")
            cur.execute("UPDATE ai_execution_grants SET status='consumed', consumed_at=? WHERE id=?", (_now(), grant_id))
            return str(row["idempotency_key"])

    def complete_grant(
        self, grant_id: str, result: dict[str, Any], *, status: str = "completed",
    ) -> None:
        if status not in {"completed", "failed", "interrupted"}:
            raise AssistantError("ExecutionGrant 结束状态无效")
        with self._tx() as cur:
            cur.execute(
                "UPDATE ai_execution_grants SET status=?, result_json=? WHERE id=? AND status='consumed'",
                (status, _dump(redact(result)), grant_id),
            )
