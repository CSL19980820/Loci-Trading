"""IdentityStore：identity.db 的唯一读写口。

连接策略与 ops/palace 对齐：每次构造开一条新连接，WAL + busy_timeout，
用完 close。不做连接池——SQLite 的并发瓶颈在写锁，不在连接创建。

**这里的 SQL 是全仓唯一能读到 password_hash 与 session id 的地方。**
任何「顺手在别处查一下 users 表」的写法都要挡回来：绕过这里就绕过了
``status``/``revoked_at`` 这些闸门。
"""
from __future__ import annotations

from datetime import timedelta
from pathlib import Path
from typing import Any
import hashlib
import json
import secrets
import sqlite3

from src.identity.domain.models import (
    ConflictError,
    AuthenticationError,
    ValidationError,
    Identity,
    SessionInfo,
    User,
    iso,
    in_seconds,
    utc_now,
)
from src.identity.infrastructure.schema import apply_schema
from src.identity.infrastructure.store_platform import PlatformMixin, like_needle
from src.identity.infrastructure.store_tickets import AuthTicketsMixin

#: 会话滑动窗口与绝对上限。滑动 7 天覆盖「每周用一次」的研究者；
#: 绝对 30 天确保改密/离职后最长一个月一定掉线。
SESSION_SLIDING_SEC = 7 * 24 * 3600
SESSION_ABSOLUTE_SEC = 30 * 24 * 3600


def new_id(prefix: str) -> str:
    """业务 id：前缀 + 12 位 url-safe 随机。不用自增，防遍历枚举。"""
    body = secrets.token_hex(6)
    return f"{prefix}_{body}"


def token_digest(token: str) -> str:
    """会话/验证 token 的库内形态。token 本身高熵，sha256 足够，不需要慢哈希。"""
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def _dumps(payload: Any) -> str:
    return json.dumps(payload, ensure_ascii=False, separators=(",", ":"))


def _loads(raw: str | None) -> Any:
    if not raw:
        return {}
    try:
        return json.loads(raw)
    except (TypeError, ValueError):
        return {}


def _user_filters(keyword: str = "", status: str = "") -> tuple[str, list[Any]]:
    """用户列表/计数共用的 WHERE 条件（不含 ``WHERE`` 关键字，恒非空）。

    ``status <> 'deleted'`` 是基线：软删的账号不该出现在任何后台列表里，也不该
    被计入总数。列表与计数分开手写过一次就一定会漂移，让分页器数字对不上。

    LIKE 的 ``%`` ``_`` 一律转义（配 ``ESCAPE '\\'``）：管理员在搜索框敲一个
    ``%`` 不该等于「把全表捞出来」。
    """
    clauses = ["status <> 'deleted'"]
    params: list[Any] = []
    if keyword:
        clauses.append(
            "(lower(username) LIKE ? ESCAPE '\\' OR lower(email) LIKE ? ESCAPE '\\'"
            " OR display_name LIKE ? ESCAPE '\\')"
        )
        lowered = like_needle(keyword.lower())
        params.extend([lowered, lowered, like_needle(keyword)])
    if status:
        clauses.append("status = ?")
        params.append(status)
    return " AND ".join(clauses), params


