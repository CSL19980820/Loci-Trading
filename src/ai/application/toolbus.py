"""统一工具总线：Skill CLI + MCP + 少量内置工具 → Agent function calling。

Skill 声明权威在 ``SKILL.md`` frontmatter；MCP 权威在 ``data/mcp.json``。
"""
from __future__ import annotations

from dataclasses import dataclass, field
import json
import logging
from pathlib import Path
from typing import Any, Callable

from src.ai.application.tool_schema import invoke_mcp_tool, mcp_tool_fullname, tool_schema
from src.ops.application.skill_cli import run_skill_cli
from src.ops import SkillError
from src.shared.observability import (
    current as current_observation,
    event as observation_event,
    new_id,
    span as observation_span,
)

logger = logging.getLogger(__name__)

EventCallback = Callable[[dict[str, Any]], None]


def _notify(callback: EventCallback | None, payload: dict[str, Any]) -> None:
    """把当前 tool receipt 追加到 UI 事件，不泄露参数之外的新数据。"""
    if callback is None:
        return
    receipt_id = current_observation().tool_receipt_id
    callback(
        {
            **payload,
            **({"tool_receipt_id": receipt_id} if receipt_id else {}),
        }
    )


@dataclass
class ToolBus:
    """装配好的 schemas + executor。"""

    schemas: list[dict[str, Any]]
    executor: Callable[[str, dict[str, Any]], dict[str, Any]]
    routing: dict[str, str] = field(default_factory=dict)


