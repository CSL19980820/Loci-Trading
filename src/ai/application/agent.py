"""增强版 Agent 环：支持消息续跑、HITL 暂停、事件回调。"""
from __future__ import annotations

from dataclasses import dataclass, field
import json
import logging
import re
from typing import Any, Callable

from src.ai import ChatMessage, ChatResponse, LLMError, ProviderConfig, ToolCall, chat
from src.ai.infrastructure.client_stream import chat_stream

logger = logging.getLogger(__name__)

DEFAULT_MAX_ROUNDS = 8
DEFAULT_MAX_CALLS_PER_ROUND = 8
MAX_TOOL_RESULT_CHARS = 12000

# Hermes run_agent.py：工具后空正文催办（tools 保持可用；禁止把工具前计划句当终稿）
POST_TOOL_EMPTY_NUDGE = (
    "You just executed tool calls but returned an "
    "empty response. Please process the tool "
    "results above and continue with the task."
)
# OpenClaw incomplete-turn.ts
EMPTY_RESPONSE_RETRY_INSTRUCTION = (
    "The previous attempt did not produce a user-visible answer. "
    "Continue from the current state and produce the visible answer now. "
    "Do not restart from scratch."
)
REASONING_ONLY_RETRY_INSTRUCTION = (
    "The previous assistant turn recorded reasoning but did not produce a "
    "user-visible answer. Continue from that partial turn and produce the "
    "visible answer now. Do not restate the reasoning or restart from scratch."
)
EMPTY_ASSISTANT_SENTINEL = "(empty)"
# OpenClaw DEFAULT_EMPTY_RESPONSE_RETRY_LIMIT；Hermes 另有独立 post-tool nudge
MAX_EMPTY_CONTENT_RETRIES = 1
# Hermes nudge LLM + OpenClaw retry LLM；while-else 观察空结果不占工具预算
RECOVERY_ROUND_SLACK = 3

EMPTY_COMPLETION_USER_TEXT = (
    "本轮模型未产出可读终稿（常见于思考档位只返回推理、正文为空）。"
    "请点「重新生成」，或把思考档位调低后再问。"
)

EventCallback = Callable[[dict[str, Any]], None]

_THINK_TAG_RE = re.compile(
    r"<think>.*?</think>|"
    r"<thinking>.*?</thinking>|"
    r"<reasoning>.*?</reasoning>|"
    r"<REASONING_SCRATCHPAD>.*?</REASONING_SCRATCHPAD>",
    flags=re.DOTALL | re.IGNORECASE,
)
_THINK_TAG_OPEN_RE = re.compile(
    r"</?(?:think|thinking|reasoning|thought|REASONING_SCRATCHPAD)\s*>",
    flags=re.IGNORECASE,
)


def visible_text(content: str | None) -> str:
    """Hermes ``_strip_think_blocks``：去掉思考标签后的可见正文。"""
    if not content:
        return ""
    cleaned = _THINK_TAG_RE.sub("", content)
    cleaned = _THINK_TAG_OPEN_RE.sub("", cleaned)
    return cleaned.strip()


def _recent_has_tool_result(messages: list[ChatMessage], *, window: int = 5) -> bool:
    """Hermes：检查近几条是否刚落过 tool 结果（用于 post-tool empty nudge）。"""
    for msg in messages[-window:]:
        if msg.role == "tool":
            return True
    return False


def _append_empty_recovery(
    messages: list[ChatMessage],
    *,
    instruction: str,
) -> None:
    """Hermes 消息序：assistant("(empty)") → user(nudge)；禁止 tool→user 直连。"""
    messages.append(ChatMessage(role="assistant", content=EMPTY_ASSISTANT_SENTINEL))
    messages.append(ChatMessage(role="user", content=instruction))


_EMPTY_RECOVERY_INSTRUCTIONS = frozenset({
    POST_TOOL_EMPTY_NUDGE,
    EMPTY_RESPONSE_RETRY_INSTRUCTION,
    REASONING_ONLY_RETRY_INSTRUCTION,
})


def _is_empty_recovery_pair(assistant: ChatMessage, user: ChatMessage) -> bool:
    return (
        assistant.role == "assistant"
        and assistant.content == EMPTY_ASSISTANT_SENTINEL
        and not assistant.tool_calls
        and user.role == "user"
        and user.content in _EMPTY_RECOVERY_INSTRUCTIONS
    )


def _drop_all_empty_recovery(messages: list[ChatMessage]) -> None:
    """Hermes scaffolding scrub：去掉全部合成 (empty)/nudge（含 HITL 前夹在中间的）。"""
    kept: list[ChatMessage] = []
    index = 0
    while index < len(messages):
        if index + 1 < len(messages) and _is_empty_recovery_pair(
            messages[index], messages[index + 1]
        ):
            index += 2
            continue
        kept.append(messages[index])
        index += 1
    messages[:] = kept


