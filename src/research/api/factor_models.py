"""Strict HTTP contracts for fixed, research-only factor experiments."""
from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator


class Pth252FactorSplitRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    train_start: str = Field(pattern=r"^\d{4}-\d{2}-\d{2}$")
    train_end: str = Field(pattern=r"^\d{4}-\d{2}-\d{2}$")
    oos_start: str = Field(pattern=r"^\d{4}-\d{2}-\d{2}$")
    oos_end: str = Field(pattern=r"^\d{4}-\d{2}-\d{2}$")


class Pth252BacktestConfigRequest(BaseModel):
    """PTH252 execution costs are committed, not user-tunable through the UI."""

    model_config = ConfigDict(extra="forbid")

    hold_days: Literal[20] = 20
    stop_loss_pct: None = None
    take_profit_pct: None = None
    commission_bps: Literal[3.0] = 3.0
    stamp_duty_bps: Literal[10.0] = 10.0
    slippage_bps: Literal[5.0] = 5.0
    allow_limit_up_entry: Literal[False] = False
    benchmark: Literal["000300"] = "000300"


class Pth252FactorJobRequest(BaseModel):
    """The pre-registered PTH252 candidate, with no production tuning fields."""

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    factor_id: Literal["pth252"] = "pth252"
    start: str = Field(pattern=r"^\d{4}-\d{2}-\d{2}$")
    end: str = Field(pattern=r"^\d{4}-\d{2}-\d{2}$")
    split: Pth252FactorSplitRequest
    top_quantile: Literal[0.9] = 0.9
    rebalance_every: Literal[20] = 20
    backtest_config: Pth252BacktestConfigRequest = Field(
        default_factory=Pth252BacktestConfigRequest
    )
    initial_capital: Literal[200000] = 200000
    max_positions: Literal[20] = 20
    strict_pit: Literal[True] = True
    historical_universe_id: str = Field(min_length=1, max_length=128)

    @model_validator(mode="after")
    def validate_windows(self) -> Pth252FactorJobRequest:
        split = self.split
        if not (
            self.start <= split.train_start <= split.train_end
            < split.oos_start <= split.oos_end <= self.end
        ):
            raise ValueError("train/OOS 必须递增、不重叠，并包含在样本总区间内")
        return self


__all__ = [
    "Pth252BacktestConfigRequest",
    "Pth252FactorJobRequest",
    "Pth252FactorSplitRequest",
]
