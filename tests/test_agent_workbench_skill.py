import json
from copy import deepcopy
from types import SimpleNamespace

import pytest
from pydantic import ValidationError

from src.market.domain.exchange_schedule import scheduled_trading_days
from src.ops.application.agent_workbench_skill import (
    authority_calendar,
    normalize_stock_agent_research,
    prepare_agent_workbench_skill,
)
from src.ops.application.stock_agent_decision import StockAgentDecision


def payload():
    codes = [f"600{index:03}" for index in range(16)]
    return {"phase": "research", "research_date": "2026-09-30",
            "portfolio": {"watchlist": [{"code": code} for code in codes], "positions": [{"code": "301180"}]},
            "candidate_scope": {"research_codes": [*codes, "301181"]},
            "watch_snapshot": {"quotes": {}, "missing_codes": [codes[-1]]}}


def assessment(code, **changes):
    return {"code": code, "stance": "wait", "summary": "来源仍有效，等待回踩承接确认", **changes}


def decision(**changes):
    return StockAgentDecision.model_validate({"summary": "等待有效触发，本轮空仓", "orders": [], **changes})


def test_sixteen_pool_qualification_is_distinct_from_two_focused_stocks():
    data = payload()
    required = [row["code"] for row in data["portfolio"]["watchlist"]] + ["301180"]
    value = decision(assessments=[assessment(code, focus=index < 2) for index, code in enumerate(required)])
    normalized, meta = normalize_stock_agent_research(value, data)
    coverage = meta["assessment_coverage"]
    assert coverage["total"] == coverage["reviewed"] == 17
    assert coverage["complete"] is True
    assert coverage["focus_codes"] == required[:2]
    assert "301181" not in coverage["required_codes"]  # 落选研究资格不等于必扫名单。
    assert len(normalized.assessments) == 17


def test_missing_assessments_are_truthful_and_quote_failure_clears_target_price():
    data = payload()
    original = deepcopy(data)
    value = decision(assessments=[assessment("600000", focus=True),
        assessment("600015", expected_entry_price=12.5, data_status="available")])
    normalized, meta = normalize_stock_agent_research(value, data)
    assert meta["assessment_coverage"]["reviewed"] == 2
    assert meta["assessment_coverage"]["complete"] is False
    assert len(meta["assessment_coverage"]["unreviewed_codes"]) == 15
    missing = next(row for row in normalized.assessments if row.code == "600001")
    assert missing.stance == "unreviewed" and missing.expected_entry_price is None and not missing.focus
    unavailable = next(row for row in normalized.assessments if row.code == "600015")
    assert unavailable.data_status == "missing" and unavailable.expected_entry_price is None
    assert len(value.assessments) == 2 and data == original


@pytest.mark.parametrize("field", ["assessments", "research_plan_structured"])
def test_falcon_structured_fields_cannot_introduce_market_stocks(field):
    changes = {field: [assessment("600519")]} if field == "assessments" else {
        field: {"stocks": [{"code": "600519", "entry_condition": "关注池外股票"}]}}
    with pytest.raises(ValueError, match="超出猎隼"):
        normalize_stock_agent_research(decision(**changes), payload())


def test_actual_exchange_schedule_corrects_holiday_plan_and_preserves_model_value(monkeypatch):
    import src.ops.application.agent_workbench_skill as module
    monkeypatch.setattr(module, "scheduled_trading_days", scheduled_trading_days)
    data = payload()
    value = decision(research_plan_structured={"market_view": "假期等待", "next_trade_date": "2026-10-09"})
    normalized, meta = normalize_stock_agent_research(value, data)
    assert authority_calendar(data)["next_trade_date"] == "2026-10-08"
    assert normalized.research_plan_structured.next_trade_date == "2026-10-08"
    assert value.research_plan_structured.next_trade_date == "2026-10-09"
    assert meta["calendar_validation"] == {"model_next_trade_date": "2026-10-09", "next_trade_date": "2026-10-08", "corrected": True}


def test_unpublished_year_stays_unknown_instead_of_weekday_guess(monkeypatch):
    import src.ops.application.agent_workbench_skill as module
    monkeypatch.setattr(module, "scheduled_trading_days", scheduled_trading_days)
    result = authority_calendar({"research_date": "2026-12-31"})
    assert result["status"] == "unknown" and result["next_trade_date"] is None
    assert "尚未配置" in result["reason"]


def test_workbench_skill_is_real_manifest_loaded_without_strategy_capability():
    source = payload()
    enriched, instructions, receipt = prepare_agent_workbench_skill(source)
    assert receipt["loaded"] and receipt["slug"] == "compact-stock-research" and len(receipt["sha256"]) == 64
    assert "assessments" in instructions and "operations" not in enriched
    assert enriched["authority_calendar"]["basis"] == "system_exchange_schedule"
    assert len(enriched["required_assessment_codes"]) == 17
    assert "authority_calendar" not in source


def test_leader_intraday_required_review_respects_existing_positions_only_boundary():
    data = {**payload(), "phase": "intraday"}
    enriched, _, _ = prepare_agent_workbench_skill(data, kind="leader")
    assert enriched["required_assessment_codes"] == ["301180"]
    _, meta = normalize_stock_agent_research(decision(), data, kind="leader")
    assert meta["assessment_coverage"]["required_codes"] == ["301180"]


def test_old_string_plans_remain_parseable_and_new_fields_have_character_limits():
    assert decision(research_plan="旧历史长计划" * 1000).research_plan.startswith("旧历史")
    for changes in ({"assessments": [assessment("600000", summary="字" * 121)]},
                    {"assessments": [assessment("600000", expected_entry_price=float("nan"))]},
                    {"assessments": [assessment("600000", expected_entry_price=True)]},
                    {"assessments": [assessment("600000"), assessment("600000")]},
                    {"assessments": [assessment("600000", stance="unreviewed", focus=True)]},
                    {"detail": {"market_summary": "字" * 201}}):
        with pytest.raises(ValidationError):
            decision(**changes)


def test_decide_loads_skill_and_validates_real_parser_without_invoking_model(monkeypatch):
    import src.ops.application.stock_agent_decide as module
    provider = SimpleNamespace(model="fixture", protocol="openai_compatible")
    monkeypatch.setattr(module, "resolve_config", lambda *_a, **_k: provider)
    monkeypatch.setattr(module, "stock_agent_tools", lambda *_a, **_k: ([], lambda *_: {}, {}))
    captured = {}
    def complete(*_args, **kwargs):
        captured.update(kwargs)
        result = kwargs["decision_parser"](json.dumps({"summary": "先观察", "orders": [],
            "assessments": [assessment("600000", focus=True)]}), require_execution_terms=True)
        return result, {"model": "fixture", "context_documents": {}}
    monkeypatch.setattr(module, "complete_decision", complete)
    config = {"kind": "falcon", "provider": "fixture", "model": "fixture", "prompt": "研判", "common_prompt": "只研究系统范围",
        "daily_selection_limit": 0, "watch_limit": 0, "position_limit": 0, "temporary_position_limit": 0, "max_position_pct": 100}
    result, usage = module.decide_stock_agent(None, {"config": config}, payload(), palace_path="unused",
        checkpoint=lambda *_: None, deadline=10**20)
    assert "实际加载的内置辅助技能：compact-stock-research" in captured["system"]
    assert captured["payload"]["authority_calendar"]["next_trade_date"] == "2026-10-08"
    assert usage["builtin_skills"][0]["validated"] is True
    assert len(result.assessments) == 17 and usage["assessment_coverage"]["reviewed"] == 1
