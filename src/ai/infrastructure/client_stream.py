"""真流式 LLM 对话：把供应商原生 reasoning / content delta 回调出去。

不做假打字机；无原生思考增量时不发 think。返回结构与 ``chat`` 对齐。
"""
from __future__ import annotations

import json
import logging
from contextlib import closing
from typing import Any, Callable

from src.ai.infrastructure.client import (
    ChatMessage,
    ChatResponse,
    LLMError,
    LLMNoReplayError,
    LLMGenerationInterrupted,
    ProviderConfig,
    ToolCall,
    _anthropic_messages,
    _apply_anthropic_thinking,
    _apply_openai_thinking,
    _openai_messages,
    _redact,
    _safe_json,
)

from src.ai.infrastructure.stream_deadline import DeadlineStreamClient

logger = logging.getLogger(__name__)

#: kind 为 ``think``（原生 reasoning）或 ``token``（正文）
StreamDeltaCallback = Callable[[str, str], None]


def chat_stream(
    config: ProviderConfig,
    messages: list[ChatMessage],
    *,
    system: str = "",
    max_tokens: int = 4096,
    temperature: float = 0.3,
    tools: list[dict[str, Any]] | None = None,
    thinking: str = "",
    on_delta: StreamDeltaCallback | None = None,
    first_response_timeout: float | None = None,
    deadline: float | None = None,
) -> ChatResponse:
    """一次流式对话；``on_delta('think'|'token', delta)`` 接收增量。"""
    transport = DeadlineStreamClient(config, first_response_timeout, deadline, on_delta)
    on_delta = transport.delta
    if config.protocol == "anthropic":
        return _stream_anthropic(
            config,
            messages,
            system,
            max_tokens,
            temperature,
            tools,
            thinking=thinking,
            on_delta=on_delta,
            transport=transport,
        )
    return _stream_openai(
        config,
        messages,
        system,
        max_tokens,
        temperature,
        tools,
        thinking=thinking,
        on_delta=on_delta,
        transport=transport,
    )


def _emit(on_delta: StreamDeltaCallback | None, kind: str, delta: str) -> None:
    if on_delta and delta:
        on_delta(kind, delta)


def _iter_sse_data_lines(response: Any) -> Any:
    """逐行读取 SSE；只产出 ``data:`` 负载（去掉前缀）。"""
    with closing(response.iter_lines()) as lines:
        for raw in lines:
            if raw is None:
                continue
            line = raw.decode("utf-8", errors="replace") if isinstance(raw, (bytes, bytearray)) else str(raw)
            line = line.strip()
            if not line or line.startswith(":"):
                continue
            if line.startswith("data:"):
                yield line[5:].strip()


def _stream_error(response: Any, config: ProviderConfig) -> None:
    if response.status_code < 400:
        return
    try:
        detail = response.read()
        if isinstance(detail, (bytes, bytearray)):
            detail = detail.decode("utf-8", errors="replace")
        else:
            detail = str(detail or "")
    except Exception:
        detail = ""
    detail = _redact(detail, config.api_key)
    hint = ""
    if response.status_code == 401:
        hint = "（API Key 无效或已过期）"
    elif response.status_code == 429:
        hint = "（触发限流，稍后再试）"
    error = LLMNoReplayError if getattr(response, "extensions", {}).get("loci_transport") == b"grpc" else LLMError
    if response.status_code in {408, 429, 500, 502, 503, 504}:
        error = LLMGenerationInterrupted
    raise error(f"{config.name} 流式返回 {response.status_code}{hint}：{detail}")


_BUSY_ERROR_CODES = frozenset({"408", "429", "500", "502", "503", "504", "529"})
_BUSY_ERROR_WORDS = ("overload", "rate_limit", "rate limit", "too many requests", "timeout",
                     "temporarily unavailable", "server_error", "api_error")


def _stream_payload_error(config: ProviderConfig, error: Any, *, recoverable: bool) -> LLMError:
    """把流里的 error 事件还原成真实原因（限流、过载、内容审核、余额……）。

    原先 OpenAI 兼容流里的 ``{"error": ...}`` 块被当成无 choices 的普通块跳过，
    最终只剩一句“模型流在结束标记前中断”，内容审核等真实原因被吞掉，还会被
    当作瞬时中断白白重跑两次。忙碌类错误（限流/过载/上游超时）仍按可恢复中断
    交给显式开启恢复的调用方；其余错误重跑结果相同，不重放。
    """
    if isinstance(error, dict):
        message = error.get("message") or error.get("msg") or error.get("error") or error
        code = " ".join(str(error.get(key) or "") for key in ("code", "status", "type"))
    else:
        message, code = error, ""
    text = f"{config.name} 流式返回错误：{_redact(str(message), config.api_key)}"
    probe = f"{code} {message}".lower()
    busy = any(part in _BUSY_ERROR_CODES for part in code.split()) or any(word in probe for word in _BUSY_ERROR_WORDS)
    if busy:
        return LLMGenerationInterrupted(text) if recoverable else LLMError(text)
    return LLMNoReplayError(text)


