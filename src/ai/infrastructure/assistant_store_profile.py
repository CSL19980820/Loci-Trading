"""助手画像与双仓记忆（ops.db）。"""
from __future__ import annotations

from typing import Any
from uuid import uuid4

from src.ai.domain.assistant import AssistantError
from src.ai.domain.assistant_defaults import (
    DEFAULT_MEMORY_SEEDS,
    DEFAULT_RESPONSE_STYLE,
    DEFAULT_RULES,
    PRODUCT_DEFAULTS_VERSION,
    _LEGACY_RESPONSE_STYLE_PREFIX_V2,
    _LEGACY_RESPONSE_STYLE_PREFIX_V3,
)
from src.ai.infrastructure.assistant_store_util import _dump, _load, _now, redact

PROFILE_ID = "default"
MEMORY_USER_LIMIT = 2200
MEMORY_NOTES_LIMIT = 4000
ABOUT_USER_LIMIT = 2000
RESPONSE_STYLE_LIMIT = 4000
RULES_TOTAL_LIMIT = 6000
DEFAULT_AUTO_MEMORY_MIN_TURNS = 20
AUTO_MEMORY_MIN_TURNS_MIN = 5
AUTO_MEMORY_MIN_TURNS_MAX = 100

_MEMORY_TARGETS = frozenset({"user", "memory"})
_MEMORY_SOURCES = frozenset({"manual", "tool", "auto", "builtin"})


