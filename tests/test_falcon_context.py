import json
from copy import deepcopy
from types import SimpleNamespace

from src.ops.application.guardian_research_context import ResearchContext
from src.ops.application.stock_agent_decide import compact_stock_agent_payload, decide_stock_agent


def test_large_target_evidence_is_readable_without_filling_initial_context():
    evidence = {"score_components": {"trend": 30}, "explanation": "目标股证据" * 3000}
    payload = {"candidate_scope": {"candidate_codes": ["301180"], "research_codes": ["301180"],
        "candidates": [{"code": "301180", "score": 88, "decision": "精选", "evidence": evidence}]},
        "portfolio": {"positions": [], "cash_cents": 20_000_000}}
    original = deepcopy(payload)
    archive = ResearchContext()
    compact, metrics = compact_stock_agent_payload(archive, payload, kind="falcon")
    row = compact["candidate_scope"]["candidates"][0]
    assert row["code"] == "301180" and row["score"] == 88
    assert compact["candidate_scope"]["candidate_codes"] == ["301180"]
    assert compact["portfolio"] == payload["portfolio"]
    assert metrics["prompt_characters"] < metrics["original_characters"] / 4
    query = {"ref": row["evidence"]["source"]["evidence_ref"], "limit": 24000}
    readback = json.loads(archive.read(query)["text"])
    assert json.loads(readback["text"]) == evidence
    assert payload == original


def test_completion_tool_audit_is_saved_without_private_repair_objects(monkeypatch):
    import src.ops.application.stock_agent_decide as module
    provider = SimpleNamespace(model="deepseek-v4.1-flash", protocol="openai_compatible")
    monkeypatch.setattr(module, "resolve_config", lambda *_a, **_k: provider)
    monkeypatch.setattr(module, "stock_agent_tools", lambda *_a, **_k: ([], lambda *_: {}, {}))
    meta = {"model": provider.model, "input_tokens": 10, "output_tokens": 5, "rounds": 1,
        "tool_calls": 1, "tools": [{"name": "falcon_candidates_read", "arguments": {}, "ok": True}],
        "context_documents": {"evidence:abc": {"label": "目标股资料", "text": "证据"}},
        "attempts": [{"finish_reason": "stop"}], "_repair": {"private": object()}}
    monkeypatch.setattr(module, "complete_decision", lambda *_a, **_k: (object(), meta))
    config = {"kind": "falcon", "provider": "B.AI · 守护", "model": provider.model, "prompt": "研判",
        "common_prompt": "范围", "thinking": "", "parallel_tools": 4,
        "daily_selection_limit": 0, "watch_limit": 0, "position_limit": 0,
        "temporary_position_limit": 0, "max_position_pct": 100}
    _, usage = decide_stock_agent(None, {"config": config}, {"phase": "research", "candidate_scope": {}},
        palace_path="unused", checkpoint=lambda *_: None, deadline=10**20)
    assert usage["tools"] == meta["tools"]
    assert usage["context_documents"]["evidence:abc"]["label"] == "目标股资料"
    assert usage["context_documents"]["evidence:abc"]["characters"] == 2
    assert "text" not in usage["context_documents"]["evidence:abc"]
    assert usage["attempts"] == meta["attempts"]
    assert "_repair" not in usage
    json.dumps(usage)


def test_full_review_window_has_readable_run_index_instead_of_repeated_bodies():
    runs = [{"id": f"run-{i}", "evidence_id": f"run-{i}", "phase": "review", "status": "success",
             "research_plan": "原始计划" * 4000, "candidate_scope": {"candidate_codes": ["301180"]}}
            for i in range(35)]
    archive = ResearchContext()
    compact, metrics = compact_stock_agent_payload(archive, {"review_evidence": {"runs": runs}}, kind="falcon")
    index = compact["review_evidence"]["runs"]
    assert len(index) == 35
    assert [row["evidence_id"] for row in index] == [row["evidence_id"] for row in runs]
    assert metrics["prompt_characters"] < metrics["original_characters"] / 10
    last = json.loads(archive.read({"ref": index[-1]["source"]["evidence_ref"], "limit": 24000})["text"])
    assert json.loads(last["text"]) == runs[-1]
