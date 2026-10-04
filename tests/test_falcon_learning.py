"""经验引用与合并边界：旧复盘、成交事实、归属和有界记忆。"""
import copy
import json
from datetime import datetime, timedelta

import pytest
from pydantic import ValidationError

from src.ledger.domain.guardian_account import new_guardian_account
from src.ledger.infrastructure.stock_agent_store import StockAgentStore
from src.ledger.infrastructure.stock_agent_history import encode_agent_json
from src.ops.application.falcon_learning import (
    LESSON_LIMIT,
    PROPOSAL_LIMIT,
    AUDIT_BYTE_LIMIT,
    OPERATION_LIMIT,
    apply_falcon_learning,
    falcon_learning_context,
    maintain_falcon_learning,
    public_falcon_learning,
)
from src.ops.application.falcon_review_evidence import falcon_learning_evidence, falcon_review_evidence
from src.ops.application.stock_agent_decision import StockAgentDecision, parse_stock_agent_decision
from src.ops.domain.stock_agent import StockAgentConfig
from src.shared.tenancy import tenant_scope

DAY = "2026-09-30"


def lesson(item_id="timing", reference="candidate:1", **changes):
    return {"id": item_id, "title": "等待承接", "finding": "高开后首次回踩有承接时再参与",
            "conditions": "仅适用于强板块且量能持续的环境", "status": "pending",
            "evidence_refs": [reference], "sample_size": 1, "sample_basis": "observed",
            "sample_definition": "当日系统候选1只，按股票去重", "positive_examples": [],
            "counter_examples": [], "validation_plan": "下一周分别记录承接成立和失效的候选，比较滑点和回撤",
            **changes}


def decision(*items, proposals=()):
    return StockAgentDecision.model_validate({"summary": "依据实际记录复盘", "orders": [],
        "learning": {"lessons": list(items), "optimization_proposals": list(proposals)}})


def apply(state, value, day=DAY, phase="review", *, evidence=("candidate:1",), trades=(), agent_id="falcon-a"):
    return apply_falcon_learning(state, value, phase, day, agent_id=agent_id,
                                 evidence_ids=evidence, executed_trade_ids=trades)


def test_optional_learning_keeps_other_agents_compatible():
    value = parse_stock_agent_decision('{"summary":"观察","orders":[]}')
    assert value.learning is None
    state = new_guardian_account()
    assert apply(state, value) == state


def test_learning_is_additive_and_does_not_change_account_or_strategy():
    state = new_guardian_account()
    state["strategy_config"] = {"weights": {"momentum": 30}}
    untouched = copy.deepcopy(state)
    first = apply(state, decision(lesson()))
    proposal = lesson("momentum-score", target="scoring", proposed_change="研究退潮时动量评分的校准误差")
    second = apply(first, decision(lesson("sector"), proposals=[proposal]), day="2026-10-01")
    assert state == untouched
    assert second["strategy_config"] == untouched["strategy_config"]
    assert {item["id"] for item in second["falcon_learning"]["lessons"]} == {"timing", "sector"}
    assert second["falcon_learning"]["optimization_proposals"][0]["target"] == "scoring"
    assert {key: value for key, value in second.items() if key != "falcon_learning"} == untouched


def test_update_preserves_prior_evidence_and_counterexamples():
    state = apply({}, decision(lesson(counter_examples=[{"evidence_ref": "candidate:1", "interpretation": "承接失效后继续下跌"}])))
    update = lesson(reference="candidate:2", status="supported", sample_size=1,
                    sample_definition="次日新增实际候选1只，按股票去重；前日反例仍作为适用条件限定",
                    positive_examples=[{"evidence_ref": "candidate:2", "interpretation": "承接成立后交易成本可控"}])
    changed = apply(state, decision(update), day="2026-10-01", evidence=("candidate:2",))
    result = changed["falcon_learning"]["lessons"][0]
    assert result["evidence_refs"] == ["candidate:1", "candidate:2"]
    assert len(result["counter_examples"]) == len(result["positive_examples"]) == 1
    assert result["first_review_date"] == DAY
    assert result["last_review_date"] == "2026-10-01"
    assert result["status"] == "supported"


