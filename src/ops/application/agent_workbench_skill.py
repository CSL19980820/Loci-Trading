"""股票智能体内置辅助技能：运行时加载、交易所日程与真实复核覆盖。"""
from __future__ import annotations

import hashlib
from copy import deepcopy
from datetime import date, timedelta

from src.market import scheduled_trading_days
from src.ops.application.skill_manifest import parse_manifest
from src.ops.application.stock_agent_decision import StockAgentDecision, StockAssessment
from src.shared.paths import PROJECT_ROOT

SKILL_SLUG = "compact-stock-research"


def authority_calendar(payload: dict) -> dict:
    """公告日程为准；未配置年度返回未知，不退回普通工作日。"""
    raw = str(payload.get("research_date") or payload.get("as_of") or "")[:10]
    try:
        day = date.fromisoformat(raw)
    except ValueError:
        return {"as_of_date": raw, "status": "unknown", "next_trade_date": None,
                "reason": "缺少有效研究日期", "basis": "system_exchange_schedule"}
    try:
        for offset in range(1, 46):
            target = (day + timedelta(days=offset)).isoformat()
            if scheduled_trading_days(target, target):
                return {"as_of_date": day.isoformat(), "status": "known", "next_trade_date": target,
                        "basis": "system_exchange_schedule"}
    except ValueError as exc:
        return {"as_of_date": day.isoformat(), "status": "unknown", "next_trade_date": None,
                "reason": str(exc), "basis": "system_exchange_schedule"}
    return {"as_of_date": day.isoformat(), "status": "unknown", "next_trade_date": None,
            "reason": "公告日程中未找到随后45天的交易日", "basis": "system_exchange_schedule"}


def _required_codes(payload: dict, kind: str) -> list[str]:
    portfolio = payload.get("portfolio") or {}
    keys = ("positions",) if kind == "leader" and payload.get("phase") in {"intraday", "closeout"} else ("watchlist", "positions")
    return list(dict.fromkeys(str(row["code"]) for key in keys
                             for row in portfolio.get(key, []) if row.get("code")))


def prepare_agent_workbench_skill(payload: dict, *, kind: str = "falcon") -> tuple[dict, str, dict]:
    """每轮实际读入宿主SKILL.md；收据可审计版本和正文指纹。"""
    text = (PROJECT_ROOT / "templates" / "agent-workbench" / SKILL_SLUG / "SKILL.md").read_text(encoding="utf-8")
    manifest, instructions = parse_manifest(text)
    if manifest.get("slug") != SKILL_SLUG or manifest.get("capability") != "agent_workbench":
        raise ValueError("内置智能体辅助技能元数据不匹配")
    enriched = deepcopy(payload)
    enriched["authority_calendar"] = authority_calendar(payload)
    enriched["required_assessment_codes"] = _required_codes(payload, kind)
    receipt = {"slug": SKILL_SLUG, "name": manifest["name"], "version": manifest["version"],
               "sha256": hashlib.sha256(text.encode("utf-8")).hexdigest(), "phase": payload.get("phase", "intraday"),
               "loaded": True, "output_contract": "stock_agent_structured_v1"}
    return enriched, instructions, receipt


def normalize_stock_agent_research(decision: StockAgentDecision, payload: dict, *, kind: str = "falcon") -> tuple[StockAgentDecision, dict]:
    """补上诚实的未复核条目；覆盖指标只由实际必复核池计算。"""
    result = decision.model_copy(deep=True)
    required = _required_codes(payload, kind)
    allowed = set(required) | set((payload.get("candidate_scope") or {}).get("research_codes", []))
    outside = {row.code for row in result.assessments}
    if result.research_plan_structured:
        outside.update(row.code for row in result.research_plan_structured.stocks)
    if kind == "falcon" and outside - allowed:
        raise ValueError("每股评估或计划超出猎隼本轮研究范围：" + "、".join(sorted(outside - allowed)))
    by_code = {row.code: row for row in result.assessments}
    missing_quotes = set((payload.get("watch_snapshot") or {}).get("missing_codes", []))
    for code in required:
        if code not in by_code:
            row = StockAssessment(code=code, stance="unreviewed", summary="本轮未提供该股复核结论", data_status="missing" if code in missing_quotes else "partial")
            result.assessments.append(row)
            by_code[code] = row
        elif code in missing_quotes:
            by_code[code].data_status = "missing"
            by_code[code].expected_entry_price = None
    reviewed = [code for code in required if by_code[code].stance != "unreviewed"]
    coverage = {"required_codes": required, "reviewed_codes": reviewed,
                "unreviewed_codes": [code for code in required if code not in reviewed],
                "focus_codes": [row.code for row in result.assessments if row.focus],
                "total": len(required), "reviewed": len(reviewed), "complete": len(required) == len(reviewed)}
    calendar = authority_calendar(payload)
    original = result.research_plan_structured.next_trade_date if result.research_plan_structured else None
    if result.research_plan_structured:
        result.research_plan_structured.next_trade_date = calendar["next_trade_date"]
    return result, {"assessment_coverage": coverage, "authority_calendar": calendar,
                    "calendar_validation": {"model_next_trade_date": original,
                        "next_trade_date": calendar["next_trade_date"], "corrected": bool(result.research_plan_structured) and original != calendar["next_trade_date"]}}
