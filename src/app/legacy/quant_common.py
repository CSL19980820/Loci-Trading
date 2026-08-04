"""Shared Pydantic models and helpers for quant HTTP routers.

Keep request/response field names stable. BC api modules import from here
to avoid circular imports with the thin aggregator.
"""
from __future__ import annotations

from pathlib import Path
import threading
from typing import Any, Literal

from fastapi import HTTPException
from pydantic import BaseModel, ConfigDict, Field, model_validator

from src.shared.paths import palace_db as _default_palace_db

MAX_UPLOAD_BYTES = 20 * 1024 * 1024
DEFAULT_PALACE_DB = str(_default_palace_db())


class QuantModel(BaseModel):
    """与账本写入同样的严格校验：多一个字段就 422，不静默忽略。"""

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)


class UniverseSpecModel(QuantModel):
    """选股/回测股票池。未传时后端按 default_a_share（剔 ST、默认不含北交）。"""

    preset: str | None = Field(default="default_a_share", max_length=64)
    boards: list[Literal["main", "chi_next", "star", "bse"]] | None = None
    exclude_st: bool | None = None
    exclude_delisting: bool | None = None
    exclude_suspended: bool | None = None
    min_list_days: int | None = Field(default=None, ge=0, le=5000)
    industries_include: list[str] | None = None
    industries_exclude: list[str] | None = None
    codes_include: list[str] | None = None
    codes_exclude: list[str] | None = None


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



class SyncRequest(QuantModel):
    codes: list[str] | None = None
    limit: int = Field(default=0, ge=0, le=6000)
    workers: int = Field(default=4, ge=1, le=16)
    interval: float = Field(default=0.15, ge=0.0, le=5.0)
    force: bool = False
    refresh_instruments: bool = False
    with_factors: bool = True


class BootstrapRequest(QuantModel):
    """首次初始化历史日 K。全市场约 10–40 分钟，可断点续跑。"""

    workers: int = Field(default=4, ge=1, le=16)
    interval: float = Field(default=0.15, ge=0.0, le=5.0)
    limit: int = Field(default=0, ge=0, le=6000)
    with_factors: bool = False


_BOOTSTRAP_LOCK = threading.Lock()
_BOOTSTRAP: dict[str, Any] = {
    "status": "idle",
    "phase": "",
    "done": 0,
    "total": 0,
    "percent": 0.0,
    "code": "",
    "message": "",
    "report": None,
}


def bootstrap_snapshot() -> dict[str, Any]:
    with _BOOTSTRAP_LOCK:
        return dict(_BOOTSTRAP)


def bootstrap_update(**kwargs: Any) -> None:
    with _BOOTSTRAP_LOCK:
        _BOOTSTRAP.update(kwargs)
        total = int(_BOOTSTRAP.get("total") or 0)
        done = int(_BOOTSTRAP.get("done") or 0)
        if _BOOTSTRAP.get("status") == "done":
            _BOOTSTRAP["percent"] = 100.0
        elif total > 0:
            _BOOTSTRAP["percent"] = round(100.0 * done / total, 1)
        else:
            _BOOTSTRAP["percent"] = 0.0


def bootstrap_try_begin() -> dict[str, Any] | None:
    """若已在 running 则返回当前快照；否则置为 running 并返回 None。"""
    with _BOOTSTRAP_LOCK:
        if _BOOTSTRAP.get("status") == "running":
            return dict(_BOOTSTRAP)
        _BOOTSTRAP.update(
            {
                "status": "running",
                "phase": "instruments",
                "done": 0,
                "total": 0,
                "percent": 0.0,
                "code": "",
                "message": "正在刷新证券列表…",
                "report": None,
            }
        )
    return None


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
    header: str = Field(default="【{title}】{kind}", max_length=120)
    intro: str = Field(default="选股如下：", max_length=120)
    pick: str = Field(default="{name} {code} {pct}", max_length=120)
    pick_no_pct: str = Field(default="{name} {code}", max_length=120)
    empty: str = Field(default="（暂无入选）", max_length=80)
    more: str = Field(default="…另有 {n} 只", max_length=80)
    quant_tag: str = Field(default="量化", max_length=32)
    skills_tag: str = Field(default="skills", max_length=32)
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


class ProviderCreate(QuantModel):
    name: str = Field(min_length=1, max_length=64)
    base_url: str = Field(min_length=8, max_length=300)
    api_key: str | None = Field(default=None, max_length=500)
    protocol: Literal["openai_compatible", "anthropic"] = "openai_compatible"
    model: str = Field(default="", max_length=120)
    proxy_url: str = Field(default="", max_length=300)
    note: str = Field(default="", max_length=500)
    validate_key: bool = True
    discover_models: bool = True
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


class McpServerCreate(QuantModel):
    name: str = Field(min_length=1, max_length=64)
    url: str = Field(min_length=8, max_length=300)
    token: str | None = Field(default=None, max_length=500)
    proxy_url: str = Field(default="", max_length=300)
    note: str = Field(default="", max_length=500)
    verify: bool = True


class McpProbeRequest(QuantModel):
    """服务级 MCP 连通性探测不接受工具或工具参数。"""


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
        description="需要哪些数据上下文，如 ['screen','positions']",
    )


class LaneProbeRequest(QuantModel):
    """探测数据线路。``lane`` 为空则对所有已注册类目各探一次。"""

    lane: str | None = Field(default=None, max_length=64)
    adapter_id: str | None = Field(default=None, max_length=64)


class LaneSpeedtestRequest(QuantModel):
    """同类下载测速。P0 仅支持 hist_daily。"""

    lane: str = Field(default="hist_daily", max_length=64)
    code: str = Field(default="600519", min_length=6, max_length=10)


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


def missing_dependency(exc: ImportError) -> HTTPException:
    """缺依赖返回 503 而不是 500：这是环境没装齐，不是代码出错。"""
    return HTTPException(
        status_code=503,
        detail=(
            f"该能力所需的依赖未安装（{exc.name}）。"
            "线上镜像需要在 deploy/requirements-runtime.txt 中加入行情与分析依赖后重新发布。"
        ),
    )


def market_store(market_db: str | None):
    try:
        from src.market import MarketStore
    except ImportError as exc:
        raise missing_dependency(exc) from exc
    return MarketStore(market_db)


def ops_store(ops_db: str | None):
    try:
        from src.ops import OpsStore
    except ImportError as exc:
        raise missing_dependency(exc) from exc
    return OpsStore(ops_db)


def palace_store(palace_db: str | None):
    from src.ledger import PalaceStore

    return PalaceStore(palace_db or DEFAULT_PALACE_DB)


def should_sync_today(market_db: str | Path | None = None) -> bool:
    """判断是否需要在选股前触发同步。"""
    from datetime import date as _date

    try:
        from src.market import MarketStore

        with MarketStore(market_db) as store:
            if not store.list_instruments():
                return True
            cov = store.coverage()
        last = str(cov.get("last_date") or "")
        return not last or last < _date.today().isoformat()
    except Exception:
        return True
