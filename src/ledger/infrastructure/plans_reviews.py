"""预案、复盘写入与时间线。"""
from __future__ import annotations

import sqlite3
from typing import Any
from uuid import uuid4

from src.ledger.infrastructure.store_types import (
    PalaceError,
    _loads,
    _now,
    normalize_code,
    normalize_date,
)


class PlanReviewMixin:
    def record_plan(
        self,
        *,
        code: str,
        title: str,
        scenario: str,
        occurred_on: str | None = None,
        entry_zone: str = "",
        stop_price: float | None = None,
        target_price: float | None = None,
        layers: float | None = None,
        invalidation: str = "",
        rule_version: str = "qianlong-v1",
        source: str = "manual",
        supersedes_id: str | None = None,
        note: str = "",
    ) -> str:
        code = normalize_code(code)
        if not title.strip() or not scenario.strip():
            raise PalaceError("计划必须有标题和情景")
        if layers is not None and layers <= 0:
            raise PalaceError("计划层数必须大于 0")
        plan_id = f"PL-{uuid4().hex[:12].upper()}"
        with self._transaction() as cursor:
            stock = cursor.execute("SELECT name FROM stocks WHERE code = ?", (code,)).fetchone()
            self._upsert_stock(cursor, code, str(stock["name"]) if stock else code)
            cursor.execute(
                """
                INSERT INTO plans(
                    id, occurred_on, code, title, scenario, entry_zone, stop_price, target_price, layers,
                    invalidation, rule_version, source, supersedes_id, note, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (plan_id, normalize_date(occurred_on), code, title.strip(), scenario.strip(), entry_zone.strip(), stop_price,
                 target_price, layers, invalidation.strip(), rule_version.strip() or "qianlong-v1", source.strip() or "manual",
                 supersedes_id, note.strip(), _now()),
            )
        return plan_id

    def record_review(
        self,
        *,
        entity_type: str,
        entity_id: str,
        outcome: str,
        reviewed_on: str | None = None,
        strategy_tag: str = "qianlong",
        return_pct: float | None = None,
        max_favorable_pct: float | None = None,
        max_adverse_pct: float | None = None,
        lesson: str = "",
        next_rule: str = "",
        source: str = "manual",
    ) -> str:
        entity_type = entity_type.lower()
        if entity_type not in {"plan", "candidate", "trade"}:
            raise PalaceError("复盘对象必须为 plan、candidate 或 trade")
        if not entity_id.strip() or not outcome.strip():
            raise PalaceError("复盘必须有对象 ID 与结果")
        review_id = f"RV-{uuid4().hex[:12].upper()}"
        with self._transaction() as cursor:
            cursor.execute(
                """
                INSERT INTO reviews(
                    id, reviewed_on, entity_type, entity_id, strategy_tag, outcome, return_pct,
                    max_favorable_pct, max_adverse_pct, lesson, next_rule, source, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (review_id, normalize_date(reviewed_on), entity_type, entity_id.strip(), strategy_tag.strip() or "qianlong",
                 outcome.strip(), return_pct, max_favorable_pct, max_adverse_pct, lesson.strip(), next_rule.strip(),
                 source.strip() or "manual", _now()),
            )
        return review_id

    def plans_payload(self, status: str = "active") -> list[dict[str, Any]]:
        rows = self.conn.execute(
            """
            SELECT id, occurred_on, code, title, status, scenario, entry_zone, stop_price,
                   target_price, layers, invalidation, rule_version, source, supersedes_id, note, created_at
            FROM plans WHERE status = ? ORDER BY occurred_on DESC, created_at DESC
            """,
            (status,),
        ).fetchall()
        return [
            {
                "id": str(row["id"]),
                "date": str(row["occurred_on"]),
                "code": str(row["code"]),
                "title": str(row["title"]),
                "status": str(row["status"]),
                "scenario": str(row["scenario"]),
                "entry_zone": str(row["entry_zone"]),
                "stop_price": float(row["stop_price"]) if row["stop_price"] is not None else None,
                "target_price": float(row["target_price"]) if row["target_price"] is not None else None,
                "layers": float(row["layers"]) if row["layers"] is not None else None,
                "invalidation": str(row["invalidation"]),
                "rule_version": str(row["rule_version"]),
                "source": str(row["source"]),
                "supersedes_id": str(row["supersedes_id"] or ""),
                "note": str(row["note"]),
                "created_at": str(row["created_at"]),
            }
            for row in rows
        ]

    def timeline_payload(self, code: str) -> list[dict[str, Any]]:
        """提供单票事件流，保留原始 ID 供复盘对象精确关联。"""
        code = normalize_code(code)
        exists = self.conn.execute("SELECT 1 FROM stocks WHERE code = ?", (code,)).fetchone()
        if exists is None:
            raise PalaceError(f"账本中不存在 {code}")
        position_events = self.conn.execute(
            """
            SELECT id, occurred_on, created_at, action, shares, price, shares_before, shares_after,
                   cost_before, cost_after, realized_pnl, reason, source, correlation_id, metadata_json
            FROM position_events WHERE code = ?
            """,
            (code,),
        ).fetchall()
        candidates = self.conn.execute(
            """
            SELECT id, occurred_on, created_at, pool_id, score, decision, timing, reason,
                   rule_version, evidence_json, source
            FROM candidate_reviews WHERE code = ?
            """,
            (code,),
        ).fetchall()
        plans = self.conn.execute(
            """
            SELECT id, occurred_on, created_at, title, status, scenario, entry_zone, stop_price,
                   target_price, layers, invalidation, rule_version, note, source
            FROM plans WHERE code = ?
            """,
            (code,),
        ).fetchall()
        events: list[dict[str, Any]] = []
        events.extend(
            {
                "id": str(row["id"]), "date": str(row["occurred_on"]), "created_at": str(row["created_at"]),
                "type": "trade", "label": str(row["action"]), "detail": {
                    "shares": int(row["shares"]), "price": float(row["price"]), "shares_before": int(row["shares_before"]),
                    "shares_after": int(row["shares_after"]), "cost_before": float(row["cost_before"]),
                    "cost_after": float(row["cost_after"]), "realized_pnl": float(row["realized_pnl"]),
                    "reason": str(row["reason"]), "source": str(row["source"]),
                    "correlation_id": str(row["correlation_id"]), "metadata": _loads(str(row["metadata_json"])),
                },
            }
            for row in position_events
        )
        events.extend(
            {
                "id": str(row["id"]), "date": str(row["occurred_on"]), "created_at": str(row["created_at"]),
                "type": "candidate", "label": str(row["decision"]), "detail": {
                    "pool_id": str(row["pool_id"]), "score": float(row["score"]) if row["score"] is not None else None,
                    "timing": str(row["timing"]), "reason": str(row["reason"]), "rule_version": str(row["rule_version"]),
                    "evidence": _loads(str(row["evidence_json"])), "source": str(row["source"]),
                },
            }
            for row in candidates
        )
        events.extend(
            {
                "id": str(row["id"]), "date": str(row["occurred_on"]), "created_at": str(row["created_at"]),
                "type": "plan", "label": str(row["title"]), "detail": {
                    "status": str(row["status"]), "scenario": str(row["scenario"]), "entry_zone": str(row["entry_zone"]),
                    "stop_price": float(row["stop_price"]) if row["stop_price"] is not None else None,
                    "target_price": float(row["target_price"]) if row["target_price"] is not None else None,
                    "layers": float(row["layers"]) if row["layers"] is not None else None,
                    "invalidation": str(row["invalidation"]), "rule_version": str(row["rule_version"]),
                    "note": str(row["note"]), "source": str(row["source"]),
                },
            }
            for row in plans
        )
        # 关联到本票事件的复盘记录
        entity_ids = [str(e["id"]) for e in events]
        review_rows: list[sqlite3.Row] = []
        if entity_ids:
            placeholders = ",".join("?" for _ in entity_ids)
            review_rows = self.conn.execute(
                f"""
                SELECT id, reviewed_on, created_at, entity_type, entity_id, strategy_tag, outcome,
                       return_pct, max_favorable_pct, max_adverse_pct, lesson, next_rule, source
                FROM reviews
                WHERE entity_id IN ({placeholders})
                """,
                entity_ids,
            ).fetchall()
        events.extend(
            {
                "id": str(row["id"]),
                "date": str(row["reviewed_on"]),
                "created_at": str(row["created_at"]),
                "type": "review",
                "label": str(row["outcome"]),
                "detail": {
                    "entity_type": str(row["entity_type"]),
                    "entity_id": str(row["entity_id"]),
                    "strategy_tag": str(row["strategy_tag"]),
                    "return_pct": float(row["return_pct"]) if row["return_pct"] is not None else None,
                    "max_favorable_pct": float(row["max_favorable_pct"]) if row["max_favorable_pct"] is not None else None,
                    "max_adverse_pct": float(row["max_adverse_pct"]) if row["max_adverse_pct"] is not None else None,
                    "lesson": str(row["lesson"]),
                    "next_rule": str(row["next_rule"]),
                    "source": str(row["source"]),
                },
            }
            for row in review_rows
        )
        # 新→旧，方便从交割单点进来先看最近历史
        return sorted(events, key=lambda event: (event["date"], event["created_at"], event["id"]), reverse=True)

    def reviews_payload(self, limit: int = 100) -> list[dict[str, Any]]:
        """复盘记忆列表：按复盘日期倒序。"""
        if limit <= 0 or limit > 500:
            raise PalaceError("limit 必须在 1-500 之间")
        rows = self.conn.execute(
            """
            SELECT id, reviewed_on, entity_type, entity_id, strategy_tag, outcome,
                   return_pct, max_favorable_pct, max_adverse_pct, lesson, next_rule,
                   source, created_at
            FROM reviews
            ORDER BY reviewed_on DESC, created_at DESC, id DESC
            LIMIT ?
            """,
            (limit,),
        ).fetchall()
        return [
            {
                "id": str(row["id"]),
                "date": str(row["reviewed_on"]),
                "entity_type": str(row["entity_type"]),
                "entity_id": str(row["entity_id"]),
                "strategy_tag": str(row["strategy_tag"]),
                "outcome": str(row["outcome"]),
                "return_pct": float(row["return_pct"]) if row["return_pct"] is not None else None,
                "max_favorable_pct": float(row["max_favorable_pct"]) if row["max_favorable_pct"] is not None else None,
                "max_adverse_pct": float(row["max_adverse_pct"]) if row["max_adverse_pct"] is not None else None,
                "lesson": str(row["lesson"]),
                "next_rule": str(row["next_rule"]),
                "source": str(row["source"]),
                "created_at": str(row["created_at"]),
            }
            for row in rows
        ]

    def timeline_markdown(self, code: str) -> str:
        code = normalize_code(code)
        stock = self.conn.execute("SELECT name FROM stocks WHERE code = ?", (code,)).fetchone()
        if stock is None:
            raise PalaceError(f"账本中不存在 {code}")
        rows = self.conn.execute(
            """
            SELECT occurred_on AS event_date, created_at, '仓位事件' AS category, id,
                   action || ' ' || shares || '股 @ ' || printf('%.3f', price) ||
                   '｜余仓 ' || shares_after || '｜余票成本 ' || printf('%.3f', cost_after) ||
                   '｜已实现 ' || printf('%+.2f', realized_pnl) ||
                   CASE WHEN reason <> '' THEN '｜' || reason ELSE '' END AS detail
            FROM position_events WHERE code = ?
            UNION ALL
            SELECT occurred_on, created_at, '候选裁决', id,
                   pool_id || '｜' || decision || CASE WHEN score IS NOT NULL THEN '｜评分 ' || printf('%.1f', score) ELSE '' END ||
                   CASE WHEN timing <> '' THEN '｜' || timing ELSE '' END || '｜' || reason
            FROM candidate_reviews WHERE code = ?
            UNION ALL
            SELECT occurred_on, created_at, '作战预案', id,
                   title || '｜' || scenario || CASE WHEN invalidation <> '' THEN '｜失效：' || invalidation ELSE '' END
            FROM plans WHERE code = ?
            ORDER BY event_date, created_at
            """,
            (code, code, code),
        ).fetchall()
        lines = [f"# {stock['name']}（{code}）追溯时间线", "", "| 日期 | 类型 | ID | 事实/预案 |", "|---|---|---|---|"]
        lines.extend(f"| {row['event_date']} | {row['category']} | {row['id']} | {row['detail']} |" for row in rows)
        if not rows:
            lines.append("| - | - | - | 尚无记录 |")
        return "\n".join(lines) + "\n"
