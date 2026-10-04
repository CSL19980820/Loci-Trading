"""猎隼复盘的本账户证据窗口；分页读齐，只有已落账成交可作执行样本。"""
from datetime import date, datetime, timedelta

from src.ops.application.falcon_candidates import project_falcon_candidate_scope


def falcon_review_evidence(ledger, agent_id: str, phase: str, scope: dict, *, checkpoint=None) -> dict:
    target = date.fromisoformat(scope["research_date"])
    start = target - timedelta(days=target.weekday()) if phase == "weekly_review" else target
    cutoff = datetime.fromisoformat(scope["research_cutoff"])
    result = {"start": start.isoformat(), "end": target.isoformat(), "cutoff": cutoff.isoformat(),
              "runs": [], "trades": [], "warnings": []}
    for kind in ("runs", "trades"):
        offset = 0
        while True:
            if checkpoint:
                checkpoint()
            page = ledger.history(agent_id, kind=kind, start=start.isoformat(), end=target.isoformat(), limit=100, offset=offset)
            for row in page["items"]:
                at = row.get("finished_at") if kind == "runs" else row.get("at")
                if not at or datetime.fromisoformat(at) > cutoff:
                    continue
                if kind == "trades":
                    result["trades"].append({**row, "evidence_id": f"trade:{row['id']}"})
                    continue
                detail = ledger.run_detail(agent_id, row["id"])["detail"]
                run_evidence = {key: detail.get(key) for key in (
                    "decisions", "fills", "rejects", "learning",
                    "research_plan", "research_plan_structured", "assessments", "detail",
                    "assessment_coverage", "watch_snapshot", "learning_changes",
                    "analysis_only", "as_of", "error")}
                # 旧日记可能保存了全市场取数快照；只投影读回证据，不改写历史记录。
                run_evidence["candidate_scope"] = project_falcon_candidate_scope(detail.get("candidate_scope"))
                result["runs"].append({**row, "evidence_id": row["id"],
                                       **run_evidence})
            offset += len(page["items"])
            if offset >= page["total"] or not page["items"]:
                break
    if not result["runs"]:
        result["warnings"].append("所选窗口没有已完成的本账户日记；不推断缺失决策或补造经验。")
    return result


def falcon_learning_evidence(candidate_scope: dict, review: dict) -> dict:
    candidates = list(candidate_scope.get("candidates", []))
    for run in review.get("runs", []):
        candidates.extend((run.get("candidate_scope") or {}).get("candidates", []))
    # 不把期末重新读取的可变分数覆盖当轮已保存的历史证据。
    rows = {row["evidence_id"]: {key: row.get(key) for key in (
        "evidence_id", "code", "name", "sources", "source", "date", "score", "decision", "produced_at")}
        for row in candidates if row.get("evidence_id")}
    return {"candidates": list(rows.values()),
            "runs": [{key: row.get(key) for key in ("evidence_id", "phase", "started_at", "status", "summary")} for row in review.get("runs", [])],
            "trades": review.get("trades", []), "warnings": review.get("warnings", [])}
