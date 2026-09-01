"""IdentityStore 的平台部分：配额、用量、审计、通知、公告、API Key。

为什么这些表在 identity.db 而不是各租户的 ops.db：

- **配额与用量**要被管理员横向比较、要在跨租户的后台任务里统一裁决；
  放进租户库就没法在一条 SQL 里回答「谁这个月烧得最多」。
- **审计**必须是租户改不动的。放租户库等于让被审计者持有审计日志。
- **通知/公告/API Key** 天然跨租户。

用量计数（``usage_counters``）是**可重建的派生数据**：整表清空只会让当期
配额判定重新从 0 计，不影响任何账本事实。
"""
from __future__ import annotations

from collections.abc import Sequence
from typing import Any
import json
import secrets
import sqlite3

from src.identity.domain.models import iso, utc_now

#: 新用户默认配额。0 表示「用系统默认」，负数表示不限。
#:
#: ``job_slots``：**用户自建**定时任务的条数上限。托管任务（选股/情报/候选
#: 跟踪，子租户开箱就有 7~8 条）不占额度——那是系统给的，不是用户建的。
#:
#: ``storage_mb``：该用户私有目录（palace.db + ops.db + skills/ + skill_runs/
#: + research_runs/）的软上限。超了在清理任务里更激进地截断并在账号页红字提示，
#: 而不是拒绝写入——把人锁在门外比留点垃圾更糟。
DEFAULT_QUOTAS = {
    "llm_monthly_tokens": 300_000,
    "llm_daily_calls": 200,
    "strategy_slots": 20,
    "publish_slots": 5,
  "job_slots": 5,
    "storage_mb": 2048,
}

#: 管理员配额：不限。
ADMIN_QUOTAS = {key: -1 for key in DEFAULT_QUOTAS}


def like_escape(raw: str) -> str:
    """转义 LIKE 的元字符 ``%`` ``_``（以及转义符自身）。

    管理员在后台搜索框里敲一个 ``%``，不该等于「把全表捞出来」；敲 ``_``
    也不该变成「任意单字符」。转义后**必须**配 ``ESCAPE '\\'`` 使用，否则
    反斜杠只是普通字符，转义等于没做。
    """
    return raw.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")


def like_needle(raw: str) -> str:
    """``%…%`` 包围的转义 needle，用于「包含」匹配。"""
    return f"%{like_escape(raw)}%"


def _audit_filters(
    *,
    actor_id: str = "",
    action: str = "",
    keyword: str = "",
    outcome: str = "",
    actions: Sequence[str] | None = None,
) -> tuple[str, list[Any]]:
    """审计查询的 WHERE 构造。返回 ``("WHERE …" | "", params)``。

    列表与计数共用同一份条件——分开手写迟早漂移，让分页器显示「共 300 条」
    却只翻得到 12 条。
    """
    clauses: list[str] = []
    params: list[Any] = []
    if actor_id:
        clauses.append("actor_id = ?")
        params.append(actor_id)
    if action:
        # 前缀模糊：敲 ``account.`` 就能一次看全账号类事件，不用背全名。
        clauses.append("action LIKE ? || '%' ESCAPE '\\'")
        params.append(like_escape(action))
    if keyword:
        clauses.append(
            "(actor_id LIKE ? ESCAPE '\\' OR actor_name LIKE ? ESCAPE '\\'"
            " OR target LIKE ? ESCAPE '\\')"
        )
        needle = like_needle(keyword)
        params.extend([needle, needle, needle])
    if outcome:
        clauses.append("outcome = ?")
        params.append(outcome)
    if actions is not None:
        # 白名单（如「只看登录事件」）。空白名单是「明确一条都不要」，不是
        # 「不过滤」——退化成不过滤会把整本审计当成登录记录端出去。
        if actions:
            clauses.append(f"action IN ({','.join('?' for _ in actions)})")
            params.extend(actions)
        else:
            clauses.append("1 = 0")
    where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
    return where, params