class AssistantStoreProfileMixin:
    """画像 / 记忆读写；由 AssistantStore 混入。"""

    def _ensure_profile_schema(self, cur: Any) -> None:
        cur.executescript(
            """
            CREATE TABLE IF NOT EXISTS ai_assistant_profile (
                id TEXT PRIMARY KEY,
                about_user TEXT NOT NULL DEFAULT '',
                response_style TEXT NOT NULL DEFAULT '',
                rules_json TEXT NOT NULL DEFAULT '[]',
                memory_enabled INTEGER NOT NULL DEFAULT 1,
                auto_memory_enabled INTEGER NOT NULL DEFAULT 1,
                auto_memory_min_turns INTEGER NOT NULL DEFAULT 20,
                defaults_version INTEGER NOT NULL DEFAULT 0,
                updated_at TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS ai_memories (
                id TEXT PRIMARY KEY,
                target TEXT NOT NULL,
                content TEXT NOT NULL,
                source TEXT NOT NULL DEFAULT 'manual',
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            );
            CREATE INDEX IF NOT EXISTS idx_ai_memories_target ON ai_memories(target, updated_at DESC);
            """
        )
        cols = {
            str(row[1])
            for row in cur.execute("PRAGMA table_info(ai_assistant_profile)").fetchall()
        }
        if "defaults_version" not in cols:
            cur.execute(
                "ALTER TABLE ai_assistant_profile ADD COLUMN defaults_version INTEGER NOT NULL DEFAULT 0"
            )
        row = cur.execute(
            "SELECT about_user, response_style, rules_json, defaults_version"
            " FROM ai_assistant_profile WHERE id = ?",
            (PROFILE_ID,),
        ).fetchone()
        if row is None:
            now = _now()
            cur.execute(
                "INSERT INTO ai_assistant_profile("
                "id, about_user, response_style, rules_json,"
                " auto_memory_min_turns, defaults_version, updated_at"
                ") VALUES(?,?,?,?,?,?,?)",
                (
                    PROFILE_ID,
                    "",
                    DEFAULT_RESPONSE_STYLE,
                    _dump(list(DEFAULT_RULES)),
                    DEFAULT_AUTO_MEMORY_MIN_TURNS,
                    PRODUCT_DEFAULTS_VERSION,
                    now,
                ),
            )
            self._upsert_builtin_memories(cur)
            return
        version = int(row["defaults_version"] or 0)
        rules = _load(row["rules_json"], [])
        if not isinstance(rules, list):
            rules = []
        empty_personalization = (
            not str(row["about_user"] or "").strip()
            and not str(row["response_style"] or "").strip()
            and not any(str(item).strip() for item in rules)
        )
        style_text = str(row["response_style"] or "")
        legacy_product_pack = style_text.startswith(
            _LEGACY_RESPONSE_STYLE_PREFIX_V2
        ) or style_text.startswith(_LEGACY_RESPONSE_STYLE_PREFIX_V3)
        if version < PRODUCT_DEFAULTS_VERSION:
            # 始终刷新产品 builtin 记忆文档；规则/偏好仅在空或仍为旧产品种子时加厚
            if empty_personalization or legacy_product_pack:
                cur.execute(
                    "UPDATE ai_assistant_profile SET response_style=?, rules_json=?,"
                    " defaults_version=?, updated_at=? WHERE id=?",
                    (
                        DEFAULT_RESPONSE_STYLE,
                        _dump(list(DEFAULT_RULES)),
                        PRODUCT_DEFAULTS_VERSION,
                        _now(),
                        PROFILE_ID,
                    ),
                )
            else:
                cur.execute(
                    "UPDATE ai_assistant_profile SET defaults_version=? WHERE id=?",
                    (PRODUCT_DEFAULTS_VERSION, PROFILE_ID),
                )
            # 旧默认频率 8 → 产品新默认 20（用户已改成其他值则保留）
            cur.execute(
                "UPDATE ai_assistant_profile SET auto_memory_min_turns = ?"
                " WHERE id = ? AND auto_memory_min_turns = 8",
                (DEFAULT_AUTO_MEMORY_MIN_TURNS, PROFILE_ID),
            )
            self._upsert_builtin_memories(cur)

    def get_profile(self) -> dict[str, Any]:
        row = self.conn.execute(
            "SELECT * FROM ai_assistant_profile WHERE id = ?", (PROFILE_ID,)
        ).fetchone()
        if row is None:
            with self._tx() as cur:
                self._ensure_profile_schema(cur)
            row = self.conn.execute(
                "SELECT * FROM ai_assistant_profile WHERE id = ?", (PROFILE_ID,)
            ).fetchone()
        else:
            version = int(dict(row).get("defaults_version") or 0)
            if version < PRODUCT_DEFAULTS_VERSION:
                with self._tx() as cur:
                    self._ensure_profile_schema(cur)
                row = self.conn.execute(
                    "SELECT * FROM ai_assistant_profile WHERE id = ?", (PROFILE_ID,)
                ).fetchone()
        return self._profile(row)

    def reset_to_product_defaults(self, *, keep_about_user: bool = True) -> dict[str, Any]:
        """恢复产品默认规则/回答偏好，并幂等写入 builtin 工作记忆；默认保留「关于你」。"""
        with self._tx() as cur:
            self._ensure_profile_schema(cur)
            assignments = [
                "response_style = ?",
                "rules_json = ?",
                "defaults_version = ?",
                "auto_memory_min_turns = ?",
                "updated_at = ?",
            ]
            values: list[Any] = [
                DEFAULT_RESPONSE_STYLE,
                _dump(list(DEFAULT_RULES)),
                PRODUCT_DEFAULTS_VERSION,
                DEFAULT_AUTO_MEMORY_MIN_TURNS,
                _now(),
            ]
            if not keep_about_user:
                assignments.insert(0, "about_user = ?")
                values.insert(0, "")
            values.append(PROFILE_ID)
            cur.execute(
                f"UPDATE ai_assistant_profile SET {', '.join(assignments)} WHERE id = ?",
                values,
            )
            self._upsert_builtin_memories(cur)
        return self.get_profile()

    @staticmethod
    def _upsert_builtin_memories(cur: Any) -> None:
        now = _now()
        obsolete = ("AIMEM-BUILTIN-ENV", "AIMEM-BUILTIN-MEM")
        cur.execute(
            f"DELETE FROM ai_memories WHERE id IN ({','.join('?' for _ in obsolete)})",
            obsolete,
        )
        for seed in DEFAULT_MEMORY_SEEDS:
            existing = cur.execute(
                "SELECT id FROM ai_memories WHERE id = ?", (seed["id"],)
            ).fetchone()
            if existing:
                cur.execute(
                    "UPDATE ai_memories SET target=?, content=?, source=?, updated_at=? WHERE id=?",
                    (seed["target"], seed["content"], "builtin", now, seed["id"]),
                )
            else:
                cur.execute(
                    "INSERT INTO ai_memories(id, target, content, source, created_at, updated_at)"
                    " VALUES(?,?,?,?,?,?)",
                    (seed["id"], seed["target"], seed["content"], "builtin", now, now),
                )

    def set_memory_document(self, target: str, content: str, *, source: str = "manual") -> dict[str, Any]:
        """用一整段 Markdown 替换某仓全部记忆（设置页「一篇文档」语义）。"""
        cleaned_target = str(target).strip()
        if cleaned_target not in _MEMORY_TARGETS:
            raise AssistantError("记忆 target 必须是 user 或 memory")
        if source not in _MEMORY_SOURCES:
            raise AssistantError("非法记忆来源")
        text = str(redact(content)).strip()
        limit = MEMORY_USER_LIMIT if cleaned_target == "user" else MEMORY_NOTES_LIMIT
        if len(text) > limit:
            raise AssistantError(f"{'用户画像' if cleaned_target == 'user' else '工作记忆'}不得超过 {limit} 字")
        seed_id = next(
            (seed["id"] for seed in DEFAULT_MEMORY_SEEDS if seed["target"] == cleaned_target),
            None,
        )
        memory_id = seed_id or f"AIMEM-{uuid4().hex[:16].upper()}"
        now = _now()
        with self._tx() as cur:
            self._ensure_profile_schema(cur)
            cur.execute("DELETE FROM ai_memories WHERE target = ?", (cleaned_target,))
            if text:
                cur.execute(
                    "INSERT INTO ai_memories(id, target, content, source, created_at, updated_at)"
                    " VALUES(?,?,?,?,?,?)",
                    (memory_id, cleaned_target, text, source, now, now),
                )
        row = self.get_memory(memory_id) if text else None
        return {
            "target": cleaned_target,
            "content": text,
            "item": row,
            "usage": self.memory_char_usage(cleaned_target),
        }

    def update_profile(self, **fields: Any) -> dict[str, Any]:
        allowed = {
            "about_user",
            "response_style",
            "rules",
            "memory_enabled",
            "auto_memory_enabled",
            "auto_memory_min_turns",
        }
        unknown = set(fields) - allowed
        if unknown:
            raise AssistantError(f"不支持的画像字段：{sorted(unknown)}")
        if not fields:
            return self.get_profile()

        about = fields.get("about_user")
        style = fields.get("response_style")
        rules = fields.get("rules")
        if about is not None:
            about = str(redact(about)).strip()
            if len(about) > ABOUT_USER_LIMIT:
                raise AssistantError(f"关于你不得超过 {ABOUT_USER_LIMIT} 字")
        if style is not None:
            style = str(redact(style)).strip()
            if len(style) > RESPONSE_STYLE_LIMIT:
                raise AssistantError(f"回答偏好不得超过 {RESPONSE_STYLE_LIMIT} 字")
        if rules is not None:
            if not isinstance(rules, list) or any(not isinstance(item, str) for item in rules):
                raise AssistantError("规则必须是字符串数组")
            cleaned = [str(redact(item)).strip() for item in rules if str(item).strip()]
            total = sum(len(item) for item in cleaned)
            if total > RULES_TOTAL_LIMIT:
                raise AssistantError(f"规则总长不得超过 {RULES_TOTAL_LIMIT} 字")
            rules = cleaned
        min_turns = fields.get("auto_memory_min_turns")
        if min_turns is not None:
            min_turns = int(min_turns)
            if not AUTO_MEMORY_MIN_TURNS_MIN <= min_turns <= AUTO_MEMORY_MIN_TURNS_MAX:
                raise AssistantError(f"自动记忆频率须在 {AUTO_MEMORY_MIN_TURNS_MIN}-{AUTO_MEMORY_MIN_TURNS_MAX} 之间")

        assignments: list[str] = []
        values: list[Any] = []
        if about is not None:
            assignments.append("about_user = ?")
            values.append(about)
        if style is not None:
            assignments.append("response_style = ?")
            values.append(style)
        if rules is not None:
            assignments.append("rules_json = ?")
            values.append(_dump(rules))
        if "memory_enabled" in fields:
            assignments.append("memory_enabled = ?")
            values.append(1 if fields["memory_enabled"] else 0)
        if "auto_memory_enabled" in fields:
            assignments.append("auto_memory_enabled = ?")
            values.append(1 if fields["auto_memory_enabled"] else 0)
        if min_turns is not None:
            assignments.append("auto_memory_min_turns = ?")
            values.append(min_turns)
        assignments.append("updated_at = ?")
        values.extend([_now(), PROFILE_ID])
        with self._tx() as cur:
            self._ensure_profile_schema(cur)
            cur.execute(
                f"UPDATE ai_assistant_profile SET {', '.join(assignments)} WHERE id = ?",
                values,
            )
        return self.get_profile()

    def list_memories(self, *, target: str | None = None) -> list[dict[str, Any]]:
        if target is not None and target not in _MEMORY_TARGETS:
            raise AssistantError("记忆 target 必须是 user 或 memory")
        if target:
            rows = self.conn.execute(
                "SELECT * FROM ai_memories WHERE target = ? ORDER BY updated_at DESC, id DESC",
                (target,),
            )
        else:
            rows = self.conn.execute(
                "SELECT * FROM ai_memories ORDER BY target, updated_at DESC, id DESC"
            )
        return [self._memory(row) for row in rows]

    def get_memory(self, memory_id: str) -> dict[str, Any] | None:
        row = self.conn.execute("SELECT * FROM ai_memories WHERE id = ?", (memory_id,)).fetchone()
        return self._memory(row) if row else None

    def add_memory(
        self, *, target: str, content: str, source: str = "manual"
    ) -> dict[str, Any]:
        target = str(target).strip()
        source = str(source).strip() or "manual"
        text = str(redact(content)).strip()
        if target not in _MEMORY_TARGETS:
            raise AssistantError("记忆 target 必须是 user 或 memory")
        if source not in _MEMORY_SOURCES:
            raise AssistantError("记忆 source 无效")
        if not text:
            raise AssistantError("记忆内容不能为空")
        if len(text) > MEMORY_NOTES_LIMIT:
            raise AssistantError("单条记忆过长")
        memory_id = f"AIMEM-{uuid4().hex[:16].upper()}"
        now = _now()
        with self._tx() as cur:
            self._ensure_profile_schema(cur)
            self._assert_memory_capacity(cur, target, extra=len(text))
            cur.execute(
                "INSERT INTO ai_memories(id, target, content, source, created_at, updated_at)"
                " VALUES(?,?,?,?,?,?)",
                (memory_id, target, text, source, now, now),
            )
        return self.get_memory(memory_id) or {}

    def update_memory(
        self, memory_id: str, *, content: str | None = None, target: str | None = None
    ) -> dict[str, Any]:
        current = self.get_memory(memory_id)
        if current is None:
            raise AssistantError("记忆不存在")
        new_target = str(target).strip() if target is not None else str(current["target"])
        new_content = str(redact(content)).strip() if content is not None else str(current["content"])
        if new_target not in _MEMORY_TARGETS:
            raise AssistantError("记忆 target 必须是 user 或 memory")
        if not new_content:
            raise AssistantError("记忆内容不能为空")
        with self._tx() as cur:
            self._assert_memory_capacity(
                cur,
                new_target,
                extra=len(new_content),
                exclude_id=memory_id,
            )
            cur.execute(
                "UPDATE ai_memories SET target=?, content=?, updated_at=? WHERE id=?",
                (new_target, new_content, _now(), memory_id),
            )
            if cur.rowcount != 1:
                raise AssistantError("记忆不存在")
        return self.get_memory(memory_id) or {}

    def delete_memory(self, memory_id: str) -> bool:
        with self._tx() as cur:
            cur.execute("DELETE FROM ai_memories WHERE id = ?", (memory_id,))
            return cur.rowcount == 1

    def replace_memory_by_text(
        self, *, target: str, old_text: str, content: str, source: str = "tool"
    ) -> dict[str, Any]:
        needle = str(old_text).strip()
        if not needle:
            raise AssistantError("old_text 不能为空")
        rows = self.list_memories(target=target)
        match = next((row for row in rows if needle in str(row["content"])), None)
        if match is None:
            raise AssistantError("未找到要替换的记忆")
        return self.update_memory(str(match["id"]), content=content)

    def remove_memory_by_text(self, *, target: str, old_text: str) -> bool:
        needle = str(old_text).strip()
        if not needle:
            raise AssistantError("old_text 不能为空")
        rows = self.list_memories(target=target)
        match = next((row for row in rows if needle in str(row["content"])), None)
        if match is None:
            raise AssistantError("未找到要删除的记忆")
        return self.delete_memory(str(match["id"]))

    def memory_char_usage(self, target: str) -> int:
        row = self.conn.execute(
            "SELECT COALESCE(SUM(LENGTH(content)), 0) AS total FROM ai_memories WHERE target = ?",
            (target,),
        ).fetchone()
        return int(row["total"] if row else 0)

    def count_dialog_messages(self, session_id: str) -> int:
        row = self.conn.execute(
            "SELECT COUNT(*) AS n FROM ai_messages"
            " WHERE session_id = ? AND role IN ('user', 'assistant')",
            (session_id,),
        ).fetchone()
        return int(row["n"] if row else 0)

    def _assert_memory_capacity(
        self, cur: Any, target: str, *, extra: int, exclude_id: str | None = None
    ) -> None:
        limit = MEMORY_USER_LIMIT if target == "user" else MEMORY_NOTES_LIMIT
        if exclude_id:
            row = cur.execute(
                "SELECT COALESCE(SUM(LENGTH(content)), 0) AS total FROM ai_memories"
                " WHERE target = ? AND id <> ?",
                (target, exclude_id),
            ).fetchone()
        else:
            row = cur.execute(
                "SELECT COALESCE(SUM(LENGTH(content)), 0) AS total FROM ai_memories WHERE target = ?",
                (target,),
            ).fetchone()
        used = int(row["total"] if row else 0)
        if used + extra > limit:
            raise AssistantError(
                f"{target} 记忆仓已满（{used}+{extra}/{limit}），请先合并或删除旧条目"
            )

    @staticmethod
    def _profile(row: Any) -> dict[str, Any]:
        out = dict(row)
        out["rules"] = _load(out.pop("rules_json"), [])
        if not isinstance(out["rules"], list):
            out["rules"] = []
        out["memory_enabled"] = bool(out.get("memory_enabled", 1))
        out["auto_memory_enabled"] = bool(out.get("auto_memory_enabled", 1))
        out["auto_memory_min_turns"] = int(
            out.get("auto_memory_min_turns") or DEFAULT_AUTO_MEMORY_MIN_TURNS
        )
        out["defaults_version"] = int(out.get("defaults_version") or 0)
        return out

    @staticmethod
    def _memory(row: Any) -> dict[str, Any]:
        return dict(row)
