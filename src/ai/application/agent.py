"""增强版 Agent 环：支持消息续跑、HITL 暂停、事件回调。"""
from __future__ import annotations

from dataclasses import dataclass, field
import json
import logging
from typing import Any, Callable

from src.ai import ChatMessage, ChatResponse, LLMError, ProviderConfig, ToolCall, chat

logger = logging.getLogger(__name__)

DEFAULT_MAX_ROUNDS = 8
DEFAULT_MAX_CALLS_PER_ROUND = 8
MAX_TOOL_RESULT_CHARS = 12000

EventCallback = Callable[[dict[str, Any]], None]


@dataclass
class ToolInvocation:
    """一次工具调用的完整痕迹，用于执行记录与事后追溯。"""

    name: str
    arguments: dict[str, Any]
    ok: bool
    result_preview: str
    error: str = ""
    elapsed_ms: int = 0


@dataclass
class AgentResult:
    text: str
    rounds: int
    invocations: list[ToolInvocation] = field(default_factory=list)
    input_tokens: int = 0
    output_tokens: int = 0
    stopped_reason: str = "completed"
    model: str = ""
    #: 可序列化的消息列表，供 HITL 续跑
    messages: list[dict[str, Any]] = field(default_factory=list)
    #: waiting_user 时给前端的问题
    pending_ask: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "output": self.text,
            "rounds": self.rounds,
            "model": self.model,
            "input_tokens": self.input_tokens,
            "output_tokens": self.output_tokens,
            "stopped_reason": self.stopped_reason,
            "pending_ask": self.pending_ask,
            "tool_calls": [
                {
                    "name": call.name,
                    "arguments": call.arguments,
                    "ok": call.ok,
                    "elapsed_ms": call.elapsed_ms,
                    "preview": call.result_preview[:400],
                    "error": call.error[:400],
                }
                for call in self.invocations
            ],
        }


def _truncate(text: str, limit: int = MAX_TOOL_RESULT_CHARS) -> str:
    if len(text) <= limit:
        return text
    return text[:limit] + f"\n…（结果过长，已截断，原始长度 {len(text)} 字符）"


def messages_to_json(messages: list[ChatMessage]) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for msg in messages:
        item: dict[str, Any] = {"role": msg.role, "content": msg.content}
        if msg.tool_call_id:
            item["tool_call_id"] = msg.tool_call_id
        if msg.tool_calls:
            item["tool_calls"] = [
                {"id": c.id, "name": c.name, "arguments": c.arguments} for c in msg.tool_calls
            ]
        out.append(item)
    return out


def messages_from_json(raw: list[dict[str, Any]] | None) -> list[ChatMessage]:
    messages: list[ChatMessage] = []
    for item in raw or []:
        calls = [
            ToolCall(
                id=str(c.get("id") or ""),
                name=str(c.get("name") or ""),
                arguments=c.get("arguments") if isinstance(c.get("arguments"), dict) else {},
            )
            for c in (item.get("tool_calls") or [])
            if isinstance(c, dict)
        ]
        messages.append(
            ChatMessage(
                role=str(item.get("role") or "user"),
                content=str(item.get("content") or ""),
                tool_calls=calls,
                tool_call_id=str(item.get("tool_call_id") or ""),
            )
        )
    return messages


