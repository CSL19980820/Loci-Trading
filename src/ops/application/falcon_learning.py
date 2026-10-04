"""猎隼的有界研究记忆；经验只影响研究，不修改选股策略或判分配置。"""
from __future__ import annotations

import copy
import json
from collections.abc import Collection
from datetime import date
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from src.shared.tenancy import current_tenant

LESSON_LIMIT = 12
PROPOSAL_LIMIT = 8
REFERENCE_LIMIT = 24
EXAMPLE_LIMIT = 6
AUDIT_LIMIT = 64
AUDIT_BYTE_LIMIT = 128 * 1024
OPERATION_LIMIT = 8
TEXT_LIMITS = {"title": 40, "finding": 180, "conditions": 120,
               "sample_definition": 120, "validation_plan": 160, "proposed_change": 180}

FALCON_LEARNING_RULES = """每日复盘(review)及周复盘(weekly_review)沉淀 learning；其他阶段 learning=null。
learning 是增量修订，lessons 与 optimization_proposals 未列出的旧条目继续保留，[] 不清空记忆。
工作记忆最多12条经验、8条建议。优先维护有用旧条目；每条title最多40字、finding/改法180字、条件/样本口径120字、验证计划160字、例子解释100字。
operations用于明确维护：{op:validate|update|replace|delete,collection:lessons|optimization_proposals,id,reason,item}，单轮最多8个操作，其余留待下轮。
validate验证既有认识，item为同id的完整条目，保留原结论/条件，只改证据、样本、状态与验证计划；update同id修订完整条目；replace用完整item替代旧id；delete省略item且写删除理由。每条同轮只操作一次，不与lessons/optimization_proposals重复写同id。
同一认识沿用稳定 id，修订 finding、适用 conditions 与 status(pending待验证/supported有证据支持/rejected已被否定)，不要换 id 重复新增。
每条写 sample_size、sample_basis(executed已入本账户成交账/observed实际观察/hypothetical预演假设)、sample_definition(时期、来源、去重口径)、evidence_refs。
sample_size 对应本条结论本次明确的样本口径；重复样本不要累加，修订必须说明适用的累计或当期范围。
observed 样本数不能超过逐条引用的去重证据数，不以一份运行摘要虚增样本；累计结论引用完整可见样本，当期结论说明当期口径。
仅引用输入 learning_evidence 中提供的证据 id；正例 positive_examples 与反例 counter_examples 使用 {evidence_ref,interpretation}。
预演、拒单、等待及未成交意图不能计入 executed 样本；hypothetical 的 sample_size 必须为 0 且 status=pending。
supported 要有正例，rejected 要有反例；样本不足保持 pending，不因一次盈利把结论升为永久限制。validation_plan 写下一步如何验证及什么结果会推翻认识。
optimization_proposals 另写 target(selection选股/scoring判分) 与 proposed_change，结合来源策略及评分依据提出可验证的优化建议；这只记录建议，不授权修改策略、权重、阈值或任务配置。
日复盘关注当日执行与错失机会；周复盘归集本周每日发现、检查反例与环境变化，修订或否定旧认识。无可靠新发现时 learning=null，不凑条目。
"""


