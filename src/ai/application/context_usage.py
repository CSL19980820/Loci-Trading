"""助手上下文 token 估算（CJK 友好，与前端 assistantContextUsage 同口径）。"""
from __future__ import annotations


def estimate_tokens(text: str | None) -> int:
    """粗估：汉字≈1 token，其余≈4 字符/token。用于用量条，非计费真相。"""
    if not text:
        return 0
    cjk = 0
    other = 0
    for char in text:
        code = ord(char)
        if (
            0x4E00 <= code <= 0x9FFF
            or 0x3400 <= code <= 0x4DBF
            or 0xF900 <= code <= 0xFAFF
            or 0x3000 <= code <= 0x303F
        ):
            cjk += 1
        else:
            other += 1
    total = cjk + other
    if total <= 0:
        return 0
    return max(1, cjk + (other + 3) // 4)
