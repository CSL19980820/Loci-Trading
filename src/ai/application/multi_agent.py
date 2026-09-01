"""Skill 多 Agent：并行弹药子任务（CLI / 短 LLM），结果交主 Agent。

子 agent **禁止终裁锁票**——只交证据摘要。声明在 SKILL.md：

```yaml
agents:
  - id: scan
    role: ammo
    kind: cli
    tool: run_scan          # 引用 tools[] 里的 name
    description: 扫盘 A 级 JSON
  - id: news
    role: ammo
    kind: llm
    instructions: 只收集≤截止时刻新闻要点，不锁票、不给买入价
    max_rounds: 3
    mcp_servers: [wudao]
```
"""
from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor, as_completed
import logging
from typing import Any, Callable

from src.ai import ProviderConfig
from src.ops.application.skill_cli import run_skill_cli
from src.shared.tenancy import submit_with_tenant

logger = logging.getLogger(__name__)

EventCallback = Callable[[dict[str, Any]], None]


def run_ammo_agents(
    skill: dict[str, Any],
    *,
    provider: ProviderConfig | None = None,
    protocol: str = "openai_compatible",
    arguments: dict[str, Any] | None = None,
    on_event: EventCallback | None = None,
    max_workers: int = 4,
    trace_id: str | None = None,
    run_id: str | None = None,
    job_id: str | None = None,
) -> list[dict[str, Any]]:
    """并行跑 ``role=ammo``（默认全部 agents）子任务，返回摘要列表。"""
    specs = [
        spec
        for spec in (skill.get("agents") or [])
        if isinstance(spec, dict)
        and str(spec.get("id") or "").strip()
        and str(spec.get("role") or "ammo").lower() in {"", "ammo"}
    ]
    if not specs:
        return []

    tool_by_name = {
        str(t["name"]): t
        for t in (skill.get("tool_specs") or [])
        if isinstance(t, dict) and t.get("name")
    }

    def _one(spec: dict[str, Any]) -> dict[str, Any]:
        agent_id = str(spec["id"])
        kind = str(spec.get("kind") or "cli").lower()
        if on_event:
            on_event({"type": "subagent_start", "id": agent_id, "kind": kind})
        try:
            if kind == "cli":
                result = _run_cli_agent(skill, spec, tool_by_name, arguments or {})
            elif kind == "llm":
                if provider is None:
                    result = {
                        "id": agent_id,
                        "ok": False,
                        "text": "子 agent 需要 LLM provider，但未配置",
                    }
                else:
                    result = _run_llm_agent(
                        skill,
                        spec,
                        provider,
                        protocol,
                        arguments or {},
                        trace_id=trace_id,
                        run_id=run_id,
                        job_id=job_id,
                    )
            else:
                result = {"id": agent_id, "ok": False, "text": f"未知子 agent kind: {kind}"}
        except Exception as exc:
            result = {"id": agent_id, "ok": False, "text": f"{type(exc).__name__}: {exc}"}
        if on_event:
            on_event(
                {
                    "type": "subagent_end",
                    "id": agent_id,
                    "ok": result.get("ok", False),
                    "preview": str(result.get("text", ""))[:300],
                }
            )
        return result

    results: list[dict[str, Any]] = []
    workers = min(max_workers, max(1, len(specs)))
    # 子任务在**已带租户上下文的** Skill worker 线程里扇出；线程池不继承
    # ContextVar，裸 pool.submit 会让子 agent 的 CLI / MCP 调用按主租户解析
    # 库与技能目录（mcp.json 也是租户私有的，等于用管理员的悟道 Key）。
    with ThreadPoolExecutor(max_workers=workers) as pool:
        futures = {submit_with_tenant(pool, _one, spec): spec for spec in specs}
        for fut in as_completed(futures):
            results.append(fut.result())
    # 稳定顺序：按声明顺序
    order = {str(s["id"]): i for i, s in enumerate(specs)}
    results.sort(key=lambda row: order.get(str(row.get("id")), 999))
    return results


