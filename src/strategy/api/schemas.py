"""策略上下文的 HTTP 请求模型。

原先集中在组合根的 `app/legacy/quant_common.py`，导致每个上下文的 api 层都反向
依赖组合根。字段名对外是契约，搬迁不得改名。
"""
from __future__ import annotations

from typing import Any, Literal

from pydantic import Field, model_validator

from src.shared.api_models import QuantModel, UniverseSpecModel


class ScreenRequest(QuantModel):
    strategy: str = Field(min_length=1, max_length=64)
    date: str | None = Field(default=None, pattern=r"^\d{4}-\d{2}-\d{2}$")
    #: 区间选股起止（含）；跨度 ≤ 31 个自然日。与 date 二选一，同时传时以 start/end 为准。
    start: str | None = Field(default=None, pattern=r"^\d{4}-\d{2}-\d{2}$")
    end: str | None = Field(default=None, pattern=r"^\d{4}-\d{2}-\d{2}$")
    codes: list[str] | None = None
    params: dict[str, Any] | None = None
    universe: UniverseSpecModel | None = None
    skip_health_check: bool = False
    #: 写入候选池（同日同池覆盖）；默认开启，历史页才能看见结果
    record_candidates: bool = True
    top_n: int = Field(default=0, ge=0, le=500)
    pool_id: str | None = Field(default=None, max_length=120)

    @model_validator(mode="after")
    def _validate_date_window(self) -> ScreenRequest:
        # 校验逻辑内联，避免 quant_common ↔ strategy 循环依赖
        from datetime import date as date_cls

        start_s = self.start
        end_s = self.end
        date_s = self.date
        if start_s or end_s:
            if not start_s or not end_s:
                raise ValueError("区间选股需同时提供 start 与 end")
            a = date_cls.fromisoformat(start_s)
            b = date_cls.fromisoformat(end_s)
            if a > b:
                raise ValueError(f"起始日不能晚于结束日：{start_s} → {end_s}")
            span = (b - a).days + 1
            if span > 31:
                raise ValueError(
                    f"选股跨度不能超过一个月（最多 31 个自然日），当前共 {span} 天"
                )
            return self
        if date_s:
            date_cls.fromisoformat(date_s)
        return self


class BacktestRequest(QuantModel):
    strategy: str = Field(min_length=1, max_length=64)
    start: str | None = Field(default=None, pattern=r"^\d{4}-\d{2}-\d{2}$")
    end: str | None = Field(default=None, pattern=r"^\d{4}-\d{2}-\d{2}$")
    mode: Literal["trade", "horizon"] = "trade"
    horizons: list[int] | None = Field(default=None, max_length=8)
    hold_days: int = Field(default=3, ge=1, le=250)
    stop_loss_pct: float | None = Field(default=-6.0, ge=-100, le=0)
    take_profit_pct: float | None = Field(default=None, gt=0, le=1000)
    commission_bps: float = Field(default=3.0, ge=0, le=100)
    stamp_duty_bps: float = Field(default=10.0, ge=0, le=100)
    slippage_bps: float = Field(default=5.0, ge=0, le=100)
    benchmark: str | None = Field(default="000300", pattern=r"^\d{6}$")
    codes: list[str] | None = None
    params: dict[str, Any] | None = None
    universe: UniverseSpecModel | None = None
    include_trades: bool = False
    include_events: bool = False

    @model_validator(mode="after")
    def _horizon_needs_range(self) -> BacktestRequest:
        if self.mode != "horizon":
            return self
        if not self.start or not self.end:
            raise ValueError("horizon 回测必须指定 start 与 end")
        if self.horizons is not None:
            bad = [h for h in self.horizons if h not in (1, 3)]
            if bad:
                raise ValueError("一期 horizons 仅支持 1 与 3")
        return self


class AnalysisRequest(QuantModel):
    """横向对比与退出扫描共用的入参。"""

    strategy: str | None = Field(default=None, max_length=64)
    strategies: list[str] | None = None
    start: str | None = Field(default=None, pattern=r"^\d{4}-\d{2}-\d{2}$")
    end: str | None = Field(default=None, pattern=r"^\d{4}-\d{2}-\d{2}$")
    holds: list[int] | None = None
    targets: list[float] | None = None
    stops: list[float] | None = None
    stop_loss_pct: float | None = Field(default=None, ge=-100, le=0)
    benchmark: str | None = Field(default="000300", pattern=r"^\d{6}$")
    universe: UniverseSpecModel | None = None
    #: compare / optimize 默认在受控 spawn worker 中运行，避免把 API 进程的
    #: 大面板内存与异常拖垮；需要本地调试时可显式切回 thread。
    execution_mode: Literal["process", "thread"] = "process"


class StrategyJobConfig(QuantModel):
    """每个战法对应的定时选股参数。

    新 UI 用 schedule_mode + 时分/间隔；仍接受裸 cron 以兼容旧客户端。
    schedule_mode 非空时由服务端合成 cron。
    """

    cron: str = Field(default="", max_length=120)
    enabled: bool = True
    auto_review: bool = True
    push_wecom: bool = True
    trading_days: int = Field(default=60, ge=1, le=500)
    top_n: int = Field(default=0, ge=0, le=200)
    hold_days: int = Field(default=3, ge=1, le=250)
    stop_loss_pct: float | None = Field(default=-6.0, ge=-100, le=0)
    provider: str = Field(default="", max_length=64)
    model: str = Field(default="", max_length=120)
    thinking: str = Field(default="", max_length=16)
    use_ai_pick: bool = False
    universe: UniverseSpecModel | None = None
    schedule_mode: Literal["off", "once", "interval"] | None = None
    run_hour: int = Field(default=15, ge=0, le=23)
    run_minute: int = Field(default=30, ge=0, le=59)
    interval_minutes: int = Field(default=10, ge=1, le=60)
    window_start_hour: int = Field(default=9, ge=0, le=23)
    window_start_minute: int = Field(default=30, ge=0, le=59)
    window_end_hour: int = Field(default=14, ge=0, le=23)
    window_end_minute: int = Field(default=50, ge=0, le=59)


class StrategyConvertRequest(QuantModel):
    """AI 策略转换：通达信公式或文字描述 → Python 策略类。"""

    source: str = Field(min_length=10, max_length=8000, description="通达信公式原文或策略文字描述")
    source_type: Literal["tdx", "description"] = "tdx"
    slug: str = Field(
        min_length=2,
        max_length=40,
        pattern=r"^[a-z0-9][a-z0-9\-]*$",
        description="策略 slug，如 my-golden-cross，全小写加连字符",
    )
    name: str = Field(min_length=2, max_length=40, description="策略中文名，如 金叉选股")
    provider: str = Field(min_length=1, max_length=64, description="使用的 LLM 供应商名称")
    model: str = Field(default="", max_length=120)
    thinking: str = Field(default="", max_length=16, description="思考程度：off/low/medium/high")
    entry_timing: Literal["open", "next_open", "next_dip"] = "next_open"
    dry_run: bool = False


class StrategyDocUpsert(QuantModel):
    name: str = Field(default="", max_length=80)
    source_text: str = Field(default="", max_length=8000)
    source_type: str = Field(default="manual", max_length=20)
    assumptions: str = Field(default="", max_length=2000)
    market_cond: str = Field(default="", max_length=1000)
    failure_modes: str = Field(default="", max_length=2000)
    entry_timing: str = Field(default="", max_length=200)
    entry_instructions: str = Field(default="", max_length=2000)
    exit_rules: str = Field(default="", max_length=1000)