class PlatformMixin:
    """依赖宿主提供 ``conn``。"""

    conn: sqlite3.Connection

    # ---- quotas ---------------------------------------------------------

    def get_quota(self, user_id: str) -> dict[str, int]:
        row = self.conn.execute(
            "SELECT * FROM user_quotas WHERE user_id = ?", (user_id,)
        ).fetchone()
        if row is None:
            return dict(DEFAULT_QUOTAS)
        return {key: int(row[key]) for key in DEFAULT_QUOTAS}

    def set_quota(self, user_id: str, **limits: int) -> dict[str, int]:
        current = self.get_quota(user_id)
        current.update({key: int(value) for key, value in limits.items() if key in DEFAULT_QUOTAS})
        # 列名 / 占位符 / DO UPDATE / 参数四处统一从 DEFAULT_QUOTAS 推导：
        # 手写四份的写法已经漏过一次，加一项配额就得记得四处同改。
        columns = list(DEFAULT_QUOTAS)
        assignments = ", ".join(f"{name} = excluded.{name}" for name in columns)
        placeholders = ",".join("?" for _ in columns)
        self.conn.execute(
            f"""INSERT INTO user_quotas (user_id, {', '.join(columns)}, updated_at)
            VALUES (?,{placeholders},?)
            ON CONFLICT(user_id) DO UPDATE SET
            {assignments}, updated_at = excluded.updated_at""",
            (user_id, *(current[name] for name in columns), iso(utc_now())),
        )
        self.conn.commit()
        return current

    # ---- usage ----------------------------------------------------------

    def bump_usage(self, user_id: str, *, period: str, metric: str, delta: int = 1) -> int:
        """累加并返回累加后的值。UPSERT 单语句，并发安全。"""
        self.conn.execute(
            """INSERT INTO usage_counters (user_id, period, metric, value, updated_at)
            VALUES (?,?,?,?,?)
            ON CONFLICT(user_id, period, metric) DO UPDATE SET
            value = usage_counters.value + excluded.value,
            updated_at = excluded.updated_at""",
            (user_id, period, metric, int(delta), iso(utc_now())),
        )
        self.conn.commit()
        return self.get_usage(user_id, period=period, metric=metric)

    def get_usage(self, user_id: str, *, period: str, metric: str) -> int:
        row = self.conn.execute(
            "SELECT value FROM usage_counters WHERE user_id = ? AND period = ? AND metric = ?",
            (user_id, period, metric),
        ).fetchone()
        return int(row["value"]) if row else 0

    def usage_overview(self, user_id: str, *, period: str) -> dict[str, int]:
        rows = self.conn.execute(
            "SELECT metric, value FROM usage_counters WHERE user_id = ? AND period = ?",
            (user_id, period),
        ).fetchall()
        return {row["metric"]: int(row["value"]) for row in rows}

    def top_usage(self, *, period: str, metric: str, limit: int = 20) -> list[dict[str, Any]]:
        rows = self.conn.execute(
            """SELECT c.user_id, c.value, u.username, u.display_name
            FROM usage_counters c LEFT JOIN users u ON u.id = c.user_id
            WHERE c.period = ? AND c.metric = ?
            ORDER BY c.value DESC LIMIT ?""",
            (period, metric, limit),
        ).fetchall()
        return [dict(row) for row in rows]

    # ---- audit ----------------------------------------------------------

    def write_audit(
        self,
        *,
        action: str,
        actor_id: str = "",
        actor_name: str = "",
        target: str = "",
        outcome: str = "ok",
        detail: Any = None,
        ip: str = "",
    ) -> None:
        """只追加。审计写失败不能带走业务——调用方一律不捕获也不重试。"""
        from src.identity.infrastructure.store import new_id

        self.conn.execute(
            """INSERT INTO audit_log
            (id, occurred_at, actor_id, actor_name, action, target, outcome, detail_json, ip)
            VALUES (?,?,?,?,?,?,?,?,?)""",
            (
                new_id("aud"),
                iso(utc_now()),
                actor_id,
                actor_name,
                action,
                target,
                outcome,
                json.dumps(detail or {}, ensure_ascii=False, separators=(",", ":")),
                ip[:64],
            ),
        )
        self.conn.commit()

    def list_audit(
        self,
        *,
        limit: int = 100,
        offset: int = 0,
        actor_id: str = "",
        action: str = "",
        keyword: str = "",
        outcome: str = "",
        actions: Sequence[str] | None = None,
    ) -> list[dict[str, Any]]:
        """审计倒序分页。``action`` 是前缀匹配，``keyword`` 命中操作者或对象。

        ``actions`` 是白名单（如 ``LOGIN_ACTIONS``）：登录记录页要的是「只看这几
        类事件」，用前缀匹配表达不了「account.login 加 account.social_login，但
        不要 account.register」。
        """
        where, params = _audit_filters(
            actor_id=actor_id, action=action, keyword=keyword, outcome=outcome, actions=actions
        )
        rows = self.conn.execute(
            f"""SELECT * FROM audit_log {where}
            ORDER BY occurred_at DESC LIMIT ? OFFSET ?""",
            (*params, limit, offset),
        ).fetchall()
        return [dict(row) for row in rows]

    def count_audit(
        self,
        *,
        actor_id: str = "",
        action: str = "",
        keyword: str = "",
        outcome: str = "",
        actions: Sequence[str] | None = None,
    ) -> int:
        """与 ``list_audit`` 同一套过滤条件下的总数，供分页器用。"""
        where, params = _audit_filters(
            actor_id=actor_id, action=action, keyword=keyword, outcome=outcome, actions=actions
        )
        row = self.conn.execute(f"SELECT COUNT(*) AS n FROM audit_log {where}", params).fetchone()
        return int(row["n"]) if row else 0

    # ---- notifications ---------------------------------------------------

    def push_notification(
        self,
        *,
        user_id: str,
        title: str,
        body: str = "",
        kind: str = "system",
        link: str = "",
    ) -> str:
        from src.identity.infrastructure.store import new_id

        notification_id = new_id("ntf")
        self.conn.execute(
            """INSERT INTO notifications (id, user_id, kind, title, body, link, created_at)
            VALUES (?,?,?,?,?,?,?)""",
            (notification_id, user_id, kind, title, body, link, iso(utc_now())),
        )
        self.conn.commit()
        return notification_id

    def list_notifications(
        self, user_id: str, *, limit: int = 50, unread_only: bool = False
    ) -> list[dict[str, Any]]:
        clause = "AND read_at IS NULL" if unread_only else ""
        rows = self.conn.execute(
            f"""SELECT * FROM notifications WHERE user_id = ? {clause}
            ORDER BY created_at DESC LIMIT ?""",
            (user_id, limit),
        ).fetchall()
        return [dict(row) for row in rows]

    def unread_count(self, user_id: str) -> int:
        row = self.conn.execute(
            "SELECT COUNT(*) AS n FROM notifications WHERE user_id = ? AND read_at IS NULL",
            (user_id,),
        ).fetchone()
        return int(row["n"]) if row else 0

    def mark_notifications_read(self, user_id: str, ids: list[str] | None = None) -> int:
        now = iso(utc_now())
        if ids:
            placeholders = ",".join("?" for _ in ids)
            cursor = self.conn.execute(
                f"""UPDATE notifications SET read_at = ?
                WHERE user_id = ? AND read_at IS NULL AND id IN ({placeholders})""",
                (now, user_id, *ids),
            )
        else:
            cursor = self.conn.execute(
                "UPDATE notifications SET read_at = ? WHERE user_id = ? AND read_at IS NULL",
                (now, user_id),
            )
        self.conn.commit()
        return cursor.rowcount

    # ---- announcements ----------------------------------------------------

    def upsert_announcement(self, payload: dict[str, Any]) -> str:
        from src.identity.infrastructure.store import new_id

        now = iso(utc_now())
        announcement_id = payload.get("id") or new_id("ann")
        self.conn.execute(
            """INSERT INTO announcements
            (id, title, body_md, level, published_at, expires_at, created_by, created_at, updated_at)
            VALUES (?,?,?,?,?,?,?,?,?)
            ON CONFLICT(id) DO UPDATE SET
            title = excluded.title, body_md = excluded.body_md, level = excluded.level,
            published_at = excluded.published_at, expires_at = excluded.expires_at,
            updated_at = excluded.updated_at""",
            (
                announcement_id,
                str(payload.get("title") or ""),
                str(payload.get("body_md") or ""),
                str(payload.get("level") or "info"),
                payload.get("published_at"),
                payload.get("expires_at"),
                str(payload.get("created_by") or ""),
                now,
                now,
            ),
        )
        self.conn.commit()
        return announcement_id

    def list_announcements(self, *, only_live: bool = True) -> list[dict[str, Any]]:
        if only_live:
            now = iso(utc_now())
            rows = self.conn.execute(
                """SELECT * FROM announcements
                WHERE published_at IS NOT NULL AND published_at <= ?
                AND (expires_at IS NULL OR expires_at > ?)
                ORDER BY published_at DESC LIMIT 20""",
                (now, now),
            ).fetchall()
        else:
            rows = self.conn.execute(
                "SELECT * FROM announcements ORDER BY created_at DESC LIMIT 100"
            ).fetchall()
        return [dict(row) for row in rows]

    def delete_announcement(self, announcement_id: str) -> bool:
        cursor = self.conn.execute("DELETE FROM announcements WHERE id = ?", (announcement_id,))
        self.conn.commit()
        return cursor.rowcount > 0

    # ---- api keys ----------------------------------------------------------

    def create_api_key(self, *, user_id: str, name: str, scopes: str = "read") -> tuple[str, str]:
        """返回 ``(key_id, 明文 key)``；明文只此一次，库里存 sha256。"""
        from src.identity.infrastructure.store import new_id, token_digest

        secret = secrets.token_urlsafe(32)
        plaintext = f"loci_{secret}"
        key_id = new_id("ak")
        self.conn.execute(
            """INSERT INTO api_keys (id, user_id, name, prefix, key_hash, scopes, created_at)
            VALUES (?,?,?,?,?,?,?)""",
            (
                key_id,
                user_id,
                name[:64],
                plaintext[:12],
                token_digest(plaintext),
                scopes,
                iso(utc_now()),
            ),
        )
        self.conn.commit()
        return key_id, plaintext

    def resolve_api_key(self, plaintext: str) -> dict[str, Any] | None:
        from src.identity.infrastructure.store import token_digest

        now = iso(utc_now())
        row = self.conn.execute(
            """SELECT * FROM api_keys WHERE key_hash = ? AND revoked_at IS NULL
            AND (expires_at IS NULL OR expires_at > ?)""",
            (token_digest(plaintext), now),
        ).fetchone()
        if row is None:
            return None
        self.conn.execute("UPDATE api_keys SET last_used_at = ? WHERE id = ?", (now, row["id"]))
        self.conn.commit()
        return dict(row)

    def list_api_keys(self, user_id: str) -> list[dict[str, Any]]:
        rows = self.conn.execute(
            """SELECT id, name, prefix, scopes, created_at, last_used_at, expires_at, revoked_at
            FROM api_keys WHERE user_id = ? ORDER BY created_at DESC""",
            (user_id,),
        ).fetchall()
        return [dict(row) for row in rows]

    def revoke_api_key(self, key_id: str, user_id: str) -> bool:
        cursor = self.conn.execute(
            "UPDATE api_keys SET revoked_at = ? WHERE id = ? AND user_id = ? AND revoked_at IS NULL",
            (iso(utc_now()), key_id, user_id),
        )
        self.conn.commit()
        return cursor.rowcount > 0
