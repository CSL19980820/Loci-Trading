"""将一轮 run 的事件折叠为消息 metadata 富字段（ADR-006）。

约定写入 ``ai_messages.metadata_json`` 的键：
``thinking`` / ``tool_receipts`` / ``artifacts`` / ``warnings`` / ``agents`` / ``hitl``。
旧消息无这些键时由 API 省略，前端忽略即可。
"""
from __future__ import annotations

from typing import Any


_RICH_KEYS = ("thinking", "tool_receipts", "artifacts", "warnings", "agents", "images", "hitl")


def events_after_latest_resume(events: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """同 run HITL 续跑后，只折叠 resume 之后的事件，避免把暂停前 hitl/工具灌进新助手气泡。"""
    if not events:
        return events
    last_resume = -1
    for index, event in enumerate(events):
        etype, _, _ = _normalize_event(event)
        if etype == "resume":
            last_resume = index
    if last_resume < 0:
        return events
    return events[last_resume + 1 :]


def fold_run_rich_metadata(events: list[dict[str, Any]]) -> dict[str, Any]:
    """从 ``poll_events`` 行折叠出可写入 message.metadata 的富状态。

    兼容 event 行（``event_type`` + ``payload``）与已公开的 SSE 形状（``type`` + ``data``）。
    """
    thinking_parts: list[str] = []
    receipts: list[dict[str, Any]] = []
    artifacts: list[dict[str, Any]] = []
    warnings: list[str] = []
    agents: list[dict[str, Any]] = []
    hitl: dict[str, Any] | None = None

    for event in events:
        etype, data, event_id = _normalize_event(event)
        if etype == "think":
            delta = data.get("delta")
            if isinstance(delta, str) and delta:
                thinking_parts.append(delta)
            continue
        if etype == "waiting_user":
            ask = data.get("ask") if isinstance(data.get("ask"), dict) else data
            if isinstance(ask, dict):
                prompt = str(ask.get("prompt") or data.get("prompt") or data.get("message") or "").strip()
                options = ask.get("options") if isinstance(ask.get("options"), list) else []
                hitl = {
                    "prompt": prompt,
                    "options": [str(item) for item in options if str(item).strip()],
                }
                questions = _public_hitl_questions(ask.get("questions"))
                if questions:
                    hitl["questions"] = questions
                    if not prompt:
                        hitl["prompt"] = str(questions[0].get("prompt") or "")
                risk = str(ask.get("risk") or data.get("risk") or "").strip()
                if risk:
                    hitl["risk"] = risk
            continue
        if etype == "warning":
            message = data.get("message")
            if isinstance(message, str) and message.strip():
                warnings.append(message.strip())
            continue
        if etype == "context_compacted":
            message = data.get("message")
            text = str(message).strip() if message is not None else ""
            if not text:
                text = "已压缩较早对话（库内原文仍在）"
            warnings.append(text)
            continue
        if etype == "tool_start":
            _upsert_receipt(
                receipts,
                {
                    "call_id": _call_id(data),
                    "name": str(data.get("name") or "工具"),
                    "status": "running",
                    **_optional_receipt_fields(data),
                },
            )
            continue
        if etype == "tool_end":
            ok = data.get("ok")
            _upsert_receipt(
                receipts,
                {
                    "call_id": _call_id(data),
                    "name": str(data.get("name") or "工具"),
                    "status": "error" if ok is False else "done",
                    **_optional_receipt_fields(data),
                },
            )
            continue
        if etype in {"artifact", "qianlong_kline", "candidate_verdict"}:
            artifact = _artifact_from_event(etype, data, event_id)
            if artifact is not None:
                _upsert_artifact(artifacts, artifact)
            continue
        if etype.startswith("subagent_"):
            _upsert_agent(agents, etype, data)

    out: dict[str, Any] = {}
    thinking = "".join(thinking_parts)
    if thinking:
        out["thinking"] = thinking
    if receipts:
        out["tool_receipts"] = receipts
    if artifacts:
        out["artifacts"] = artifacts
    if warnings:
        out["warnings"] = warnings
    if agents:
        out["agents"] = agents
    if hitl is not None:
        out["hitl"] = hitl
    return out


def public_rich_fields(metadata: dict[str, Any] | None) -> dict[str, Any]:
    """从 message.metadata 抽出对外字段；缺省或空值不返回键。"""
    if not isinstance(metadata, dict):
        return {}
    out: dict[str, Any] = {}
    thinking = metadata.get("thinking")
    if isinstance(thinking, str) and thinking:
        out["thinking"] = thinking
    receipts = metadata.get("tool_receipts")
    if isinstance(receipts, list) and receipts:
        out["tool_receipts"] = receipts
    artifacts = metadata.get("artifacts")
    if isinstance(artifacts, list) and artifacts:
        out["artifacts"] = artifacts
    warnings = metadata.get("warnings")
    if isinstance(warnings, list) and warnings:
        out["warnings"] = [str(item) for item in warnings if str(item).strip()]
        if not out["warnings"]:
            out.pop("warnings", None)
    agents = metadata.get("agents")
    if isinstance(agents, list) and agents:
        out["agents"] = agents
    images = metadata.get("images")
    if isinstance(images, list) and images:
        cleaned = [str(item) for item in images if isinstance(item, str) and item.startswith("data:image/")]
        if cleaned:
            out["images"] = cleaned[:4]
    hitl = metadata.get("hitl")
    if isinstance(hitl, dict):
        prompt = str(hitl.get("prompt") or "").strip()
        options = hitl.get("options") if isinstance(hitl.get("options"), list) else []
        cleaned_options = [str(item) for item in options if str(item).strip()]
        questions = _public_hitl_questions(hitl.get("questions"))
        if prompt or cleaned_options or questions:
            public_hitl: dict[str, Any] = {"prompt": prompt, "options": cleaned_options}
            if questions:
                public_hitl["questions"] = questions
            risk = str(hitl.get("risk") or "").strip()
            if risk:
                public_hitl["risk"] = risk
            out["hitl"] = public_hitl
    return out


def _public_hitl_questions(raw: Any) -> list[dict[str, Any]]:
    if not isinstance(raw, list):
        return []
    out: list[dict[str, Any]] = []
    for item in raw[:8]:
        if not isinstance(item, dict):
            continue
        qid = str(item.get("id") or "").strip()
        prompt = str(item.get("prompt") or "").strip()
        if not qid or not prompt:
            continue
        row: dict[str, Any] = {"id": qid, "prompt": prompt}
        opts = item.get("options")
        if isinstance(opts, list):
            cleaned = [str(o).strip() for o in opts if str(o).strip()]
            if cleaned:
                row["options"] = cleaned
        if item.get("allow_free_text") is True:
            row["allow_free_text"] = True
        out.append(row)
    return out


def _normalize_event(event: dict[str, Any]) -> tuple[str, dict[str, Any], str]:
    if "event_type" in event or "payload" in event:
        etype = str(event.get("event_type") or "")
        payload = event.get("payload")
        data = payload if isinstance(payload, dict) else {}
        if not etype:
            etype = str(data.get("type") or "")
        return etype, data, str(event.get("id") or "")
    etype = str(event.get("type") or "")
    data = event.get("data")
    if not isinstance(data, dict):
        data = {k: v for k, v in event.items() if k not in {"type", "id", "data"}}
    return etype, data, str(event.get("id") or "")


def _call_id(data: dict[str, Any], *, fallback_keys: tuple[str, ...] = ()) -> str:
    for key in ("call_id", *fallback_keys, "name"):
        value = data.get(key)
        if value is not None and str(value).strip():
            return str(value)
    return "tool"


def _optional_receipt_fields(data: dict[str, Any]) -> dict[str, Any]:
    out: dict[str, Any] = {}
    arguments = data.get("arguments")
    if isinstance(arguments, dict):
        out["arguments"] = arguments
    preview = data.get("preview")
    if isinstance(preview, str) and preview:
        out["preview"] = preview
    elapsed = data.get("elapsed_ms")
    if isinstance(elapsed, (int, float)) and elapsed == elapsed:
        out["elapsed_ms"] = int(elapsed)
    risk = data.get("risk")
    if isinstance(risk, str) and risk:
        out["risk"] = risk
    summary = data.get("summary")
    if isinstance(summary, str) and summary:
        out["summary"] = summary
    return out


def _artifact_from_event(
    etype: str, data: dict[str, Any], event_id: str
) -> dict[str, Any] | None:
    kind = str(data.get("kind") or (etype if etype != "artifact" else "")).strip()
    if not kind:
        return None
    payload = data.get("data")
    if not isinstance(payload, dict):
        payload = {}
    artifact_id = data.get("id")
    if artifact_id is None or not str(artifact_id).strip():
        artifact_id = event_id or f"{kind}-{len(payload)}"
    out: dict[str, Any] = {
        "id": str(artifact_id),
        "kind": kind,
        "data": payload,
    }
    title = data.get("title")
    if isinstance(title, str) and title.strip():
        out["title"] = title.strip()
    status = data.get("status")
    if isinstance(status, str) and status.strip():
        out["status"] = status.strip()
    return out


def _upsert_receipt(receipts: list[dict[str, Any]], next_row: dict[str, Any]) -> None:
    call_id = str(next_row.get("call_id") or "")
    for index, row in enumerate(receipts):
        if str(row.get("call_id") or "") == call_id:
            receipts[index] = {**row, **next_row}
            return
    receipts.append(next_row)


def _upsert_artifact(artifacts: list[dict[str, Any]], next_row: dict[str, Any]) -> None:
    artifact_id = str(next_row.get("id") or "")
    for index, row in enumerate(artifacts):
        if str(row.get("id") or "") == artifact_id:
            artifacts[index] = {**row, **next_row}
            return
    artifacts.append(next_row)


def _upsert_agent(agents: list[dict[str, Any]], etype: str, data: dict[str, Any]) -> None:
    agent_id = str(data.get("id") or data.get("agent_id") or "").strip()
    if not agent_id:
        return
    if etype == "subagent_tool":
        index = next((i for i, row in enumerate(agents) if str(row.get("id")) == agent_id), -1)
        previous = agents[index] if index >= 0 else {"id": agent_id, "status": "running"}
        receipts = list(previous.get("tool_receipts") or [])
        call_id = str(data.get("call_id") or data.get("tool_receipt_id") or data.get("tool_name") or "tool")
        tool_name = str(data.get("tool_name") or data.get("name") or "工具")
        status = str(data.get("status") or "running")
        if status not in {"running", "done", "error"}:
            status = "running"
        receipt: dict[str, Any] = {
            "call_id": call_id,
            "name": tool_name,
            "status": status,
        }
        preview = data.get("preview")
        if isinstance(preview, str) and preview.strip():
            receipt["preview"] = preview.strip()[:240]
        elapsed = data.get("elapsed_ms")
        if isinstance(elapsed, (int, float)) and elapsed == elapsed:
            receipt["elapsed_ms"] = int(elapsed)
        args = data.get("arguments")
        if isinstance(args, dict):
            receipt["arguments"] = args
        found = next((i for i, row in enumerate(receipts) if str(row.get("call_id")) == call_id), -1)
        if found >= 0:
            receipts[found] = {**receipts[found], **receipt}
        else:
            receipts.append(receipt)
        next_row = {**previous, "id": agent_id, "tool_receipts": receipts[-24:]}
        if index < 0:
            agents.append(next_row)
        else:
            agents[index] = next_row
        return
    if etype == "subagent_end":
        status = "error" if data.get("ok") is False else "done"
    else:
        status = "running"
    detail = data.get("detail")
    if not isinstance(detail, str) or not detail.strip():
        for key in ("text", "preview"):
            value = data.get(key)
            if isinstance(value, str) and value.strip():
                detail = value.strip()
                break
        else:
            detail = None
    else:
        detail = detail.strip()
    name = data.get("name")
    if not isinstance(name, str) or not name.strip():
        kind = data.get("kind")
        name = str(kind).strip() if isinstance(kind, str) and kind.strip() else agent_id
    else:
        name = name.strip()
    progress = data.get("progress")
    progress_n = None
    if isinstance(progress, (int, float)) and progress == progress:
        progress_n = max(0, min(100, int(progress)))

    index = next((i for i, row in enumerate(agents) if str(row.get("id")) == agent_id), -1)
    previous = agents[index] if index >= 0 else {}
    timeline = list(previous.get("timeline") or [])
    if isinstance(timeline, list) and detail:
        if not timeline or timeline[-1] != detail:
            timeline = [*timeline, detail][-12:]
    next_row: dict[str, Any] = {
        "id": agent_id,
        "name": name or previous.get("name") or agent_id,
        "status": status,
    }
    if progress_n is not None:
        next_row["progress"] = progress_n
    elif previous.get("progress") is not None:
        next_row["progress"] = previous["progress"]
    if detail:
        next_row["detail"] = detail
    elif previous.get("detail"):
        next_row["detail"] = previous["detail"]
    if timeline:
        next_row["timeline"] = timeline
    # 保留嵌套工具回执：progress/end 不得冲掉 subagent_tool 已写入的 receipts
    prior_receipts = previous.get("tool_receipts")
    if isinstance(prior_receipts, list) and prior_receipts:
        next_row["tool_receipts"] = prior_receipts
    if index < 0:
        agents.append(next_row)
    else:
        agents[index] = next_row


__all__ = [
    "events_after_latest_resume",
    "fold_run_rich_metadata",
    "public_rich_fields",
    *_RICH_KEYS,
]