def test_historical_review_does_not_overwrite_newer_live_memory():
    state = apply({}, decision(lesson()), day="2026-10-02")
    changed = apply(state, decision(lesson(finding="较早时点的不同观点")), day=DAY)
    assert changed == state
    assert falcon_learning_context(state, agent_id="falcon-a", research_date=DAY) == {
        "lessons": [], "optimization_proposals": []}
    with pytest.raises(ValueError, match="未提供的证据"):
        apply(state, decision(lesson(reference="invented:99")), day=DAY)


def test_weekly_review_can_reject_a_lesson_and_daily_does_not_undo_it():
    state = apply({}, decision(lesson()))
    rejected = lesson(status="rejected", counter_examples=[{"evidence_ref": "candidate:1", "interpretation": "周内反例不支持原结论"}])
    state = apply(state, decision(rejected), phase="weekly_review")
    changed = apply(state, decision(lesson(finding="随后补做的日复盘")))
    assert changed["falcon_learning"]["lessons"] == state["falcon_learning"]["lessons"]


def test_empty_or_null_learning_preserves_memory():
    state = apply({}, decision(lesson()))
    assert apply(state, decision()) == state
    assert apply(state, {"learning": None}) == state


@pytest.mark.parametrize("phase", ["auction", "premarket", "intraday", "closeout"])
def test_non_review_cannot_write_learning(phase):
    with pytest.raises(ValueError, match="每日或每周复盘"):
        apply({}, decision(lesson()), phase=phase)


def test_unprovided_evidence_is_rejected_and_does_not_mutate_state():
    state = new_guardian_account()
    before = copy.deepcopy(state)
    with pytest.raises(ValueError, match="未提供的证据"):
        apply(state, decision(lesson(reference="invented:99")))
    assert state == before


@pytest.mark.parametrize("reference", ["preflight:1", "rejected-order:1", "run:1"])
def test_preflight_reject_and_run_id_are_not_committed_trade_samples(reference):
    with pytest.raises(ValueError, match="已入账的成交"):
        apply({}, decision(lesson(reference=reference, sample_basis="executed")), evidence=(reference,))


def test_executed_samples_require_cited_real_trades_and_bound_sample_size():
    record = lesson(reference="trade:1", sample_basis="executed")
    state = apply({}, decision(record), evidence=(), trades=("trade:1",))
    assert state["falcon_learning"]["lessons"][0]["sample_basis"] == "executed"
    with pytest.raises(ValueError, match="样本数"):
        apply({}, decision({**record, "sample_size": 2}), evidence=(), trades=("trade:1", "trade:2"))


@pytest.mark.parametrize("changes", [
    {"sample_basis": "hypothetical", "sample_size": 1},
    {"sample_basis": "hypothetical", "sample_size": 0, "status": "supported"},
    {"status": "supported"},
    {"status": "rejected"},
    {"positive_examples": [{"evidence_ref": "missing:1", "interpretation": "未提供来源"}]},
    {"sample_size": True},
])
def test_learning_schema_rejects_unsupported_fact_status(changes):
    with pytest.raises(ValidationError):
        decision(lesson(**changes))


def test_pending_hypothesis_is_kept_distinct_from_observed_result():
    state = apply({}, decision(lesson(sample_basis="hypothetical", sample_size=0)))
    assert state["falcon_learning"]["lessons"][0]["status"] == "pending"


def test_observed_samples_are_bounded_by_deduplicated_visible_references():
    with pytest.raises(ValueError, match="去重可见证据"):
        apply({}, decision(lesson(evidence_refs=["candidate:1", "candidate:1"], sample_size=2)))
    record = lesson(evidence_refs=["candidate:1", "candidate:2"], sample_size=2)
    state = apply({}, decision(record), evidence=("candidate:1", "candidate:2"))
    assert state["falcon_learning"]["lessons"][0]["sample_size"] == 2


def test_agent_and_tenant_ownership_are_enforced_on_reads_and_writes():
    with tenant_scope("tenant-a"):
        state = apply({}, decision(lesson()))
        with pytest.raises(ValueError, match="归属不匹配"):
            apply(state, decision(lesson()), agent_id="falcon-b")
    with tenant_scope("tenant-b"):
        with pytest.raises(ValueError, match="归属不匹配"):
            apply(state, decision(lesson()))
        with pytest.raises(ValueError, match="归属不匹配"):
            falcon_learning_context(state, agent_id="falcon-a", research_date=DAY)