def _missing_finish_reason(config: ProviderConfig, done_marker: bool) -> LLMError:
    if done_marker:
        # 流已由供应商正常收尾，只是不回传结束原因：重跑结果一样，不按中断恢复浪费两次完整生成。
        return LLMNoReplayError(
            f"{config.name} 流已结束但未返回结束原因（finish_reason/stop_reason），无法证明输出完整、未被截断；"
            "交易决策不采用。请改用会回传结束原因的供应商或中转。"
        )
    return LLMGenerationInterrupted("模型流在结束标记前中断，未采用不完整输出")


def _openai_reasoning_delta(delta: dict[str, Any]) -> str:
    """兼容 DeepSeek / OpenRouter / 部分 o 系列的 reasoning 字段名。"""
    raw = delta.get("reasoning_content")
    if isinstance(raw, str) and raw:
        return raw
    raw = delta.get("reasoning")
    if isinstance(raw, str) and raw:
        return raw
    if isinstance(raw, dict):
        text = raw.get("content") or raw.get("text") or ""
        return str(text) if text else ""
    return ""


def _stream_openai(
    config: ProviderConfig,
    messages: list[ChatMessage],
    system: str,
    max_tokens: int,
    temperature: float,
    tools: list[dict[str, Any]] | None,
    *,
    thinking: str,
    on_delta: StreamDeltaCallback | None,
    transport: DeadlineStreamClient,
) -> ChatResponse:
    body: dict[str, Any] = {
        "model": config.model,
        "messages": _openai_messages(messages, system),
        "max_tokens": max_tokens,
        "temperature": temperature,
        "stream": True,
        "stream_options": {"include_usage": True},
    }
    if tools:
        body["tools"] = tools
        body["tool_choice"] = "auto"
    _apply_openai_thinking(body, thinking)

    text_parts: list[str] = []
    reasoning_parts: list[str] = []
    reasoning_seen = False
    tool_acc: dict[int, dict[str, str]] = {}
    model = config.model
    input_tokens = output_tokens = 0
    raw_chunks: list[dict[str, Any]] = []
    finish_reason = ""
    done_marker = False

    with transport as client:
        try:
            with client.stream(
                "POST",
                f"{config.base_url}/chat/completions",
                headers={
                    "Authorization": f"Bearer {config.api_key}",
                    "Content-Type": "application/json",
                    "Accept": "text/event-stream",
                },
                json=body,
            ) as response, closing(_iter_sse_data_lines(response)) as payloads:
                _stream_error(response, config)
                for payload in payloads:
                    if payload == "[DONE]":
                        done_marker = True
                        break
                    try:
                        chunk = json.loads(payload)
                    except json.JSONDecodeError:
                        logger.debug("%s 跳过非法 SSE 块", config.name)
                        continue
                    if not isinstance(chunk, dict):
                        continue
                    raw_chunks.append(chunk)
                    if chunk.get("error") and not chunk.get("choices"):
                        raise _stream_payload_error(config, chunk["error"],
                                                    recoverable=transport.first_deadline is not None)
                    if chunk.get("model"):
                        model = str(chunk["model"])
                    usage = chunk.get("usage") or {}
                    if usage:
                        input_tokens = int(usage.get("prompt_tokens", input_tokens) or input_tokens)
                        output_tokens = int(
                            usage.get("completion_tokens", output_tokens) or output_tokens
                        )
                    choices = chunk.get("choices") or []
                    if not choices:
                        continue
                    if choices[0].get("finish_reason"):
                        finish_reason = str(choices[0]["finish_reason"])
                    delta = choices[0].get("delta") or {}
                    if not isinstance(delta, dict):
                        continue
                    reasoning = delta.get("reasoning_content")
                    if isinstance(reasoning, str):
                        reasoning_seen = True
                        reasoning_parts.append(reasoning)
                    reason = _openai_reasoning_delta(delta)
                    if reason:
                        _emit(on_delta, "think", reason)
                    content = delta.get("content")
                    if isinstance(content, str) and content:
                        text_parts.append(content)
                        _emit(on_delta, "token", content)
                    for item in delta.get("tool_calls") or []:
                        if not isinstance(item, dict):
                            continue
                        if transport.first_deadline is not None and (item.get("id") or item.get("function")):
                            _emit(on_delta, "tool_delta", "received")
                        idx = int(item.get("index", 0) or 0)
                        slot = tool_acc.setdefault(idx, {"id": "", "name": "", "arguments": ""})
                        if item.get("id"):
                            slot["id"] = str(item["id"])
                        function = item.get("function") or {}
                        if function.get("name"):
                            slot["name"] = str(function["name"])
                        if function.get("arguments"):
                            slot["arguments"] += str(function["arguments"])
        except LLMError:
            raise
        except Exception as exc:
            raise LLMError(
                f"{config.name} 流式请求失败：{type(exc).__name__}: "
                f"{_redact(str(exc), config.api_key)}"
            ) from exc

    if transport.first_deadline is not None and not finish_reason:
        raise _missing_finish_reason(config, done_marker)
    calls = [
        ToolCall(
            id=slot["id"],
            name=slot["name"],
            arguments=_safe_json(slot["arguments"], config.name),
        )
        for _, slot in sorted(tool_acc.items())
    ]
    return ChatResponse(
        text="".join(text_parts),
        model=model,
        input_tokens=input_tokens,
        output_tokens=output_tokens,
        tool_calls=calls,
        raw={"stream_chunks": len(raw_chunks), "protocol": "openai_compatible",
             "finish_reason": finish_reason},
        reasoning_content="".join(reasoning_parts) if reasoning_seen else None,
    )


