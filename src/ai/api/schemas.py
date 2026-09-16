"""AI 上下文的 HTTP 请求模型：LLM 供应商与 AI 判断留痕。

从组合根 `app/legacy/quant_common.py` 搬入。字段名对外是契约，不得改名。
"""
from __future__ import annotations

from typing import Literal

from pydantic import Field

from src.shared.api_models import QuantModel


class ProviderCreate(QuantModel):
    name: str = Field(min_length=1, max_length=64)
    base_url: str = Field(min_length=8, max_length=300)
    api_key: str | None = Field(default=None, max_length=500)
    protocol: Literal["openai_compatible", "anthropic"] = "openai_compatible"
    model: str = Field(default="", max_length=120)
    proxy_url: str = Field(default="", max_length=300)
    note: str = Field(default="", max_length=500)
    validate_key: bool = False
    discover_models: bool = False
    is_default: bool = False


class ProviderModelEntry(QuantModel):
    id: str = Field(min_length=1, max_length=200)
    name: str = Field(default="", max_length=200)
    enabled: bool = True
    context_window: int | None = Field(default=None, ge=1, le=10_000_000)
    max_output_tokens: int | None = Field(default=None, ge=1, le=2_000_000)
    source: Literal["discovered", "manual"] = "manual"


class ProviderModelsUpdate(QuantModel):
    models: list[ProviderModelEntry] = Field(default_factory=list)
    default_model: str | None = Field(default=None, max_length=200)


class AiJudgmentCreate(QuantModel):
    occurred_on: str | None = Field(default=None, pattern=r"^\d{4}-\d{2}-\d{2}$")
    strategy_tag: str = Field(min_length=1, max_length=64)
    decision: Literal["buy", "hold_cash", "partial"]
    top_codes: list[str] = Field(default_factory=list)
    reason: str = Field(default="", max_length=2000)
    provider: str = Field(default="", max_length=64)
    model: str = Field(default="", max_length=120)
    token_used: int = Field(default=0, ge=0)
    source: str = Field(default="ai", max_length=32)


#: 503 的两种成因在前端要给完全不同的引导（装依赖 vs 稍后重试），但状态码一样。
#: 只有「缺依赖」带这个响应头，SQLite 繁忙那条（见 app/main.py 的异常处理器）不带。
