"""skill 任务执行器：技能包 + LLM Agent。"""
from __future__ import annotations

from datetime import datetime, timezone
import logging
import time
from typing import Any

from src.ops.application.jobs.context import (
    DEFAULT_PALACE_DB,
    JobContext,
    JobError,
    _llm_meta,
    skill_system_prefix,
)

logger = logging.getLogger(__name__)


def execute_skill(config: dict[str, Any], context: JobContext) -> dict[str, Any]:
    """用配置的 LLM 执行一个技能包定义的模式。

    这是"装个 zip 就多一个可定时运行的模式"的落点。技能包提供指令，
    config 提供供应商与上下文，铁律由 SKILL_SYSTEM_PREFIX 强制前置——
    技能包本身无权覆盖它。

    定时 Job **不支持 HITL**（ask_user 会失败提示改用对话式 Skill Run）。
    若 skill 声明了 ``agents:``，会先并行跑弹药子任务再进主 Agent。
    """
    from src.ai import resolve_config
    from src.ai.application.agent import format_tool_trace, run_agent
    from src.ai.application.multi_agent import format_subagent_briefs, run_ammo_agents

    slug = config.get("skill")
    provider_name = config.get("provider")
    if not slug:
        raise JobError("skill 任务必须指定 skill")
    if not provider_name:
        raise JobError("skill 任务必须指定 provider（LLM 供应商名称）")
    if context.ops_store is None:
        raise JobError("缺少运维库连接，无法读取技能与供应商配置")

    skill = None
    try:
        from src.ops.application.skills import resolve_skill

        skill = resolve_skill(str(slug))
    except Exception:
        skill = None
    if skill is None:
        raise JobError(f"未安装的技能：{slug}（请复制到 data/skills/{slug}/SKILL.md）")
    if not skill.get("enabled", True):
        raise JobError(f"技能 {slug} 已停用")

    provider = resolve_config(
        context.ops_store,
        str(provider_name),
        model=str(config.get("model", "")),
        master_key=context.master_key,
    )

    context_blocks = _gather_context(config, context)
    if str(skill.get("isolation") or "") == "skill_only":
        # weipan 等：禁止把 palace/项目上下文塞进 prompt
        context_blocks = {}
    user_prompt = _compose_prompt(config, context_blocks)

    subagent_meta: list[dict[str, Any]] = []
    if skill.get("agents"):
        ammo_args = {
            k: config[k]
            for k in ("date", "cutoff", "extra_codes")
            if config.get(k) not in (None, "")
        }
        ammo = run_ammo_agents(
            skill,
            provider=provider,
            protocol=provider.protocol,
            arguments=ammo_args,
        )
        subagent_meta = [
            {"id": row.get("id"), "ok": row.get("ok"), "kind": row.get("kind")} for row in ammo
        ]
        briefs = format_subagent_briefs(ammo)
        if briefs:
            user_prompt = (user_prompt + "\n\n" + briefs).strip()

    def run_subs(arguments: dict[str, Any]) -> list[dict[str, Any]]:
        return run_ammo_agents(
            skill,
            provider=provider,
            protocol=provider.protocol,
            arguments=arguments,
        )

    tool_schemas, executor = _resolve_tools(
        config, skill, context, provider.protocol, run_subagents=run_subs
    )

    thinking = str(config.get("thinking") or "")
    agent_started = time.monotonic()
    result = run_agent(
        provider,
        system=skill_system_prefix(str(skill.get("policy") or "")) + "\n" + skill["instructions"],
        user_prompt=user_prompt or "请按技能指令执行。需要外部数据时调用工具。",
        tool_schemas=tool_schemas,
        tool_executor=executor,
        max_rounds=int(config.get("max_rounds", 8)),
        max_tokens=int(config.get("max_tokens", 4096)),
        temperature=float(config.get("temperature", 0.3)),
        thinking=thinking,
        allow_hitl=False,
    )

    payload = result.to_dict()
    payload.update(
        {
            "skill": skill["slug"],
            "skill_name": skill.get("name") or skill["slug"],
            "skill_version": skill["version"],
            "provider": provider.name,
            "context_used": sorted(context_blocks),
            "tool_trace": format_tool_trace(result.invocations),
            "llm_meta": _llm_meta(provider, thinking),
            "latency_ms": int((time.monotonic() - agent_started) * 1000),
            "subagents": subagent_meta,
        }
    )
    # 若技能上下文里跑过选股，把 picks 挂到结果上，供企微 skills 模板使用
    screen_block = context_blocks.get("screen")
    if isinstance(screen_block, dict) and isinstance(screen_block.get("picks"), list):
        payload["picks"] = screen_block["picks"]
        if screen_block.get("strategy"):
            payload["screen_strategy"] = screen_block["strategy"]
        if screen_block.get("trade_date"):
            payload["trade_date"] = screen_block["trade_date"]
    return payload


