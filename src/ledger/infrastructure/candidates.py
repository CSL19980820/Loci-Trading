"""候选池写入、查询与按日汇总。"""
from __future__ import annotations

from datetime import date
from typing import Any
from uuid import uuid4

from src.ledger.infrastructure.store_types import (
    CANONICAL_DECISIONS,
    DEFAULT_RULE_VERSION,
    PalaceError,
    _dumps,
    _loads,
    _normalize_decision,
    _normalize_reason_text,
    _normalize_rule_version,
    _normalize_timing,
    _now,
    normalize_code,
    normalize_date,
)

#: 排除区间回填 / 历史重放（不要求 created_at 同日）
EXCLUDE_BACKFILL_SQL = (
    "IFNULL(source, '') NOT LIKE '%backfill%'",
    "IFNULL(source, '') NOT LIKE '%:history'",
)
# 旧版曾在启动时把过期 API 选股改写成 backfill；当前版本在读取时派生该口径，
# 避免为了展示过滤而改写审计事实。手工补录的历史记录不受影响。
EXCLUDE_STALE_API_SCREEN_SQL = (
    "(IFNULL(source, '') NOT LIKE 'api:screen%' OR substr("
    "REPLACE(IFNULL(created_at, ''), 'T', ' '), 1, 10) = occurred_on)"
)
#: 盘后真选：排除回填 + 写入日历日须等于选股日
LIVE_CANDIDATE_SQL = EXCLUDE_BACKFILL_SQL + (
    "substr(REPLACE(IFNULL(created_at, ''), 'T', ' '), 1, 10) = occurred_on",
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
                cursor.execute(
                    """
                    UPDATE candidate_reviews
                    SET name = ?, score = ?, decision = ?, timing = ?, reason = ?,
                        rule_version = ?, strategy_slug = ?, strategy_revision = ?,
                        effective_params_json = ?, evidence_json = ?, tier = ?, source = ?,
                        created_at = ?
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

    def candidates_payload(
        self,
        occurred_on: str | None = None,
        *,
        include_backfill: bool = False,
    ) -> list[dict[str, Any]]:
        """读取候选池；未传日期时按最新候选日展示。同日同池同标的只返回最新一条。

        默认排除回填源，避免看板把区间重放当成当日真选。
        """
        target_date = normalize_date(occurred_on) if occurred_on else None
        if target_date is None:
            latest = self.conn.execute("SELECT MAX(occurred_on) AS value FROM candidate_reviews").fetchone()["value"]
            target_date = str(latest) if latest else None
        if not target_date:
            return []
        day_clauses = ["occurred_on = ?"]
        params: list[Any] = [target_date]
        if not include_backfill:
            day_clauses.extend(EXCLUDE_BACKFILL_SQL)
            day_clauses.append(EXCLUDE_STALE_API_SCREEN_SQL)
        day_where = " AND ".join(day_clauses)
        rows = self.conn.execute(
            f"""
            SELECT id, occurred_on, pool_id, code, name, score, decision, timing, reason,
                   rule_version, strategy_slug, strategy_revision, effective_params_json,
                   evidence_json, tier, source, created_at
            FROM (
                SELECT id, occurred_on, pool_id, code, name, score, decision, timing, reason,
                       rule_version, strategy_slug, strategy_revision, effective_params_json,
                       evidence_json, tier, source, created_at,
                       ROW_NUMBER() OVER (
                           PARTITION BY pool_id, code
                           ORDER BY created_at DESC, id DESC
                       ) AS rn
                FROM candidate_reviews
                WHERE {day_where}
            ) ranked
            WHERE rn = 1
            ORDER BY score DESC NULLS LAST, created_at ASC
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
                "timing": _normalize_timing(str(row["timing"])),
                "reason": _normalize_reason_text(str(row["reason"])),
                "rule_version": _normalize_rule_version(str(row["rule_version"])),
                "strategy_slug": str(row["strategy_slug"]),
                "strategy_revision": str(row["strategy_revision"]),
                "effective_params": _loads(str(row["effective_params_json"])),
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
        include_backfill: bool = False,
    ) -> list[dict[str, Any]]:
        """跨日期/战法的候选列表，供工作台列表页使用（不再按天侧栏）。

        默认排除回填源；审计回填时传 ``include_backfill=True``。
        """
        clauses: list[str] = []
        params: list[Any] = []
        if not include_backfill:
            clauses.extend(EXCLUDE_BACKFILL_SQL)
            clauses.append(EXCLUDE_STALE_API_SCREEN_SQL)
        if strategy and strategy.strip():
            raw = strategy.strip()
            like = f"%{raw}%"
            normalized = _normalize_rule_version(raw)
            if normalized != raw:
                # 输入旧 slug / 别名时，同时模糊匹配原文与归一后的中文战法名
                clauses.append(
                    "(strategy_slug LIKE ? OR rule_version LIKE ? OR rule_version LIKE ?)"
                )
                params.extend([like, like, f"%{normalized}%"])
            else:
                clauses.append("(strategy_slug LIKE ? OR rule_version LIKE ?)")
                params.extend([like, like])
        if decision and decision.strip():
            clauses.append("decision = ?")
            params.append(_normalize_decision(decision.strip()))
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
                   rule_version, strategy_slug, strategy_revision, effective_params_json,
                   evidence_json, tier, source, created_at
            FROM (
                SELECT id, occurred_on, pool_id, code, name, score, decision, timing, reason,
                       rule_version, strategy_slug, strategy_revision, effective_params_json,
                       evidence_json, tier, source, created_at,
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
                "timing": _normalize_timing(str(row["timing"])),
                "reason": _normalize_reason_text(str(row["reason"])),
                "rule_version": _normalize_rule_version(str(row["rule_version"])),
                "strategy_slug": str(row["strategy_slug"]),
                "strategy_revision": str(row["strategy_revision"]),
                "effective_params": _loads(str(row["effective_params_json"])),
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
        live_only: bool = True,
    ) -> list[dict[str, Any]]:
        """按战法（rule_version）查历史选股记录。

        每天、每标的取最新一条（同池同标的可能重跑），按日期倒序。
        用于前端"选股历史"页：按战法+日期区间浏览，不依赖账本的精选口径。

        默认 ``live_only=True``：排除回填，且要求写入日=选股日（盘后真选）。
        传 ``live_only=False`` 可含回填审计。
        """
        raw = rule_version.strip()
        params: list[Any] = [raw, _normalize_rule_version(raw)]
        clauses = ["(strategy_slug = ? OR rule_version = ?)"]
        if start:
            clauses.append("occurred_on >= ?")
            params.append(start)
        if end:
            clauses.append("occurred_on <= ?")
            params.append(end)
        if live_only:
            clauses.extend(LIVE_CANDIDATE_SQL)
        where = " AND ".join(clauses)
        params.append(int(limit))
        rows = self.conn.execute(
            f"""
            SELECT id, occurred_on, pool_id, code, name, score, decision, timing, reason,
                   rule_version, strategy_slug, strategy_revision, effective_params_json,
                   evidence_json, source, created_at
            FROM (
                SELECT id, occurred_on, pool_id, code, name, score, decision, timing, reason,
                       rule_version, strategy_slug, strategy_revision, effective_params_json,
                       evidence_json, source, created_at,
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
                "timing": _normalize_timing(str(row["timing"])),
                "reason": _normalize_reason_text(str(row["reason"])),
                "rule_version": _normalize_rule_version(str(row["rule_version"])),
                "strategy_slug": str(row["strategy_slug"]),
                "strategy_revision": str(row["strategy_revision"]),
                "effective_params": _loads(str(row["effective_params_json"])),
                "evidence": _loads(str(row["evidence_json"])),
                "source": str(row["source"]),
                "created_at": str(row["created_at"]),
            }
            for row in rows
        ]

    @staticmethod
    def _is_selected_decision(decision: str) -> bool:
        """精选口径：裁决归一后仅「精选」算入选；观察/落选不算。"""
        return _normalize_decision(decision) == "精选"

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
        visible_where = " AND ".join((*EXCLUDE_BACKFILL_SQL, EXCLUDE_STALE_API_SCREEN_SQL))
        rows = self.conn.execute(
            f"""
            SELECT occurred_on AS date, pool_id
            FROM candidate_reviews
            WHERE {visible_where}
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
