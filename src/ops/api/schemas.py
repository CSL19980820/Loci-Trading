"""运维上下文的 HTTP 请求模型：Job、企微、数据目录、线路与技能。

从组合根 `app/legacy/quant_common.py` 搬入。字段名对外是契约，不得改名。
"""
from __future__ import annotations

from typing import Any, Literal

from pydantic import Field, model_validator

from src.shared.api_models import QuantModel


class JobCreate(QuantModel):
    name: str = Field(min_length=1, max_length=64)
    kind: Literal[
        "sync",
        "screen",
        "backtest",
        "compare",
        "optimize",
        "prune",
        "skill",
        "notify",
        "outcome",
    ]
    cron: str = Field(default="", max_length=120)
    config: dict[str, Any] = Field(default_factory=dict)
    enabled: bool = True


class JobUpdate(QuantModel):
    name: str | None = Field(default=None, min_length=1, max_length=64)
    cron: str | None = Field(default=None, max_length=120)
    config: dict[str, Any] | None = None
    enabled: bool | None = None


class WecomScreenTemplateModel(QuantModel):
    """企微选股 text 模板。preset≠custom 时服务端会套用预设文案。"""

    preset: Literal["default", "compact", "with_date", "custom"] = "default"
    header: str = Field(default="【{title}】-{kind}", max_length=120)
    intro: str = Field(default="", max_length=120)
    pick: str = Field(default="📌 {name} {code} {pct}", max_length=120)
    pick_no_pct: str = Field(default="📌 {name} {code}", max_length=120)
    skill_pick: str = Field(
        default="📌 {name} {code} {pct}，{note}",
        max_length=160,
        description="技能推送行；涨跌幅后逗号接 ≤40 字说明",
    )
    skill_pick_no_pct: str = Field(
        default="📌 {name} {code}，{note}",
        max_length=160,
    )
    empty: str = Field(default="📭 暂无符合条件的标的", max_length=80)
    more: str = Field(default="…另有 {n} 只", max_length=80)
    quant_tag: str = Field(default="量化", max_length=32)
    skills_tag: str = Field(default="技能", max_length=32)
    max_picks: int = Field(default=30, ge=1, le=50)


class WecomSettingsUpdate(QuantModel):
    """更新企微配置。

    ``url`` 为 None 表示不改 webhook；空串表示清除；非空则校验后写入。
    ``screen_template`` 有值则保存选股推送模板。
    """

    url: str | None = Field(default=None, max_length=500)
    screen_template: WecomScreenTemplateModel | None = None


class DataLocationUpdate(QuantModel):
    """设置本机数据目录（写入 loci.config.json，需重启生效）。"""

    data_dir: str = Field(min_length=1, max_length=500)
    setup_done: bool = True


class MarketSyncSettings(QuantModel):
    enabled_intraday: bool = True
    interval_minutes: int = Field(default=5, ge=1, le=60)
    enabled_eod: bool = True
    eod_hour: int = Field(default=16, ge=12, le=23)
    eod_minute: int = Field(default=0, ge=0, le=59)
    workers: int = Field(default=4, ge=1, le=16)
    push_wecom_on_fail: bool = False


class SkillStrategyConfig(QuantModel):
    """专属战法 Skill：盘后 AI 选股 + 盘中信号监测（双 Job）。

    ``screen_schedule_mode=off`` 时删除 ``skill:{slug}``；``watch_schedule_mode=off`` 时删除 ``监测·{slug}``。
    盘中确定性监测不要求 provider，只有 ``watch_use_ai`` 开启时才调用 LLM。
    """

    provider: str = Field(default="", max_length=64)
    model: str = Field(default="", max_length=120)
    thinking: str = Field(default="medium", max_length=16)
    push_wecom: bool = True
    push_watch: bool = True
    watch_use_ai: bool = False
    screen_schedule_mode: Literal["off", "once", "interval"] | None = "once"
    screen_run_hour: int = Field(default=15, ge=0, le=23)
    screen_run_minute: int = Field(default=40, ge=0, le=59)
    screen_interval_minutes: int = Field(default=10, ge=1, le=60)
    screen_window_start_hour: int = Field(default=9, ge=0, le=23)
    screen_window_start_minute: int = Field(default=30, ge=0, le=59)
    screen_window_end_hour: int = Field(default=14, ge=0, le=23)
    screen_window_end_minute: int = Field(default=50, ge=0, le=59)
    watch_schedule_mode: Literal["off", "once", "interval"] | None = "interval"
    watch_run_hour: int = Field(default=10, ge=0, le=23)
    watch_run_minute: int = Field(default=0, ge=0, le=59)
    watch_interval_minutes: int = Field(default=10, ge=1, le=60)
    watch_window_start_hour: int = Field(default=9, ge=0, le=23)
    watch_window_start_minute: int = Field(default=30, ge=0, le=59)
    watch_window_end_hour: int = Field(default=14, ge=0, le=23)
    watch_window_end_minute: int = Field(default=50, ge=0, le=59)
    context: list[str] = Field(default_factory=list)
    context_strategy: str = Field(default="", max_length=64)


