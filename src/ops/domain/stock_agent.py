"""独立股票智能体配置。内置天才交易员不使用这些规则或默认提示词。"""
from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


class DiaryRetention(BaseModel):
    model_config = ConfigDict(extra="forbid")
    days: int = Field(default=30, ge=0, le=3650, strict=True)
    max_entries: int = Field(default=2000, ge=0, le=100000, strict=True)
    cleanup_hours: int = Field(default=24, ge=1, le=168, strict=True)

    @field_validator("max_entries")
    @classmethod
    def preserve_recent_context(cls, value: int) -> int:
        if 0 < value < 20:
            raise ValueError("日记条数至少保留20条；0表示不按条数清理")
        return value


class AgentSchedule(BaseModel):
    model_config = ConfigDict(extra="forbid")
    timezone: Literal["Asia/Shanghai"] = "Asia/Shanghai"
    review_time: str = Field(default="20:00", pattern=r"^(1[5-9]|2[0-3]):[0-5]\d$")
    premarket_time: str = Field(default="08:50", pattern=r"^0[6-8]:[0-5]\d$")
    auction_time: Literal["09:25"] = "09:25"
    intraday_minutes: Literal[5, 10, 15, 30] = 5
    intraday_enabled: bool = True


class StockAgentConfig(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True, allow_inf_nan=False)
    name: str = Field(min_length=1, max_length=40)
    kind: Literal["custom", "leader"] = "custom"
    description: str = Field(default="", max_length=240)
    provider: str = Field(default="", max_length=200)
    model: str = Field(default="", max_length=200)
    prompt: str = Field(default="", max_length=100000)
    common_prompt: str = Field(default="", max_length=100000)
    premarket_prompt: str = Field(default="", max_length=100000)
    review_prompt: str = Field(default="", max_length=100000)
    enabled: bool = False
    initial_capital_cents: int = Field(default=20_000_000, ge=10_000, le=100_000_000_000, strict=True)
    strategies: list[str] = Field(default_factory=list, max_length=0)
    daily_selection_limit: int = Field(default=0, ge=0, strict=True, description="0表示不设人工数量上限")
    watch_limit: int = Field(default=0, ge=0, strict=True, description="0表示不设人工数量上限")
    position_limit: int = Field(default=0, ge=0, strict=True, description="0表示不设人工数量上限")
    temporary_position_limit: int = Field(default=0, ge=0, strict=True, description="0表示不设人工数量上限")
    max_position_pct: int = Field(default=100, ge=1, le=100, strict=True)
    timeout_seconds: int = Field(default=900, ge=60, le=7200, strict=True)
    thinking: str = Field(default="", max_length=100)
    parallel_tools: int = Field(default=4, ge=1, le=16, strict=True)
    schedule: AgentSchedule = Field(default_factory=AgentSchedule)
    retention: DiaryRetention = Field(default_factory=DiaryRetention)

    @field_validator("strategies")
    @classmethod
    def unique_strategies(cls, values: list[str]) -> list[str]:
        if any(not value or len(value) > 100 for value in values):
            raise ValueError("战法标识无效")
        return list(dict.fromkeys(values))

    @model_validator(mode="after")
    def validate_policy(self) -> StockAgentConfig:
        if self.enabled and (not self.provider or not self.model):
            raise ValueError("启用前请选择可用的模型供应商和模型")
        if self.temporary_position_limit and self.temporary_position_limit < self.position_limit:
            raise ValueError("临时持仓上限不能低于常态上限")
        return self
