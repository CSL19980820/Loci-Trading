"""Agent 请求的墙钟预算和已知模型容量预检。"""
from __future__ import annotations

import json
import time
from dataclasses import replace
from typing import Any

from src.ai.application.context_usage import estimate_tokens
from src.ai.infrastructure.client import (
    ChatMessage, LLMError, ProviderConfig, _apply_anthropic_thinking,
)


def check_deadline(deadline: float | None) -> None:
    if deadline is not None and time.monotonic() >= deadline:
        raise TimeoutError("Agent 已超过本轮截止时间，停止继续请求和执行工具")


def request_config(config: ProviderConfig, deadline: float | None) -> ProviderConfig:
    """每次请求（含流式降级）重新取剩余时间，不修改共享的供应商配置。"""
    if deadline is None:
        return config
    remaining = deadline - time.monotonic()
    if remaining <= 0:
        raise TimeoutError("Agent 已超过本轮截止时间，停止请求模型")
    return replace(config, timeout=min(config.timeout, remaining))


def estimate_input_tokens(
    messages: list[ChatMessage],
    *,
    system: str,
    tools: list[dict[str, Any]] | None,
) -> int:
    """沿用仓库的文本估算；包含协议字段、工具定义、参数和原始推理。

    图片由供应商编码，不能把 data URL 的 base64 长度当成图像 token。
    此预检仅估算文本部分，不替代上游对实际多模态容量的校验。
    """
    rows: list[dict[str, Any]] = []
    for message in messages:
        row: dict[str, Any] = {"role": message.role, "content": message.content}
        if message.reasoning_content is not None:
            row["reasoning_content"] = message.reasoning_content
        if message.tool_call_id:
            row["tool_call_id"] = message.tool_call_id
        if message.tool_calls:
            row["tool_calls"] = [
                {"id": call.id, "name": call.name, "arguments": call.arguments}
                for call in message.tool_calls
            ]
        rows.append(row)
    payload = {"system": system, "messages": rows, "tools": tools or []}
    return estimate_tokens(json.dumps(payload, ensure_ascii=False, default=str))


def output_budget(
    config: ProviderConfig,
    messages: list[ChatMessage],
    *,
    system: str,
    tools: list[dict[str, Any]] | None,
    max_tokens: int,
    thinking: str = "",
) -> int:
    """仅使用配置中的容量；未知上下文窗口时不猜默认窗口、不裁剪消息。"""
    budget = (_apply_anthropic_thinking({}, thinking, max_tokens)
              if config.protocol == "anthropic" else max_tokens)
    if config.max_output_tokens is not None:
        budget = min(budget, config.max_output_tokens)
    if config.context_window is not None:
        estimated_input = estimate_input_tokens(messages, system=system, tools=tools)
        remaining = config.context_window - estimated_input
        if remaining <= 0:
            raise LLMError(
                f"上下文容量不足：估算输入 {estimated_input} tokens，"
                f"已知上下文窗口 {config.context_window} tokens；未删除工具结果或推理字段"
            )
        budget = min(budget, remaining)
    if config.protocol == "anthropic" and _apply_anthropic_thinking({}, thinking, budget) > budget:
        raise LLMError(
            f"输出容量不足：剩余预算 {budget} tokens 无法维持当前思考档位；"
            "未降低思考档位或删除推理字段"
        )
    return budget
