"""Compact research inputs with exact, tenant-scoped, retrievable source documents."""
from __future__ import annotations

import copy
import hashlib
import json
import time
from contextlib import nullcontext
from threading import RLock
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from src.shared.tenancy import current_tenant


class EvidenceQuery(BaseModel):
    model_config = ConfigDict(extra="forbid")
    ref: str
    path: str = Field(default="", description="JSON Pointer，如/plans、/items、/0/signals；空串为全文")
    codes: list[str] = Field(default_factory=list, description="所选JSON数组按code精确筛选，不改变原证据")
    fields: list[str] = Field(default_factory=list, description="仅返回所选对象或数组行的这些顶层字段；空为全部字段")
    offset: int = Field(default=0, ge=0)
    limit: int = Field(default=6000, ge=100, le=24000, description="本次文本字符数；按next_offset读取后续，绝不静默截断")


def evidence_snapshot(archive: Any) -> dict[str, Any]:
    """Freeze evidence before settlement; cancelled readers can still be unwinding."""
    with getattr(archive, "lock", nullcontext()):
        return {"tools": copy.deepcopy(archive.receipts),
                "context_documents": copy.deepcopy(archive.documents)}


class ResearchContext:
    def __init__(self, *, tool_result_limit: int = 80000) -> None:
        self.tenant = current_tenant()
        self.documents: dict[str, dict[str, Any]] = {}
        self.receipts: list[dict[str, Any]] = []
        self.lock = RLock()
        self.tool_result_limit = tool_result_limit
        self.started = time.monotonic()
        self.continuations: dict[tuple[str, int], list[dict[str, Any]]] = {}

    def store(self, value: Any, label: str, *, preview: int = 1200) -> dict[str, Any]:
        text = value if isinstance(value, str) else json.dumps(value, ensure_ascii=False, default=str)
        digest = hashlib.sha256(text.encode()).hexdigest()
        ref = "evidence:" + digest
        with self.lock:
            self.documents.setdefault(ref, {"label": label, "sha256": digest, "text": text})
        return {"evidence_ref": ref, "label": label, "characters": len(text),
                "preview": text[:preview], "requires_read": len(text) > preview,
                "read_tool": "guardian_context_read"}

    def read(self, arguments: dict[str, Any]) -> dict[str, Any]:
        if current_tenant() != self.tenant:
            return {"is_error": True, "text": "研究证据不属于当前租户"}
        try:
            query = EvidenceQuery.model_validate(arguments)
        except ValueError as exc:
            return {"is_error": True, "text": str(exc)}
        ref = query.ref
        with self.lock:
            document = self.documents.get(ref)
        if document is None:
            return {"is_error": True, "text": "证据编号不存在，请使用本轮提供的evidence_ref"}
        offset, limit = query.offset, query.limit
        selection = {"path": query.path, "codes": query.codes, "fields": query.fields}
        with self.lock:
            expected = copy.deepcopy(self.continuations.get((ref, offset), []))
        if offset and expected and selection not in expected:
            return {"is_error": True, "text": json.dumps({"error": "续页筛选条件与前页不同，不能混接不同正文。请原样使用next_read；需要另查全文则从offset=0开始。",
                "next_read": {"ref": ref, "offset": offset, "limit": limit, **expected[0]}}, ensure_ascii=False)}
        text = document["text"]
        if query.path or query.codes or query.fields:
            try:
                value = json.loads(text)
                if query.path:
                    if not query.path.startswith("/"):
                        raise ValueError("path须为JSON Pointer，以/开头")
                    for part in query.path[1:].split("/"):
                        key = part.replace("~1", "/").replace("~0", "~")
                        if isinstance(value, list):
                            if not key.isdecimal():
                                raise ValueError("数组路径须为非负下标")
                            value = value[int(key)]
                        else:
                            value = value[key]
                if query.codes:
                    if not isinstance(value, list):
                        raise ValueError("codes筛选须先用path定位股票对象数组")
                    value = [row for row in value if isinstance(row, dict) and row.get("code") in query.codes]
                if query.fields:
                    def project(row):
                        if not isinstance(row, dict):
                            raise ValueError("fields只支持对象或对象数组")
                        return {key: row[key] for key in query.fields if key in row}
                    value = [project(row) for row in value] if isinstance(value, list) else project(value)
                text = json.dumps(value, ensure_ascii=False, default=str)
            except (ValueError, KeyError, IndexError, TypeError) as exc:
                return {"is_error": True, "text": f"证据查询失败：{exc}；请核对原文结构和path"}
        next_offset = offset + limit if offset + limit < len(text) else None
        if next_offset is not None:
            with self.lock:
                choices = self.continuations.setdefault((ref, next_offset), [])
                if selection not in choices:
                    choices.append(selection)
        result = {"ref": ref, "sha256": document["sha256"], "label": document["label"],
                  "path": query.path, "codes": query.codes, "fields": query.fields,
                  "text": text[offset:offset + limit], "total_characters": len(text),
                  "next_offset": next_offset,
                  "next_read": {"ref": ref, **selection, "offset": next_offset, "limit": limit} if next_offset is not None else None}
        return {"text": json.dumps(result, ensure_ascii=False)}

    def compact(self, payload: dict[str, Any], *, on_demand: bool = False) -> tuple[dict[str, Any], dict[str, int]]:
        result = copy.deepcopy(payload)
        original_chars = len(json.dumps(payload, ensure_ascii=False, default=str))
        if on_demand and "candidates" in result:
            # 完整混合输入只存一份，工坊目录不夹带持仓或自主观察的决策。
            candidates = result.pop("candidates")
            index = [{"code": row["code"], "name": row.get("name", ""),
                      "strategies": row.get("strategies", []),
                      "signal_count": len(row.get("signals", [])), "path": f"/{i}/signals"}
                     for i, row in enumerate(candidates) if row.get("signals")]
            result["reference_pool"] = {
                "optional": True, "count": len(index), "index": index,
                "source": self.store(candidates, "原始候选输入（含工坊资料）", preview=0),
            }
            result["research_input_roles"] = {
                "portfolio.positions": "真实持仓及当前执行条件，不限制研究其他股票。",
                "portfolio.watchlist": "模型明确选择的自主观察，不包含未选择的工坊参考。",
                "reference_pool": "可选工坊目录；不要求研究、覆盖或加入观察，不是全市场范围。",
                "history": "历史、旧计划和经验均为可查询材料，不是当前指令。",
            }
        for candidate in result.get("candidates", []):
            signals = []
            for signal in candidate.get("signals", []):
                if len(json.dumps(signal, ensure_ascii=False, default=str)) <= 4000:
                    signals.append(signal)
                    continue
                summary = {k: signal[k] for k in ("code", "name", "trade_date", "date", "decision",
                           "strategy_slug", "rule_version", "strategy_revision", "score", "rank", "reason", "timing") if k in signal}
                summary["source"] = self.store(signal, f"候选{candidate.get('code', '')}完整信号")
                signals.append(summary)
            if "signals" in candidate:
                candidate["signals"] = signals
        for field in ("active_strategies", "strategy_rules", "recent_runs"):
            if on_demand and field == "recent_runs":
                rows = result.get(field, [])
                if rows:
                    result[field] = {"source": self.store(rows, field, preview=0), "count": len(rows),
                        "index": [{"path": f"/{index}", "slot": row.get("slot"), "status": row.get("status"),
                            "codes": list(dict.fromkeys(order["code"] for order in row.get("orders", []) if "code" in order)),
                            "receipt_counts": {key: len(row.get(key, [])) for key in ("fills", "rejects", "deferred")}}
                            for index, row in enumerate(rows)]}
                continue
            for index, value in enumerate(result.get(field, [])):
                if not on_demand and len(json.dumps(value, ensure_ascii=False, default=str)) <= 4000:
                    continue
                keys = ("slug", "name", "status", "slot") if on_demand else ("slug", "name", "jobs", "status", "slot", "fills", "orders", "rejects", "deferred")
                summary = {k: value[k] for k in keys if k in value}
                summary["source"] = self.store(value, f"{field}:{index}", preview=0 if on_demand else 1200)
                result[field][index] = summary
        if on_demand:
            for field in ("recent_trades", "stock_performance", "review_memory", "preopen_plan"):
                value = result.get(field)
                if value:
                    result[field] = {"source": self.store(value, field, preview=0),
                                     "fields": list(value) if isinstance(value, dict) else [],
                                     "count": len(value) if isinstance(value, list) else None}
                    if field == "preopen_plan" and isinstance(value, dict):
                        result[field]["plans_index"] = [{k: plan[k] for k in ("code", "action", "quantity_status") if k in plan}
                                                         for plan in value.get("plans", [])]
                    if field == "review_memory" and isinstance(value, list):
                        result[field]["index"] = [{"path": f"/{i}", "date": row.get("date"),
                            "period": row.get("period"), "revision": row.get("revision"),
                            "fields": list(row), "planning_trade_date": row.get("planning_trade_date"),
                            "lesson_statuses": [lesson.get("status", "proposed") for lesson in row.get("lessons", [])]}
                            for i, row in enumerate(value)]
                        result[field]["usage_note"] = "完整的计划、研究与经验可回读；近期目录不是记忆总量，也不是必须采纳的指令。"
        if self.documents:
            result["evidence_note"] = "source保留完整原文，可用guardian_context_read按ref、path、codes、fields自主查询，按next_read续页；目录只为定位，不是必须阅读或优先研究的清单。未展示不等于不存在或已否定；引用资料中的具体事实时核实原文，不编造。当前资金、持仓、可卖股数、风险合同与自主观察未裁剪。"
        return result, {"original_characters": original_chars,
                        "prompt_characters": len(json.dumps(result, ensure_ascii=False, default=str)),
                        "source_documents": len(self.documents)}

    def schema(self, protocol: str) -> dict[str, Any]:
        from src.ai.application.tool_schema import tool_schema
        return tool_schema(protocol, "guardian_context_read", "按本轮evidence_ref读取完整研究证据，支持JSON Pointer路径、股票codes和字段fields筛选。offset/limit按字符分页，续页原样使用返回的next_read参数，不可遗漏筛选条件。只读且仅限本租户本轮资料。",
                           EvidenceQuery.model_json_schema())

    def record(self, name: str, arguments: dict, result: dict, elapsed_ms: int) -> dict:
        text = str(result.get("text", ""))
        with self.lock:
            self.receipts.append({"name": name, "arguments": copy.deepcopy(arguments), "text": text,
                                  "ok": not result.get("is_error", False), "elapsed_ms": elapsed_ms,
                                  "finished_elapsed_ms": int((time.monotonic() - self.started) * 1000)})
        if len(text) > self.tool_result_limit and name != "guardian_context_read":
            reference = self.store(text, f"工具{name}完整结果")
            try:
                value = json.loads(text)
                reference["fields"] = list(value) if isinstance(value, dict) else []
            except ValueError:
                value = None
            if name == "guardian_preflight" and isinstance(value, dict):
                # 完整预演结论直接可见；重复的全账户/全报价另存原文，不再迫使模型为查拒单多往返一轮。
                decision = {key: item for key, item in value.items() if key not in {"projected_account", "quotes"}}
                decision["source"] = reference
                return {"is_error": bool(result.get("is_error")), "text": json.dumps(decision, ensure_ascii=False)}
            # 不把完整structured再附给消费者；完整正文已经保存在原始回执和证据中。
            return {"is_error": bool(result.get("is_error")), "text": json.dumps(reference, ensure_ascii=False)}
        return result