def _can_attempt_empty_recovery(
    *,
    prior_was_tool: bool,
    post_tool_empty_retried: bool,
    empty_content_retries: int,
) -> bool:
    if prior_was_tool and not post_tool_empty_retried:
        return True
    return empty_content_retries < MAX_EMPTY_CONTENT_RETRIES


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


def apply_hitl_tool_result(
    messages: list[dict[str, Any]] | list[ChatMessage] | None,
    reply: str,
) -> list[ChatMessage]:
    """把用户 HITL 答复写成末条 tool 消息正文，供同 run 续环。

    暂停时 ask_user 已落占位 tool result；resume 用用户正文覆盖。
    若快照无 tool 消息（退化路径），则追加一条 user 消息。
    """
    if messages and isinstance(messages[0], ChatMessage):
        chat = list(messages)  # type: ignore[arg-type]
    else:
        chat = messages_from_json(messages if isinstance(messages, list) else None)
    reply_text = str(reply or "").strip() or "（用户已回复）"
    for index in range(len(chat) - 1, -1, -1):
        if chat[index].role == "tool":
            chat[index] = ChatMessage(
                role="tool",
                content=_truncate(reply_text),
                tool_call_id=chat[index].tool_call_id,
            )
            return chat
    chat.append(ChatMessage(role="user", content=reply_text))
    return chat


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
    emit_terminal_event: bool = True,
    stream: bool = True,
) -> AgentResult:
    """跑 Agent 直到不再请求工具、撞刹车，或 HITL 暂停。

    ``messages`` 非空时续跑（忽略 user_prompt）。
    工具返回 ``meta.pause`` / ``meta.needs_hitl`` 且 ``allow_hitl`` 时停止并
    ``stopped_reason=waiting_user``。
    ``stream=True`` 时走 ``chat_stream``，经 ``on_event`` 发原生 ``think`` / ``token``；
    流式不可用且尚未发出增量时降级为非流式 ``chat``（仅终稿 ``done``）。
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
    # OpenClaw reasoning-only：本轮流式是否只吐了 think
    round_streamed_think = False

    def _call_llm(round_messages: list[ChatMessage]) -> ChatResponse:
        nonlocal round_streamed_think
        kwargs: dict[str, Any] = {
            "system": system,
            "max_tokens": max_tokens,
            "temperature": temperature,
            "tools": tool_schemas or None,
            "thinking": thinking,
        }
        if not stream:
            return chat(config, round_messages, **kwargs)

        streamed_any = False
        round_streamed_think = False

        def on_delta(kind: str, delta: str) -> None:
            nonlocal streamed_any, round_streamed_think
            if not delta or kind not in {"think", "token"}:
                return
            streamed_any = True
            if kind == "think":
                round_streamed_think = True
            if on_event:
                on_event({"type": kind, "delta": delta})

        try:
            return chat_stream(config, round_messages, on_delta=on_delta, **kwargs)
        except LLMError as exc:
            if streamed_any:
                raise
            logger.info("流式不可用，降级非流式：%s", exc)
            return chat(config, round_messages, **kwargs)

    rounds = 0
    # Hermes: 工具轮成功后重置，后续再空可再催一次
    post_tool_empty_retried = False
    empty_content_retries = 0
    # 工具环硬顶 max_rounds；空回复恢复可多用 RECOVERY_ROUND_SLACK 轮
    round_limit = max_rounds + RECOVERY_ROUND_SLACK
    while rounds < round_limit:
        rounds += 1
        if on_event:
            on_event({"type": "round_start", "round": rounds})
        try:
            response = _call_llm(chat_messages)
        except LLMError as exc:
            if rounds == 1 and not invocations:
                raise
            logger.warning("Agent 第 %s 轮调用失败：%s", rounds, exc)
            stopped = f"llm_error: {exc}"
            # Hermes：禁止把上一轮工具前旁白当成失败正文
            response = ChatResponse(text="", model=model)
            break

        input_tokens += response.input_tokens
        output_tokens += response.output_tokens
        model = response.model or model

        if response.wants_tools and tool_executor is not None:
            if rounds > max_rounds:
                # Slack 区只允许空回复恢复，禁止再开工具环。这一轮既没执行工具
                # 也没产出终稿：不计入已完成轮次，且与 llm_error 分支一样丢掉
                # 工具前旁白（「我再查一轮…」不是结论）。
                stopped = "max_rounds"
                rounds -= 1
                response = ChatResponse(text="", model=model)
                logger.warning("Agent 达到轮数上限 %s，拒绝继续调工具", max_rounds)
                break
            calls = response.tool_calls[:max_calls_per_round]
            if len(response.tool_calls) > max_calls_per_round:
                logger.warning(
                    "模型一次请求了 %s 个工具，已截断到 %s",
                    len(response.tool_calls),
                    max_calls_per_round,
                )

            # 工具前旁白（「先读账本…」）不是终稿；Hermes 仅在 housekeeping
            # 工具时才回退到该旁白。本仓工具均为实质查询，禁止回退。
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
                    # 多题 ask：保留 questions[]；无顶层 prompt 时用首题文案兜底
                    if isinstance(pending_ask, dict):
                        questions = pending_ask.get("questions")
                        if (
                            isinstance(questions, list)
                            and questions
                            and not str(pending_ask.get("prompt") or "").strip()
                        ):
                            first = questions[0] if isinstance(questions[0], dict) else {}
                            pending_ask = {
                                **pending_ask,
                                "prompt": str(
                                    (first.get("prompt") if isinstance(first, dict) else None)
                                    or text
                                    or "等待用户回复"
                                ),
                            }
                    stopped = "waiting_user"
                    hitl_pause = True
                    if on_event:
                        on_event({"type": "waiting_user", "ask": pending_ask})
                    break

            if hitl_pause:
                break
            # Hermes：工具执行成功后允许下一轮再触发 post-tool empty nudge
            post_tool_empty_retried = False
            empty_content_retries = 0
            continue

        # 无工具且无可见正文 → Hermes post-tool nudge，再 OpenClaw empty/reasoning retry
        # 工具 schema 全程保持注入（_call_llm 不摘 tools）。
        if not visible_text(response.text):
            prior_was_tool = _recent_has_tool_result(chat_messages)
            if _can_attempt_empty_recovery(
                prior_was_tool=prior_was_tool,
                post_tool_empty_retried=post_tool_empty_retried,
                empty_content_retries=empty_content_retries,
            ):
                if prior_was_tool and not post_tool_empty_retried:
                    # Hermes #9400：优先 post-tool nudge（与 empty retry 独立计数）
                    post_tool_empty_retried = True
                    logger.warning(
                        "Empty response after tool calls — nudging model to continue"
                    )
                    _append_empty_recovery(chat_messages, instruction=POST_TOOL_EMPTY_NUDGE)
                    continue

                # Hermes：post-tool 催过后仍可走 empty_content_retries；
                # OpenClaw：reasoning-only 用专用 instruction，否则 EMPTY_RESPONSE。
                empty_content_retries += 1
                instruction = (
                    REASONING_ONLY_RETRY_INSTRUCTION
                    if round_streamed_think
                    else EMPTY_RESPONSE_RETRY_INSTRUCTION
                )
                logger.warning(
                    "Empty/reasoning-only response — retry %s/%s",
                    empty_content_retries,
                    MAX_EMPTY_CONTENT_RETRIES,
                )
                _append_empty_recovery(chat_messages, instruction=instruction)
                continue

        break
    else:
        # while 自然耗尽：若最后仍是空正文，禁止伪装成「轮数上限成功」
        if response is not None and not visible_text(response.text):
            stopped = "completed"
            logger.warning(
                "Recovery slack exhausted with empty response — will mark empty_completion"
            )
        else:
            stopped = "max_rounds"
            logger.warning("Agent 达到轮数上限 %s，强制结束", max_rounds)

    if str(stopped).startswith("llm_error"):
        text = (
            f"模型调用失败：{stopped.removeprefix('llm_error: ').strip() or stopped}。"
            "请稍后重试，或检查供应商与网络。"
        )
    else:
        text = visible_text(response.text) if response else ""

    if stopped == "max_rounds":
        text += (
            f"\n\n（已达到工具调用轮数上限 {max_rounds}，分析可能不完整。"
            "以上结论仅基于已取得的数据。）"
        )
    if stopped == "waiting_user" and not text:
        text = str(pending_ask.get("prompt") or "等待用户回复")

    if stopped == "completed" and not text:
        # Hermes/OpenClaw：耗尽重试后显式失败，禁止用工具前计划句冒充终稿
        text = EMPTY_COMPLETION_USER_TEXT
        stopped = "empty_completion"
        logger.warning("Empty response after retries — marking empty_completion")

    if emit_terminal_event and on_event and stopped not in {"waiting_user"}:
        # OpenClaw：无可见终稿发 error，禁止用 done 伪装成功
        if stopped == "empty_completion" or str(stopped).startswith("llm_error"):
            on_event({
                "type": "error",
                "stopped_reason": stopped,
                "message": text,
                "text": text,
                "content": text,
            })
        else:
            on_event({
                "type": "done",
                "stopped_reason": stopped,
                "text": text,
                "content": text,
            })

    # Hermes：合成 empty/nudge 不进入可续跑 transcript（含 HITL 中间夹层）
    _drop_all_empty_recovery(chat_messages)

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
        from src.intel import McpClient, guarded_client_call

        if isinstance(client, McpClient):
            return guarded_client_call(client, name, arguments, pool="skill")
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