def test_duplicate_ids_are_rejected_and_memory_is_bounded():
    with pytest.raises(ValidationError, match="id 不能重复"):
        decision(lesson(), lesson())
    state = {}
    for index in range(LESSON_LIMIT + 3):
        proposal = lesson(f"proposal-{index}", target="selection", proposed_change="验证环境分类是否改善排序")
        state = apply(state, decision(lesson(f"lesson-{index}"), proposals=[proposal]))
    assert len(state["falcon_learning"]["lessons"]) == LESSON_LIMIT
    assert len(state["falcon_learning"]["optimization_proposals"]) == PROPOSAL_LIMIT
    assert state["falcon_learning"]["lessons"][0]["id"] == "lesson-3"
    context = falcon_learning_context(state, agent_id="falcon-a", research_date=DAY)
    assert len(context["lessons"]) == 12
    assert len(context["optimization_proposals"]) == 8
    context["lessons"].clear()
    assert len(state["falcon_learning"]["lessons"]) == LESSON_LIMIT


def test_merged_references_and_examples_are_bounded_together():
    state = {}
    for index in range(30):
        ref = f"candidate:{index}"
        item = lesson(reference=ref, positive_examples=[{"evidence_ref": ref, "interpretation": f"观察{index}"}])
        state = apply(state, decision(item), evidence=(ref,))
    record = state["falcon_learning"]["lessons"][0]
    assert len(record["evidence_refs"]) == 24
    assert len(record["positive_examples"]) == 6
    assert all(example["evidence_ref"] in record["evidence_refs"] for example in record["positive_examples"])


def maintain(state, *operations, evidence=("candidate:1",), agent_id="falcon-a", day=DAY):
    return maintain_falcon_learning(state, list(operations), agent_id=agent_id, research_date=day,
                                   evidence_ids=evidence, actor="fixture-user")


def operation(op, item=None, **changes):
    return {"op": op, "collection": "lessons", "id": "timing", "reason": "核对实际样本后维护认识",
            **({"item": item} if item is not None else {}), **changes}


def test_experience_can_validate_update_replace_delete_with_complete_audit():
    state = apply({}, decision(lesson()))
    validated = lesson(status="supported", positive_examples=[{"evidence_ref": "candidate:1", "interpretation": "真实观察符合原假设"}])
    state = maintain(state, operation("validate", validated))
    assert state["falcon_learning"]["lessons"][0]["status"] == "supported"
    state = maintain(state, operation("update", {**validated, "finding": "仅在承接确认且量能持续时适用"}))
    state = maintain(state, operation("replace", lesson("timing-v2", finding="原经验需按环境重新分层")))
    assert [row["id"] for row in state["falcon_learning"]["lessons"]] == ["timing-v2"]
    state = maintain(state, operation("delete", id="timing-v2", reason="与现有环境经验重复，保留审计后删除"))
    memory = state["falcon_learning"]
    assert memory["lessons"] == []
    assert [row["op"] for row in memory["audit"]] == ["create", "validate", "update", "replace", "delete"]
    assert memory["last_changes"][0]["before"]["id"] == "timing-v2"
    assert memory["last_changes"][0]["after"] is None
    assert memory["last_changes"][0]["actor"] == "fixture-user"
    assert memory["audit"][1]["before"]["status"] == "pending"


def test_model_review_uses_the_same_maintenance_contract():
    state = apply({}, decision(lesson()))
    value = StockAgentDecision.model_validate({"summary": "删除重复认识", "orders": [],
        "learning": {"operations": [operation("delete", reason="内容重复且暂无持续研究价值")]}})
    changed = apply(state, value, phase="weekly_review")
    assert changed["falcon_learning"]["lessons"] == []
    assert changed["falcon_learning"]["last_changes"][0]["actor"] == "model"
    assert state["falcon_learning"]["lessons"]


def test_validation_cannot_rewrite_the_original_hypothesis_and_failures_are_atomic():
    state = apply({}, decision(lesson()))
    original = copy.deepcopy(state)
    with pytest.raises(ValueError, match="保留原结论"):
        maintain(state, operation("validate", lesson(finding="偷偷改成不同认识")))
    with pytest.raises(ValueError, match="不存在"):
        maintain(state, operation("delete"), operation("delete", id="missing"))
    assert state == original


