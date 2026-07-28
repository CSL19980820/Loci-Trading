"""OpsStore：LLM 供应商读写。"""
from __future__ import annotations

from typing import Any
import sqlite3

from src.ops.infrastructure.store_helpers import dumps, loads, new_id


class OpsProvidersMixin:
    """llm_providers。依赖宿主提供 conn 与 _transaction。"""

    conn: sqlite3.Connection

    def upsert_provider(self, payload: dict[str, Any]) -> str:
        provider_id = payload.get("id") or new_id("LLM")
        is_default_val = payload.get("is_default")
        is_default_insert = 1 if is_default_val else 0
        with self._transaction() as cursor:
            if "is_default" in payload:
                conflict_default = "is_default=excluded.is_default,"
            else:
                conflict_default = ""
            cursor.execute(
                f"""
                INSERT INTO llm_providers(id, name, protocol, base_url, encrypted_key,
                                          key_last4, default_model, models_json,
                                          models_synced_at, proxy_url, is_active, is_default,
                                          validated_at, note, created_at, updated_at)
                VALUES(?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, datetime('now'), datetime('now'))
                ON CONFLICT(name) DO UPDATE SET
                    protocol=excluded.protocol, base_url=excluded.base_url,
                    encrypted_key=COALESCE(excluded.encrypted_key, llm_providers.encrypted_key),
                    key_last4=CASE WHEN excluded.encrypted_key IS NOT NULL
                                   THEN excluded.key_last4 ELSE llm_providers.key_last4 END,
                    default_model=excluded.default_model, models_json=excluded.models_json,
                    models_synced_at=excluded.models_synced_at, proxy_url=excluded.proxy_url,
                    is_active=excluded.is_active, {conflict_default}
                    validated_at=excluded.validated_at,
                    note=excluded.note, updated_at=excluded.updated_at
                """,
                (
                    provider_id,
                    str(payload["name"]),
                    str(payload["protocol"]),
                    str(payload["base_url"]).rstrip("/"),
                    payload.get("encrypted_key"),
                    str(payload.get("key_last4", "")),
                    str(payload.get("default_model", "")),
                    dumps(payload.get("models", [])),
                    str(payload.get("models_synced_at", "")),
                    str(payload.get("proxy_url", "")),
                    1 if payload.get("is_active", True) else 0,
                    is_default_insert,
                    str(payload.get("validated_at", "")),
                    str(payload.get("note", "")),
                ),
            )
        return provider_id

    def set_default_provider(self, name_or_id: str) -> bool:
        """将指定供应商设为默认，其余全部清零。"""
        record = self.get_provider(name_or_id)
        if record is None:
            return False
        with self._transaction() as cursor:
            cursor.execute("UPDATE llm_providers SET is_default = 0")
            cursor.execute(
                "UPDATE llm_providers SET is_default = 1, updated_at = datetime('now')"
                " WHERE id = ?",
                (record["id"],),
            )
        return True

    def get_default_provider(self, *, include_secret: bool = False) -> dict[str, Any] | None:
        row = self.conn.execute(
            "SELECT * FROM llm_providers WHERE is_default = 1 AND is_active = 1 LIMIT 1"
        ).fetchone()
        return self._provider_row(row, include_secret=include_secret) if row else None

    def get_provider(self, name_or_id: str, *, include_secret: bool = False) -> dict[str, Any] | None:
        row = self.conn.execute(
            "SELECT * FROM llm_providers WHERE name = ? OR id = ?", (name_or_id, name_or_id)
        ).fetchone()
        return self._provider_row(row, include_secret=include_secret) if row else None

    def list_providers(self) -> list[dict[str, Any]]:
        return [
            self._provider_row(row)
            for row in self.conn.execute(
                "SELECT * FROM llm_providers ORDER BY is_default DESC, name"
            )
        ]

    def delete_provider(self, name_or_id: str) -> bool:
        with self._transaction() as cursor:
            cursor.execute(
                "DELETE FROM llm_providers WHERE name = ? OR id = ?", (name_or_id, name_or_id)
            )
            return cursor.rowcount > 0

    @staticmethod
    def _provider_row(row: sqlite3.Row, *, include_secret: bool = False) -> dict[str, Any]:
        data = dict(row)
        data["models"] = loads(data.pop("models_json", "[]"), [])
        data["is_active"] = bool(data.get("is_active"))
        data["is_default"] = bool(data.get("is_default"))
        secret = data.pop("encrypted_key", None)
        data["has_key"] = secret is not None
        if include_secret:
            # 只有真正要发起调用时才带上密文，且调用方需立刻解密使用、不得留存。
            data["encrypted_key"] = secret
        return data