class SkillJobConfig(QuantModel):
    """每个技能对应的定时运行参数（含推送开关）。

    schedule_mode=off 时删除 ``skill:{slug}`` 绑定。开启定时必须指定 LLM provider。
    ``push_wecom`` 开启后，定时任务成功/失败结束由 registry 附带企微 text 推送。
    """

    cron: str = Field(default="", max_length=120)
    enabled: bool = True
    push_wecom: bool = True
    provider: str = Field(default="", max_length=64)
    model: str = Field(default="", max_length=120)
    thinking: str = Field(default="", max_length=16)
    context: list[str] = Field(default_factory=list)
    context_strategy: str = Field(default="", max_length=64)
    schedule_mode: Literal["off", "once", "interval"] | None = None
    run_hour: int = Field(default=15, ge=0, le=23)
    run_minute: int = Field(default=30, ge=0, le=59)
    interval_minutes: int = Field(default=10, ge=1, le=60)
    window_start_hour: int = Field(default=9, ge=0, le=23)
    window_start_minute: int = Field(default=30, ge=0, le=59)
    window_end_hour: int = Field(default=14, ge=0, le=23)
    window_end_minute: int = Field(default=50, ge=0, le=59)


class SkillGenerateRequest(QuantModel):
    """AI 生成 Skill 指令文件。"""

    description: str = Field(min_length=20, max_length=2000, description="技能用途的文字描述")
    slug: str = Field(min_length=2, max_length=40, pattern=r"^[a-z0-9][a-z0-9\-]*$")
    name: str = Field(min_length=2, max_length=40)
    provider: str = Field(min_length=1, max_length=64)
    model: str = Field(default="", max_length=120)
    thinking: str = Field(default="", max_length=16, description="思考程度：off/low/medium/high")
    context_hints: list[str] = Field(
        default_factory=list,
        description="需要哪些数据上下文，如 ['screen','market_coverage']",
    )


class LaneProviderPatch(QuantModel):
    """启用/禁用某家接入（只写 loci.config 开关，不含字段映射）。

    ``lane`` 缺省时改源总开关；给了 lane 就只改这家在该线路上的单个工具。
    """

    enabled: bool = True
    lane: str | None = Field(default=None, max_length=64)


class SkillRunCreate(QuantModel):
    provider: str = Field(min_length=1, max_length=64)
    model: str = Field(default="", max_length=120)
    config: dict[str, Any] = Field(default_factory=dict)
    background: bool = True


class SkillRunReply(QuantModel):
    reply: str = Field(min_length=1, max_length=4000)
    background: bool = True


class WatchTuningIn(QuantModel):
    """战法监测调参补丁：按段合并，只传哪段就只改哪段。

    传 ``preset`` 时整档套用命名预设（aggressive / balanced / defensive），
    与段/阈值字段互斥——preset 优先。值域校验交给 ``normalize_tuning``。
    """

    preset: Literal["aggressive", "balanced", "defensive"] | None = None
    stages: dict[str, bool] | None = None
    gate: dict[str, float] | None = None
    roles: dict[str, float] | None = None
    scan: dict[str, float] | None = None
    auction: dict[str, float] | None = None