def test_operations_require_true_evidence_and_respect_historical_tenant_scope():
    state = apply({}, decision(lesson()), day="2026-10-02")
    with pytest.raises(ValueError, match="未提供的证据"):
        maintain(state, operation("update", lesson(reference="fabricated:1")))
    assert maintain(state, operation("delete"), day=DAY) == state
    with tenant_scope("another-tenant"), pytest.raises(ValueError, match="归属不匹配"):
        maintain(state, operation("delete"))
    with pytest.raises(ValueError, match="已入账的成交"):
        maintain(state, operation("update", lesson(sample_basis="executed")))


def test_manual_maintenance_is_not_undone_by_same_day_weekly_precedence():
    state = apply({}, decision(lesson()), phase="weekly_review")
    changed = maintain(state, operation("update", lesson(finding="用户明确缩小适用条件")))
    assert changed["falcon_learning"]["lessons"][0]["finding"] == "用户明确缩小适用条件"


@pytest.mark.parametrize("ops", [
    [operation("delete", reason="")],
    [operation("delete", lesson())],
    [operation("update")],
    [operation("update", lesson("different-id"))],
    [operation("delete"), operation("delete")],
    [operation("replace", lesson("exists")), operation("update", lesson("exists"), id="exists")],
])
def test_operation_schema_rejects_ambiguous_or_empty_changes(ops):
    with pytest.raises(ValidationError):
        maintain({}, *ops)


def test_new_experience_fields_are_bounded_and_old_text_is_projected_without_rewriting():
    with pytest.raises(ValidationError):
        decision(lesson(finding="字" * 181))
    state = apply({}, decision(lesson()))
    state["falcon_learning"]["lessons"][0]["finding"] = "旧长研究" * 300
    state["falcon_learning"]["lessons"][0]["validation_plan"] = "旧长计划" * 300
    original = copy.deepcopy(state)
    context = falcon_learning_context(state, agent_id="falcon-a", research_date=DAY)
    assert len(context["lessons"][0]["finding"]) == 180
    assert len(context["lessons"][0]["validation_plan"]) == 160
    assert "audit" not in context and state == original
    changed = apply(state, decision(lesson("new")))
    assert any(row["op"] == "compact" and row["before"]["finding"] == original["falcon_learning"]["lessons"][0]["finding"]
               for row in changed["falcon_learning"]["last_changes"])


def test_capacity_pruning_is_audited_instead_of_silent_loss():
    state = {}
    for index in range(LESSON_LIMIT + 1):
        state = apply(state, decision(lesson(f"entry-{index}")))
    assert len(state["falcon_learning"]["lessons"]) == 12
    pruning = next(row for row in state["falcon_learning"]["last_changes"] if row["op"] == "prune")
    assert pruning["before"]["id"] == "entry-0" and pruning["after"] is None


def test_optimization_maintenance_and_replacement_cannot_overwrite_another_entry():
    first = lesson("source-quality", target="selection", proposed_change="按风险环境对候选比较")
    state = apply({}, decision(lesson(), lesson("other"), proposals=[first]))
    with pytest.raises(ValueError, match="id已存在"):
        maintain(state, operation("replace", lesson("other")))
    proposal = {**first, "proposed_change": "对来源质量做有费用口径的对照"}
    changed = maintain(state, operation("update", proposal, id="source-quality", collection="optimization_proposals"))
    assert changed["falcon_learning"]["optimization_proposals"][0]["proposed_change"] == proposal["proposed_change"]
    assert changed["falcon_learning"]["last_changes"][0]["collection"] == "optimization_proposals"
    with pytest.raises(ValidationError, match="类型一致"):
        maintain(state, operation("update", first, id="source-quality"))