def build_toolbus(
    skill: dict[str, Any],
    *,
    protocol: str = "openai_compatible",
    mcp_server_names: list[str] | None = None,
    allow: list[str] | None = None,
    on_event: EventCallback | None = None,
    hitl_enabled: bool = False,
    run_subagents: Callable[[dict[str, Any]], list[dict[str, Any]]] | None = None,
    trace_id: str | None = None,
    run_id: str | None = None,
    job_id: str | None = None,
    source_id: str | None = None,
) -> ToolBus | None:
    """根据 skill 记录装配工具面。没有任何工具时返回 None。"""
    allow_set = {str(item) for item in (allow or skill.get("allowed_tools") or []) if item}

    schemas: list[dict[str, Any]] = []
    handlers: dict[str, Callable[[dict[str, Any]], dict[str, Any]]] = {}
    routing: dict[str, str] = {}

    skill_root = Path(str(skill.get("install_path") or ""))
    for spec in skill.get("tool_specs") or []:
        if not isinstance(spec, dict):
            continue
        name = str(spec.get("name") or "").strip()
        if not name:
            continue
        if allow_set and name not in allow_set:
            continue
        kind = str(spec.get("kind") or "cli").lower()
        description = str(spec.get("description") or name)
        args_schema = spec.get("args_schema") if isinstance(spec.get("args_schema"), dict) else {}
        schemas.append(tool_schema(protocol, name, description, args_schema))
        routing[name] = f"skill:{kind}"

        if kind == "cli":
            command = spec.get("command") or []
            cwd = str(spec.get("cwd") or ".")
            timeout = int(spec.get("timeout_sec") or 120)

            def make_cli(cmd=command, work=cwd, to=timeout, root=skill_root, tool=name):
                def _run(arguments: dict[str, Any]) -> dict[str, Any]:
                    _notify(on_event, {"type": "tool_start", "name": tool, "arguments": arguments})
                    try:
                        result = run_skill_cli(
                            root, cmd, arguments=arguments, cwd=work, timeout_sec=to
                        )
                    except SkillError as exc:
                        result = {"text": str(exc), "is_error": True, "meta": {}}
                    _notify(
                        on_event,
                        {
                            "type": "tool_end",
                            "name": tool,
                            "ok": not result.get("is_error"),
                            "preview": str(result.get("text", ""))[:400],
                        },
                        )
                    return result

                return _run

            handlers[name] = make_cli()
        elif kind == "builtin":
            handlers[name] = _make_builtin(
                name, skill, on_event, hitl_enabled=hitl_enabled, run_subagents=run_subagents
            )
        else:
            handlers[name] = lambda arguments, tool=name: {
                "text": f"请使用 MCP 工具（带 server 前缀），本地声明 {tool} 仅为文档别名",
                "is_error": True,
            }

    # 始终挂载运行时内置工具（不受 allowed_tools 收窄，除非显式排除）
    builtins = [
        (
            "ask_user",
            "多路径时必须调用：向老板提问并等待回复。参数 prompt + options(字符串数组)。",
            {
                "type": "object",
                "properties": {
                    "prompt": {"type": "string"},
                    "options": {"type": "array", "items": {"type": "string"}},
                },
                "required": ["prompt"],
            },
        ),
        (
            "write_journal",
            "写入本技能 journal/tail-journal.md 与 picks.jsonl。",
            {
                "type": "object",
                "properties": {
                    "tail_journal_md": {"type": "string"},
                    "picks_jsonl": {},
                },
            },
        ),
        (
            "dispatch_subagents",
            "并行重跑 frontmatter agents[] 弹药子任务，返回证据摘要。禁止让子 agent 锁票。",
            {
                "type": "object",
                "properties": {
                    "date": {"type": "string"},
                    "cutoff": {"type": "string"},
                    "extra_codes": {"type": "string"},
                },
            },
        ),
    ]
    # 运行时内置工具始终挂载：ask_user / write_journal / dispatch_subagents
    # 是技能循环的控制面，不参与 allowed_tools 白名单收窄。
    for bname, bdesc, bschema in builtins:
        if bname in handlers:
            continue
        schemas.append(tool_schema(protocol, bname, bdesc, bschema))
        routing[bname] = "skill:builtin"
        handlers[bname] = _make_builtin(
            bname, skill, on_event, hitl_enabled=hitl_enabled, run_subagents=run_subagents
        )

    # MCP 工具（名称带 server__ 前缀）
    server_names = mcp_server_names
    if server_names is None:
        server_names = list(skill.get("mcp_servers") or [])
    if server_names:
        try:
            from src.intel import McpTool, build_client, collect_tools
        except ImportError as exc:
            logger.warning("MCP 不可用：%s", exc)
        else:
            tools, _mcp_routing = collect_tools(list(server_names), allow=None)
            clients: dict[str, Any] = {}
            for server in {tool.server for tool in tools}:
                try:
                    clients[server] = build_client(server)
                except Exception as exc:
                    logger.warning("MCP server %s 不可用：%s", server, exc)

            for tool in tools:
                full = mcp_tool_fullname(tool.server, tool.name)
                if allow_set and tool.name not in allow_set and full not in allow_set:
                    continue
                if tool.server not in clients:
                    continue
                schema = (
                    tool.to_anthropic_schema()
                    if protocol == "anthropic"
                    else tool.to_openai_schema()
                )
                schemas.append(schema)
                routing[full] = f"mcp:{tool.server}"

                def make_mcp(t: McpTool = tool, fname: str = full):
                    def _run(arguments: dict[str, Any]) -> dict[str, Any]:
                        _notify(
                            on_event,
                            {"type": "tool_start", "name": fname, "arguments": arguments},
                        )
                        result = invoke_mcp_tool(
                            clients.get(t.server),
                            server=t.server,
                            full_name=fname,
                            arguments=arguments,
                        )
                        _notify(
                            on_event,
                            {
                                "type": "tool_end",
                                "name": fname,
                                "ok": not result.get("is_error"),
                                "preview": str(result.get("text", ""))[:400],
                            },
                            )
                        return result

                    return _run

                handlers[full] = make_mcp()

    if not schemas:
        return None

    def executor(name: str, arguments: dict[str, Any]) -> dict[str, Any]:
        receipt_id = new_id("tool")
        handler = handlers.get(name)
        inherited = current_observation()
        routed_source = source_id or routing.get(name, "")
        with observation_span(
            "tool.invoke",
            trace_id=trace_id or inherited.trace_id,
            run_id=run_id or inherited.run_id,
            job_id=job_id or inherited.job_id,
            source_id=routed_source,
            tool_receipt_id=receipt_id,
            labels={"component": "toolbus", "operation": "invoke"},
        ):
            if handler is None:
                available = ", ".join(sorted(handlers)[:20])
                outcome = {
                    "text": f"没有名为 {name} 的工具。可用：{available}",
                    "is_error": True,
                }
            else:
                try:
                    outcome = handler(arguments or {})
                except Exception as exc:
                    outcome = {
                        "text": f"工具失败：{type(exc).__name__}: {exc}",
                        "is_error": True,
                    }
            if not isinstance(outcome, dict):
                outcome = {"text": str(outcome), "is_error": False}
            result = dict(outcome)
            meta = result.get("meta") if isinstance(result.get("meta"), dict) else {}
            result["meta"] = {**meta, "tool_receipt_id": receipt_id}
            result["tool_receipt_id"] = receipt_id
            observation_event(
                logger,
                logging.INFO if not result.get("is_error") else logging.WARNING,
                "tool_invocation",
                fields={
                    "operation": "invoke",
                    "outcome": "error" if result.get("is_error") else "ok",
                },
            )
        return result

    return ToolBus(schemas=schemas, executor=executor, routing=routing)


