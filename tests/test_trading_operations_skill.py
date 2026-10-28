from copy import deepcopy
import hashlib

import pytest

from src.ops.application import trading_operations_skill as skill


def test_default_skill_is_the_real_shared_document_and_never_expands_account():
    payload = {"phase": "intraday", "portfolio": {"cash_cents": 100000, "positions": []},
               "position_policy": {"buyable_boards": ["沪深主板"]}, "candidate_scope": {"entry_codes": ["000001"]}}
    before = deepcopy(payload)
    context, instructions, receipt = skill.prepare_trading_operations_skill(payload)
    text = (skill.PROJECT_ROOT / "templates/agent-workbench/trading-operations/SKILL.md").read_text(encoding="utf-8")
    _, body = skill.parse_manifest(text)
    assert body in instructions
    assert receipt["sha256"] == hashlib.sha256(text.encode()).hexdigest()
    assert receipt["loaded"] and receipt["default_context"] and "validated" not in receipt
    assert context["position_policy"] == payload["position_policy"]
    assert context["candidate_scope"] == payload["candidate_scope"]
    assert context["execution_policy"]["mode"] == "paper_quote"
    assert payload == before


@pytest.mark.parametrize("phase", ["auction", "premarket", "review", "research", "consultation"])
def test_analysis_phases_cannot_be_mistaken_for_permission_to_settle(phase):
    context, _, _ = skill.prepare_trading_operations_skill({"phase": phase}, paper=False)
    assert context["execution_policy"] == {"mode": "order_book", "phase": phase,
                                           "analysis_only": True, "price_tolerance_pct": 2}


def test_next_round_reads_updated_skill_instead_of_a_role_or_cached_copy(tmp_path, monkeypatch):
    path = tmp_path / "templates/agent-workbench/trading-operations/SKILL.md"
    path.parent.mkdir(parents=True)
    path.write_text("---\nname: trading-operations\nslug: trading-operations\nversion: 1.0.0\ncapability: agent_workbench\n---\nfirst", encoding="utf-8")
    monkeypatch.setattr(skill, "PROJECT_ROOT", tmp_path)
    first, a = skill.load_trading_operations_skill()
    path.write_text(path.read_text(encoding="utf-8").replace("first", "second"), encoding="utf-8")
    second, b = skill.load_trading_operations_skill()
    assert "first" in first and "second" in second and a["sha256"] != b["sha256"]


def test_missing_or_mismatched_builtin_skill_is_an_explicit_packaging_failure(tmp_path, monkeypatch):
    monkeypatch.setattr(skill, "PROJECT_ROOT", tmp_path)
    with pytest.raises(FileNotFoundError):
        skill.load_trading_operations_skill()
    path = tmp_path / "templates/agent-workbench/trading-operations/SKILL.md"
    path.parent.mkdir(parents=True)
    path.write_text("---\nname: trading-operations\nslug: another\nversion: 1\ncapability: agent_workbench\n---\nrules", encoding="utf-8")
    with pytest.raises(ValueError, match="元数据不匹配"):
        skill.load_trading_operations_skill()


def test_planning_keeps_actual_account_permissions_after_role_rule_extraction():
    from src.ops.application.guardian_review_agent import planning_facts
    facts = {"period": "daily", "current_position_policy": {
        "buyable_boards": ["沪深主板", "创业板"], "legacy_positions_sellable": True}}
    planned = planning_facts(facts)
    assert planned["current_position_policy"] == facts["current_position_policy"]
    assert planned["current_position_policy"] is not facts["current_position_policy"]