def test_public_legacy_learning_is_compact_readonly_and_preserves_evidence_facts():
    memory = {"agent_id": "falcon-a", "tenant_id": "__primary__", "last_review_date": DAY,
              "last_review_phase": "weekly_review", "audit": [{"private": "原维护审计" * 1000}],
              "last_changes": [{"private": "原变更批次"}], "audit_truncated_count": 3,
              "lessons": [lesson(f"lesson-{index}", title="旧标题" * 100, finding="旧结论" * 500,
                  conditions="旧条件" * 400, sample_definition="旧样本口径" * 400,
                  validation_plan="旧验证计划" * 400, first_review_date=DAY, last_review_date=DAY,
                  counter_examples=[{"evidence_ref": "candidate:1", "interpretation": "旧反例" * 300}])
                  for index in range(24)],
              "optimization_proposals": [lesson(f"proposal-{index}", target="scoring",
                  proposed_change="旧判分建议" * 300, last_review_date=DAY) for index in range(16)]}
    last = memory["lessons"][-1]
    last.update(status="supported", sample_size=1,
                positive_examples=[{"evidence_ref": "candidate:1", "interpretation": "当时有实际样本支持"}])
    original = copy.deepcopy(memory)
    projected = public_falcon_learning(memory)
    assert projected["limits"] == {"lessons": 12, "optimization_proposals": 8}
    assert len(projected["lessons"]) == 12 and len(projected["optimization_proposals"]) == 8
    assert projected["lessons"][0]["id"] == "lesson-12"
    assert projected["optimization_proposals"][0]["id"] == "proposal-8"
    visible = projected["lessons"][-1]
    for key, limit in (("title", 40), ("finding", 180), ("conditions", 120),
                       ("sample_definition", 120), ("validation_plan", 160)):
        assert len(visible[key]) == limit
    assert len(visible["counter_examples"][0]["interpretation"]) == 100
    assert len(projected["optimization_proposals"][-1]["proposed_change"]) == 180
    for key in ("status", "sample_size", "sample_basis", "evidence_refs", "first_review_date", "last_review_date"):
        assert visible[key] == last[key]
    assert visible["positive_examples"] == last["positive_examples"]
    assert projected["last_review_phase"] == "weekly_review"
    assert "audit" not in projected and "last_changes" not in projected and "audit_truncated_count" not in projected
    assert memory == original
    projected["lessons"][-1]["evidence_refs"].clear()
    assert memory == original
    assert public_falcon_learning(None) == {"lessons": [], "optimization_proposals": [],
                                           "limits": {"lessons": 12, "optimization_proposals": 8}}


def dense_lesson(item_id="memory", **changes):
    refs = ["candidate:" + str(index) + ":" + "r" * 145 for index in range(24)]
    return lesson(item_id, title="题" * 40, finding="结" * 180, conditions="条" * 120,
                  evidence_refs=refs, sample_size=24, sample_definition="口" * 120,
                  validation_plan="验" * 160,
                  positive_examples=[{"evidence_ref": ref, "interpretation": "正" * 100} for ref in refs[:6]],
                  counter_examples=[{"evidence_ref": ref, "interpretation": "反" * 100} for ref in refs[6:12]], **changes)


def test_audit_byte_budget_keeps_complete_latest_changes_and_prevents_ledger_limit_failure():
    state = {}
    for index in range(50):
        item = dense_lesson()
        item["validation_plan"] = ("验" if index % 2 else "证") * 160
        state = apply(state, decision(item), evidence=item["evidence_refs"])
    memory = state["falcon_learning"]
    assert len(encode_agent_json(memory["audit"]).encode("utf-8")) <= AUDIT_BYTE_LIMIT
    assert memory["audit_truncated_count"] == 50 - len(memory["audit"])
    assert memory["last_changes"][-1] == memory["audit"][-1]
    assert memory["last_changes"][-1]["before"]["validation_plan"] == "证" * 160
    assert memory["last_changes"][-1]["after"]["validation_plan"] == "验" * 160
    assert len(encode_agent_json(state).encode("utf-8")) < 512 * 1024
    full_latest = copy.deepcopy(memory["last_changes"])
    memory["audit"][-1]["reason"] = "调用方只改变审计副本"
    assert memory["last_changes"] == full_latest


def test_eight_dense_operations_keep_persisted_memory_bounded_and_ninth_is_rejected():
    lessons = [dense_lesson(f"lesson-{index}") for index in range(LESSON_LIMIT)]
    proposals = [dense_lesson(f"proposal-{index}", target="scoring", proposed_change="改" * 180)
                 for index in range(PROPOSAL_LIMIT)]
    state = apply({}, decision(*lessons, proposals=proposals), evidence=lessons[0]["evidence_refs"])
    ops = [operation("update", {**proposals[index], "proposed_change": "新" * 180},
                     collection="optimization_proposals", id=proposals[index]["id"]) for index in range(OPERATION_LIMIT)]
    changed = maintain(state, *ops, evidence=lessons[0]["evidence_refs"])
    memory = changed["falcon_learning"]
    assert len(memory["last_changes"]) == OPERATION_LIMIT
    assert all(row["before"]["proposed_change"] == "改" * 180 and row["after"]["proposed_change"] == "新" * 180
               for row in memory["last_changes"])
    # Job先写完整learning_changes，账户只持久化有界工作记忆和有界审计。
    persisted = {key: value for key, value in memory.items() if key != "last_changes"}
    assert len(encode_agent_json(persisted).encode("utf-8")) < 512 * 1024
    assert len(encode_agent_json(memory["last_changes"]).encode("utf-8")) < 256 * 1024
    ninth = operation("delete", id=lessons[0]["id"])
    with pytest.raises(ValidationError):
        maintain(state, *ops, ninth, evidence=lessons[0]["evidence_refs"])


