"""账本共享类型、校验与序列化助手。"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime
import json
from typing import Any

SCHEMA_VERSION = 5


class PalaceError(ValueError):
    """用户输入或账本状态不满足约束时抛出。"""


@dataclass(frozen=True, slots=True)
class Position:
    code: str
    name: str
    shares: int
    cost: float
    updated_on: str
    note: str

    @property
    def cost_value(self) -> float:
        return round(self.shares * self.cost, 2)


def normalize_code(value: str) -> str:
    """规范为六位 A 股代码，避免不同写法产生两份账本。"""
    digits = "".join(char for char in str(value) if char.isdigit())
    if len(digits) > 6:
        digits = digits[-6:]
    if len(digits) != 6:
        raise PalaceError("股票代码必须为 6 位数字")
    return digits


def normalize_date(value: str | None) -> str:
    """校验日期并统一输出 ISO 日期；未传时使用当天。"""
    if not value:
        return date.today().isoformat()
    try:
        return date.fromisoformat(value).isoformat()
    except ValueError as exc:
        raise PalaceError("日期必须为 YYYY-MM-DD") from exc


def _now() -> str:
    return datetime.now().astimezone().isoformat(timespec="seconds")


def _dumps(value: Any) -> str:
    return json.dumps(value or {}, ensure_ascii=False, sort_keys=True)


def _normalize_decision(value: str) -> str:
    """把历史英文裁决口径归一成中文，界面只展示中文。"""
    mapping = {
        "select": "精选",
        "selected": "精选",
        "core": "精选",
        "buy": "买入",
        "reject": "落选",
        "rejected": "落选",
        "drop": "落选",
        "exclude": "落选",
        "剔除": "落选",
        "watch": "观察",
        "hold": "观察",
        "hold_cash": "空仓观望",
        "partial": "部分参与",
    }
    stripped = value.strip()
    key = stripped.lower()
    if key in mapping:
        return mapping[key]
    if stripped in mapping:
        return mapping[stripped]
    return stripped


def _loads(value: str | None) -> dict[str, Any]:
    if not value:
        return {}
    try:
        result = json.loads(value)
    except json.JSONDecodeError:
        return {}
    return result if isinstance(result, dict) else {}


# 进程内已完成 schema 初始化的库路径，避免每个请求都写 meta 表抢锁。
_SCHEMA_READY: set[str] = set()
