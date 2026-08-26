"""AI 判定记录。"""
from __future__ import annotations

import json
from typing import Any
from uuid import uuid4

from src.ledger.infrastructure.store_types import _now, normalize_date


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
                " VALUES(?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
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
                    # 全库其余表都用 _now()（本地时区 + 偏移 + 微秒 + 'T'）。这里原先是 SQLite
                    # 的 datetime('now')：UTC、秒级、空格分隔——同一个 palace.db 两套时钟两种
                    # 格式，跨表排序和比较必错。
                    _now(),
                ),
            )
        return jid

    def ai_judgment_payload(self, strategy_tag: str, limit: int = 100) -> list[dict[str, Any]]:
        """返回指定战法的 AI 判定记录，按日期倒序。

        created_at 走 julianday() 而不是字符串比较：本表在改用 _now() 之前写的是
        datetime('now') 的 UTC "YYYY-MM-DD HH:MM:SS"，同一张表里现在新旧两种格式并存，
        按字符串排等于把 UTC 和本地时间混着比。julianday() 把两者折算到同一条时间轴
        （不带偏移的旧值按 UTC 解释，正是它当初的含义），旧行因此仍排在正确位置；
        解析不了的脏值 COALESCE 成 0 沉底，读取不会为此抛错。julianday 是 double，
        同秒内的微秒差它分辨不出来，所以再拿 created_at 做一次字符串兜底排序。
        """
        rows = self.conn.execute(
            "SELECT * FROM ai_judgments WHERE strategy_tag = ?"
            " ORDER BY occurred_on DESC, COALESCE(julianday(created_at), 0) DESC,"
            " created_at DESC LIMIT ?",
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