def test_memory_roundtrips_atomically_with_agent_state_and_survives_diary_cleanup(tmp_path):
    now = datetime.fromisoformat(f"{DAY}T16:00:00+08:00")
    config = StockAgentConfig(name="经验测试", enabled=True, provider="fixture", model="fixture").model_dump()
    with tenant_scope("tenant-memory"), StockAgentStore(tmp_path / "palace.db") as store:
        profile = store.create(config, now=now)
        claimed = store.claim_run(profile["id"], f"{DAY}:review:review", "review", now=now)
        assert claimed is not None
        value = decision(lesson())
        state = apply(claimed["state"], value, agent_id=profile["id"])
        result = {"summary": value.summary, "fills": [], "actions": [], "decisions": [],
                  "learning": value.learning.model_dump(mode="json")}
        store.finish_run(profile["id"], claimed["run_id"], state, result, now=now + timedelta(seconds=1))
        saved = store.get(profile["id"])
        assert saved["state"]["falcon_learning"] == state["falcon_learning"]
        assert store.run_detail(profile["id"], claimed["run_id"])["detail"]["learning"] == result["learning"]
        # 日记清理只删可再生运行材料，长期经验仍在账户 state_json。
        store.prune_diary(profile["id"], now=now + timedelta(days=100))
        assert store.get(profile["id"])["state"]["falcon_learning"] == state["falcon_learning"]


@pytest.mark.parametrize("phase", ["review", "weekly_review"])
def test_saved_structured_workbench_records_remain_available_in_complete_review_window(tmp_path, phase):
    now = datetime.fromisoformat(f"{DAY}T16:00:00+08:00")
    config = StockAgentConfig(name="结构化复盘", enabled=True, provider="fixture", model="fixture").model_dump()
    candidate_scope = {"research_date": DAY, "research_codes": ["301180"], "candidate_codes": ["301180"],
        "candidates": [{"code": "301180", "score": 90, "evidence_id": "candidate:saved", "evidence": {
            "trend_score": 30, "_data_snapshot": {"requested_codes": ["301180", "600519"]}}}]}
    saved_fields = {
        "research_plan": None,
        "research_plan_structured": {"market_view": "风险偏好一般", "next_trade_date": "2026-10-08",
            "stocks": [{"code": "301180", "entry_condition": "回踩确认承接", "exit_condition": "逻辑走弱退出"}]},
        "assessments": [{"code": "301180", "stance": "wait", "summary": "来源有效，等待承接", "focus": True,
            "expected_entry_price": 12.0, "data_status": "available", "evidence_refs": ["candidate:saved"]}],
        "detail": {"market_summary": "环境尚需确认", "changes": "保持观察", "next_steps": "下一交易日核验承接"},
        "assessment_coverage": {"required_codes": ["301180"], "reviewed_codes": ["301180"],
            "unreviewed_codes": [], "focus_codes": ["301180"], "total": 1, "reviewed": 1, "complete": True},
        "watch_snapshot": {"as_of": now.isoformat(), "quotes": {"301180": {"price": 12.0,
            "trade_date": DAY, "trade_time": "15:00:00", "source": "fixture"}}, "missing_codes": []},
        "learning_changes": [{"op": "validate", "collection": "lessons", "id": "timing", "reason": "新增实际证据",
            "before": {"status": "pending"}, "after": {"status": "supported"}}],
    }
    result = {"summary": "等待承接，本轮无成交", "decisions": [], "fills": [], "rejects": [], "actions": [],
              "candidate_scope": candidate_scope, "analysis_only": True, "as_of": now.isoformat(), **saved_fields}
    with StockAgentStore(tmp_path / "palace.db") as ledger:
        profile = ledger.create(config, now=now)
        claimed = ledger.claim_run(profile["id"], f"{DAY}:research:structured", "research", now=now)
        ledger.finish_run(profile["id"], claimed["run_id"], claimed["state"], result, now=now + timedelta(seconds=1))
        original = ledger.run_detail(profile["id"], claimed["run_id"])
        review = falcon_review_evidence(ledger, profile["id"], phase,
            {"research_date": DAY, "research_cutoff": (now + timedelta(minutes=1)).isoformat()})
        assert len(review["runs"]) == 1
        record = review["runs"][0]
        assert record["evidence_id"] == claimed["run_id"]
        for key, expected in saved_fields.items():
            assert record[key] == expected
        assert record["research_plan"] is None and record["research_plan_structured"]["stocks"]
        assert record["candidate_scope"]["candidates"][0]["evidence"]["trend_score"] == 30
        assert "_data_snapshot" not in json.dumps(record["candidate_scope"], ensure_ascii=False)
        assert ledger.run_detail(profile["id"], claimed["run_id"]) == original