def _resolve_tools(
    config: dict[str, Any],
    skill: dict[str, Any],
    context: JobContext,
    protocol: str,
    *,
    run_subagents=None,
):
    """装配 Skill CLI + MCP 工具面（ToolBus）。Job 路径 hitl_enabled=False。"""
    try:
        from src.ai.application.toolbus import build_toolbus
    except ImportError as exc:
        logger.warning("ToolBus 不可用（%s），技能将以无工具模式运行", getattr(exc, "name", exc))
        return None, None

    server_names = config.get("mcp_servers")
    if server_names is None:
        server_names = skill.get("mcp_servers")
    allow = config.get("tools") or skill.get("allowed_tools") or None
    # 空 allow 列表在 build_toolbus 里表示不收窄；传 None 同理
    if isinstance(allow, list) and len(allow) == 0:
        allow = None

    bus = build_toolbus(
        skill,
        protocol=protocol,
        mcp_server_names=list(server_names) if server_names else None,
        allow=list(allow) if allow else None,
        hitl_enabled=False,
        run_subagents=run_subagents,
    )
    if bus is None:
        return None, None
    return bus.schemas, bus.executor


def _gather_context(config: dict[str, Any], context: JobContext) -> dict[str, Any]:
    """按 config.context 声明的项目，把真实数据准备好交给模型。

    只喂真实取到的数据，取不到就如实标注——铁律 1 靠这里落实，
    不能只靠 prompt 里写一句"不许编"。
    """
    from src.ops.application.jobs.screen import execute_screen

    wanted = config.get("context") or []
    blocks: dict[str, Any] = {}

    if "market_coverage" in wanted:
        try:
            with context.market() as store:
                blocks["market_coverage"] = store.coverage()
        except Exception as exc:
            blocks["market_coverage"] = f"未取得真实数据：{type(exc).__name__}: {exc}"

    if "screen" in wanted:
        strategy = config.get("context_strategy") or config.get("strategy")
        if not strategy:
            blocks["screen"] = "未取得真实数据：未指定 context_strategy"
        else:
            try:
                blocks["screen"] = execute_screen({"strategy": strategy}, context)
            except Exception as exc:
                blocks["screen"] = f"未取得真实数据：{type(exc).__name__}: {exc}"

    if "positions" in wanted:
        try:
            from src.ledger import PalaceStore

            with PalaceStore(context.palace_db or DEFAULT_PALACE_DB) as palace:
                blocks["positions"] = palace.positions_payload()
        except Exception as exc:
            blocks["positions"] = f"未取得真实数据：{type(exc).__name__}: {exc}"

    return blocks


def _compose_prompt(config: dict[str, Any], blocks: dict[str, Any]) -> str:
    import json

    parts: list[str] = []
    today = datetime.now(timezone.utc).astimezone().strftime("%Y-%m-%d")
    parts.append(f"今天是 {today}。")
    if config.get("prompt"):
        parts.append(str(config["prompt"]))
    for name, payload in blocks.items():
        rendered = payload if isinstance(payload, str) else json.dumps(
            payload, ensure_ascii=False, indent=2, default=str
        )
        parts.append(f"\n## 数据：{name}\n```json\n{rendered}\n```")
    if not config.get("prompt") and not blocks:
        parts.append("请按技能指令执行。")
    return "\n".join(parts)
