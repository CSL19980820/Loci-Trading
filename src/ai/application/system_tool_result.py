"""SystemToolBus 与各工具子模块共用的 ToolResult 构造。"""
from __future__ import annotations

import json
from typing import Any

ToolResult = dict[str, Any]

MAX_TOOL_TEXT_CHARS = 12000


def ok(data: Any) -> ToolResult:
    """序列化工具成功结果；正文截断避免撑爆模型上下文。

    截断必须显式告知：模型只读 ``text``，一段被砍掉半行的 JSON 如果不标注，
    它会当成完整结果去数行、去下结论。
    """
    body = json.dumps(data, ensure_ascii=False, default=str)
    truncated = len(body) > MAX_TOOL_TEXT_CHARS
    if truncated:
        body = (
            f"{body[:MAX_TOOL_TEXT_CHARS]}\n"
            f"…（结果过长已截断，原始长度 {len(body)} 字符；"
            "以上不是全量，请缩小范围后重查，不要按此计数或求和）"
        )
    return {
        "text": body,
        "structured": data,
        "is_error": False,
        "truncated": truncated,
    }
