"""社区 HTTP 写入请求模型。全部 ``extra="forbid"``：拼错字段要报错，不能静默丢。"""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field


class WriteModel(BaseModel):
    """社区写入的公共约束：只接受声明过的字段，字符串自动去空白。"""

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)


class BacktestEvidence(WriteModel):
    """上架必须附的回测证据。

    ``model_config`` 放开 extra：回测结果字段还在演进，这里只卡清单要用的那几项，
    其余原样冻进版本 manifest（多存无害，少存就没法解释「当时凭什么给上架」）。
    """

    model_config = ConfigDict(extra="allow", str_strip_whitespace=True)

    trades: int = Field(default=0, ge=0)
    start: str = ""
    end: str = ""
    commission_bps: float | None = None
    stamp_duty_bps: float | None = None
    slippage_bps: float | None = None


class PublishInput(WriteModel):
    title: str = Field(min_length=1, max_length=80)
    summary: str = Field(min_length=1, max_length=500)
    kind: Literal["screen", "timing", "portfolio", "factor", "other"] = "screen"
    entry_timing: Literal["open", "close", "next_open", "next_dip"]
    slug: str = Field(default="", max_length=60)
    visibility: Literal["public", "unlisted", "private"] = "public"
    tags: list[str] = Field(default_factory=list, max_length=8)
    source_text: str = Field(min_length=1)
    params: dict[str, Any] = Field(default_factory=dict)
    manifest: dict[str, Any] = Field(default_factory=dict)
    release_notes: str = Field(default="", max_length=500)
    backtest: BacktestEvidence


class VersionInput(WriteModel):
    source_text: str = Field(min_length=1)
    params: dict[str, Any] = Field(default_factory=dict)
    manifest: dict[str, Any] = Field(default_factory=dict)
    release_notes: str = Field(default="", max_length=500)
    entry_timing: Literal["open", "close", "next_open", "next_dip"] | None = None
    backtest: BacktestEvidence


class ListingUpdateInput(WriteModel):
    """改文案，不碰版本内容（版本冻结，改内容请发新版）。"""

    title: str | None = Field(default=None, min_length=1, max_length=80)
    summary: str | None = Field(default=None, min_length=1, max_length=500)
    kind: Literal["screen", "timing", "portfolio", "factor", "other"] | None = None
    tags: list[str] | None = Field(default=None, max_length=8)


class VisibilityInput(WriteModel):
    visibility: Literal["public", "unlisted", "private"]


class CloneInput(WriteModel):
    version: int | None = Field(default=None, ge=1)


class CommentInput(WriteModel):
    body: str = Field(min_length=1, max_length=1000)
    parent_id: str = Field(default="", max_length=64)


class SubscribeInput(WriteModel):
    """订阅参数。**没有 mode 字段**：只推信号，不自动下单，不给调用方选择的余地。"""

    notify_channels: list[Literal["inapp", "desktop", "email"]] = Field(
        default_factory=lambda: ["inapp"], max_length=3
    )


class SignalBroadcastInput(WriteModel):
    """作者发当日信号快照。"""

    trade_date: str = Field(default="", pattern=r"^(\d{4}-\d{2}-\d{2})?$")
    payload: dict[str, Any] = Field(default_factory=dict)


class MetricsInput(WriteModel):
    """写一期绩效切片。``score`` 不在这里——它由服务端按统一公式现算。"""

    as_of: str = Field(default="", pattern=r"^(\d{4}-\d{2}-\d{2})?$")
    sharpe_1y: float = 0.0
    annual_return: float = 0.0
    max_drawdown: float = 0.0
    win_rate: float = 0.0
    profit_factor: float = 0.0
    trades: int = Field(default=0, ge=0)
    live_days: int = Field(default=0, ge=0)
    oos_return: float = 0.0
    metrics: dict[str, Any] = Field(default_factory=dict)


class RebuildBoardInput(WriteModel):
    board: Literal["overall", "sharpe", "return", "rookie"] = "overall"
    as_of: str = Field(default="", pattern=r"^(\d{4}-\d{2}-\d{2})?$")
    limit: int = Field(default=100, ge=1, le=200)
