"""AI 决策留痕：记录每一轮「模型看到了什么、说了什么、最后成交了什么」。

为什么单独一张表而不是塞进 ``monitor_runs.snapshot_json``：

- ``monitor_runs`` 的 snapshot 只存 codes 列表，**不存报价数值**，事后无法知道
  模型当时看到的是什么价；prompt 原文与模型原始回复也完全没落盘。缺这三样，
  「AI 当时凭什么这么判」就永远查不清，调 prompt 只能靠猜。
- prompt + 报价快照单条可到几十 KB，而 `list_monitor_runs` 是前端面板每次打开
  都要拉 20 条的热查询，塞进去会把它拖垮。

按 `src/AGENTS.md` §5.1：这是运行历史，落 ops.db，**可整表删除**——删了只丢
AI 复盘能力，不影响纸面持仓与成交。已登记进 `PERSONAL_TABLES`，分享包会清空。
"""
from __future__ import annotations

from typing import Any

from src.ops.infrastructure.store_helpers import dumps, loads, new_id

#: 单条留痕的字段体量上限。prompt 与原始回复都可能很长，截断优于把库撑爆；
#: 截断标记保留在正文里，避免事后误以为模型真的只说了这么多。
_MAX_TEXT = 20_000


def _clip(text: Any, limit: int = _MAX_TEXT) -> str:
    value = str(text or "")
    if len(value) <= limit:
        return value
    return f"{value[:limit]}\n…（已截断，原长 {len(value)} 字符）"


class OpsAiDecisionsMixin:
    """AI 决策留痕读写。依赖宿主提供 conn / _transaction / _now。"""

    def insert_ai_decision(self, payload: dict[str, Any]) -> str:
        decision_id = str(payload.get("id") or "").strip() or new_id("AID")
        with self._transaction() as cursor:  # type: ignore[attr-defined]
            cursor.execute(
                """
                INSERT INTO ai_decisions(
                    id, slug, run_id, trade_date, session_phase, model,
                    system_prompt, user_payload_json, raw_output,
                    parsed_orders_json, applied_orders_json, quotes_json,
                    status, error_text, input_tokens, output_tokens,
                    latency_ms, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    decision_id,
                    str(payload.get("slug") or ""),
                    str(payload.get("run_id") or ""),
                    str(payload.get("trade_date") or ""),
                    str(payload.get("session_phase") or ""),
                    str(payload.get("model") or ""),
                    _clip(payload.get("system_prompt")),
                    _clip(dumps(payload.get("user_payload") or {})),
                    _clip(payload.get("raw_output")),
                    dumps(payload.get("parsed_orders") or []),
                    dumps(payload.get("applied_orders") or []),
                    dumps(payload.get("quotes") or {}),
                    str(payload.get("status") or "ok"),
                    str(payload.get("error_text") or ""),
                    int(payload.get("input_tokens") or 0),
                    int(payload.get("output_tokens") or 0),
                    int(payload.get("latency_ms") or 0),
                    str(payload.get("created_at") or self._now()),  # type: ignore[attr-defined]
                ),
            )
        return decision_id

    def list_ai_decisions(
        self, slug: str, *, limit: int = 20, include_prompt: bool = False
    ) -> list[dict[str, Any]]:
        """按时间倒序取决策留痕。

        ``include_prompt`` 默认关：列表页只需要「什么时候、判了什么、成没成交」，
        把几十 KB 的 prompt 一起拉出来只会拖慢面板。
        """
        rows = self.conn.execute(  # type: ignore[attr-defined]
            "SELECT * FROM ai_decisions WHERE slug = ? ORDER BY created_at DESC LIMIT ?",
            (slug, int(limit)),
        ).fetchall()
        out: list[dict[str, Any]] = []
        for row in rows:
            item = dict(row)
            item["parsed_orders"] = loads(item.pop("parsed_orders_json", "") or "[]")
            item["applied_orders"] = loads(item.pop("applied_orders_json", "") or "[]")
            if include_prompt:
                item["user_payload"] = loads(item.pop("user_payload_json", "") or "{}")
                item["quotes"] = loads(item.pop("quotes_json", "") or "{}")
            else:
                item.pop("user_payload_json", None)
                item.pop("quotes_json", None)
                item.pop("system_prompt", None)
                item.pop("raw_output", None)
            out.append(item)
        return out

    def get_ai_decision(self, decision_id: str) -> dict[str, Any] | None:
        row = self.conn.execute(  # type: ignore[attr-defined]
            "SELECT * FROM ai_decisions WHERE id = ?", (str(decision_id),)
        ).fetchone()
        if row is None:
            return None
        item = dict(row)
        item["parsed_orders"] = loads(item.pop("parsed_orders_json", "") or "[]")
        item["applied_orders"] = loads(item.pop("applied_orders_json", "") or "[]")
        item["user_payload"] = loads(item.pop("user_payload_json", "") or "{}")
        item["quotes"] = loads(item.pop("quotes_json", "") or "{}")
        return item

    def purge_ai_decisions(self, *, before: str = "") -> int:
        """按日期清理留痕；不传 before 则整表清空。可重建缓存语义，删了不影响账。"""
        with self._transaction() as cursor:  # type: ignore[attr-defined]
            if before:
                cursor.execute(
                    "DELETE FROM ai_decisions WHERE created_at < ?", (str(before),)
                )
            else:
                cursor.execute("DELETE FROM ai_decisions")
            return int(cursor.rowcount or 0)


__all__ = ["OpsAiDecisionsMixin"]