def _stream_anthropic(
    config: ProviderConfig,
    messages: list[ChatMessage],
    system: str,
    max_tokens: int,
    temperature: float,
    tools: list[dict[str, Any]] | None,
    *,
    thinking: str,
    on_delta: StreamDeltaCallback | None,
    transport: DeadlineStreamClient,
) -> ChatResponse:
    body: dict[str, Any] = {
        "model": config.model,
        "max_tokens": max_tokens,
        "temperature": temperature,
        "messages": _anthropic_messages(messages),
        "stream": True,
    }
    if system:
        body["system"] = system
    if tools:
        body["tools"] = tools
    body["max_tokens"] = _apply_anthropic_thinking(body, thinking, max_tokens)

    text_parts: list[str] = []
    tool_blocks: dict[int, dict[str, Any]] = {}
    model = config.model
    input_tokens = output_tokens = 0
    event_count = 0
    finish_reason = ""
    done_marker = False

    with transport as client:
        try:
            with client.stream(
                "POST",
                f"{config.base_url}/messages",
                headers={
                    "x-api-key": config.api_key,
                    "anthropic-version": "2023-06-01",
                    "Content-Type": "application/json",
                    "Accept": "text/event-stream",
                },
                json=body,
            ) as response, closing(_iter_sse_data_lines(response)) as payloads:
                _stream_error(response, config)
                for payload in payloads:
                    try:
                        event = json.loads(payload)
                    except json.JSONDecodeError:
                        continue
                    if not isinstance(event, dict):
                        continue
                    event_count += 1
                    kind = str(event.get("type") or "")
                    if kind == "message_start":
                        message = event.get("message") or {}
                        if message.get("model"):
                            model = str(message["model"])
                        usage = message.get("usage") or {}
                        input_tokens = int(usage.get("input_tokens", 0) or 0)
                    elif kind == "content_block_start":
                        index = int(event.get("index", 0) or 0)
                        block = event.get("content_block") or {}
                        if block.get("type") == "tool_use":
                            if transport.first_deadline is not None:
                                _emit(on_delta, "tool_delta", "received")
                            tool_blocks[index] = {
                                "id": str(block.get("id") or ""),
                                "name": str(block.get("name") or ""),
                                "arguments": "",
                            }
                    elif kind == "content_block_delta":
                        index = int(event.get("index", 0) or 0)
                        delta = event.get("delta") or {}
                        dtype = str(delta.get("type") or "")
                        if dtype == "thinking_delta":
                            piece = str(delta.get("thinking") or "")
                            _emit(on_delta, "think", piece)
                        elif dtype == "text_delta":
                            piece = str(delta.get("text") or "")
                            if piece:
                                text_parts.append(piece)
                                _emit(on_delta, "token", piece)
                        elif dtype == "input_json_delta" and index in tool_blocks:
                            tool_blocks[index]["arguments"] += str(delta.get("partial_json") or "")
                    elif kind == "message_delta":
                        if (event.get("delta") or {}).get("stop_reason"):
                            finish_reason = str(event["delta"]["stop_reason"])
                        usage = event.get("usage") or {}
                        if usage.get("output_tokens") is not None:
                            output_tokens = int(usage.get("output_tokens") or 0)
                    elif kind == "message_stop":
                        done_marker = True
                    elif kind == "error":
                        err = event.get("error") or {}
                        if transport.first_deadline is not None:
                            raise _stream_payload_error(config, err or event, recoverable=True)
                        raise LLMError(
                            f"{config.name} 流式错误：{_redact(err.get('message') or event, config.api_key)}"
                        )
        except LLMError:
            raise
        except Exception as exc:
            raise LLMError(
                f"{config.name} 流式请求失败：{type(exc).__name__}: "
                f"{_redact(str(exc), config.api_key)}"
            ) from exc

    if transport.first_deadline is not None and not finish_reason:
        raise _missing_finish_reason(config, done_marker)
    calls = [
        ToolCall(
            id=str(slot["id"]),
            name=str(slot["name"]),
            arguments=_safe_json(slot["arguments"], config.name),
        )
        for _, slot in sorted(tool_blocks.items())
    ]
    return ChatResponse(
        text="".join(text_parts),
        model=model,
        input_tokens=input_tokens,
        output_tokens=output_tokens,
        tool_calls=calls,
        raw={"stream_events": event_count, "protocol": "anthropic",
             "finish_reason": finish_reason},
    )