class FalconLearningExample(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    evidence_ref: str = Field(min_length=1, max_length=160)
    interpretation: str = Field(min_length=1, max_length=100)


class FalconLesson(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    id: str = Field(min_length=1, max_length=64, pattern=r"^[A-Za-z0-9][A-Za-z0-9_.:-]*$")
    title: str = Field(min_length=1, max_length=TEXT_LIMITS["title"])
    finding: str = Field(min_length=1, max_length=TEXT_LIMITS["finding"])
    conditions: str = Field(min_length=1, max_length=TEXT_LIMITS["conditions"])
    status: Literal["pending", "supported", "rejected"] = "pending"
    evidence_refs: list[str] = Field(min_length=1, max_length=REFERENCE_LIMIT)
    sample_size: int = Field(ge=0, strict=True)
    sample_basis: Literal["executed", "observed", "hypothetical"]
    sample_definition: str = Field(min_length=1, max_length=TEXT_LIMITS["sample_definition"])
    positive_examples: list[FalconLearningExample] = Field(default_factory=list, max_length=EXAMPLE_LIMIT)
    counter_examples: list[FalconLearningExample] = Field(default_factory=list, max_length=EXAMPLE_LIMIT)
    validation_plan: str = Field(min_length=1, max_length=TEXT_LIMITS["validation_plan"])

    @model_validator(mode="after")
    def evidence_and_status(self) -> FalconLesson:
        if any(not isinstance(ref, str) or not ref.strip() or len(ref) > 160 for ref in self.evidence_refs):
            raise ValueError("经验引用必须是非空证据 id")
        self.evidence_refs = list(dict.fromkeys(ref.strip() for ref in self.evidence_refs))
        if any(example.evidence_ref not in self.evidence_refs
               for example in [*self.positive_examples, *self.counter_examples]):
            raise ValueError("经验正反例必须引用 evidence_refs 中的证据")
        if self.sample_basis == "hypothetical" and (self.status != "pending" or self.sample_size):
            raise ValueError("预演假设只能待验证，不得作为已观察或成交样本")
        if self.status == "supported" and (not self.sample_size or not self.positive_examples):
            raise ValueError("有证据支持的经验必须提供实际样本与正例")
        if self.status == "rejected" and (not self.sample_size or not self.counter_examples):
            raise ValueError("否定经验必须提供实际样本与反例")
        return self


class FalconOptimizationProposal(FalconLesson):
    target: Literal["selection", "scoring"]
    proposed_change: str = Field(min_length=1, max_length=TEXT_LIMITS["proposed_change"])


class FalconLearningOperation(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    op: Literal["validate", "update", "replace", "delete"]
    collection: Literal["lessons", "optimization_proposals"] = "lessons"
    id: str = Field(min_length=1, max_length=64, pattern=r"^[A-Za-z0-9][A-Za-z0-9_.:-]*$")
    reason: str = Field(min_length=1, max_length=160)
    item: FalconOptimizationProposal | FalconLesson | None = None

    @model_validator(mode="after")
    def operation_payload(self) -> FalconLearningOperation:
        if self.op == "delete":
            if self.item is not None:
                raise ValueError("删除经验不应提供替代条目")
            return self
        if self.item is None:
            raise ValueError("验证、更新或替换经验必须提供完整item")
        if (self.collection == "optimization_proposals") != isinstance(self.item, FalconOptimizationProposal):
            raise ValueError("维护条目必须与经验或优化建议类型一致")
        if self.op != "replace" and self.item.id != self.id:
            raise ValueError("验证或更新经验必须沿用原id")
        return self


class FalconLearning(BaseModel):
    model_config = ConfigDict(extra="forbid")
    lessons: list[FalconLesson] = Field(default_factory=list, max_length=LESSON_LIMIT)
    optimization_proposals: list[FalconOptimizationProposal] = Field(default_factory=list, max_length=PROPOSAL_LIMIT)
    operations: list[FalconLearningOperation] = Field(default_factory=list, max_length=OPERATION_LIMIT)

    @model_validator(mode="after")
    def unique_ids(self) -> FalconLearning:
        for items in (self.lessons, self.optimization_proposals):
            if len({item.id for item in items}) != len(items):
                raise ValueError("同轮经验或优化建议 id 不能重复")
        seen = {("lessons", item.id) for item in self.lessons} | {("optimization_proposals", item.id) for item in self.optimization_proposals}
        for operation in self.operations:
            keys = {(operation.collection, operation.id)}
            if operation.item is not None:
                keys.add((operation.collection, operation.item.id))
            if seen & keys:
                raise ValueError("同轮经验维护不能重复操作同一id")
            seen |= keys
        return self


def _owned_memory(state: dict[str, Any], agent_id: str) -> dict[str, Any]:
    if not agent_id:
        raise ValueError("经验归属的智能体 id 不能为空")
    memory = state.get("falcon_learning") or {}
    if memory and (memory.get("agent_id") != agent_id or memory.get("tenant_id") != current_tenant()):
        raise ValueError("猎隼经验的租户或智能体归属不匹配")
    return memory


def falcon_learning_context(state: dict[str, Any], *, agent_id: str, research_date: str) -> dict[str, Any]:
    """给模型的紧凑副本；历史复盘看不到研究日之后修订的经验。"""
    target = date.fromisoformat(research_date).isoformat()
    memory = _owned_memory(state, agent_id)
    context: dict[str, Any] = {"lessons": [], "optimization_proposals": []}
    for key, limit in (("lessons", LESSON_LIMIT), ("optimization_proposals", PROPOSAL_LIMIT)):
        context[key] = [_compact_record(item) for item in memory.get(key, [])
                       if item.get("last_review_date", "") <= target][-limit:]
    return context


def _compact_record(item: dict) -> dict:
    record = copy.deepcopy(item)
    for key, limit in TEXT_LIMITS.items():
        if key in record:
            record[key] = str(record[key])[:limit]
    for key in ("positive_examples", "counter_examples"):
        record[key] = [{**example, "interpretation": str(example.get("interpretation", ""))[:100]}
                       for example in record.get(key, [])][-EXAMPLE_LIMIT:]
    record["evidence_refs"] = list(dict.fromkeys(record.get("evidence_refs", [])))[-REFERENCE_LIMIT:]
    for key in ("positive_examples", "counter_examples"):
        record[key] = [example for example in record[key] if example["evidence_ref"] in record["evidence_refs"]]
    return record


def public_falcon_learning(memory: dict[str, Any] | None) -> dict[str, Any]:
    """账户展示只读投影；调用方传state.get('falcon_learning')，不传整个state。

    只返回最近的有界条目与容量。原账户和源日记保留完整内容，展示不会验证、
    修改状态或样本，也不会暴露维护审计批次。
    """
    source = memory or {}
    public = {key: copy.deepcopy(source[key]) for key in (
        "agent_id", "tenant_id", "last_review_date", "last_review_phase") if key in source}
    public["limits"] = {"lessons": LESSON_LIMIT, "optimization_proposals": PROPOSAL_LIMIT}
    for key, limit, model in (("lessons", LESSON_LIMIT, FalconLesson),
                              ("optimization_proposals", PROPOSAL_LIMIT, FalconOptimizationProposal)):
        rows = sorted(source.get(key, []), key=lambda row: row.get("last_review_date", ""))[-limit:]
        visible = []
        fields = set(model.model_fields) | {"first_review_date", "last_review_date", "last_review_phase"}
        for row in rows:
            record = _compact_record({field: value for field, value in row.items() if field in fields})
            # 引用是事实归属，展示投影不重新去重、截断或换成“已验证”证据。
            record["evidence_refs"] = copy.deepcopy(row.get("evidence_refs", []))
            visible.append(record)
        public[key] = visible
    return public


def _merge_items(previous: list[dict], incoming: list[dict], *, day: str, phase: str, limit: int) -> list[dict]:
    merged = {item["id"]: copy.deepcopy(item) for item in previous}
    for item in incoming:
        old = merged.get(item["id"], {})
        # 同日周总结的经验不能被随后补做的日复盘降回旧认识。
        if old.get("last_review_date") == day and old.get("last_review_phase") == "weekly_review" and phase not in {"weekly_review", "learning_maintenance"}:
            continue
        record = {**item, "first_review_date": old.get("first_review_date", day),
                  "last_review_date": day, "last_review_phase": phase}
        record["evidence_refs"] = list(dict.fromkeys([*old.get("evidence_refs", []), *item["evidence_refs"]]))[-REFERENCE_LIMIT:]
        for key in ("positive_examples", "counter_examples"):
            examples = {example["evidence_ref"]: example for example in old.get(key, [])}
            examples.update({example["evidence_ref"]: example for example in item[key]})
            record[key] = list(examples.values())[-EXAMPLE_LIMIT:]
        # 裁剪引用时同时清掉引用已不在条目中的旧例子。
        for key in ("positive_examples", "counter_examples"):
            record[key] = [example for example in record[key] if example["evidence_ref"] in record["evidence_refs"]]
        merged.pop(item["id"], None)
        merged[item["id"]] = record
    return sorted(merged.values(), key=lambda item: item.get("last_review_date", ""))[-limit:]


def _bounded_audit(entries: list[dict]) -> list[dict]:
    """保留最近完整审计，条数和UTF-8落账字节双上限；完整本批另在last_changes。"""
    sizes = [len(json.dumps(entry, ensure_ascii=False, allow_nan=False,
                           separators=(",", ":")).encode("utf-8")) for entry in entries]
    start = max(0, len(entries) - AUDIT_LIMIT)
    total = 2 + sum(sizes[start:]) + max(0, len(entries) - start - 1)
    while total > AUDIT_BYTE_LIMIT and start < len(entries):
        total -= sizes[start] + int(start + 1 < len(entries))
        start += 1
    return copy.deepcopy(entries[start:])


def apply_falcon_learning(state: dict[str, Any], decision: Any, phase: str, research_date: str, *,
                          agent_id: str, evidence_ids: Collection[str],
                          executed_trade_ids: Collection[str] = ()) -> dict[str, Any]:
    """返回待原子落账的账户副本；不访问数据库、不改变策略，也不落历史成交。"""
    learning = getattr(decision, "learning", None) if not isinstance(decision, dict) else decision.get("learning")
    if learning is None:
        _owned_memory(state, agent_id)
        return copy.deepcopy(state)
    if phase not in {"review", "weekly_review"}:
        raise ValueError("经验只允许在猎隼每日或每周复盘中沉淀")
    parsed = learning if isinstance(learning, FalconLearning) else FalconLearning.model_validate(learning)
    return _apply_learning(state, parsed, phase, research_date, agent_id=agent_id,
                           evidence_ids=evidence_ids, executed_trade_ids=executed_trade_ids, actor="model")


def maintain_falcon_learning(state: dict[str, Any], operations: list[dict], *, agent_id: str,
                            research_date: str, evidence_ids: Collection[str],
                            executed_trade_ids: Collection[str] = (), actor: str = "user") -> dict[str, Any]:
    """供账户原子维护入口调用；归属、日期、字段与证据和模型复盘采用相同防线。"""
    if not actor.strip():
        raise ValueError("经验维护审计操作者不能为空")
    parsed = FalconLearning.model_validate({"operations": operations})
    return _apply_learning(state, parsed, "learning_maintenance", research_date, agent_id=agent_id,
                           evidence_ids=evidence_ids, executed_trade_ids=executed_trade_ids, actor=actor)


def _apply_learning(state: dict[str, Any], parsed: FalconLearning, phase: str, research_date: str, *,
                    agent_id: str, evidence_ids: Collection[str], executed_trade_ids: Collection[str], actor: str) -> dict:
    updated = copy.deepcopy(state)
    memory = _owned_memory(state, agent_id)
    day = date.fromisoformat(research_date).isoformat()
    committed = set(executed_trade_ids)
    known = set(evidence_ids) | committed
    incoming = [*parsed.lessons, *parsed.optimization_proposals,
                *(operation.item for operation in parsed.operations if operation.item is not None)]
    for item in incoming:
        refs = set(item.evidence_refs)
        if refs - known:
            raise ValueError("猎隼经验引用了本轮未提供的证据：" + "、".join(sorted(refs - known)))
        if item.sample_basis == "observed" and item.sample_size > len(refs):
            raise ValueError("观察经验的样本数不得超过逐条引用的去重可见证据数")
        if item.sample_basis == "executed" and (not item.sample_size or item.sample_size > len(refs & committed)):
            raise ValueError("成交经验的样本数必须由本智能体已入账的成交引用支持，预演或拒单不算成交")
    if memory.get("last_review_date", "") > day:
        return updated  # 历史发现保留在本轮日记，不能污染较新的实时工作记忆。
    if not incoming and not parsed.operations:
        return updated
    records = {key: copy.deepcopy(memory.get(key, [])) for key in ("lessons", "optimization_proposals")}
    changes = []
    def audit(op, collection, item_id, before, after, reason):
        if before == after:
            return
        changes.append({"op": op, "collection": collection, "id": item_id, "reason": reason,
                        "date": day, "phase": phase, "actor": actor, "before": copy.deepcopy(before),
                        "after": copy.deepcopy(after)})

    for key, items in (("lessons", parsed.lessons), ("optimization_proposals", parsed.optimization_proposals)):
        for item in items:
            before = next((row for row in records[key] if row["id"] == item.id), None)
            records[key] = _merge_items(records[key], [item.model_dump(mode="json")],
                                        day=day, phase=phase, limit=len(records[key]) + 1)
            after = next(row for row in records[key] if row["id"] == item.id)
            audit("update" if before else "create", key, item.id, before, after, "日周复盘增量沉淀")
    for operation in parsed.operations:
        key = operation.collection
        before = next((row for row in records[key] if row["id"] == operation.id), None)
        if before is None:
            raise ValueError("待维护的经验不存在：" + operation.id)
        if phase != "learning_maintenance" and before.get("last_review_date") == day and before.get("last_review_phase") == "weekly_review" and phase != "weekly_review":
            continue
        after = None
        if operation.op != "delete":
            item = operation.item.model_dump(mode="json")
            if operation.op == "validate" and any(item.get(field) != before.get(field)
                    for field in ("title", "finding", "conditions", "target", "proposed_change")):
                raise ValueError("验证经验须保留原结论与条件，修订请用update或replace")
            if operation.op == "replace":
                if item["id"] != operation.id and any(row["id"] == item["id"] for row in records[key]):
                    raise ValueError("替换后的经验id已存在")
                after = {**item, "first_review_date": day, "last_review_date": day, "last_review_phase": phase}
            else:
                after = next(row for row in _merge_items([before], [item], day=day, phase=phase, limit=1) if row["id"] == item["id"])
        records[key] = [row for row in records[key] if row["id"] != operation.id]
        if after is not None:
            records[key].append(after)
        audit(operation.op, key, operation.id, before, after, operation.reason)
    for key, limit in (("lessons", LESSON_LIMIT), ("optimization_proposals", PROPOSAL_LIMIT)):
        records[key].sort(key=lambda row: row.get("last_review_date", ""))
        for row in records[key][:-limit]:
            audit("prune", key, row["id"], row, None, "超过工作记忆上限，原结论保留在审计与源日记")
        records[key] = records[key][-limit:]
        for index, row in enumerate(records[key]):
            compact = _compact_record(row)
            audit("compact", key, row["id"], row, compact, "旧版长条目投影为有界工作记忆，原文保留在审计")
            records[key][index] = compact
    all_audit = [*memory.get("audit", []), *changes]
    bounded_audit = _bounded_audit(all_audit)
    updated["falcon_learning"] = {**memory, "agent_id": agent_id, "tenant_id": current_tenant(), "last_review_date": day,
        "last_review_phase": phase, **records, "audit": bounded_audit, "last_changes": changes,
        "audit_truncated_count": memory.get("audit_truncated_count", 0) + len(all_audit) - len(bounded_audit)}
    return updated
