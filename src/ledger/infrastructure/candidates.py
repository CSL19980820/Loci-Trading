"""候选池写入。"""
from __future__ import annotations

from typing import Any
from uuid import uuid4

from src.ledger.infrastructure.store_types import (
    CANONICAL_DECISIONS,
    DEFAULT_RULE_VERSION,
    PalaceError,
    _dumps,
    _normalize_decision,
    _normalize_reason_text,
    _normalize_rule_version,
    _normalize_timing,
    _now,
    normalize_code,
    normalize_date,
)

__all__ = ["CandidateMixin"]

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
        rule_version: str = DEFAULT_RULE_VERSION,
        strategy_slug: str = "",
        strategy_revision: str = "",
        effective_params: dict[str, Any] | None = None,
        evidence: dict[str, Any] | None = None,
        tier: str = "core",
        source: str = "manual",
    ) -> str:
        """写入候选裁决。同日同池同标的只占一席：重复提交幂等，改判则覆盖。"""
        code = normalize_code(code)
        occurred_on = normalize_date(occurred_on)
        if not decision.strip() or not reason.strip():
            raise PalaceError("候选记录必须有裁决和理由")
        decision_value = _normalize_decision(decision.strip())
        if decision_value not in CANONICAL_DECISIONS:
            raise PalaceError("裁决必须是：精选 / 落选 / 观察")
        if "满仓" in reason and decision_value == "落选":
            raise PalaceError("账户满仓不能作为拒绝理由；请按标的本身质量裁决")
        effective_pool = pool_id.strip() or f"POOL-{occurred_on}"
        name_value = name.strip() or code
        reason_value = _normalize_reason_text(reason.strip())
        timing_value = _normalize_timing(timing)
        rule_value = _normalize_rule_version(rule_version)
        strategy_slug_value = strategy_slug.strip() or rule_version.strip()
        strategy_revision_value = strategy_revision.strip()
        effective_params_json = _dumps(effective_params)
        source_value = source.strip() or "manual"
        tier_value = tier.strip() or "core"
        evidence_json = _dumps(evidence)
        with self._transaction() as cursor:
            self._upsert_stock(cursor, code, name_value)
            existing = cursor.execute(
                """
                SELECT id, name, score, decision, timing, reason, rule_version,
                       strategy_slug, strategy_revision, effective_params_json,
                       evidence_json, tier, source
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
                    and str(existing["strategy_slug"]) == strategy_slug_value
                    and str(existing["strategy_revision"]) == strategy_revision_value
                    and str(existing["effective_params_json"]) == effective_params_json
                    and str(existing["evidence_json"]) == evidence_json
                    and str(existing["tier"]) == tier_value
                    and str(existing["source"]) == source_value
                )
                if same:
                    return str(existing["id"])
                # created_at 保持首次写入时刻：盘后真选口径（LIVE_CANDIDATE_SQL）
                # 拿它的日历日与 occurred_on 比对，改判时刷新会让隔日修正过的
                # 候选被重判成回填，从当日真选里整条消失。
                cursor.execute(
                    """
                    UPDATE candidate_reviews
                    SET name = ?, score = ?, decision = ?, timing = ?, reason = ?,
                        rule_version = ?, strategy_slug = ?, strategy_revision = ?,
                        effective_params_json = ?, evidence_json = ?, tier = ?, source = ?
                    WHERE id = ?
                    """,
                    (
                        name_value,
                        score,
                        decision_value,
                        timing_value,
                        reason_value,
                        rule_value,
                        strategy_slug_value,
                        strategy_revision_value,
                        effective_params_json,
                        evidence_json,
                        tier_value,
                        source_value,
                        str(existing["id"]),
                    ),
                )
                return str(existing["id"])

            candidate_id = f"CA-{uuid4().hex[:12].upper()}"
            cursor.execute(
                """
                INSERT INTO candidate_reviews(
                    id, occurred_on, pool_id, code, name, score, decision, timing, reason,
                    rule_version, strategy_slug, strategy_revision, effective_params_json,
                    evidence_json, tier, source, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
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
                    strategy_slug_value,
                    strategy_revision_value,
                    effective_params_json,
                    evidence_json,
                    tier_value,
                    source_value,
                    _now(),
                ),
            )
        return candidate_id

    def record_candidates(self, candidates: list[dict[str, Any]]) -> list[str]:
        """全量候选裁决要么全部落账，要么在失败时一起回滚。"""
        if not isinstance(candidates, list) or not candidates or any(
            not isinstance(item, dict) for item in candidates
        ):
            raise PalaceError("候选批次必须至少包含一条对象")
        with self._transaction():
            return [self.record_candidate(**dict(item)) for item in candidates]

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

    def delete_candidates_for_pool(
        self,
        *,
        occurred_on: str,
        pool_id: str,
        sources_like: str | None = None,
    ) -> int:
        """删除某日某池候选（重选全量替换 / 0 只清空）。

        ``sources_like`` 非空时只删匹配源（如 ``%backfill%``），用于回填
        不覆盖盘后真选。
        """
        day = normalize_date(occurred_on)
        pool = pool_id.strip()
        if not pool:
            return 0
        sql = "DELETE FROM candidate_reviews WHERE occurred_on = ? AND pool_id = ?"
        params: list[Any] = [day, pool]
        if sources_like:
            sql += " AND source LIKE ?"
            params.append(sources_like)
        with self._transaction() as cursor:
            cursor.execute(sql, params)
            return int(cursor.rowcount)

    def delete_candidates_for_strategy(self, strategy_slug: str) -> int:
        """删除某个策略的全部候选历史及其同策略选股池记录。"""
        key = str(strategy_slug or "").strip()
        if not key:
            return 0
        with self._transaction() as cursor:
            cursor.execute(
                """
                DELETE FROM candidate_reviews
                WHERE strategy_slug = ?
                   OR rule_version = ?
                   OR pool_id LIKE ?
                """,
                (key, key, f"{key}@%"),
            )
            return int(cursor.rowcount)

    def candidate_scoring_rows(
        self, strategy_slug: str, *, since: str | None = None, until: str | None = None,
    ) -> list[dict[str, Any]]:
        """某战法已入库候选的评分相关字段（按日期、代码排序），供按新口径重算评分。"""
        key = str(strategy_slug or "").strip()
        if not key:
            return []
        sql = ("SELECT id, occurred_on, pool_id, code, name, score, decision, reason, evidence_json, source"
               " FROM candidate_reviews WHERE strategy_slug = ?")
        params: list[Any] = [key]
        if since:
            sql += " AND occurred_on >= ?"
            params.append(normalize_date(since))
        if until:
            sql += " AND occurred_on <= ?"
            params.append(normalize_date(until))
        rows = self.conn.execute(sql + " ORDER BY occurred_on, code", params).fetchall()
        return [dict(row) for row in rows]

    def update_candidate_scoring(
        self, updates: list[tuple[str, float | None, str, dict[str, Any]]],
    ) -> int:
        """只改 score / reason / evidence（全部成功或全部回滚）。

        不动 ``created_at``、``source`` 与裁决：盘后真选口径依赖它们，重算评分不能把真选改判成回填。
        """
        changed = 0
        with self._transaction() as cursor:
            for candidate_id, score, reason, evidence in updates:
                reason_value = _normalize_reason_text(str(reason).strip())
                if not reason_value:
                    raise PalaceError("候选记录必须有理由")
                cursor.execute(
                    "UPDATE candidate_reviews SET score = ?, reason = ?, evidence_json = ? WHERE id = ?",
                    (score, reason_value, _dumps(evidence), str(candidate_id)),
                )
                changed += cursor.rowcount
        return changed
