"""Skill 运行时：多 Agent 弹药 → 主 Agent（可 HITL）→ 续跑。"""
from __future__ import annotations

import logging
from typing import Any

from src.ai.application.agent import format_tool_trace, messages_from_json, run_agent
from src.ai.application.multi_agent import format_subagent_briefs, run_ammo_agents
from src.ai.application.toolbus import build_toolbus
from src.ops import OpsError, skill_runs
from src.ops.application.jobs import JobContext, JobError, _compose_prompt, _gather_context, skill_system_prefix

logger = logging.getLogger(__name__)


def start_skill_run(
    *,
    skill_slug: str,
    provider_name: str,
    context: JobContext,
    config: dict[str, Any] | None = None,
    allow_hitl: bool = True,
    run_subagents_first: bool = True,
) -> dict[str, Any]:
    """同步创建并执行一轮 Skill Run（可在 waiting_user 暂停）。"""
    cfg = dict(config or {})
    state = skill_runs.create_run(skill=skill_slug, provider=provider_name, config=cfg)
    return drive_skill_run(
        state["id"],
        context=context,
        allow_hitl=allow_hitl,
        run_subagents_first=run_subagents_first,
        user_reply=None,
    )


def reply_skill_run(
    run_id: str,
    *,
    reply: str,
    context: JobContext,
) -> dict[str, Any]:
    """用户回复后继续跑。"""
    state = skill_runs.load_run(run_id)
    if state is None:
        raise JobError(f"找不到 run：{run_id}")
    claimed = skill_runs.claim_user_reply(run_id, reply)
    if claimed is None:
        current = skill_runs.load_run(run_id) or state
        raise JobError(f"run 状态不是 waiting_user：{current.get('status')}")

    return drive_skill_run(
        run_id,
        context=context,
        allow_hitl=True,
        run_subagents_first=False,
        user_reply=str(reply),
    )


def drive_skill_run(
    run_id: str,
    *,
    context: JobContext,
    allow_hitl: bool = True,
    run_subagents_first: bool = True,
    user_reply: str | None = None,
) -> dict[str, Any]:
    """驱动已创建的 run（首次或续跑）。"""
    from src.ai import resolve_config
    from src.ops.application.skills import resolve_skill

    state = skill_runs.load_run(run_id)
    if state is None:
        raise JobError(f"找不到 run：{run_id}")

    try:
        if context.ops_store is None:
            raise JobError("缺少运维库连接")

        skill = resolve_skill(str(state["skill"]))
        if skill is None:
            raise JobError(f"未安装的技能：{state['skill']}")
        if not skill.get("enabled", True):
            raise JobError(f"技能 {state['skill']} 已停用")

        cfg = dict(state.get("config") or {})
        provider = resolve_config(
            context.ops_store,
            str(state["provider"]),
            model=str(cfg.get("model") or ""),
            master_key=context.master_key,
        )

        def on_event(event: dict[str, Any]) -> None:
            skill_runs.append_event(run_id, event)

        return _drive(
            state=state,
            skill=skill,
            provider=provider,
            context=context,
            cfg=cfg,
            allow_hitl=allow_hitl,
            run_subagents_first=run_subagents_first and user_reply is None,
            on_event=on_event,
            resume_messages=messages_from_json(state.get("messages")) if user_reply is not None else None,
            user_reply=user_reply,
        )
    except Exception as exc:
        logger.exception("skill run %s failed", run_id)
        state = skill_runs.load_run(run_id) or state
        state["status"] = "error"
        state["error"] = str(exc)
        skill_runs.save_run(state)
        skill_runs.append_event(run_id, {"type": "error", "message": str(exc)})
        if isinstance(exc, OpsError):
            raise JobError(str(exc)) from exc
        raise


def _drive(
    *,
    state: dict[str, Any],
    skill: dict[str, Any],
    provider: Any,
    context: JobContext,
    cfg: dict[str, Any],
    allow_hitl: bool,
    run_subagents_first: bool,
    on_event: Any,
    resume_messages: list | None,
    user_reply: str | None,
) -> dict[str, Any]:
    run_id = state["id"]
    protocol = provider.protocol

    def run_subs(arguments: dict[str, Any]) -> list[dict[str, Any]]:
        return run_ammo_agents(
            skill,
            provider=provider,
            protocol=protocol,
            arguments=arguments,
            on_event=on_event,
        )

    bus = build_toolbus(
        skill,
        protocol=protocol,
        mcp_server_names=list(cfg.get("mcp_servers") or skill.get("mcp_servers") or []) or None,
        allow=list(cfg.get("tools") or skill.get("allowed_tools") or []) or None,
        on_event=on_event,
        hitl_enabled=allow_hitl,
        run_subagents=run_subs,
    )

    sub_briefs = ""
    if run_subagents_first and (skill.get("agents") or []):
        on_event({"type": "phase", "name": "subagents"})
        args = {
            k: cfg[k]
            for k in ("date", "cutoff", "extra_codes")
            if cfg.get(k) not in (None, "")
        }
        results = run_subs(args)
        state["subagents"] = [
            {"id": r.get("id"), "ok": r.get("ok"), "kind": r.get("kind")} for r in results
        ]
        sub_briefs = format_subagent_briefs(results)
        skill_runs.save_run(state)

    if resume_messages is not None:
        from src.ai import ChatMessage

        messages = list(resume_messages)
        messages.append(ChatMessage(role="user", content=f"老板回复：{user_reply}"))
        user_prompt = ""
        messages_arg = messages
    else:
        context_blocks = _gather_context(cfg, context)
        if str(skill.get("isolation") or "") == "skill_only":
            context_blocks = {}
        user_prompt = _compose_prompt(cfg, context_blocks)
        if sub_briefs:
            user_prompt = (user_prompt + "\n\n" + sub_briefs).strip()
        if not user_prompt:
            user_prompt = "请按技能指令执行。需要外部数据时调用工具；多路径时必须 ask_user。"
        messages_arg = None

    on_event({"type": "phase", "name": "main_agent"})
    result = run_agent(
        provider,
        system=skill_system_prefix(str(skill.get("policy") or "")) + "\n" + skill["instructions"],
        user_prompt=user_prompt,
        messages=messages_arg,
        tool_schemas=bus.schemas if bus else None,
        tool_executor=bus.executor if bus else None,
        max_rounds=int(cfg.get("max_rounds") or 8),
        max_tokens=int(cfg.get("max_tokens") or 4096),
        temperature=float(cfg.get("temperature") or 0.3),
        thinking=str(cfg.get("thinking") or ""),
        allow_hitl=allow_hitl,
        on_event=on_event,
    )

    state["messages"] = result.messages
    payload = result.to_dict()
    payload.update(
        {
            "skill": skill["slug"],
            "skill_version": skill.get("version"),
            "provider": provider.name,
            "tool_trace": format_tool_trace(result.invocations),
            "subagents": state.get("subagents") or [],
        }
    )

    if result.stopped_reason == "waiting_user":
        state["status"] = "waiting_user"
        state["pending_ask"] = result.pending_ask
        state["result"] = payload
        skill_runs.save_run(state)
        return {"run": state, "result": payload}

    state["status"] = "done" if result.stopped_reason == "completed" else "error"
    state["pending_ask"] = {}
    state["result"] = payload
    if result.stopped_reason not in {"completed", "waiting_user"}:
        state["error"] = result.stopped_reason
    skill_runs.save_run(state)
    return {"run": state, "result": payload}
