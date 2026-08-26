"""密钥展示脱敏（末四位）。本机 LLM/MCP Key 明文存储，不再做主密钥加密。"""

from __future__ import annotations


def mask_secret(plaintext: str) -> str:
    """给 UI 展示用的末四位。永远不回显完整密钥。"""
    tail = plaintext[-4:] if len(plaintext) >= 4 else plaintext
    return f"****{tail}"
