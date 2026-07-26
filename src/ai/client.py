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
class ChatMessage:
    role: str
    content: str


@dataclass
class ChatResponse:
    text: str
    model: str = ""
    input_tokens: int = 0
    output_tokens: int = 0
    raw: dict[str, Any] = field(default_factory=dict)

    @property
    def total_tokens(self) -> int:
        return self.input_tokens + self.output_tokens


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

    def __post_init__(self) -> None:
        if self.protocol not in PROTOCOLS:
            raise LLMError(f"未知协议：{self.protocol}（可选 {list(PROTOCOLS)}）")
        self.base_url = self.base_url.rstrip("/")


def _client(config: ProviderConfig) -> httpx2.Client:
    kwargs: dict[str, Any] = {"timeout": config.timeout}
    if config.proxy_url:
        kwargs["proxy"] = config.proxy_url
    return httpx2.Client(**kwargs)


def _redact(text: str) -> str:
    """确保错误信息里不会漏出密钥。上游偶尔会把请求头回显在报错里。"""
    return text.replace("Bearer ", "Bearer ***")[:600]


def _raise_for_status(response: Any, provider: str) -> dict[str, Any]:
    if response.status_code >= 400:
        detail = _redact(response.text or "")
        hint = ""
        if response.status_code == 401:
            hint = "（API Key 无效或已过期）"
        elif response.status_code == 402:
            hint = "（账户余额不足）"
        elif response.status_code == 429:
            hint = "（触发限流，稍后再试）"
        elif response.status_code == 404:
            hint = "（Base URL 或模型名不对）"
        raise LLMError(f"{provider} 返回 {response.status_code}{hint}：{detail}")
    try:
        return response.json()
    except Exception as exc:
        raise LLMError(f"{provider} 返回的不是合法 JSON：{_redact(response.text or '')}") from exc


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
) -> ChatResponse:
    """一次非流式对话。两种协议在这里被抹平成同一个返回结构。"""
    if config.protocol == "anthropic":
        return _chat_anthropic(config, messages, system, max_tokens, temperature)
    return _chat_openai(config, messages, system, max_tokens, temperature)


def _chat_openai(
    config: ProviderConfig, messages: list[ChatMessage], system: str,
    max_tokens: int, temperature: float,
) -> ChatResponse:
    payload_messages = ([{"role": "system", "content": system}] if system else []) + [
        {"role": message.role, "content": message.content} for message in messages
    ]
    body = {
        "model": config.model,
        "messages": payload_messages,
        "max_tokens": max_tokens,
        "temperature": temperature,
    }
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
            raise LLMError(f"{config.name} 请求失败：{type(exc).__name__}: {exc}") from exc
    data = _raise_for_status(response, config.name)

    choices = data.get("choices") or []
    if not choices:
        raise LLMError(f"{config.name} 未返回任何回复内容")
    text = (choices[0].get("message") or {}).get("content") or ""
    usage = data.get("usage") or {}
    return ChatResponse(
        text=text,
        model=str(data.get("model", config.model)),
        input_tokens=int(usage.get("prompt_tokens", 0) or 0),
        output_tokens=int(usage.get("completion_tokens", 0) or 0),
        raw=data,
    )


def _chat_anthropic(
    config: ProviderConfig, messages: list[ChatMessage], system: str,
    max_tokens: int, temperature: float,
) -> ChatResponse:
    body: dict[str, Any] = {
        "model": config.model,
        "max_tokens": max_tokens,
        "temperature": temperature,
        "messages": [
            {"role": message.role, "content": message.content} for message in messages
        ],
    }
    if system:
        body["system"] = system
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
            raise LLMError(f"{config.name} 请求失败：{type(exc).__name__}: {exc}") from exc
    data = _raise_for_status(response, config.name)

    blocks = data.get("content") or []
    text = "".join(block.get("text", "") for block in blocks if block.get("type") == "text")
    usage = data.get("usage") or {}
    return ChatResponse(
        text=text,
        model=str(data.get("model", config.model)),
        input_tokens=int(usage.get("input_tokens", 0) or 0),
        output_tokens=int(usage.get("output_tokens", 0) or 0),
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


def list_models(config: ProviderConfig) -> list[str]:
    """拉可用模型列表。

    拉不到不算错误——Anthropic 官方就没有公开的列表接口。返回空列表让
    调用方降级为手填，而不是让整个保存流程失败。
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
            logger.info("拉取 %s 模型列表失败：%s", config.name, exc)
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
    models = [
        str(item.get("id"))
        for item in items
        if isinstance(item, dict) and item.get("id")
    ]
    return sorted(set(models))
