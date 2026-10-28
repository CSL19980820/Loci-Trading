"""Default operations guidance reaches actual model calls without widening authority."""
from copy import deepcopy
import hashlib
import json
from types import SimpleNamespace

import pytest

from src.ops.application.skill_manifest import parse_manifest
from src.shared.paths import PROJECT_ROOT


def operations_skill():
    text = (PROJECT_ROOT / "templates" / "agent-workbench" / "trading-operations" / "SKILL.md").read_text(encoding="utf-8")
    _, body = parse_manifest(text)
    return body, hashlib.sha256(text.encode("utf-8")).hexdigest()


def assert_operations_loaded(system, receipts=None):
    body, digest = operations_skill()
    assert system.count(body) == 1
    if receipts is not None:
        receipt = next(item for item in receipts if item["slug"] == "trading-operations")
        assert receipt["loaded"] is True and receipt["default_context"] is True and receipt["sha256"] == digest


def test_guardian_actual_call_loads_manual_and_keeps_custom_prompt_and_policy(monkeypatch):
    import src.ai
    from src.ops.application import guardian_agent, guardian_config
    from src.ops.application.guardian_decision import GuardianDecision

    captured = {}
    monkeypatch.setattr(src.ai, "resolve_config", lambda *_a, **_k: SimpleNamespace(model="fixture", protocol="openai"))
    monkeypatch.setattr(guardian_agent, "compose_research_tools", lambda *_a, **_k: ([], lambda *_: {}, {}))

    def complete(*_args, **kwargs):
        captured.update(kwargs)
        return GuardianDecision(summary="等待新证据", orders=[]), {"tools": []}

    monkeypatch.setattr(guardian_agent, "complete_decision", complete)
    config = {**guardian_config.DEFAULTS, "provider": "fixture", "model": "fixture",
              "common_prompt": "保留我的比较偏好", "prompt": "保留我的盘中任务"}
    original = deepcopy(config)
    _, meta = guardian_agent.decide(None, config, {
        "as_of": "2026-10-14T10:05:00+08:00", "portfolio": {"positions": [], "watchlist": []}})
    assert_operations_loaded(captured["system"], meta["builtin_skills"])
    assert captured["system"].count("保留我的比较偏好") == 1
    assert captured["system"].count("保留我的盘中任务") == 1 and config == original
    assert "position_policy" in captured["payload"]
    assert "required_assessment_codes" not in captured["payload"]
    assert "compact-stock-research" not in captured["system"]


@pytest.mark.parametrize("kind", ["falcon", "leader", "custom"])
def test_stock_agent_actual_call_loads_shared_manual_and_own_workbench(monkeypatch, kind):
    from src.ops.application import stock_agent_decide as module

    captured = {}
    provider = SimpleNamespace(model="fixture", protocol="openai_compatible")
    monkeypatch.setattr(module, "resolve_config", lambda *_a, **_k: provider)
    monkeypatch.setattr(module, "stock_agent_tools", lambda *_a, **_k: ([], lambda *_: {}, {}))

    def complete(*_args, **kwargs):
        captured.update(kwargs)
        decision = kwargs["decision_parser"]('{"summary":"保持等待","orders":[]}', require_execution_terms=True)
        return decision, {"tools": [], "context_documents": {}}

    monkeypatch.setattr(module, "complete_decision", complete)
    config = {"kind": kind, "provider": "fixture", "model": "fixture", "common_prompt": "保留独立角色偏好",
              "prompt": "保留独立阶段任务", "daily_selection_limit": 0, "watch_limit": 0,
              "position_limit": 0, "temporary_position_limit": 0, "max_position_pct": 100}
    data = {"as_of": "2026-10-14T10:05:00+08:00", "phase": "intraday", "analysis_only": False,
            "portfolio": {"positions": [], "watchlist": []}, "candidate_scope": {"candidate_codes": [], "research_codes": []}}
    original = deepcopy(data)
    _, usage = module.decide_stock_agent(None, {"config": config}, data, palace_path="unused",
                                         checkpoint=lambda *_: None, deadline=10**20)
    assert_operations_loaded(captured["system"], usage["builtin_skills"])
    assert usage["builtin_skills"][0]["slug"] == "compact-stock-research"
    assert usage["builtin_skills"][1]["slug"] == "trading-operations"
    assert captured["payload"]["execution_policy"]["mode"] == ("paper_quote" if kind == "falcon" else "order_book")
    assert captured["system"].count("保留独立角色偏好") == 1
    assert captured["system"].count("保留独立阶段任务") == 1 and data == original
    if kind == "leader":
        assert "不新开仓或加仓" in captured["system"]
        assert "不增删或替换观察池" in captured["system"]
    elif kind == "falcon":
        assert "新买入/加仓/新增观察仅限candidate_codes" in captured["system"]
        assert "不对自动公式对象输出unwatch" in captured["system"]


