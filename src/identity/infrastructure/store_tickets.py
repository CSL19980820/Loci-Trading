"""IdentityStore 的票据部分：邮箱验证 / 密码重置 / 扫码登录 state。

两类票据都遵守同一组规则：

1. 库里只存 ``sha256(token)``，明文只在邮件正文或 Cookie 里出现一次。
2. **单次使用**。用过即写 ``used_at`` / 状态推进到 ``consumed``，重放无效。
3. 有效期短：邮箱验证 24h、密码重置 30min、扫码 5min。
4. 状态推进用**条件 UPDATE**（CAS），不是「先查再写」——后者在并发下会双花。
"""
from __future__ import annotations

from typing import Any
import secrets
import sqlite3

from src.identity.domain.models import QrStatus, in_seconds, iso, utc_now

#: 邮箱验证 24 小时；密码重置 30 分钟（OWASP 建议重置窗口尽量短）。
VERIFY_TTL_SEC = 24 * 3600
RESET_TTL_SEC = 30 * 60
#: 扫码票据 5 分钟，与微信带参二维码的 expire_seconds 量级对齐。
QR_TTL_SEC = 300


class AuthTicketsMixin:
    """依赖宿主提供 ``conn``。"""

    conn: sqlite3.Connection

    # ---- email verifications -------------------------------------------

    def create_verification(
        self,
        *,
        user_id: str,
        email: str,
        purpose: str = "verify",
        request_ip: str = "",
    ) -> tuple[str, str]:
        """作废该用途的旧票据并签发新票据，返回 ``(明文 token, 6 位数字码)``。

                同时给 token 与 code 两种形态：邮件里既可以放链接（桌面端方便），
           也可以放验证码（手机上复制粘贴更省事）。两者指向同一行。
           """
        from src.identity.infrastructure.store import new_id, token_digest

        self.conn.execute(
            """UPDATE email_verifications SET used_at = ?
            WHERE user_id = ? AND purpose = ? AND used_at IS NULL""",
            (iso(utc_now()), user_id, purpose),
        )
        token = secrets.token_urlsafe(32)
        code = f"{secrets.randbelow(1000000):06d}"
        ttl = VERIFY_TTL_SEC if purpose == "verify" else RESET_TTL_SEC
        self.conn.execute(
            """INSERT INTO email_verifications
            (id, user_id, purpose, email, token_hash, code, expires_at, request_ip, created_at)
            VALUES (?,?,?,?,?,?,?,?,?)""",
            (
                new_id("evt"),
                user_id,
                purpose,
                email,
                token_digest(token),
                code,
                in_seconds(ttl),
                request_ip[:64],
                iso(utc_now()),
            ),
        )
        self.conn.commit()
        return token, code

    def consume_verification(
        self, *, token: str = "", code: str = "", email: str = "", purpose: str = "verify"
    ) -> dict[str, Any] | None:
        """校验并一次性消费票据。token 与 code 二选一。"""
        from src.identity.infrastructure.store import token_digest

        now = iso(utc_now())
        if token:
            row = self.conn.execute(
                """SELECT * FROM email_verifications
                WHERE token_hash = ? AND purpose = ? AND used_at IS NULL AND expires_at > ?""",
                (token_digest(token), purpose, now),
            ).fetchone()
        elif code and email:
            row = self.conn.execute(
                """SELECT * FROM email_verifications
                WHERE code = ? AND lower(email) = ? AND purpose = ?
                AND used_at IS NULL AND expires_at > ?""",
                (code, email.lower(), purpose, now),
            ).fetchone()
        else:
            row = None
        if row is None:
            return None
        cursor = self.conn.execute(
            "UPDATE email_verifications SET used_at = ? WHERE id = ? AND used_at IS NULL",
            (now, row["id"]),
        )
        self.conn.commit()
        if cursor.rowcount == 0:
            # 并发下被别人先消费掉了。宁可让这次失败，也不能双花。
            return None
        return dict(row)

    def last_verification_at(self, user_id: str, purpose: str) -> str | None:
        row = self.conn.execute(
            """SELECT created_at FROM email_verifications
            WHERE user_id = ? AND purpose = ? ORDER BY created_at DESC LIMIT 1""",
            (user_id, purpose),
        ).fetchone()
        return row["created_at"] if row else None

    # ---- oauth / qr states ---------------------------------------------

    def create_oauth_state(
        self,
        *,
        provider: str,
        binding_hash: str = "",
        redirect_to: str = "/",
        qr_content: str = "",
        ttl_sec: int = QR_TTL_SEC,
    ) -> str:
        state = secrets.token_urlsafe(32)
        now = iso(utc_now())
        self.conn.execute(
            """INSERT INTO oauth_states
            (state, provider, status, binding_hash, qr_content, redirect_to,
            created_at, updated_at, expires_at)
            VALUES (?,?,'pending',?,?,?,?,?,?)""",
            (state, provider, binding_hash, qr_content, redirect_to, now, now, in_seconds(ttl_sec)),
        )
        self.conn.commit()
        return state

    def get_oauth_state(self, state: str) -> dict[str, Any] | None:
        row = self.conn.execute(
            "SELECT * FROM oauth_states WHERE state = ?", (state,)
        ).fetchone()
        return dict(row) if row else None

    def advance_oauth_state(
        self,
        state: str,
        *,
        to: QrStatus,
        expect: tuple[str, ...] = (),
        user_id: str | None = None,
        session_token_hash: str | None = None,
        error: str | None = None,
    ) -> bool:
        """条件推进状态机。``expect`` 为空表示不限制来源状态。

                confirmed → consumed 必须带 ``expect=(\"confirmed\",)``：这一条 CAS
           就是防重放的全部——同一个 state 只能兑出一个会话。
           """
        clauses = ["state = ?", "expires_at > ?"]
        params: list[Any] = [state, iso(utc_now())]
        if expect:
            placeholders = ",".join("?" for _ in expect)
            clauses.append(f"status IN ({placeholders})")
            params.extend(expect)
        assignments = ["status = ?", "updated_at = ?"]
        values: list[Any] = [to, iso(utc_now())]
        if user_id is not None:
            assignments.append("user_id = ?")
            values.append(user_id)
        if session_token_hash is not None:
            assignments.append("session_token_hash = ?")
            values.append(session_token_hash)
        if error is not None:
            assignments.append("error = ?")
            values.append(error)
        cursor = self.conn.execute(
            f"UPDATE oauth_states SET {', '.join(assignments)} WHERE {' AND '.join(clauses)}",
            (*values, *params),
        )
        self.conn.commit()
        return cursor.rowcount > 0

    def fail_oauth_state(self, state: str, message: str) -> None:
        """失败态不受 expires_at 约束——过期票据也要能记下失败原因供排查。"""
        self.conn.execute(
            "UPDATE oauth_states SET status = 'failed', error = ?, updated_at = ? WHERE state = ?",
            (message[:256], iso(utc_now()), state),
        )
        self.conn.commit()
