"""统一 LLM 客户端：一套代码同时说 OpenAI 兼容协议与 Anthropic 协议。

刻意**不硬编码任何厂商**。一个供应商 = 名称 + Base URL + Key + 协议，
新增一家只是加一行配置记录，不改代码。这样 DeepSeek、OpenRouter、
Kimi、通义、硅基流动、任何自建中转，以及 Anthropic 官方，全都能接。

实测（服务器容器内直连，无代理）：
- OpenRouter 200 可达，一个 key 接 100+ 模型（含 Claude），OpenAI 兼容
- DeepSeek 401 可达，境内直连最快
- Anthropic 403 / OpenAI 不可达，需要走代理

所以 proxy 是**每个供应商单独配**的，不是全局开关：不能为了连一家境外
模型，把境内的行情接口也绕道出去。
"""
from __future__ import annotations

from dataclasses import dataclass, field
import json
import logging
import re
from typing import Any, Iterator

import httpx2

logger = logging.getLogger(__name__)

PROTOCOLS = ("openai_compatible", "anthropic")

DEFAULT_TIMEOUT = 120.0
#: 拉模型列表用短超时：它只是个便利功能，不该让设置页卡住。
LIST_MODELS_TIMEOUT = 20.0


class LLMError(RuntimeError):
    """调用失败。消息可以给用户看，但绝不包含 Authorization 头的内容。"""


@dataclass
class ToolCall:
    """模型请求调用某个工具。两种协议的差异在这里被抹平。"""

    id: str
    name: str
    arguments: dict[str, Any] = field(default_factory=dict)


@dataclass
class ChatMessage:
    role: str
    content: str
    #: assistant 消息可能带工具调用请求
    tool_calls: list[ToolCall] = field(default_factory=list)
    #: tool 消息要指明回应的是哪一次调用
    tool_call_id: str = ""
    #: 用户附图：data:image/...;base64,...（供多模态模型）
    images: list[str] = field(default_factory=list)


@dataclass
class ChatResponse:
    text: str
    model: str = ""
    input_tokens: int = 0
    output_tokens: int = 0
    tool_calls: list[ToolCall] = field(default_factory=list)
    raw: dict[str, Any] = field(default_factory=dict)

    @property
    def total_tokens(self) -> int:
        return self.input_tokens + self.output_tokens

    @property
    def wants_tools(self) -> bool:
        return bool(self.tool_calls)


@dataclass
class ProviderConfig:
    """发起一次调用需要的全部信息。api_key 只在内存里存在。"""

    name: str
    protocol: str
    base_url: str
    api_key: str
    model: str = ""
    proxy_url: str = ""
    timeout: float = DEFAULT_TIMEOUT
    context_window: int | None = None
    max_output_tokens: int | None = None

    def __post_init__(self) -> None:
        if self.protocol not in PROTOCOLS:
            raise LLMError(f"未知协议：{self.protocol}（可选 {list(PROTOCOLS)}）")
        self.base_url = self.base_url.rstrip("/")
        if self.context_window is not None and self.context_window <= 0:
            self.context_window = None
        if self.max_output_tokens is not None and self.max_output_tokens <= 0:
            self.max_output_tokens = None


def _client(config: ProviderConfig) -> httpx2.Client:
    kwargs: dict[str, Any] = {"timeout": config.timeout}
    if config.proxy_url:
        kwargs["proxy"] = config.proxy_url
    return httpx2.Client(**kwargs)


_BEARER = re.compile(r"(?i)(bearer\s+)[^\s,;\"'}]+")
_SECRET_FIELD = re.compile(
    r"(?ix)(?P<name>[\"']?\b(?:x-api-key|api[_-]?key|authorization|"
    r"(?:access[_-]?)?token|secret|password)\b[\"']?)"
    r"(?P<separator>\s*(?:=|:)\s*)(?P<quote>[\"']?)(?P<value>[^,\s&\"'}]+)(?P=quote)"
)


def redact_text(text: object, *, api_key: str = "") -> str:
    """向 UI 或日志暴露上游文本前移除已知及常见格式的凭据。"""
    value = str(text or "")
    if api_key:
        value = value.replace(api_key, "[REDACTED]")
    value = _BEARER.sub(r"\1[REDACTED]", value)
    value = _SECRET_FIELD.sub(
        lambda match: (
            f"{match.group('name')}{match.group('separator')}"
            f"{match.group('quote')}[REDACTED]{match.group('quote')}"
        ),
        value,
    )
    return value[:600]


