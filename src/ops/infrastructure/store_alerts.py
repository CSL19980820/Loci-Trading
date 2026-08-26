"""ops.db 价格提醒规则 / 命中。"""
from __future__ import annotations

import sqlite3
from typing import Any

from src.ops.infrastructure.store_helpers import OpsError, dumps, loads, new_id


def _is_duplicate_hit(exc: sqlite3.IntegrityError) -> bool:
    """只有唯一约束冲突才算「这一桶已经命中过」。

    ``IntegrityError`` 同时覆盖 UNIQUE / FOREIGN KEY / NOT NULL / CHECK：只有前者是
    幂等重复（重复扫同一分钟桶、或重放同一个 hit id），其余都是调用方或 schema 的真错。
    """
    return "UNIQUE constraint failed" in str(exc)


class OpsAlertsMixin:
    def upsert_alert_rule(self, payload: dict[str, Any]) -> dict[str, Any]:
        rule_id = str(payload.get("id") or "").strip() or new_id("ALR")
        code = str(payload.get("code") or "").strip()
        if not code:
            from src.ops.infrastructure.store import OpsError

            raise OpsError("提醒规则需要 code")
        now = self._now()  # type: ignore[attr-defined]
        row = {
            "id": rule_id,
            "code": code,
            "name": str(payload.get("name") or ""),
            "enabled": 1 if payload.get("enabled", True) else 0,
            "condition_group_json": dumps(payload.get("condition_group") or {}),
            "market_hours_mode": str(payload.get("market_hours_mode") or "session"),
            "cooldown_minutes": int(payload.get("cooldown_minutes") or 5),
            "max_triggers_per_day": int(payload.get("max_triggers_per_day") or 10),
            "repeat_mode": str(payload.get("repeat_mode") or "repeat"),
            "expire_at": str(payload.get("expire_at") or ""),
            "plan_id_optional": str(payload.get("plan_id_optional") or ""),
            "channel_ids_json": dumps(payload.get("channel_ids") or []),
            "last_trigger_at": str(payload.get("last_trigger_at") or ""),
            "trigger_count_today": int(payload.get("trigger_count_today") or 0),
            "trigger_date": str(payload.get("trigger_date") or ""),
            "created_at": str(payload.get("created_at") or now),
            "updated_at": now,
        }
        with self._transaction() as cursor:  # type: ignore[attr-defined]
            cursor.execute(
                """
                INSERT INTO alert_rules(
                    id, code, name, enabled, condition_group_json, market_hours_mode,
                    cooldown_minutes, max_triggers_per_day, repeat_mode, expire_at,
                    plan_id_optional, channel_ids_json, last_trigger_at,
                    trigger_count_today, trigger_date, created_at, updated_at
                ) VALUES (
                    :id, :code, :name, :enabled, :condition_group_json, :market_hours_mode,
                    :cooldown_minutes, :max_triggers_per_day, :repeat_mode, :expire_at,
                    :plan_id_optional, :channel_ids_json, :last_trigger_at,
                    :trigger_count_today, :trigger_date, :created_at, :updated_at
                )
                ON CONFLICT(id) DO UPDATE SET
                    code=excluded.code,
                    name=excluded.name,
                    enabled=excluded.enabled,
                    condition_group_json=excluded.condition_group_json,
                    market_hours_mode=excluded.market_hours_mode,
                    cooldown_minutes=excluded.cooldown_minutes,
                    max_triggers_per_day=excluded.max_triggers_per_day,
                    repeat_mode=excluded.repeat_mode,
                    expire_at=excluded.expire_at,
                    plan_id_optional=excluded.plan_id_optional,
                    channel_ids_json=excluded.channel_ids_json,
                    updated_at=excluded.updated_at
                """,
                row,
            )
        return self.get_alert_rule(rule_id) or {}

    def get_alert_rule(self, rule_id: str) -> dict[str, Any] | None:
        row = self.conn.execute(  # type: ignore[attr-defined]
            "SELECT * FROM alert_rules WHERE id = ?", (rule_id,)
        ).fetchone()
        return self._alert_rule_row(row) if row else None

    def list_alert_rules(self, *, enabled_only: bool = False) -> list[dict[str, Any]]:
        sql = "SELECT * FROM alert_rules"
        if enabled_only:
            sql += " WHERE enabled = 1"
        sql += " ORDER BY updated_at DESC"
        rows = self.conn.execute(sql).fetchall()  # type: ignore[attr-defined]
        return [self._alert_rule_row(row) for row in rows]

    def delete_alert_rule(self, rule_id: str) -> bool:
        with self._transaction() as cursor:  # type: ignore[attr-defined]
            cursor.execute("DELETE FROM alert_rules WHERE id = ?", (rule_id,))
            return cursor.rowcount > 0

    def touch_alert_trigger(
        self,
        rule_id: str,
        *,
        trigger_at: str,
        trigger_date: str,
        trigger_count_today: int,
    ) -> None:
        with self._transaction() as cursor:  # type: ignore[attr-defined]
            cursor.execute(
                """
                UPDATE alert_rules
                SET last_trigger_at = ?, trigger_date = ?, trigger_count_today = ?, updated_at = ?
                WHERE id = ?
                """,
                (trigger_at, trigger_date, trigger_count_today, self._now(), rule_id),  # type: ignore[attr-defined]
            )

    def insert_alert_hit(self, payload: dict[str, Any]) -> dict[str, Any]:
        """写入一条命中；返回空 dict **只**表示幂等跳过（同一 rule+bucket 已命中过）。

        这里曾是 ``except Exception: return {}``，把外键违例（``rule_id`` 指向不存在的规则）、
        NOT NULL、schema 漂移一起压成「跳过」。后果不是少一行日志：种子数据忘了先建
        ``alert_rules`` 父行时，5 次写入一行都没落库，接口却逐次返回「成功」，照着它写的
        测试也跟着一起绿。真失败必须冒出来，能静默的只有预期内的重复。
        """
        hit_id = str(payload.get("id") or "").strip() or new_id("ALH")
        with self._transaction() as cursor:  # type: ignore[attr-defined]
            try:
                cursor.execute(
                    """
                    INSERT INTO alert_hits(
                        id, rule_id, trigger_bucket, trigger_time,
                        snapshot_json, notify_ok, notify_error
                    ) VALUES (?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        hit_id,
                        str(payload.get("rule_id") or ""),
                        str(payload.get("trigger_bucket") or ""),
                        str(payload.get("trigger_time") or ""),
                        dumps(payload.get("snapshot") or {}),
                        1 if payload.get("notify_ok") else 0,
                        str(payload.get("notify_error") or ""),
                    ),
                )
            except sqlite3.IntegrityError as exc:
                if _is_duplicate_hit(exc):
                    return {}
                raise OpsError(f"写入提醒命中失败：{exc}") from exc
        return {"id": hit_id, **payload}

    def list_alert_hits(self, *, rule_id: str | None = None, limit: int = 50) -> list[dict[str, Any]]:
        if rule_id:
            rows = self.conn.execute(  # type: ignore[attr-defined]
                "SELECT * FROM alert_hits WHERE rule_id = ? ORDER BY trigger_time DESC LIMIT ?",
                (rule_id, limit),
            ).fetchall()
        else:
            rows = self.conn.execute(  # type: ignore[attr-defined]
                "SELECT * FROM alert_hits ORDER BY trigger_time DESC LIMIT ?",
                (limit,),
            ).fetchall()
        return [
            {
                "id": row["id"],
                "rule_id": row["rule_id"],
                "trigger_bucket": row["trigger_bucket"],
                "trigger_time": row["trigger_time"],
                "snapshot": loads(row["snapshot_json"]),
                "notify_ok": bool(row["notify_ok"]),
                "notify_error": row["notify_error"],
            }
            for row in rows
        ]

    def _alert_rule_row(self, row: Any) -> dict[str, Any]:
        return {
            "id": row["id"],
            "code": row["code"],
            "name": row["name"],
            "enabled": bool(row["enabled"]),
            "condition_group": loads(row["condition_group_json"]) or {},
            "market_hours_mode": row["market_hours_mode"],
            "cooldown_minutes": int(row["cooldown_minutes"] or 0),
            "max_triggers_per_day": int(row["max_triggers_per_day"] or 0),
            "repeat_mode": row["repeat_mode"],
            "expire_at": row["expire_at"],
            "plan_id_optional": row["plan_id_optional"],
            "channel_ids": loads(row["channel_ids_json"]) or [],
            "last_trigger_at": row["last_trigger_at"],
            "trigger_count_today": int(row["trigger_count_today"] or 0),
            "trigger_date": row["trigger_date"],
            "created_at": row["created_at"],
            "updated_at": row["updated_at"],
        }