class IdentityStore(AuthTicketsMixin, PlatformMixin):
    """identity.db 门面。用作上下文管理器：``with IdentityStore(path) as store:``。"""

    def __init__(self, db_path: Path | str | None = None) -> None:
        from src.shared.paths import identity_db

        resolved = Path(db_path) if db_path else identity_db()
        resolved.parent.mkdir(parents=True, exist_ok=True)
        self.db_path = resolved
        self.conn = sqlite3.connect(str(resolved), timeout=30)
        self.conn.row_factory = sqlite3.Row
        self.conn.execute("PRAGMA foreign_keys = ON")
        self.conn.execute("PRAGMA busy_timeout = 30000")
        try:
            self.conn.execute("PRAGMA journal_mode = WAL")
        except sqlite3.DatabaseError:
            # 只读挂载或网络盘上 WAL 会失败；退回默认日志模式仍可用。
            pass
        apply_schema(self.conn)

    def __enter__(self) -> IdentityStore:
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()

    def close(self) -> None:
        try:
            self.conn.close()
        except sqlite3.Error:
            pass

    # ---- users ---------------------------------------------------------

    @staticmethod
    def _user(row: sqlite3.Row | None) -> User | None:
        if row is None:
            return None
        return User(
            id=row["id"],
            tenant_id=row["tenant_id"],
            username=row["username"],
            email=row["email"],
            display_name=row["display_name"],
            role=row["role"],
            status=row["status"],
            avatar_url=row["avatar_url"],
            bio=row["bio"],
            email_verified_at=row["email_verified_at"],
            password_algo=row["password_algo"],
            created_at=row["created_at"],
            updated_at=row["updated_at"],
            last_login_at=row["last_login_at"],
            must_change_password=bool(row["must_change_password"]),
            view_tenant_id=row["view_tenant_id"],
        )

    def create_user(
        self,
        *,
        username: str,
        email: str,
        password_hash: str | None,
        password_algo: str,
        display_name: str = "",
        role: str = "visitor",
        status: str = "pending",
        tenant_id: str | None = None,
        must_change_password: bool = False,
        view_tenant_id: str = "",
    ) -> User:
        if role not in ("admin", "visitor"):
            raise ValidationError("角色只能是 admin 或 visitor")
        now = iso(utc_now())
        user_id = new_id("u")
        resolved_tenant = tenant_id or user_id
        try:
            self.conn.execute(
                """INSERT INTO users (id, tenant_id, username, email, password_hash, password_algo,
                password_updated_at, must_change_password, display_name, role, status,
                created_at, updated_at, view_tenant_id)
                VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                (
                    user_id,
                    resolved_tenant,
                    username,
                    email,
                    password_hash,
                    password_algo,
                    now if password_hash else None,
                    1 if must_change_password else 0,
                    display_name or username,
                    role,
                    status,
                    now,
                    now,
                    (view_tenant_id or resolved_tenant) if role == "visitor" else "",
                ),
            )
        except sqlite3.IntegrityError as exc:
            raise ConflictError("登录名或邮箱已被占用") from exc
        self.conn.commit()
        found = self.get_user(user_id)
        assert found is not None
        return found

    def get_user(self, user_id: str) -> User | None:
        row = self.conn.execute("SELECT * FROM users WHERE id = ?", (user_id,)).fetchone()
        return self._user(row)

    def get_user_by_login(self, handle: str) -> User | None:
        """登录名或邮箱都能登。两者都建了 lower() 唯一索引，不会撞车。"""
        value = (handle or "").strip().lower()
        if not value:
            return None
        row = self.conn.execute(
            "SELECT * FROM users WHERE lower(username) = ? OR (email <> '' AND lower(email) = ?)",
            (value, value),
        ).fetchone()
        return self._user(row)

    def get_password_hash(self, user_id: str) -> str | None:
        row = self.conn.execute(
            "SELECT password_hash FROM users WHERE id = ?", (user_id,)
        ).fetchone()
        return row["password_hash"] if row else None

    def set_password(self, user_id: str, *, password_hash: str, algo: str) -> None:
        now = iso(utc_now())
        self.conn.execute(
            """UPDATE users SET password_hash = ?, password_algo = ?, password_updated_at = ?,
            must_change_password = 0, updated_at = ? WHERE id = ?""",
            (password_hash, algo, now, now, user_id),
        )
        self.conn.commit()

    def update_user(self, user_id: str, **fields: Any) -> User | None:
        """白名单字段更新。不在名单里的键直接忽略，避免路由层字段漏检写穿。"""
        allowed = {
            "username",
            "email",
            "display_name",
            "avatar_url",
            "bio",
            "role",
            "status",
            "email_verified_at",
            "last_login_at",
            "must_change_password",
            "view_tenant_id",
        }
        updates = {key: value for key, value in fields.items() if key in allowed}
        if not updates:
            return self.get_user(user_id)
        updates["updated_at"] = iso(utc_now())
        assignments = ", ".join(f"{key} = ?" for key in updates)
        try:
            self.conn.execute(
                 f"UPDATE users SET {assignments} WHERE id = ?",
                (*updates.values(), user_id),
            )
        except sqlite3.IntegrityError as exc:
            raise ConflictError("登录名或邮箱已被占用") from exc
        self.conn.commit()
        return self.get_user(user_id)

    def list_users(
        self, *, limit: int = 50, offset: int = 0, keyword: str = "", status: str = ""
    ) -> list[User]:
        where, params = _user_filters(keyword, status)
        rows = self.conn.execute(
            f"SELECT * FROM users WHERE {where} ORDER BY created_at DESC LIMIT ? OFFSET ?",
            (*params, limit, offset),
        ).fetchall()
        return [user for user in (self._user(row) for row in rows) if user is not None]

    def count_users(self, *, keyword: str = "", status: str = "") -> int:
        """匹配 ``list_users`` 同一份过滤条件的总数。

        **无参调用的语义不变**：仍是「未软删的账号总数」——``platform_overview``
        与首启种子（``tenant = PRIMARY_TENANT if not store.count_users()``）都靠它。
        """
        where, params = _user_filters(keyword, status)
        row = self.conn.execute(f"SELECT COUNT(*) AS n FROM users WHERE {where}", params).fetchone()
        return int(row["n"]) if row else 0

    def admin_exists(self) -> bool:
        row = self.conn.execute(
            "SELECT 1 FROM users WHERE role = 'admin' AND status = 'active' LIMIT 1"
        ).fetchone()
        return row is not None

    # ---- identities ----------------------------------------------------

    @staticmethod
    def _identity(row: sqlite3.Row | None) -> Identity | None:
        if row is None:
            return None
        return Identity(
            id=row["id"],
            user_id=row["user_id"],
            provider=row["provider"],
            family=row["family"],
            subject=row["subject"],
            union_key=row["union_key"],
            display_name=row["display_name"],
            avatar_url=row["avatar_url"],
            created_at=row["created_at"],
            last_login_at=row["last_login_at"],
        )

    def find_identity(self, provider: str, subject: str) -> Identity | None:
        row = self.conn.execute(
            "SELECT * FROM identities WHERE provider = ? AND subject = ?",
            (provider, subject),
        ).fetchone()
        return self._identity(row)

    def find_identity_by_union(self, family: str, union_key: str) -> Identity | None:
        """unionid 的作用域是「厂商开放平台账号」，不是单个应用。

              同一个微信用户从网站应用和公众号进来 openid 不同、unionid 相同，
                靠这条查询把两次登录合并到同一个账号。
                """
        if not union_key:
            return None
        row = self.conn.execute(
            "SELECT * FROM identities WHERE family = ? AND union_key = ?",
            (family, union_key),
        ).fetchone()
        return self._identity(row)

    def list_identities(self, user_id: str) -> list[Identity]:
        rows = self.conn.execute(
            "SELECT * FROM identities WHERE user_id = ? ORDER BY created_at", (user_id,)
        ).fetchall()
        return [item for item in (self._identity(row) for row in rows) if item is not None]

    def upsert_identity(
        self,
        *,
        user_id: str,
        provider: str,
        family: str,
        subject: str,
        union_key: str | None = None,
        display_name: str = "",
        avatar_url: str = "",
        raw_profile: Any = None,
    ) -> Identity:
        now = iso(utc_now())
        existing = self.find_identity(provider, subject)
        if existing is not None:
            self.conn.execute(
                """UPDATE identities SET union_key = COALESCE(NULLIF(?, ''), union_key),
                display_name = ?, avatar_url = ?, raw_profile = ?, updated_at = ?,
                last_login_at = ? WHERE id = ?""",
                (
                    union_key or "",
                    display_name,
                    avatar_url,
                    _dumps(raw_profile or {}),
                    now,
                    now,
                    existing.id,
                ),
            )
            self.conn.commit()
            found = self.find_identity(provider, subject)
            assert found is not None
            return found
        identity_id = new_id("idt")
        try:
            self.conn.execute(
                """INSERT INTO identities (id, user_id, provider, family, subject, union_key,
                display_name, avatar_url, raw_profile, created_at, updated_at, last_login_at)
                VALUES (?,?,?,?,?,?,?,?,?,?,?,?)""",
                (
                    identity_id,
                    user_id,
                    provider,
                    family,
                    subject,
                    union_key or None,
                    display_name,
                    avatar_url,
                    _dumps(raw_profile or {}),
                    now,
                    now,
                    now,
                ),
            )
        except sqlite3.IntegrityError as exc:
            raise ConflictError("该第三方账号已绑定到其他用户") from exc
        self.conn.commit()
        found = self.find_identity(provider, subject)
        assert found is not None
        return found

    def delete_identity(self, identity_id: str, user_id: str) -> bool:
        cursor = self.conn.execute(
            "DELETE FROM identities WHERE id = ? AND user_id = ?", (identity_id, user_id)
        )
        self.conn.commit()
        return cursor.rowcount > 0

    # ---- sessions ------------------------------------------------------

    def create_session(
        self,
        *,
        user_id: str,
        identity_id: str | None = None,
        ip: str = "",
        user_agent: str = "",
    ) -> str:
        """返回**明文 token**（只此一次）。库里只留 sha256。"""
        token = secrets.token_urlsafe(32)
        now = utc_now()
        # Revocation and creation share the same SQLite write transaction. A pair
        # of concurrent visitor logins can never leave two live sessions behind.
        with self.conn:
            self.conn.execute("BEGIN IMMEDIATE")
            user = self.get_user(user_id)
            if user is None or not user.can_login:
                raise AuthenticationError("账号不可登录")
            if not user.is_admin:
                self.conn.execute(
                    "UPDATE sessions SET revoked_at = ? WHERE user_id = ? AND revoked_at IS NULL",
                    (iso(now), user_id),
                )
            self.conn.execute(
                """INSERT INTO sessions (id, user_id, identity_id, created_at, last_seen_at,
                expires_at, absolute_expires_at, ip, user_agent) VALUES (?,?,?,?,?,?,?,?,?)""",
                (token_digest(token), user_id, identity_id, iso(now), iso(now),
                 in_seconds(SESSION_SLIDING_SEC, now=now), in_seconds(SESSION_ABSOLUTE_SEC, now=now),
                 ip[:64], user_agent[:256]),
            )
        return token

    def get_session(self, token: str) -> SessionInfo | None:
        row = self.conn.execute(
            "SELECT * FROM sessions WHERE id = ?", (token_digest(token),)
        ).fetchone()
        if row is None:
            return None
        return SessionInfo(
            id=row["id"],
            user_id=row["user_id"],
            identity_id=row["identity_id"],
            created_at=row["created_at"],
            last_seen_at=row["last_seen_at"],
            expires_at=row["expires_at"],
            absolute_expires_at=row["absolute_expires_at"],
            revoked_at=row["revoked_at"],
            ip=row["ip"],
            user_agent=row["user_agent"],
        )

    def touch_session(self, session_id: str) -> None:
        """滑动续期。绝对上限不动——那才是真正的天花板。"""
        now = utc_now()
        self.conn.execute(
            "UPDATE sessions SET last_seen_at = ?, expires_at = ? WHERE id = ?",
            (iso(now), in_seconds(SESSION_SLIDING_SEC, now=now), session_id),
        )
        self.conn.commit()

    def revoke_session(self, session_id: str) -> None:
        self.conn.execute(
            "UPDATE sessions SET revoked_at = ? WHERE id = ? AND revoked_at IS NULL",
            (iso(utc_now()), session_id),
        )
        self.conn.commit()

    def revoke_user_sessions(self, user_id: str, *, keep_session_id: str = "") -> int:
        """改密 / 封号 / 远程下线。这是「服务端会话」相对 JWT 的核心价值。"""
        cursor = self.conn.execute(
            "UPDATE sessions SET revoked_at = ? WHERE user_id = ? AND revoked_at IS NULL AND id <> ?",
            (iso(utc_now()), user_id, keep_session_id),
        )
        self.conn.commit()
        return cursor.rowcount

    def list_sessions(self, user_id: str) -> list[dict[str, Any]]:
        rows = self.conn.execute(
            """SELECT id, created_at, last_seen_at, expires_at, ip, user_agent, revoked_at
            FROM sessions WHERE user_id = ? ORDER BY last_seen_at DESC LIMIT 50""",
            (user_id,),
        ).fetchall()
        return [dict(row) for row in rows]

    def purge_expired(self) -> int:
        """清理过期会话与票据。挂在运维清理任务上，不影响任何账本语义。"""
        now = iso(utc_now())
        total = 0
        total += self.conn.execute(
            "DELETE FROM sessions WHERE absolute_expires_at < ?", (now,)
        ).rowcount
        total += self.conn.execute(
            "DELETE FROM oauth_states WHERE expires_at < ?", (now,)
        ).rowcount
        total += self.conn.execute(
            "DELETE FROM email_verifications WHERE expires_at < ? AND used_at IS NULL", (now,)
        ).rowcount
        self.conn.commit()
        return total

    def purge_notifications(self, *, read_days: int = 15, unread_days: int = 90) -> int:
        """按保留期清理站内通知。已读的短留，未读的长留。

        **必须用 ``julianday`` 而不是字符串比较。** ``created_at`` 是带偏移的
        ISO 串（``...T...+08:00``），跟裸 UTC 串直接比会差 8 小时，而且
        ``'T' > ' '`` 让排序也一起错。这是 ``store_runs.RUN_STALE_SQL`` 已经
        踩过的同一个坑。

        未读留得久，是因为「没看到」和「看过了」不是一回事：把一条用户还没
        读过的通知按 15 天删掉，等于替他决定这条消息不重要。
        """
        read_cut = f"-{max(int(read_days), 0)} days"
        unread_cut = f"-{max(int(unread_days), 0)} days"
        removed = self.conn.execute(
            """DELETE FROM notifications
            WHERE (read_at IS NOT NULL AND julianday(created_at) < julianday('now', ?))
               OR (read_at IS NULL AND julianday(created_at) < julianday('now', ?))""",
            (read_cut, unread_cut),
        ).rowcount
        self.conn.commit()
        return removed

    def purge_usage_counters(self, *, keep_days: int = 15) -> int:
        """清理过期的**日粒度**用量计数。

        ``period`` 是 ``'2026-08'``（月）或 ``'2026-08-27'``（日）两种形状。
        这里**只删日粒度**：月计数一行一个月，攒一年也才 12 行，而它正是
        ``llm_monthly_tokens`` 判定的依据，删了当月配额会凭空复位。

        日期键是定长零填充的纯日期，字符串比较即正确；**不要**在这里套
        ``julianday``——它对 ``'2026-08'`` 这种月份键返回 NULL，会把月计数
        静默漏出清理范围（今天恰好是我们要的结果，但那是巧合不是判断）。
        ``length(period) = 10`` 才是那个判断，写出来才改得动。
        """
        cutoff = utc_now() - timedelta(days=max(int(keep_days), 0))
        removed = self.conn.execute(
            "DELETE FROM usage_counters WHERE length(period) = 10 AND period < ?",
            (cutoff.strftime("%Y-%m-%d"),),
        ).rowcount
        self.conn.commit()
        return removed

    def get_user_by_tenant(self, tenant_id: str) -> User | None:
        """按租户反查用户。清理任务解析 ``storage_mb`` 配额时用。

        没有这条，调用方只能分页扫 ``list_users`` 逐个比对 ``tenant_id``——
        用户上千之后每次清理都要扫全表。
        """
        row = self.conn.execute(
            "SELECT * FROM users WHERE tenant_id = ? AND status <> 'deleted' LIMIT 1",
            (tenant_id,),
        ).fetchone()
        return self._user(row)
