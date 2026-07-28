"""AI 判定记录。"""
from __future__ import annotations

import json
from typing import Any
from uuid import uuid4

from src.ledger.infrastructure.store_types import normalize_date


class AiJudgmentMixin:
    def record_ai_judgment(
        self,
        *,
        occurred_on: str | None = None,
        strategy_tag: str,
        decision: str,
        top_codes: list[str],
        reason: str = "",
        provider: str = "",
        model: str = "",
        token_used: int = 0,
        source: str = "ai",
    ) -> str:
        """记录 AI 的选/弃仓决定，独立于量化选股池。
        事后可算 AI 否决的那些天量化 top3 真实涨了多少（AI alpha 核算）。
        """
        jid = f"AJ-{uuid4().hex[:12].upper()}"
        date_value = normalize_date(occurred_on)
        with self._transaction() as cursor:
            cursor.execute(
                "INSERT INTO ai_judgments(id, occurred_on, strategy_tag, decision, top_codes,"
                " reason, provider, model, token_used, source, created_at)"
                " VALUES(?, ?, ?, ?, ?, ?, ?, ?, ?, ?, datetime('now'))",
                (
                    jid,
                    date_value,
                    strategy_tag,
                    decision,
                    json.dumps(top_codes, ensure_ascii=False),
                    reason[:2000],
                    provider[:64],
                    model[:120],
                    int(token_used),
                    source,
                ),
            )
        return jid

    def ai_judgment_payload(self, strategy_tag: str, limit: int = 100) -> list[dict[str, Any]]:
        """返回指定战法的 AI 判定记录，按日期倒序。"""
        rows = self.conn.execute(
            "SELECT * FROM ai_judgments WHERE strategy_tag = ?"
            " ORDER BY occurred_on DESC, created_at DESC LIMIT ?",
            (strategy_tag, limit),
        ).fetchall()
        result = []
        for row in rows:
            d = dict(row)
            raw = d.get("top_codes") or "[]"
            try:
                d["top_codes"] = json.loads(raw)
            except (json.JSONDecodeError, TypeError):
                d["top_codes"] = []
            result.append(d)
        return result