def run_agent(
    config: ProviderConfig,
    *,
    system: str,
    user_prompt: str = "",
    tool_schemas: list[dict[str, Any]] | None = None,
    tool_executor: Callable[[str, dict[str, Any]], dict[str, Any]] | None = None,
    max_rounds: int = DEFAULT_MAX_ROUNDS,
    max_calls_per_round: int = DEFAULT_MAX_CALLS_PER_ROUND,
    max_tokens: int = 4096,
    temperature: float = 0.3,
    thinking: str = "",
    messages: list[ChatMessage] | None = None,
    allow_hitl: bool = False,
    on_event: EventCallback | None = None,
) -> AgentResult:
    """跑 Agent 直到不再请求工具、撞刹车，或 HITL 暂停。

    ``messages`` 非空时续跑（忽略 user_prompt）。
    工具返回 ``meta.pause`` / ``meta.needs_hitl`` 且 ``allow_hitl`` 时停止并
    ``stopped_reason=waiting_user``。
    """
    import time

    if messages is not None:
        chat_messages = list(messages)
    else:
        chat_messages = [ChatMessage(role="user", content=user_prompt)]

    invocations: list[ToolInvocation] = []
    input_tokens = output_tokens = 0
    stopped = "completed"
    model = config.model
    response: ChatResponse | None = None
    pending_ask: dict[str, Any] = {}

    rounds = 0
    while rounds < max_rounds:
        rounds += 1
        if on_event:
            on_event({"type": "round_start", "round": rounds})
        try:
            response = chat(
                config,
                chat_messages,
                system=system,
                max_tokens=max_tokens,
                temperature=temperature,
                tools=tool_schemas or None,
                thinking=thinking,
            )
        except LLMError as exc:
            if rounds == 1 and not invocations:
                raise
            logger.warning("Agent 第 %s 轮调用失败：%s", rounds, exc)
            stopped = f"llm_error: {exc}"
            break

        input_tokens += response.input_tokens
        output_tokens += response.output_tokens
        model = response.model or model

        if not response.wants_tools or tool_executor is None:
            break

        calls = response.tool_calls[:max_calls_per_round]
        if len(response.tool_calls) > max_calls_per_round:
            logger.warning(
                "模型一次请求了 %s 个工具，已截断到 %s",
                len(response.tool_calls),
                max_calls_per_round,
            )

        chat_messages.append(
            ChatMessage(role="assistant", content=response.text, tool_calls=calls)
        )

        hitl_pause = False
        for call in calls:
            started = time.monotonic()
            try:
                outcome = tool_executor(call.name, call.arguments)
                text = str(outcome.get("text", ""))
                failed = bool(outcome.get("is_error"))
                error = text if failed else ""
                meta = outcome.get("meta") if isinstance(outcome.get("meta"), dict) else {}
            except Exception as exc:
                text = f"工具调用失败：{type(exc).__name__}: {exc}"
                failed = True
                error = text
                meta = {}
            elapsed = int((time.monotonic() - started) * 1000)

            invocations.append(
                ToolInvocation(
                    name=call.name,
                    arguments=call.arguments,
                    ok=not failed,
                    result_preview=text[:600],
                    error=error[:600],
                    elapsed_ms=elapsed,
                )
            )
            chat_messages.append(
                ChatMessage(role="tool", content=_truncate(text), tool_call_id=call.id)
            )

            if allow_hitl and (meta.get("pause") or meta.get("needs_hitl")):
                pending_ask = meta.get("ask") if isinstance(meta.get("ask"), dict) else {
                    "prompt": text,
                    "options": meta.get("options") or [],
                }
                stopped = "waiting_user"
                hitl_pause = True
                if on_event:
                    on_event({"type": "waiting_user", "ask": pending_ask})
                break

        if hitl_pause:
            break
    else:
        stopped = "max_rounds"
        logger.warning("Agent 达到轮数上限 %s，强制结束", max_rounds)

    text = response.text if response else ""
    if stopped == "max_rounds":
        text += (
            f"\n\n（已达到工具调用轮数上限 {max_rounds}，分析可能不完整。"
            "以上结论仅基于已取得的数据。）"
        )
    if stopped == "waiting_user" and not text:
        text = str(pending_ask.get("prompt") or "等待用户回复")

    if on_event and stopped not in {"waiting_user"}:
        on_event({"type": "done", "stopped_reason": stopped})

    return AgentResult(
        text=text,
        rounds=rounds,
        invocations=invocations,
        input_tokens=input_tokens,
        output_tokens=output_tokens,
        stopped_reason=stopped,
        model=model,
        messages=messages_to_json(chat_messages),
        pending_ask=pending_ask,
    )


def make_mcp_executor(
    clients: dict[str, Any], routing: dict[str, str]
) -> Callable[[str, dict[str, Any]], dict[str, Any]]:
    """把「带 server 前缀的工具名」路由到对应的 MCP 客户端。"""

    def execute(name: str, arguments: dict[str, Any]) -> dict[str, Any]:
        server = routing.get(name)
        if server is None:
            available = ", ".join(sorted(routing)[:15])
            return {
                "text": f"没有名为 {name} 的工具。可用工具：{available}",
                "is_error": True,
            }
        client = clients.get(server)
        if client is None:
            return {"text": f"MCP server {server} 不可用", "is_error": True}
        return client.call_tool(name, arguments)

    return execute


def format_tool_trace(invocations: list[ToolInvocation]) -> str:
    """把工具调用过程压成可读文本，放进执行记录。"""
    if not invocations:
        return "（本次未调用任何工具）"
    lines = []
    for index, call in enumerate(invocations, 1):
        mark = "✓" if call.ok else "✗"
        args = json.dumps(call.arguments, ensure_ascii=False)[:160]
        lines.append(f"{index}. {mark} {call.name}({args}) {call.elapsed_ms}ms")
        if not call.ok:
            lines.append(f"   错误：{call.error[:200]}")
    return "\n".join(lines)