@pytest.mark.parametrize("period", ["premarket", "daily", "weekly"])
@pytest.mark.parametrize("stage", ["report", "planning", "retrospective"])
def test_report_phases_load_manual_without_treating_current_rules_as_history(period, stage):
    from src.ops.application.guardian_config import DEFAULTS
    from src.ops.application.guardian_review_prompts import review_system

    config = {**DEFAULTS, "common_prompt": "保留复盘共用偏好", "premarket_prompt": "保留自定阶段任务",
              "review_prompt": "保留自定阶段任务", "weekly_prompt": "保留自定阶段任务"}
    system = review_system(config, period, {}, stage=stage)
    assert_operations_loaded(system)
    assert system.count("保留复盘共用偏好") == 1 and system.count("保留自定阶段任务") == 1
    if stage == "retrospective":
        assert "不能倒推历史成交" in system
    assert "不核验盘口、涨跌停排队和挂单量" not in system


def test_experience_repair_does_not_widen_to_trade_or_planning_tasks():
    from src.ops.application.guardian_config import DEFAULTS
    from src.ops.application.guardian_review_prompts import review_system

    system = review_system(DEFAULTS, "daily", {}, stage="experience")
    assert "本阶段只修复本轮经验列表" in system
    body, _ = operations_skill()
    assert body not in system


@pytest.mark.parametrize("stage", ["report", "retrospective", "planning"])
def test_review_actual_model_call_receives_manual_and_only_research_authority(tmp_path, monkeypatch, stage):
    import src.ai
    from src.ops.application import guardian_completion, guardian_research_tools, guardian_review_agent

    captured = {}
    source_options = {}
    monkeypatch.setattr(src.ai, "resolve_config", lambda *_a, **_k: SimpleNamespace(
        model="fixture", protocol="openai", max_output_tokens=4096))

    def sources(*_args, **kwargs):
        source_options.update(kwargs)
        return [], lambda *_a: {}, {}

    monkeypatch.setattr(guardian_research_tools, "compose_research_tools", sources)

    def run(*_args, **kwargs):
        captured.update(kwargs)
        body = {"plans": [], "next_steps": [], "watchlist_updates": []} if stage == "planning" else {
            "summary": "本阶段只做研究与复核", "experience": None}
        return SimpleNamespace(text=json.dumps(body), stopped_reason="completed", finish_reason="stop", output_tokens=10)

    monkeypatch.setattr(guardian_completion, "run_accounted_agent", run)
    config = {"provider": "fixture", "model": "fixture", "common_prompt": "保留实际复盘偏好"}
    facts = {"period": "daily", "trade_date": "2026-10-14", "created_at": "2026-10-14T16:00:00+08:00",
             "account": {"positions": []}, "experience": {"revision": 1, "items": [], "text": ""}, "evidence_ids": [],
             "current_position_policy": {"buyable_boards": ["沪深主板", "创业板"]}}
    if stage == "planning":
        facts = guardian_review_agent.planning_facts(facts)
    _, usage, _ = guardian_review_agent._generate_review(
        None, config, facts, stage=stage, palace_path=str(tmp_path / "palace.db"))
    assert_operations_loaded(captured["system"], usage["builtin_skills"])
    assert source_options["read_only"] is True
    assert "保留实际复盘偏好" in captured["system"]
    assert '"analysis_only": true' in captured["system"]
    assert json.loads(captured["user_prompt"])["current_position_policy"]["buyable_boards"] == ["沪深主板", "创业板"]


def test_consultation_actual_call_loads_manual_and_preserves_read_only_scope(tmp_path, monkeypatch):
    import src.ai
    from src.ledger import GuardianStore
    from src.ops.application import guardian_consult as module, guardian_completion, guardian_research_tools

    captured = {}
    provider = SimpleNamespace(model="fixture", protocol="openai", context_window=10000, max_output_tokens=1000)
    monkeypatch.setattr(src.ai, "resolve_config", lambda *_a, **_k: provider)
    monkeypatch.setattr(module, "get_config", lambda _: {"provider": "fixture", "model": "fixture", "common_prompt": "保留咨询偏好"})
    monkeypatch.setattr(guardian_research_tools, "compose_research_tools", lambda *_a, **_k: ([], lambda *_: {}, {}))

    def run(*_args, **kwargs):
        captured.update(kwargs)
        return SimpleNamespace(text="等待新证据", model="fixture", invocations=[], messages=[],
                               stopped_reason="completed", finish_reason="stop")

    monkeypatch.setattr(guardian_completion, "run_accounted_agent", run)
    with GuardianStore(tmp_path / "palace.db") as ledger:
        ledger.submit_consultation("topic", "request", "讨论当前计划", "")
        turn = ledger.claim_consultation("request")
        result, _ = module.answer_consultation(None, ledger, turn)
    assert_operations_loaded(captured["system"], result["usage"]["builtin_skills"])
    assert captured["system"].count("保留咨询偏好") == 1
    assert "不输出订单JSON、不执行交易" in captured["system"]
    assert "此对话不能改变模拟账户、自动任务、观察池或实盘持仓" in captured["system"]
    snapshot = json.loads(captured["messages"][-1].content)
    assert snapshot["current_position_policy"]["buyable_boards"] == ["沪深主板", "创业板"]
