"""服务端 Agent 循环：让模型能自己调工具查数据，而不是只能读我们预先塞的上下文。

## 边界

这一版**只接只读工具**（外部 MCP 的行情/情报查询）。账本写入不在其中——
写账本必须走"AI 提议 → 人工确认"的两段式，那属于交互式对话，不该发生在
无人值守的定时任务里。定时跑的技能模式能查任意数据、能给结论，但改不了
任何一条账本记录。

## 三道刹车

无人值守场景下，一个陷入循环的 Agent 会安静地把配额和 token 烧光：

1. **轮数上限**：超过就停下并如实说明，不假装完成了。
2. **单轮工具数上限**：模型偶尔会一口气请求几十个调用。
3. **工具失败不中断**：把错误原文回给模型让它换个方式，而不是整轮崩掉。
   但错误要如实回传——不能编一个空结果让模型以为查到了。
"""
from __future__ import annotations

from dataclasses import dataclass, field
import json
import logging
from typing import Any, Callable

from src.ai.client import ChatMessage, ChatResponse, LLMError, ProviderConfig, ToolCall, chat

logger = logging.getLogger(__name__)

DEFAULT_MAX_ROUNDS = 8
DEFAULT_MAX_CALLS_PER_ROUND = 8
#: 单次工具结果注入模型的字符上限。行情接口一次能吐几万字，
#: 不截断的话几轮就把上下文撑爆。
MAX_TOOL_RESULT_CHARS = 12000


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

    def to_dict(self) -> dict[str, Any]:
        return {
            "output": self.text,
            "rounds": self.rounds,
            "model": self.model,
            "input_tokens": self.input_tokens,
            "output_tokens": self.output_tokens,
            "stopped_reason": self.stopped_reason,
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


def run_agent(
    config: ProviderConfig,
    *,
    system: str,
    user_prompt: str,
    tool_schemas: list[dict[str, Any]] | None = None,
    tool_executor: Callable[[str, dict[str, Any]], dict[str, Any]] | None = None,
    max_rounds: int = DEFAULT_MAX_ROUNDS,
    max_calls_per_round: int = DEFAULT_MAX_CALLS_PER_ROUND,
    max_tokens: int = 4096,
    temperature: float = 0.3,
) -> AgentResult:
    """跑一轮 Agent 直到模型不再请求工具，或撞上刹车。

    tool_executor 接收 (工具名, 参数) 返回 ``{"text": ..., "is_error": bool}``。
    没有传工具时退化成一次普通对话。
    """
    import time

    messages: list[ChatMessage] = [ChatMessage(role="user", content=user_prompt)]
    invocations: list[ToolInvocation] = []
    input_tokens = output_tokens = 0
    stopped = "completed"
    model = config.model
    response: ChatResponse | None = None

    rounds = 0
    while rounds < max_rounds:
        rounds += 1
        try:
            response = chat(
                config, messages, system=system, max_tokens=max_tokens,
                temperature=temperature, tools=tool_schemas or None,
            )
        except LLMError as exc:
            if rounds == 1:
                raise
            # 中途失败：把已经拿到的内容交出去，不要让前面几轮白跑。
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
                len(response.tool_calls), max_calls_per_round,
            )

        messages.append(
            ChatMessage(role="assistant", content=response.text, tool_calls=calls)
        )

        for call in calls:
            started = time.monotonic()
            try:
                outcome = tool_executor(call.name, call.arguments)
                text = str(outcome.get("text", ""))
                failed = bool(outcome.get("is_error"))
                error = text if failed else ""
            except Exception as exc:
                # 工具挂了不该让整轮崩掉，但必须如实告诉模型——
                # 返回空结果会让它以为"查到了但没数据"，进而编造结论。
                text = f"工具调用失败：{type(exc).__name__}: {exc}"
                failed = True
                error = text
            elapsed = int((time.monotonic() - started) * 1000)

            invocations.append(
                ToolInvocation(
                    name=call.name, arguments=call.arguments, ok=not failed,
                    result_preview=text[:600], error=error[:600], elapsed_ms=elapsed,
                )
            )
            messages.append(
                ChatMessage(role="tool", content=_truncate(text), tool_call_id=call.id)
            )
    else:
        stopped = "max_rounds"
        logger.warning("Agent 达到轮数上限 %s，强制结束", max_rounds)

    text = response.text if response else ""
    if stopped == "max_rounds":
        text += (
            f"\n\n（已达到工具调用轮数上限 {max_rounds}，分析可能不完整。"
            "以上结论仅基于已取得的数据。）"
        )
    return AgentResult(
        text=text, rounds=rounds, invocations=invocations,
        input_tokens=input_tokens, output_tokens=output_tokens,
        stopped_reason=stopped, model=model,
    )


def make_mcp_executor(
    clients: dict[str, Any], routing: dict[str, str]
) -> Callable[[str, dict[str, Any]], dict[str, Any]]:
    """把"带 server 前缀的工具名"路由到对应的 MCP 客户端。

    模型看到的名字是 ``wudao__kline`` 这种带前缀的形式，避免多个 server
    的同名工具互相覆盖。
    """

    def execute(name: str, arguments: dict[str, Any]) -> dict[str, Any]:
        server = routing.get(name)
        if server is None:
            # 模型偶尔会凭空发明一个工具名。如实告诉它，别静默返回空。
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
    """把工具调用过程压成可读文本，放进执行记录。

    定时任务出问题时，"它到底查了什么、拿到了什么"是第一个要看的东西。
    """
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