def _redact(text: str, api_key: str = "") -> str:
    return redact_text(text, api_key=api_key)


def _raise_for_status(response: Any, config: ProviderConfig) -> dict[str, Any]:
    if response.status_code >= 400:
        detail = _redact(response.text or "", config.api_key)
        hint = ""
        if response.status_code == 401:
            hint = "（API Key 无效或已过期）"
        elif response.status_code == 402:
            hint = "（账户余额不足）"
        elif response.status_code == 429:
            hint = "（触发限流，稍后再试）"
        elif response.status_code == 404:
            hint = "（Base URL 或模型名不对）"
        raise LLMError(f"{config.name} 返回 {response.status_code}{hint}：{detail}")
    try:
        return response.json()
    except Exception as exc:
        raise LLMError(
            f"{config.name} 返回的不是合法 JSON：{_redact(response.text or '', config.api_key)}"
        ) from exc


# --------------------------------------------------------------------------
# 对话
# --------------------------------------------------------------------------

def chat(
    config: ProviderConfig,
    messages: list[ChatMessage],
    *,
    system: str = "",
    max_tokens: int = 4096,
    temperature: float = 0.3,
    tools: list[dict[str, Any]] | None = None,
    thinking: str = "",
) -> ChatResponse:
    """一次非流式对话。两种协议在这里被抹平成同一个返回结构。

    thinking: off/low/medium/high/xhigh/max。同供应商不同次调用可传不同模型与思考程度。
    tools 用各协议自己的 schema 格式（由 McpTool.to_*_schema 生成）。
    """
    if config.protocol == "anthropic":
        return _chat_anthropic(
            config, messages, system, max_tokens, temperature, tools, thinking=thinking
        )
    return _chat_openai(
        config, messages, system, max_tokens, temperature, tools, thinking=thinking
    )


_THINKING_EFFORTS = frozenset({"low", "medium", "high", "xhigh", "max"})


def _normalize_thinking(thinking: str) -> str:
    level = (thinking or "").strip().lower()
    if level in ("", "off", "none", "false", "0"):
        return ""
    if level in _THINKING_EFFORTS:
        return level
    return ""


def _apply_openai_thinking(body: dict[str, Any], thinking: str) -> None:
    level = _normalize_thinking(thinking)
    if not level:
        return
    # OpenAI o 系列 / OpenRouter 推理模型常用字段；不支持的供应商会 4xx，由调用方降级。
    body["reasoning_effort"] = level


def _apply_anthropic_thinking(
    body: dict[str, Any], thinking: str, max_tokens: int
) -> int:
    level = _normalize_thinking(thinking)
    if not level:
        return max_tokens
    budgets = {
        "low": 1024,
        "medium": 4096,
        "high": 10000,
        "xhigh": 16000,
        "max": 32000,
    }
    budget = budgets[level]
    body["thinking"] = {"type": "enabled", "budget_tokens": budget}
    # Anthropic 开启 thinking 时要求 temperature=1
    body["temperature"] = 1
    return max(max_tokens, budget + 1024)


def parse_data_image(url: str) -> tuple[str, str] | None:
    """解析 data:image/...;base64,... → (media_type, raw_base64)。"""
    text = (url or "").strip()
    if not text.lower().startswith("data:image/") or "," not in text:
        return None
    header, _, payload = text.partition(",")
    if ";base64" not in header.lower() or not payload:
        return None
    media = header[5:].split(";", 1)[0].strip().lower()
    if media == "image/jpg":
        media = "image/jpeg"
    if media not in {"image/png", "image/jpeg", "image/webp", "image/gif"}:
        return None
    return media, payload


# 域内旧调用点别名；application 应使用 parse_data_image。
_parse_data_image = parse_data_image


def _openai_content(message: ChatMessage) -> Any:
    if not message.images:
        return message.content
    parts: list[dict[str, Any]] = []
    if message.content:
        parts.append({"type": "text", "text": message.content})
    for url in message.images:
        if _parse_data_image(url):
            parts.append({"type": "image_url", "image_url": {"url": url}})
    return parts if parts else message.content


def _anthropic_content(message: ChatMessage) -> Any:
    if not message.images:
        return message.content
    blocks: list[dict[str, Any]] = []
    if message.content:
        blocks.append({"type": "text", "text": message.content})
    for url in message.images:
        parsed = _parse_data_image(url)
        if not parsed:
            continue
        media, data = parsed
        blocks.append(
            {
                "type": "image",
                "source": {"type": "base64", "media_type": media, "data": data},
            }
        )
    return blocks if blocks else message.content


