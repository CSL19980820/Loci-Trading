"""盯盘 LLM 决策：调用、输出解析、决策留痕。

从 `paper_quant_monitor` 拆出（该文件已贴 600 行上限，只允许拆出不允许再堆）。
**调用点仍留在 monitor**：那边 `mock.patch("...paper_quant_monitor._call_monitor_llm")`
的测试依赖模块全局解析，把调用一起搬过来会让 patch 失效。
"""
from __future__ import annotations

import json
import logging
import re
from typing import Any

from src.ops.application.paper_exec import PaperOrder

logger = logging.getLogger(__name__)


class MonitorLLMUnusableError(Exception):
    """模型失语：空文本或非 JSON，禁止回退规则替 AI 下单。"""

    def __init__(self, message: str, *, snippet: str = "") -> None:
        super().__init__(message)
        self.snippet = snippet


def _parse_orders_from_text(text: str) -> tuple[list[PaperOrder], str]:
    """从模型输出中提取 JSON orders；解析失败抛 MonitorLLMUnusableError。"""
    notes = ""
    payload: dict[str, Any] | None = None
    raw = (text or "").strip()
    try:
        payload = json.loads(raw)
    except json.JSONDecodeError:
        match = re.search(r"\{[\s\S]*\}", raw)
        if match:
            try:
                payload = json.loads(match.group(0))
            except json.JSONDecodeError:
                payload = None
    if not isinstance(payload, dict):
        raise MonitorLLMUnusableError(
            "模型未产出可执行 JSON 输出",
            snippet=raw[:500],
        )
    notes = str(payload.get("notes") or "")
    orders_raw = payload.get("orders") or payload.get("actions") or []
    orders: list[PaperOrder] = []
    if isinstance(orders_raw, list):
        for item in orders_raw:
            if not isinstance(item, dict):
                continue
            action = str(item.get("action") or item.get("side") or "hold").lower()
            if action in {"buy"}:
                action = "add"
            if action in {"sell"}:
                action = "reduce"
            layers = item.get("layers")
            if layers is None and action in {"open", "add", "buy_dip"}:
                layers = 0.5
            orders.append(
                PaperOrder(
                    code=str(item.get("code") or ""),
                    action=action,
                    layers=float(layers or 0),
                    reason=str(item.get("reason") or ""),
                    name=str(item.get("name") or ""),
                    # 价格一律不从模型输出解析：execute_orders 会用实时快照回填，
                    # 模型即使编了价格也进不来。
                    decided_by="ai",
                )
            )
    return orders, notes


def _call_monitor_llm(
    *,
    store: Any,
    model: str,
    thinking: str,
    system: str,
    user: str,
    timeout_seconds: float,
) -> str:
    from src.ai import ChatMessage, chat_text_with_thinking_fallback, resolve_config

    config = resolve_config(store, model=model or "", timeout=timeout_seconds)
    sys = system
    if thinking and thinking != "off":
        sys += f"\n思考档位偏好：{thinking}。输出必须是合法 JSON。"
    text = chat_text_with_thinking_fallback(
        config,
        [ChatMessage(role="user", content=user)],
        system=sys,
        thinking=thinking or "",
        max_tokens=4096,
        temperature=0.2,
    )
    if text:
        return text
    raise MonitorLLMUnusableError("模型返回空文本（失语）")


def record_ai_decision(store: Any, payload: dict[str, Any]) -> str:
    """写一条决策留痕。**任何失败都不得影响交易**——审计坏了顶多丢复盘能力。"""
    try:
        return str(store.insert_ai_decision(payload))
    except Exception as exc:  # noqa: BLE001
        logger.warning("record_ai_decision failed: %s", exc)
        return ""


__all__ = [
    "MonitorLLMUnusableError",
    "_call_monitor_llm",
    "_parse_orders_from_text",
    "record_ai_decision",
]
