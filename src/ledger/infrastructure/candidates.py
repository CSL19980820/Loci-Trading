"""候选池写入、查询与按日汇总。"""
from __future__ import annotations

from datetime import date
from typing import Any
from uuid import uuid4

from src.ledger.infrastructure.store_types import (
    PalaceError,
    _dumps,
    _loads,
    _normalize_decision,
    _now,
    normalize_code,
    normalize_date,
)


class CandidateMixin:
    def record_candidate(
        self,
        *,
        code: str,
        name: str,
        decision: str,
        reason: str,
        occurred_on: str | None = None,
        pool_id: str = "",
        score: float | None = None,
        timing: str = "",
        rule_version: str = "qianlong-v1",
        evidence: dict[str, Any] | None = None,
        tier: str = "core",
        source: str = "manual",
    ) -> str:
        """写入候选裁决。同日同池同标的只占一席：重复提交幂等，改判则覆盖。"""
        code = normalize_code(code)
        occurred_on = normalize_date(occurred_on)
        if not decision.strip() or not reason.strip():
            raise PalaceError("候选记录必须有裁决和理由")
        if "满仓" in reason and any(
            token in decision for token in ("落选", "排除", "放弃", "否决", "剔除", "reject")
        ):
            raise PalaceError("账户满仓不能作为拒绝理由；请按标的本身质量裁决")
        effective_pool = pool_id.strip() or f"POOL-{occurred_on}"
        name_value = name.strip() or code
        decision_value = _normalize_decision(decision.strip())
        reason_value = reason.strip()
        timing_value = timing.strip()
        rule_value = rule_version.strip() or "qianlong-v1"
        source_value = source.strip() or "manual"
        tier_value = tier.strip() or "core"
        evidence_json = _dumps(evidence)
        with self._transaction() as cursor:
            self._upsert_stock(cursor, code, name_value)
            existing = cursor.execute(
                """
                SELECT id, name, score, decision, timing, reason, rule_version, evidence_json, tier, source
                FROM candidate_reviews
                WHERE occurred_on = ? AND pool_id = ? AND code = ?
                """,
                (occurred_on, effective_pool, code),
            ).fetchone()
            if existing:
                same = (
                    str(existing["name"]) == name_value
                    and (
                        (existing["score"] is None and score is None)
                        or (
                            existing["score"] is not None
                            and score is not None
                            and float(existing["score"]) == float(score)
                        )
                    )
                    and str(existing["decision"]) == decision_value
                    and str(existing["timing"]) == timing_value
                    and str(existing["reason"]) == reason_value
                    and str(existing["rule_version"]) == rule_value
                    and str(existing["evidence_json"]) == evidence_json
                    and str(existing["tier"]) == tier_value
                    and str(existing["source"]) == source_value
                )
                if same:
                    return str(existing["id"])
                cursor.execute(
                    """
                    UPDATE candidate_reviews
                    SET name = ?, score = ?, decision = ?, timing = ?, reason = ?,
                        rule_version = ?, evidence_json = ?, tier = ?, source = ?, created_at = ?
                    WHERE id = ?
                    """,
                    (
                        name_value,
                        score,
                        decision_value,
                        timing_value,
                        reason_value,
                        rule_value,
                        evidence_json,
                        tier_value,
                        source_value,
                        _now(),
                        str(existing["id"]),
                    ),
                )
                return str(existing["id"])

            candidate_id = f"CA-{uuid4().hex[:12].upper()}"
            cursor.execute(
                """
                INSERT INTO candidate_reviews(
                    id, occurred_on, pool_id, code, name, score, decision, timing, reason,
                    rule_version, evidence_json, tier, source, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    candidate_id,
                    occurred_on,
                    effective_pool,
                    code,
                    name_value,
                    score,
                    decision_value,
                    timing_value,
                    reason_value,
                    rule_value,
                    evidence_json,
                    tier_value,
                    source_value,
                    _now(),
                ),
            )
        return candidate_id

    def delete_candidate(self, candidate_id: str) -> bool:
        """删除一条候选记录。"""
        with self._transaction() as cursor:
            cursor.execute("DELETE FROM candidate_reviews WHERE id = ?", (candidate_id.strip(),))
            return cursor.rowcount > 0

    def delete_candidates(self, candidate_ids: list[str]) -> int:
        """批量删除候选；返回实际删除条数。"""
        cleaned = [cid.strip() for cid in candidate_ids if cid and str(cid).strip()]
        if not cleaned:
            return 0
        removed = 0
        with self._transaction() as cursor:
            for candidate_id in cleaned:
                cursor.execute("DELETE FROM candidate_reviews WHERE id = ?", (candidate_id,))
                removed += cursor.rowcount
        return removed

    def candidates_payload(self, occurred_on: str | None = None) -> list[dict[str, Any]]:
        """读取候选池；未传日期时按最新候选日展示。同日同池同标的只返回最新一条。"""
        target_date = normalize_date(occurred_on) if occurred_on else None
        if target_date is None:
            latest = self.conn.execute("SELECT MAX(occurred_on) AS value FROM candidate_reviews").fetchone()["value"]
            target_date = str(latest) if latest else None
        if not target_date:
            return []
        rows = self.conn.execute(
            """
            SELECT id, occurred_on, pool_id, code, name, score, decision, timing, reason,
                   rule_version, evidence_json, tier, source, created_at
            FROM (
                SELECT id, occurred_on, pool_id, code, name, score, decision, timing, reason,
                       rule_version, evidence_json, tier, source, created_at,
                       ROW_NUMBER() OVER (
                           PARTITION BY pool_id, code
                           ORDER BY created_at DESC, id DESC
                       ) AS rn
                FROM candidate_reviews
                WHERE occurred_on = ?
            ) ranked
            WHERE rn = 1
            ORDER BY score DESC NULLS LAST, created_at ASC
            """,
            (target_date,),
        ).fetchall()
        return [
            {
                "id": str(row["id"]),
                "date": str(row["occurred_on"]),
                "pool_id": str(row["pool_id"]),
                "code": str(row["code"]),
                "name": str(row["name"]),
                "score": float(row["score"]) if row["score"] is not None else None,
                "decision": _normalize_decision(str(row["decision"])),
                "timing": str(row["timing"]),
                "reason": str(row["reason"]),
                "rule_version": str(row["rule_version"]),
                "evidence": _loads(str(row["evidence_json"])),
                "tier": str(row["tier"]),
                "source": str(row["source"]),
                "created_at": str(row["created_at"]),
            }
            for row in rows
        ]

    def candidates_list_payload(
        self,
        *,
        strategy: str | None = None,
        decision: str | None = None,
        start: str | None = None,
        end: str | None = None,
        limit: int = 200,
    ) -> list[dict[str, Any]]:
        """跨日期/战法的候选列表，供工作台列表页使用（不再按天侧栏）。"""
        clauses: list[str] = []
        params: list[Any] = []
        if strategy and strategy.strip():
            clauses.append("rule_version = ?")
            params.append(strategy.strip())
        if decision and decision.strip():
            clauses.append("decision = ?")
            params.append(decision.strip())
        if start:
            clauses.append("occurred_on >= ?")
            params.append(normalize_date(start))
        if end:
            clauses.append("occurred_on <= ?")
            params.append(normalize_date(end))
        where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
        rows = self.conn.execute(
            f"""
            SELECT id, occurred_on, pool_id, code, name, score, decision, timing, reason,
                   rule_version, evidence_json, tier, source, created_at
            FROM (
                SELECT id, occurred_on, pool_id, code, name, score, decision, timing, reason,
                       rule_version, evidence_json, tier, source, created_at,
                       ROW_NUMBER() OVER (
                           PARTITION BY occurred_on, pool_id, code
                           ORDER BY created_at DESC, id DESC
                       ) AS rn
                FROM candidate_reviews
                {where}
            ) ranked
            WHERE rn = 1
            ORDER BY occurred_on DESC, score DESC NULLS LAST, created_at DESC
            LIMIT ?
            """,
            (*params, int(limit)),
        ).fetchall()
        return [
            {
                "id": str(row["id"]),
                "date": str(row["occurred_on"]),
                "pool_id": str(row["pool_id"]),
                "code": str(row["code"]),
                "name": str(row["name"]),
                "score": float(row["score"]) if row["score"] is not None else None,
                "decision": _normalize_decision(str(row["decision"])),
                "timing": str(row["timing"]),
                "reason": str(row["reason"]),
                "rule_version": str(row["rule_version"]),
                "evidence": _loads(str(row["evidence_json"])),
                "tier": str(row["tier"]),
                "source": str(row["source"]),
                "created_at": str(row["created_at"]),
            }
            for row in rows
        ]

    def candidates_by_strategy(
        self,
        rule_version: str,
        *,
        start: str | None = None,
        end: str | None = None,
        limit: int = 200,
    ) -> list[dict[str, Any]]:
        """按战法（rule_version）查历史选股记录。

        每天、每标的取最新一条（同池同标的可能重跑），按日期倒序。
        用于前端"选股历史"页：按战法+日期区间浏览，不依赖账本的精选口径。
        """
        params: list[Any] = [rule_version]
        clauses = ["rule_version = ?"]
        if start:
            clauses.append("occurred_on >= ?")
            params.append(start)
        if end:
            clauses.append("occurred_on <= ?")
            params.append(end)
        where = " AND ".join(clauses)
        params.append(int(limit))
        rows = self.conn.execute(
            f"""
            SELECT id, occurred_on, pool_id, code, name, score, decision, timing, reason,
                   rule_version, evidence_json, source, created_at
            FROM (
                SELECT id, occurred_on, pool_id, code, name, score, decision, timing, reason,
                       rule_version, evidence_json, source, created_at,
                       ROW_NUMBER() OVER (
                           PARTITION BY occurred_on, code
                           ORDER BY created_at DESC, id DESC
                       ) AS rn
                FROM candidate_reviews
                WHERE {where}
            ) ranked
            WHERE rn = 1
            ORDER BY occurred_on DESC, score DESC NULLS LAST
            LIMIT ?
            """,
            params,
        ).fetchall()
        return [
            {
                "id": str(row["id"]),
                "date": str(row["occurred_on"]),
                "pool_id": str(row["pool_id"]),
                "code": str(row["code"]),
                "name": str(row["name"]),
                "score": float(row["score"]) if row["score"] is not None else None,
                "decision": _normalize_decision(str(row["decision"])),
                "timing": str(row["timing"]),
                "reason": str(row["reason"]),
                "rule_version": str(row["rule_version"]),
                "evidence": _loads(str(row["evidence_json"])),
                "source": str(row["source"]),
                "created_at": str(row["created_at"]),
            }
            for row in rows
        ]

    @staticmethod
    def _is_selected_decision(decision: str) -> bool:
        """精选口径：与 outcomes.POSITIVE_HINTS 对齐；观察/落选不算精选。"""
        normalized = _normalize_decision(decision)
        if normalized in ("观察", "落选", "空仓观望", "部分参与"):
            return False
        if normalized == "精选":
            return True
        rejected_tokens = ("落选", "排除", "放弃", "否决", "剔除", "过滤")
        if any(token in normalized for token in rejected_tokens):
            return False
        if any(token in normalized.lower() for token in ("reject", "drop", "exclude")):
            return False
        positive_hints = ("买", "精选", "入选", "重点", "建仓", "参与")
        return any(hint in normalized for hint in positive_hints)

    def candidate_day_summary(self, candidates: list[dict[str, Any]]) -> dict[str, Any]:
        """汇总当日候选：结构化条目，方便前端排版；正文只转述账本字段，不新增价位判断。"""
        selected = [item for item in candidates if self._is_selected_decision(str(item["decision"]))]
        filtered = [item for item in candidates if not self._is_selected_decision(str(item["decision"]))]

        def _card(item: dict[str, Any]) -> dict[str, Any]:
            score = item.get("score")
            return {
                "id": str(item.get("id") or ""),
                "code": str(item["code"]),
                "name": str(item["name"]),
                "score": float(score) if score is not None else None,
                "decision": str(item.get("decision") or ""),
                "timing": str(item.get("timing") or "").strip(),
                "reason": str(item.get("reason") or "").strip() or "（未写理由）",
            }

        picks = [_card(item) for item in selected]
        drops = [_card(item) for item in filtered]

        if not candidates:
            headline = "当日无候选"
            note = "账本无候选记录。"
        elif selected and not filtered:
            headline = f"全选 {len(selected)} 只"
            note = "本池均为精选。纪要只汇总账本原文，不生成新价位或买卖建议。"
        elif selected and filtered:
            headline = f"精选 {len(selected)} / 全量 {len(candidates)}"
            note = f"未选 {len(filtered)} 只。纪要只汇总账本原文，不生成新价位或买卖建议。"
        else:
            headline = f"全量 {len(candidates)} 只 · 无精选"
            note = "当日无精选标的。纪要只汇总账本原文，不生成新价位或买卖建议。"

        # 纯文本兜底：多行，给 CLI / Agent 用
        lines = [headline, note]
        if picks:
            lines.append("精选")
            for card in picks:
                score_text = f"{card['score']:.0f}" if card["score"] is not None else "—"
                timing = f" · {card['timing']}" if card["timing"] else ""
                lines.append(f"- {card['name']} {card['code']}  {score_text}  {card['decision']}{timing}")
                lines.append(f"  {card['reason']}")
        if drops:
            lines.append("未选")
            for card in drops:
                score_text = f"{card['score']:.0f}" if card["score"] is not None else "—"
                lines.append(f"- {card['name']} {card['code']}  {score_text}  {card['decision']}")
                lines.append(f"  {card['reason']}")

        return {
            "headline": headline,
            "note": note,
            "text": "\n".join(lines),
            "total": len(candidates),
            "selected_count": len(selected),
            "filtered_count": len(filtered),
            "all_selected": bool(selected) and not filtered,
            "picks": picks,
            "drops": drops,
        }

    def pool_dates_payload(self) -> list[dict[str, Any]]:
        """候选池按日汇总，便于复盘时跳转某日全量 vs 精选差异。"""
        rows = self.conn.execute(
            """
            SELECT occurred_on AS date, pool_id
            FROM candidate_reviews
            GROUP BY occurred_on, pool_id
            ORDER BY occurred_on DESC, pool_id ASC
            """
        ).fetchall()
        result: list[dict[str, Any]] = []
        for row in rows:
            day = str(row["date"])
            pool_id = str(row["pool_id"])
            candidates = self.candidates_payload(day)
            pool_candidates = [item for item in candidates if item["pool_id"] == pool_id]
            selected = [item for item in pool_candidates if self._is_selected_decision(str(item["decision"]))]
            scored = [item for item in pool_candidates if item["score"] is not None]
            avg_score = round(sum(float(item["score"]) for item in scored) / len(scored), 2) if scored else None
            result.append(
                {
                    "date": day,
                    "pool_id": pool_id,
                    "total": len(pool_candidates),
                    "selected": len(selected),
                    "filtered": max(len(pool_candidates) - len(selected), 0),
                    "scored": len(scored),
                    "avg_score": avg_score,
                }
            )
        return result

    def pool_day_payload(self, occurred_on: str | None = None, pool_id: str | None = None) -> dict[str, Any]:
        """某一日（可选指定 pool）候选全量，并拆出精选/未精选差异。"""
        candidates = self.candidates_payload(occurred_on)
        if not candidates:
            target = normalize_date(occurred_on) if occurred_on else date.today().isoformat()
            empty_summary = self.candidate_day_summary([])
            return {
                "date": target,
                "pool_id": pool_id or "",
                "total": 0,
                "selected_count": 0,
                "filtered_count": 0,
                "selected": [],
                "filtered": [],
                "all": [],
                "summary": empty_summary,
            }
        target_date = str(candidates[0]["date"])
        if pool_id:
            candidates = [item for item in candidates if str(item["pool_id"]) == pool_id]
        selected = [item for item in candidates if self._is_selected_decision(str(item["decision"]))]
        filtered = [item for item in candidates if not self._is_selected_decision(str(item["decision"]))]
        resolved_pool = pool_id or (str(candidates[0]["pool_id"]) if candidates else "")
        summary = self.candidate_day_summary(candidates)
        return {
            "date": target_date,
            "pool_id": resolved_pool,
            "total": len(candidates),
            "selected_count": len(selected),
            "filtered_count": len(filtered),
            "selected": selected,
            "filtered": filtered,
            "all": candidates,
            "summary": summary,
        }