def _openai_messages(messages: list[ChatMessage], system: str) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    if system:
        out.append({"role": "system", "content": system})
    for message in messages:
        if message.role == "tool":
            out.append(
                {
                    "role": "tool",
                    "tool_call_id": message.tool_call_id,
                    "content": message.content,
                }
            )
        elif message.tool_calls:
            out.append(
                {
                    "role": "assistant",
                    "content": message.content or None,
                    "tool_calls": [
                        {
                            "id": call.id,
                            "type": "function",
                            "function": {
                                "name": call.name,
                                "arguments": json.dumps(call.arguments, ensure_ascii=False),
                            },
                        }
                        for call in message.tool_calls
                    ],
                }
            )
        else:
            out.append({"role": message.role, "content": _openai_content(message)})
    return out


def _chat_openai(
    config: ProviderConfig, messages: list[ChatMessage], system: str,
    max_tokens: int, temperature: float, tools: list[dict[str, Any]] | None = None,
    *, thinking: str = "",
) -> ChatResponse:
    body: dict[str, Any] = {
        "model": config.model,
        "messages": _openai_messages(messages, system),
        "max_tokens": max_tokens,
        "temperature": temperature,
    }
    if tools:
        body["tools"] = tools
        body["tool_choice"] = "auto"
    _apply_openai_thinking(body, thinking)
    with _client(config) as client:
        try:
            response = client.post(
                f"{config.base_url}/chat/completions",
                headers={
                    "Authorization": f"Bearer {config.api_key}",
                    "Content-Type": "application/json",
                },
                json=body,
            )
        except Exception as exc:
            raise LLMError(
                f"{config.name} 请求失败：{type(exc).__name__}: {_redact(str(exc), config.api_key)}"
            ) from exc
    data = _raise_for_status(response, config)

    choices = data.get("choices") or []
    if not choices:
        raise LLMError(f"{config.name} 未返回任何回复内容")
    message = choices[0].get("message") or {}
    usage = data.get("usage") or {}

    calls: list[ToolCall] = []
    for item in message.get("tool_calls") or []:
        function = item.get("function") or {}
        calls.append(
            ToolCall(
                id=str(item.get("id", "")),
                name=str(function.get("name", "")),
                # arguments 是 JSON 字符串；模型偶尔会给出不合法 JSON，
                # 这时降级为空参数并把原文留在日志里，而不是整轮崩掉。
                arguments=_safe_json(function.get("arguments"), config.name),
            )
        )

    return ChatResponse(
        text=message.get("content") or "",
        model=str(data.get("model", config.model)),
        input_tokens=int(usage.get("prompt_tokens", 0) or 0),
        output_tokens=int(usage.get("completion_tokens", 0) or 0),
        tool_calls=calls,
        raw=data,
    )


def _safe_json(raw: Any, provider: str) -> dict[str, Any]:
    if isinstance(raw, dict):
        return raw
    if not raw:
        return {}
    try:
        parsed = json.loads(raw)
        return parsed if isinstance(parsed, dict) else {}
    except json.JSONDecodeError:
        logger.warning("%s 返回的工具参数不是合法 JSON，已按空参数处理", provider)
        return {}


def _anthropic_messages(messages: list[ChatMessage]) -> list[dict[str, Any]]:
    """Anthropic 用 content block 表达工具调用，且 tool_result 属于 user 角色。"""
    out: list[dict[str, Any]] = []
    for message in messages:
        if message.role == "tool":
            out.append(
                {
                    "role": "user",
                    "content": [
                        {
                            "type": "tool_result",
                            "tool_use_id": message.tool_call_id,
                            "content": message.content,
                        }
                    ],
                }
            )
        elif message.tool_calls:
            blocks: list[dict[str, Any]] = []
            if message.content:
                blocks.append({"type": "text", "text": message.content})
            blocks.extend(
                {"type": "tool_use", "id": call.id, "name": call.name, "input": call.arguments}
                for call in message.tool_calls
            )
            out.append({"role": "assistant", "content": blocks})
        else:
            out.append({"role": message.role, "content": _anthropic_content(message)})
    return out


