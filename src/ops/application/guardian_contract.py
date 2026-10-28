"""Validation of structured decisions before execution."""
from __future__ import annotations

from datetime import datetime
from decimal import Decimal
import math
from typing import Any, Literal
from zoneinfo import ZoneInfo

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

SHANGHAI = ZoneInfo("Asia/Shanghai")


class ExecutionTerms(BaseModel):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)
    kind: Literal["market", "limit"]
    valid_until: str = Field(description="ISO timestamp with explicit timezone (+08:00); intent expiry")
    min_price: float | None = Field(default=None, gt=0)
    max_price: float | None = Field(default=None, gt=0)
    reference_price: float | None = Field(default=None, gt=0,
        description="固定的执行参考价；市价意图未提供时由程序绑定首次有效执行报价，不随刷新上移")

    @field_validator("min_price", "max_price", "reference_price", mode="before")
    @classmethod
    def real_price(cls, value: Any) -> Any:
        if isinstance(value, bool):
            raise ValueError("Price cannot be a boolean")
        return value

    @field_validator("valid_until")
    @classmethod
    def aware_expiry(cls, value: str) -> str:
        stamp = datetime.fromisoformat(value)
        if stamp.tzinfo is None or stamp.utcoffset() is None:
            # 只交易A股、全程北京时间，输入的execution_deadline也是+08:00：漏写时区没有歧义，
            # 按北京时间解释，不再因此让整份决策作废。含时区的输入保持原样。
            stamp = stamp.replace(tzinfo=SHANGHAI)
        return stamp.isoformat()

    @model_validator(mode="after")
    def valid_range(self) -> ExecutionTerms:
        if self.kind == "limit" and self.min_price is None and self.max_price is None:
            raise ValueError("条件成交至少给出一个价格边界")
        if self.kind == "market" and (self.min_price is not None or self.max_price is not None):
            raise ValueError("有价格条件时使用limit；market表示明确接受本轮核验后的市场报价")
        if self.min_price is not None and self.max_price is not None and self.min_price > self.max_price:
            raise ValueError("成交价格下限不能大于上限")
        return self


# 兼容已有引用；通用操作只有一份SKILL正文，实际入口逐轮加载并记录指纹。
from src.ops.application.trading_operations_skill import load_trading_operations_skill

EXECUTION_RULES = load_trading_operations_skill(paper=False)[0]
GUARDIAN_EXECUTION_RULES = load_trading_operations_skill(paper=True)[0]


EXECUTION_TOLERANCE = Decimal("0.02")


def execution_bounds(terms: ExecutionTerms) -> tuple[Decimal | None, Decimal | None]:
    """用户授权的2%容差；始终从原始边界/参考价计算，禁止重复扩张。"""
    lower = Decimal(str(terms.min_price)) * (1 - EXECUTION_TOLERANCE) if terms.min_price is not None else None
    upper = Decimal(str(terms.max_price)) * (1 + EXECUTION_TOLERANCE) if terms.max_price is not None else None
    if terms.reference_price is not None:
        reference = Decimal(str(terms.reference_price))
        floor, ceiling = reference * (1 - EXECUTION_TOLERANCE), reference * (1 + EXECUTION_TOLERANCE)
        lower = max(lower, floor) if lower is not None else floor
        upper = min(upper, ceiling) if upper is not None else ceiling
    return lower, upper


def execution_cage(terms: ExecutionTerms) -> dict[str, Any]:
    lower, upper = execution_bounds(terms)
    return {"policy_version": 2, "tolerance_pct": 2,
            "reference_price": terms.reference_price,
            "effective_min_price": float(lower) if lower is not None else None,
            "effective_max_price": float(upper) if upper is not None else None}


def execution_error(terms: ExecutionTerms | None, price: float, now: datetime, *, required: bool) -> tuple[str, str]:
    if terms is None:
        return ("missing_execution", "买卖意图缺少明确价格授权与失效时间execution") if required else ("", "")
    if isinstance(price, bool) or not isinstance(price, (int, float)) or not math.isfinite(price) or price <= 0:
        return "price_condition", "成交价格必须是有限正数"
    if now >= datetime.fromisoformat(terms.valid_until):
        return "intent_expired", "交易意图已过有效期，须重新研判"
    lower, upper = execution_bounds(terms)
    actual = Decimal(str(price))
    if lower is not None and actual < lower:
        return "price_condition", f"最新报价{price:g}低于2%执行容差下沿{lower}，本轮未成交"
    if upper is not None and actual > upper:
        return "price_condition", f"最新报价{price:g}高于2%执行容差上沿{upper}，本轮未成交"
    return "", ""


def completion_error(result: Any, label: str = "模型") -> str:
    if result.stopped_reason != "completed":
        return f"{label}未完成：{result.stopped_reason}"
    reason = getattr(result, "finish_reason", "") or ""
    if reason in {"length", "max_tokens"}:
        return f"{label}输出被截断：{reason}，不能将片段作为完整决策"
    if reason not in {"stop", "end_turn"}:
        return f"{label}未正常结束：{reason}"
    return ""


def rejection_code(reason: str) -> str:
    for code, words in (
        ("cash", ("现金不足",)),
        ("t_plus_one", ("T+1",)),
        ("position_limit", ("持仓上限", "收盘上限")),
        ("quantity", ("股数", "零股", "整数倍", "不足")),
    ):
        if any(word in reason for word in words):
            return code
    return "account_rule"
