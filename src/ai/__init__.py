"""LLM 接入层。

通用供应商模型：名称 + Base URL + Key + 协议（openai_compatible / anthropic）。
不硬编码任何厂商，新增一家只是加一行配置记录。
"""
from src.ai.client import (
    PROTOCOLS,
    ChatMessage,
    ChatResponse,
    LLMError,
    ProviderConfig,
    chat,
    list_models,
    validate,
)
from src.ai.crypto import CryptoError, MASTER_KEY_ENV, generate_master_key, mask_secret
from src.ai.providers import refresh_models, resolve_config, save_provider

__all__ = [
    "MASTER_KEY_ENV",
    "PROTOCOLS",
    "ChatMessage",
    "ChatResponse",
    "CryptoError",
    "LLMError",
    "ProviderConfig",
    "chat",
    "generate_master_key",
    "list_models",
    "mask_secret",
    "refresh_models",
    "resolve_config",
    "save_provider",
    "validate",
]
