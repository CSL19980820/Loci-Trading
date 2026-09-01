"""候选池查询与按日汇总（Mixin）。"""
from __future__ import annotations

from datetime import date
from typing import Any

from src.ledger.infrastructure.candidates_sql import (
    EXCLUDE_BACKFILL_SQL,
    EXCLUDE_STALE_API_SCREEN_SQL,
    LIVE_CANDIDATE_SQL,
)
from src.ledger.infrastructure.store_types import (
    _loads,
    _normalize_decision,
    _normalize_reason_text,
    _normalize_rule_version,
    _normalize_timing,
    normalize_date,
)


class CandidateQueryMixin:
    def candidate_outcome_rows(self, *, limit: int = 500) -> list[dict[str, Any]]:
        """复盘 T+N 用：跨日去重后的候选裁决行（默认排除 backfill / :history）。"""
        backfill_where = " AND ".join(EXCLUDE_BACKFILL_SQL)
        rows = self.conn.execute(
            f"""
            SELECT id, occurred_on, code, name, score, decision, tier,
                   strategy_slug, rule_version, pool_id
            FROM (
                SELECT *, ROW_NUMBER() OVER (
                    PARTITION BY occurred_on, pool_id, code
                    ORDER BY created_at DESC, id DESC
                ) AS rn FROM candidate_reviews
                WHERE {backfill_where}
            ) ranked WHERE rn = 1
            ORDER BY occurred_on DESC, code
            LIMIT ?
            """,
            (int(limit),),
        )
        return [dict(row) for row in rows]

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
        code: str | None = None,
        strategy: str | None = None,
        decision: str | None = None,
        start: str | None = None,
        end: str | None = None,
        limit: int = 200,
        include_backfill: bool = False,
    ) -> list[dict[str, Any]]:
        """查询候选列表。

        默认排除回填源；审计回填时传 ``include_backfill=True``。
        """
        clauses: list[str] = []
        params: list[Any] = []
        if not include_backfill:
            clauses.extend(EXCLUDE_BACKFILL_SQL)
            clauses.append(EXCLUDE_STALE_API_SCREEN_SQL)
        if code and code.strip():
            clauses.append("code = ?")
            params.append(code.strip())
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

    def candidates_by_strategies(
        self,
        strategies: list[str],
        *,
        start: str | None = None,
        end: str | None = None,
        limit_per_strategy: int = 80,
        live_only: bool = True,
    ) -> dict[str, list[dict[str, Any]]]:
        """多战法选股历史（单次连接多查），供盘面聚合，避免前端 N+1 HTTP。"""
        out: dict[str, list[dict[str, Any]]] = {}
        for raw in strategies:
            slug = str(raw or "").strip()
            if not slug or slug in out:
                continue
            out[slug] = self.candidates_by_strategy(
                slug,
                start=start,
                end=end,
                limit=limit_per_strategy,
                live_only=live_only,
            )
        return out

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