def _chat_anthropic(
    config: ProviderConfig, messages: list[ChatMessage], system: str,
    max_tokens: int, temperature: float, tools: list[dict[str, Any]] | None = None,
    *, thinking: str = "",
) -> ChatResponse:
    body: dict[str, Any] = {
        "model": config.model,
        "max_tokens": max_tokens,
        "temperature": temperature,
        "messages": _anthropic_messages(messages),
    }
    if system:
        body["system"] = system
    if tools:
        body["tools"] = tools
    body["max_tokens"] = _apply_anthropic_thinking(body, thinking, max_tokens)
    with _client(config) as client:
        try:
            response = client.post(
                f"{config.base_url}/messages",
                headers={
                    "x-api-key": config.api_key,
                    "anthropic-version": "2023-06-01",
                    "Content-Type": "application/json",
                },
                json=body,
            )
        except Exception as exc:
            raise LLMError(
                f"{config.name} 请求失败：{type(exc).__name__}: {_redact(str(exc), config.api_key)}"
            ) from exc
    data = _raise_for_status(response, config)

    blocks = data.get("content") or []
    text = "".join(block.get("text", "") for block in blocks if block.get("type") == "text")
    calls = [
        ToolCall(
            id=str(block.get("id", "")),
            name=str(block.get("name", "")),
            arguments=block.get("input") if isinstance(block.get("input"), dict) else {},
        )
        for block in blocks
        if block.get("type") == "tool_use"
    ]
    usage = data.get("usage") or {}
    return ChatResponse(
        text=text,
        model=str(data.get("model", config.model)),
        input_tokens=int(usage.get("input_tokens", 0) or 0),
        output_tokens=int(usage.get("output_tokens", 0) or 0),
        tool_calls=calls,
        raw=data,
    )


# --------------------------------------------------------------------------
# 校验与模型发现
# --------------------------------------------------------------------------

def validate(config: ProviderConfig) -> ChatResponse:
    """发一次最小请求确认 Key 真的能用。

    只在保存时调用一次。不做这一步的话，错误的 Key 要等到第一次定时任务
    在半夜跑失败才被发现。
    """
    probe = ProviderConfig(
        name=config.name,
        protocol=config.protocol,
        base_url=config.base_url,
        api_key=config.api_key,
        model=config.model,
        proxy_url=config.proxy_url,
        timeout=LIST_MODELS_TIMEOUT,
    )
    return chat(probe, [ChatMessage(role="user", content="hi")], max_tokens=1, temperature=0.0)


def list_models(config: ProviderConfig) -> list[dict[str, Any]]:
    """拉可用模型目录条目（至少含 id）。

    拉不到不算错误——Anthropic 官方就没有公开的列表接口。返回空列表让
    调用方降级为手填，而不是让整个保存流程失败。
    若上游带 ``context_length`` / ``max_model_len`` 等字段则写入 context_window。
    """
    if config.protocol != "openai_compatible":
        return []
    with _client(config) as client:
        try:
            response = client.get(
                f"{config.base_url}/models",
                headers={"Authorization": f"Bearer {config.api_key}"},
                timeout=LIST_MODELS_TIMEOUT,
            )
        except Exception as exc:
            logger.info("拉取 %s 模型列表失败：%s", config.name, _redact(str(exc), config.api_key))
            return []
    if response.status_code >= 400:
        logger.info("拉取 %s 模型列表返回 %s", config.name, response.status_code)
        return []
    try:
        data = response.json()
    except Exception:
        return []
    items = data.get("data") if isinstance(data, dict) else data
    if not isinstance(items, list):
        return []
    out: list[dict[str, Any]] = []
    seen: set[str] = set()
    for item in items:
        if not isinstance(item, dict) or not item.get("id"):
            continue
        mid = str(item["id"]).strip()
        if not mid or mid in seen:
            continue
        seen.add(mid)
        context = (
            item.get("context_length")
            or item.get("context_window")
            or item.get("max_model_len")
            or item.get("max_input_tokens")
        )
        max_out = item.get("max_output_tokens") or item.get("max_tokens")
        name = item.get("name") or item.get("display_name") or ""
        entry: dict[str, Any] = {"id": mid, "source": "discovered"}
        if name:
            entry["name"] = str(name)
        try:
            if context is not None and int(context) > 0:
                entry["context_window"] = int(context)
        except (TypeError, ValueError):
            pass
        try:
            if max_out is not None and int(max_out) > 0:
                entry["max_output_tokens"] = int(max_out)
        except (TypeError, ValueError):
            pass
        out.append(entry)
    return sorted(out, key=lambda row: str(row["id"]))