def _make_builtin(
    name: str,
    skill: dict[str, Any],
    on_event: EventCallback | None,
    *,
    hitl_enabled: bool = False,
    run_subagents: Callable[[dict[str, Any]], list[dict[str, Any]]] | None = None,
) -> Callable[[dict[str, Any]], dict[str, Any]]:
    skill_root = Path(str(skill.get("install_path") or ""))

    def _run(arguments: dict[str, Any]) -> dict[str, Any]:
        _notify(on_event, {"type": "tool_start", "name": name, "arguments": arguments})
        if name == "write_journal":
            result = _builtin_write_journal(skill_root, arguments)
        elif name == "ask_user":
            prompt = str(arguments.get("prompt") or "").strip()
            options = arguments.get("options") or []
            if not isinstance(options, list):
                options = [str(options)]
            options = [str(x) for x in options]
            if hitl_enabled:
                result = {
                    "text": prompt or "请老板抉择",
                    "is_error": False,
                    "meta": {
                        "pause": True,
                        "needs_hitl": True,
                        "ask": {"prompt": prompt or "请老板抉择", "options": options},
                    },
                }
            else:
                result = {
                    "text": (
                        "ask_user 在无人值守 Job 中不可用（无停等）。"
                        "请把选项写进结论，或改用对话式 Skill Run。"
                        f" 问题：{prompt} 选项：{options}"
                    ),
                    "is_error": True,
                    "meta": {"needs_hitl": True, "ask": {"prompt": prompt, "options": options}},
                }
        elif name == "dispatch_subagents":
            if run_subagents is None:
                result = {"text": "当前运行未挂载子 agent 调度器", "is_error": True}
            else:
                try:
                    from src.ai.application.multi_agent import format_subagent_briefs

                    briefs = run_subagents(arguments or {})
                    text = format_subagent_briefs(briefs)
                    result = {
                        "text": text or "(子 agent 无输出)",
                        "is_error": False,
                        "meta": {"agents": [b.get("id") for b in briefs]},
                    }
                except Exception as exc:
                    result = {"text": f"子 agent 失败：{exc}", "is_error": True}
        else:
            result = {"text": f"未知内置工具：{name}", "is_error": True}
        _notify(
            on_event,
            {
                "type": "tool_end",
                "name": name,
                "ok": not result.get("is_error"),
                "preview": str(result.get("text", ""))[:400],
            },
            )
        return result

    return _run


def _builtin_write_journal(skill_root: Path, arguments: dict[str, Any]) -> dict[str, Any]:
    """写入 skill 目录下 journal/（路径 jail）。"""
    if not skill_root.is_dir():
        return {"text": "技能目录无效，无法写 journal", "is_error": True}
    journal = (skill_root / "journal").resolve()
    if not journal.is_relative_to(skill_root.resolve()):
        return {"text": "journal 路径越界", "is_error": True}
    journal.mkdir(parents=True, exist_ok=True)

    md = str(arguments.get("tail_journal_md") or arguments.get("markdown") or "")
    jsonl_line = arguments.get("picks_jsonl") or arguments.get("jsonl")
    written: list[str] = []
    if md.strip():
        path = journal / "tail-journal.md"
        existing = path.read_text(encoding="utf-8") if path.is_file() else ""
        path.write_text(existing.rstrip() + "\n\n" + md.strip() + "\n", encoding="utf-8")
        written.append(str(path))
    if jsonl_line is not None:
        path = journal / "picks.jsonl"
        line = jsonl_line if isinstance(jsonl_line, str) else json.dumps(jsonl_line, ensure_ascii=False)
        with open(path, "a", encoding="utf-8") as handle:
            handle.write(line.rstrip() + "\n")
        written.append(str(path))
    if not written:
        return {"text": "未提供 tail_journal_md / picks_jsonl", "is_error": True}
    return {"text": "已写入：" + ", ".join(written), "is_error": False, "meta": {"paths": written}}