def _run_cli_agent(
    skill: dict[str, Any],
    spec: dict[str, Any],
    tool_by_name: dict[str, dict[str, Any]],
    arguments: dict[str, Any],
) -> dict[str, Any]:
    agent_id = str(spec["id"])
    tool_name = str(spec.get("tool") or "").strip()
    command = spec.get("command")
    timeout = int(spec.get("timeout_sec") or 300)
    cwd = str(spec.get("cwd") or ".")
    if tool_name and tool_name in tool_by_name:
        tool = tool_by_name[tool_name]
        command = tool.get("command") or command
        timeout = int(tool.get("timeout_sec") or timeout)
        cwd = str(tool.get("cwd") or cwd)
    if not command:
        return {"id": agent_id, "ok": False, "text": f"子 agent {agent_id} 缺少 command/tool"}
    outcome = run_skill_cli(
        skill.get("install_path") or "",
        list(command),
        arguments=arguments,
        cwd=cwd,
        timeout_sec=timeout,
    )
    text = str(outcome.get("text") or "")
    # 截断进主 prompt，避免撑爆
    if len(text) > 12000:
        text = text[:12000] + "\n…(子 agent 输出已截断)"
    return {
        "id": agent_id,
        "ok": not outcome.get("is_error"),
        "kind": "cli",
        "description": str(spec.get("description") or ""),
        "text": text,
        "meta": outcome.get("meta") or {},
    }


def _run_llm_agent(
    skill: dict[str, Any],
    spec: dict[str, Any],
    provider: ProviderConfig,
    protocol: str,
    arguments: dict[str, Any],
    *,
    trace_id: str | None = None,
    run_id: str | None = None,
    job_id: str | None = None,
) -> dict[str, Any]:
    from src.ai.application.agent import run_agent
    from src.ai.application.toolbus import build_toolbus
    from src.ops.application.jobs import skill_system_prefix

    agent_id = str(spec["id"])
    instructions = str(spec.get("instructions") or "").strip()
    if not instructions:
        instructions = (
            f"你是子 agent「{agent_id}」。只收集证据，禁止锁票、禁止给出买入价或「今天就干」。"
        )
    # 子 agent 工具面：可收窄 mcp / tools
    sub_skill = dict(skill)
    if spec.get("mcp_servers") is not None:
        sub_skill["mcp_servers"] = list(spec.get("mcp_servers") or [])
    if spec.get("tools") is not None:
        # 只保留列出的 tool_specs
        allow = {str(x) for x in (spec.get("tools") or [])}
        sub_skill["tool_specs"] = [
            t for t in (skill.get("tool_specs") or []) if str(t.get("name")) in allow
        ]
        sub_skill["allowed_tools"] = list(allow)

    bus = build_toolbus(
        sub_skill,
        protocol=protocol,
        mcp_server_names=list(sub_skill.get("mcp_servers") or []) or None,
        allow=list(sub_skill.get("allowed_tools") or []) or None,
        hitl_enabled=False,
        trace_id=trace_id,
        run_id=run_id,
        job_id=job_id,
    )
    user = (
        "请按你的职责收集证据并简要汇报。禁止终裁买谁。"
        f"\n调用参数：{arguments}"
        f"\n职责：{spec.get('description') or agent_id}"
    )
    result = run_agent(
        provider,
        system=skill_system_prefix("research") + "\n" + instructions,
        user_prompt=user,
        tool_schemas=bus.schemas if bus else None,
        tool_executor=bus.executor if bus else None,
        max_rounds=int(spec.get("max_rounds") or 3),
        max_tokens=int(spec.get("max_tokens") or 2048),
        allow_hitl=False,
        emit_terminal_event=False,
    )
    text = result.text or ""
    if len(text) > 8000:
        text = text[:8000] + "\n…(截断)"
    return {
        "id": agent_id,
        "ok": result.stopped_reason == "completed",
        "kind": "llm",
        "description": str(spec.get("description") or ""),
        "text": text,
        "meta": {"rounds": result.rounds, "stopped": result.stopped_reason},
    }


def format_subagent_briefs(results: list[dict[str, Any]]) -> str:
    if not results:
        return ""
    blocks = ["## 子任务弹药（仅证据，非终裁）"]
    for row in results:
        mark = "成功" if row.get("ok") else "失败"
        kind = {"cli": "命令行", "llm": "语言模型"}.get(str(row.get("kind") or ""), str(row.get("kind") or ""))
        blocks.append(
            f"### [{mark}] {row.get('id')}（{kind}）\n"
            f"{row.get('description') or ''}\n\n"
            f"{row.get('text') or '(无输出)'}"
        )
    return "\n\n".join(blocks)