@pytest.mark.parametrize("phase, expected_start", [("review", DAY), ("weekly_review", "2026-09-28")])
def test_review_projects_legacy_million_character_scope_without_rewriting_diary(phase, expected_start):
    candidate = {"code": "301180", "name": "目标候选", "score": 94.68, "decision": "精选",
                 "evidence_id": "candidate:legacy-yangshi", "strategy_slug": "yangshi-tail-v1",
                 "date": "2026-09-29", "produced_at": "2026-09-29T14:50:00+08:00",
                 "evidence": {"trend_score": 30, "related_rows": [
                     {"code": "301180", "score": 94.68}, {"code": "600519", "score": 99}],
                     "_data_snapshot": {"source_evidence": {
                         "requested_codes": ["301180", "600519"],
                         "attempts_not_observed_receipt_ids": ["foreign-receipt-" + "x" * 32] * 25_794}}}}
    legacy_scope = {"as_of": f"{DAY}T12:10:49+08:00", "research_date": DAY,
                    "candidate_codes": ["301180"], "research_codes": ["301180"],
                    "strategy_slugs": ["yangshi-tail-v1"], "candidates": [candidate]}
    assert len(json.dumps(legacy_scope, ensure_ascii=False)) > 1_000_000
    original_detail = {"candidate_scope": legacy_scope, "decisions": [], "fills": [],
                       "rejects": [], "analysis_only": True, "research_plan": "等待承接确认"}
    untouched = copy.deepcopy(original_detail)

    class LegacyLedger:
        def __init__(self):
            self.queries = []
            self.detail_reads = []

        def history(self, agent_id, **query):
            self.queries.append((agent_id, query))
            if query["kind"] == "trades":
                return {"items": [], "total": 0}
            return {"items": [
                {"id": "old-run", "finished_at": f"{DAY}T12:12:26+08:00"},
                {"id": "future-run", "finished_at": f"{DAY}T17:00:00+08:00"},
                {"id": "running-run", "finished_at": None}], "total": 3}

        def run_detail(self, agent_id, run_id):
            self.detail_reads.append((agent_id, run_id))
            return {"detail": original_detail}

    ledger = LegacyLedger()
    review = falcon_review_evidence(ledger, "falcon-a", phase,
        {"research_date": DAY, "research_cutoff": f"{DAY}T16:00:00+08:00"})
    assert review["start"] == expected_start and review["end"] == DAY
    assert ledger.detail_reads == [("falcon-a", "old-run")]
    assert all(agent_id == "falcon-a" and query["start"] == expected_start and query["end"] == DAY
               for agent_id, query in ledger.queries)
    saved_scope = review["runs"][0]["candidate_scope"]
    projected = saved_scope["candidates"][0]
    assert saved_scope["candidate_codes"] == saved_scope["research_codes"] == ["301180"]
    assert projected["evidence_id"] == candidate["evidence_id"] and projected["score"] == 94.68
    assert projected["evidence"]["trend_score"] == 30
    assert projected["evidence"]["related_rows"] == [{"code": "301180", "score": 94.68}]
    encoded = json.dumps({"review_evidence": review}, ensure_ascii=False)
    assert len(encoded) < 10_000
    assert "_data_snapshot" not in encoded and "foreign-receipt" not in encoded and "600519" not in encoded
    learning = falcon_learning_evidence({}, review)
    assert learning["candidates"][0]["evidence_id"] == candidate["evidence_id"]
    assert learning["candidates"][0]["score"] == 94.68
    assert original_detail == untouched
