"""悟道 MCP ``kline`` 返回体 → 标准日线 DataFrame。

供行情适配器与战法监测共用，避免各自重写一遍解析。
"""
from __future__ import annotations

import json
import logging
from math import isfinite
from typing import Any

import pandas as pd

logger = logging.getLogger(__name__)

FRAME_COLUMNS = ("date", "open", "high", "low", "close", "volume", "amount")
_PRICE_FIELDS = ("open", "high", "low", "close")


def _structured_of(payload: dict[str, Any]) -> dict[str, Any] | None:
    structured = payload.get("structured")
    if isinstance(structured, dict):
        return structured
    try:
        parsed = json.loads(str(payload.get("text") or "").strip())
    except json.JSONDecodeError:
        return None
    return parsed if isinstance(parsed, dict) else None


def _rows_of(structured: dict[str, Any]) -> list[Any]:
    rows = structured.get("rows") or structured.get("items") or []
    if isinstance(rows, list) and rows:
        return rows
    # 多标的批量返回：batch.items[0].rows
    batch = structured.get("batch")
    if isinstance(batch, dict):
        items = batch.get("items") or []
        if isinstance(items, list) and items and isinstance(items[0], dict):
            nested = items[0].get("rows") or items[0].get("kline") or []
            if isinstance(nested, list):
                return nested
    return []


def _price(value: Any) -> float | None:
    """价格缺失 / 改名 / 不可解析时返回 None。

    这里**不能**退回 0：补 0 会凭空造出一根 0 元 K 线，且能通过列契约校验，
    等于把「没取到」伪装成「当天就是这个价」。
    """
    if value is None or isinstance(value, bool):
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if isfinite(number) and number > 0 else None


def _size(*values: Any) -> float:
    """成交量/额：取第一个可解析值；真停牌就是 0，缺列也按 0 但不影响价格可信度。"""
    for value in values:
        if isinstance(value, bool):
            continue
        try:
            number = float(value)
        except (TypeError, ValueError):
            continue
        if isfinite(number):
            return number
    return 0.0


def _frame_of(rows: list[Any]) -> pd.DataFrame:
    records: list[dict[str, Any]] = []
    dropped = 0
    for row in rows:
        if not isinstance(row, dict):
            continue
        date = str(row.get("trade_date") or row.get("date") or "")[:10]
        if not date:
            continue
        prices = {name: _price(row.get(name)) for name in _PRICE_FIELDS}
        if any(value is None for value in prices.values()):
            dropped += 1
            continue
        records.append(
            {
                "date": date,
                **prices,
                "volume": _size(row.get("volume"), row.get("vol")),
                "amount": _size(row.get("amount"), row.get("turnover")),
            }
        )
    if dropped:
        logger.warning("悟道 kline 有 %s 行缺少有效 OHLC，已丢弃（不补 0）", dropped)
    if not records:
        return pd.DataFrame()
    return pd.DataFrame(records).sort_values("date").reset_index(drop=True)


def kline_payload_to_frame(payload: dict[str, Any]) -> pd.DataFrame:
    """解析失败或无数据时返回空 DataFrame，由调用方决定是否报错。"""
    structured = _structured_of(payload)
    if structured is None:
        return pd.DataFrame()
    return _frame_of(_rows_of(structured))


def _batch_code_of(item: dict[str, Any]) -> str:
    stock = item.get("stock") if isinstance(item.get("stock"), dict) else {}
    raw = item.get("code") or item.get("stockCode") or stock.get("code") or ""
    digits = "".join(char for char in str(raw) if char.isdigit())
    return digits[-6:] if len(digits) >= 6 else ""


def kline_payload_frames(payload: dict[str, Any]) -> dict[str, pd.DataFrame]:
    """批量 ``kline`` 返回体 → ``{code: 日线 DataFrame}``。

    一次多标的的 ``codes`` 查询只回一个 payload；单标的调用没有 batch 段，
    调用方仍需要按代码取回自己的那一份。
    """
    structured = _structured_of(payload)
    if structured is None:
        return {}
    batch = structured.get("batch")
    items = batch.get("items") if isinstance(batch, dict) else structured.get("items")
    frames: dict[str, pd.DataFrame] = {}
    if isinstance(items, list):
        for item in items:
            if not isinstance(item, dict):
                continue
            code = _batch_code_of(item)
            rows = item.get("rows") or item.get("kline") or []
            if not code or not isinstance(rows, list):
                continue
            frame = _frame_of(rows)
            if not frame.empty:
                frames[code] = frame
    if frames:
        return frames
    single = kline_payload_to_frame(payload)
    if single.empty:
        return {}
    code = _batch_code_of(structured) or _batch_code_of(
        structured.get("stock") if isinstance(structured.get("stock"), dict) else {}
    )
    return {code: single} if code else {}
