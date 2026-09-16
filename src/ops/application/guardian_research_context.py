"""Compact research inputs with exact, tenant-scoped, retrievable source documents."""
from __future__ import annotations

import copy
import hashlib
import json
from contextlib import nullcontext
from threading import RLock
from typing import Any

from src.shared.tenancy import current_tenant


def evidence_snapshot(archive: Any) -> dict[str, Any]:
    """Freeze evidence before settlement; cancelled readers can still be unwinding."""
    with getattr(archive, "lock", nullcontext()):
        return {"tools": copy.deepcopy(archive.receipts),
                "context_documents": copy.deepcopy(archive.documents)}


class ResearchContext:
    def __init__(self) -> None:
        self.tenant = current_tenant()
        self.documents: dict[str, dict[str, Any]] = {}
        self.receipts: list[dict[str, Any]] = []
        self.lock = RLock()

    def store(self, value: Any, label: str) -> dict[str, Any]:
        text = value if isinstance(value, str) else json.dumps(value, ensure_ascii=False, default=str)
        digest = hashlib.sha256(text.encode()).hexdigest()
        ref = "evidence:" + digest
        with self.lock:
            self.documents.setdefault(ref, {"label": label, "sha256": digest, "text": text})
        return {"evidence_ref": ref, "label": label, "characters": len(text),
                "preview": text[:1200], "requires_read": len(text) > 1200,
                "read_tool": "guardian_context_read"}

    def read(self, arguments: dict[str, Any]) -> dict[str, Any]:
        if current_tenant() != self.tenant:
            return {"is_error": True, "text": "研究证据不属于当前租户"}
        ref = str(arguments.get("ref") or "")
        with self.lock:
            document = self.documents.get(ref)
        if document is None:
            return {"is_error": True, "text": "证据编号不存在，请使用本轮提供的evidence_ref"}
        offset = max(0, int(arguments.get("offset") or 0))
        limit = min(24000, max(100, int(arguments.get("limit") or 12000)))
        text = document["text"]
        result = {"ref": ref, "sha256": document["sha256"], "label": document["label"],
                  "text": text[offset:offset + limit], "total_characters": len(text),
                  "next_offset": offset + limit if offset + limit < len(text) else None}
        return {"text": json.dumps(result, ensure_ascii=False)}

    def compact(self, payload: dict[str, Any]) -> tuple[dict[str, Any], dict[str, int]]:
        result = copy.deepcopy(payload)
        original_chars = len(json.dumps(payload, ensure_ascii=False, default=str))
        for candidate in result.get("candidates", []):
            signals = []
            for signal in candidate.get("signals", []):
                if len(json.dumps(signal, ensure_ascii=False, default=str)) <= 4000:
                    signals.append(signal)
                    continue
                summary = {k: signal[k] for k in ("code", "name", "trade_date", "date", "decision",
                           "strategy_slug", "rule_version", "strategy_revision", "score", "rank", "reason") if k in signal}
                summary["source"] = self.store(signal, f"候选{candidate.get('code', '')}完整信号")
                signals.append(summary)
            if "signals" in candidate:
                candidate["signals"] = signals
        for field in ("active_strategies", "strategy_rules", "recent_runs"):
            for index, value in enumerate(result.get(field, [])):
                if len(json.dumps(value, ensure_ascii=False, default=str)) <= 4000:
                    continue
                summary = {k: value[k] for k in ("slug", "name", "jobs", "status", "slot", "fills", "orders", "rejects", "deferred") if k in value}
                summary["source"] = self.store(value, f"{field}:{index}")
                result[field][index] = summary
        if self.documents:
            result["evidence_note"] = "大段历史材料以摘要和完整证据编号提供；需要其细节时用guardian_context_read读取，不能把摘要未展示的内容当作不存在。财务及最新持仓行情未裁剪。"
        return result, {"original_characters": original_chars,
                        "prompt_characters": len(json.dumps(result, ensure_ascii=False, default=str)),
                        "source_documents": len(self.documents)}

    def schema(self, protocol: str) -> dict[str, Any]:
        from src.ai.application.tool_schema import tool_schema
        return tool_schema(protocol, "guardian_context_read", "按本轮evidence_ref读取完整研究证据，可按next_offset继续。只读且仅限本租户本轮资料。",
                           {"type": "object", "properties": {"ref": {"type": "string"},
                            "offset": {"type": "integer", "minimum": 0},
                            "limit": {"type": "integer", "minimum": 100, "maximum": 24000}},
                            "required": ["ref"], "additionalProperties": False})

    def record(self, name: str, arguments: dict, result: dict, elapsed_ms: int) -> dict:
        text = str(result.get("text", ""))
        with self.lock:
            self.receipts.append({"name": name, "arguments": copy.deepcopy(arguments), "text": text,
                                  "ok": not result.get("is_error", False), "elapsed_ms": elapsed_ms})
        if len(text) > 80000 and name != "guardian_context_read":
            return {**result, "text": json.dumps(self.store(text, f"工具{name}完整结果"), ensure_ascii=False)}
        return result
