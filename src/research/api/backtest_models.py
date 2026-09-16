"""研究回测 HTTP 请求契约。"""
from __future__ import annotations

from datetime import date
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator


class BacktestConfigRequest(BaseModel):
    """审计回测允许固定的交易成本和持仓配置，不接受任意引擎选项。"""

    model_config = ConfigDict(extra="forbid")

    hold_days: int = Field(default=3, ge=1, le=60)
    stop_loss_pct: float | None = Field(default=-6.0, ge=-100, le=0)
    take_profit_pct: float | None = Field(default=None, ge=0, le=10_000)
    commission_bps: float = Field(default=3.0, ge=0, le=1_000)
    stamp_duty_bps: float = Field(default=10.0, ge=0, le=1_000)
    slippage_bps: float = Field(default=5.0, ge=0, le=1_000)
    allow_limit_up_entry: bool = False
    benchmark: str | None = Field(default="000300", max_length=16)
    strict_limit_prices: bool = False
    economic_returns: bool = False
    valuation_end: str | None = Field(default=None, pattern=r"^\d{4}-\d{2}-\d{2}$")
    signal_dataset: str | None = Field(default=None, pattern=r"^[A-Za-z0-9][A-Za-z0-9_-]{0,95}$")

    @model_validator(mode="after")
    def validate_valuation_end(self) -> BacktestConfigRequest:
        if self.valuation_end is not None:
            _parse_date(self.valuation_end, "valuation_end")
        return self


class TrainOOSSplitRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    train_start: str = Field(pattern=r"^\d{4}-\d{2}-\d{2}$")
    train_end: str = Field(pattern=r"^\d{4}-\d{2}-\d{2}$")
    oos_start: str = Field(pattern=r"^\d{4}-\d{2}-\d{2}$")
    oos_end: str = Field(pattern=r"^\d{4}-\d{2}-\d{2}$")

    @model_validator(mode="after")
    def validate_order(self) -> TrainOOSSplitRequest:
        train_start = _parse_date(self.train_start, "train_start")
        train_end = _parse_date(self.train_end, "train_end")
        oos_start = _parse_date(self.oos_start, "oos_start")
        oos_end = _parse_date(self.oos_end, "oos_end")
        if train_start > train_end:
            raise ValueError("训练结束日不能早于训练开始日")
        if oos_start > oos_end:
            raise ValueError("OOS 结束日不能早于 OOS 开始日")
        if train_end >= oos_start:
            raise ValueError("OOS 必须严格晚于训练区间，不能重叠或倒序")
        return self


class ResearchBacktestRequest(BaseModel):
    """可审计回测的固定输入；一次提交对应一张不可变 run card。"""

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    strategy: str = Field(min_length=1, max_length=128)
    start: str = Field(pattern=r"^\d{4}-\d{2}-\d{2}$")
    end: str = Field(pattern=r"^\d{4}-\d{2}-\d{2}$")
    params: dict[str, Any] = Field(default_factory=dict)
    backtest_config: BacktestConfigRequest = Field(default_factory=BacktestConfigRequest)
    universe: dict[str, Any] | None = None
    split: TrainOOSSplitRequest | None = None
    hypothesis_id: str | None = Field(default=None, min_length=3, max_length=81)
    hypothesis_revision: int | None = Field(default=None, ge=1)
    initial_capital: float = Field(default=200_000.0, gt=0, le=100_000_000)
    max_positions: int = Field(default=2, ge=1, le=100)
    lot_size: int = Field(default=100, ge=1, le=100_000)
    account_model: Literal["cost_until_exit", "daily_close"] = "cost_until_exit"
    seed: int = Field(default=0, ge=0, le=2_147_483_647)
    random_repeats: int = Field(default=500, ge=1, le=2_000)
    bootstrap_iterations: int = Field(default=500, ge=1, le=2_000)
    monte_carlo_iterations: int = Field(default=500, ge=1, le=2_000)
    historical_universe_id: str | None = Field(default=None, min_length=1, max_length=128)
    strict_pit: bool = False

    @model_validator(mode="after")
    def validate_research_ranges(self) -> ResearchBacktestRequest:
        start = _parse_date(self.start, "start")
        end = _parse_date(self.end, "end")
        if start > end:
            raise ValueError("回测结束日不能早于开始日")
        if self.strict_pit and not self.historical_universe_id:
            raise ValueError("strict_pit=true 时必须提供 historical_universe_id")
        if self.split is None:
            raise ValueError("研究回测必须提供完整且不重叠的训练/OOS 区间")
        train_start = _parse_date(self.split.train_start, "split.train_start")
        train_end = _parse_date(self.split.train_end, "split.train_end")
        oos_start = _parse_date(self.split.oos_start, "split.oos_start")
        oos_end = _parse_date(self.split.oos_end, "split.oos_end")
        if train_start < start or train_end > end or oos_start < start or oos_end > end:
            raise ValueError("训练区间和 OOS 区间必须完全位于回测总区间内")
        return self


def _parse_date(value: str, field: str) -> date:
    try:
        return date.fromisoformat(value)
    except ValueError as exc:
        raise ValueError(f"{field} 必须是有效 ISO 日期") from exc


class ResearchBacktestPublicationRequest(BaseModel):
    """人工发布必须绑定当前 artifact manifest 和可追责签署信息。"""

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    manifest_sha256: str = Field(pattern=r"^[A-Fa-f0-9]{64}$")
    reviewer: str = Field(min_length=1, max_length=128)
    reason: str = Field(min_length=1, max_length=2_000)


class ResearchBacktestRejectionRequest(ResearchBacktestPublicationRequest):
    """人工否决也必须绑定当前 artifact manifest。"""


__all__ = [
    "BacktestConfigRequest",
    "ResearchBacktestPublicationRequest",
    "ResearchBacktestRejectionRequest",
    "ResearchBacktestRequest",
    "TrainOOSSplitRequest",
]
