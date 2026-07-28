"""Shared Pydantic models and helpers for quant HTTP routers.

Keep request/response field names stable. BC api modules import from here
to avoid circular imports with the thin aggregator.
"""
from __future__ import annotations

from pathlib import Path
import threading
from typing import Any, Literal

from fastapi import HTTPException
from pydantic import BaseModel, ConfigDict, Field

from src.shared.paths import palace_db as _default_palace_db

MAX_UPLOAD_BYTES = 20 * 1024 * 1024
DEFAULT_PALACE_DB = str(_default_palace_db())


class QuantModel(BaseModel):
    """与账本写入同样的严格校验：多一个字段就 422，不静默忽略。"""

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)


class UniverseSpecModel(QuantModel):
    """选股/回测股票池。未传时后端按 default_a_share（剔 ST、无北交）。"""

    preset: str | None = Field(default="default_a_share", max_length=64)
    boards: list[Literal["main", "chi_next", "star"]] | None = None
    exclude_st: bool | None = None
    exclude_delisting: bool | None = None
    exclude_suspended: bool | None = None
    min_list_days: int | None = Field(default=None, ge=0, le=5000)
    codes_include: list[str] | None = None
    codes_exclude: list[str] | None = None


class ScreenRequest(QuantModel):
    strategy: str = Field(min_length=1, max_length=64)
    date: str | None = Field(default=None, pattern=r"^\d{4}-\d{2}-\d{2}$")
    codes: list[str] | None = None
    params: dict[str, Any] | None = None
    universe: UniverseSpecModel | None = None
    skip_health_check: bool = False


class BacktestRequest(QuantModel):
    strategy: str = Field(min_length=1, max_length=64)
    start: str | None = Field(default=None, pattern=r"^\d{4}-\d{2}-\d{2}$")
    end: str | None = Field(default=None, pattern=r"^\d{4}-\d{2}-\d{2}$")
    hold_days: int = Field(default=3, ge=1, le=250)
    stop_loss_pct: float | None = Field(default=-6.0, ge=-100, le=0)
    take_profit_pct: float | None = Field(default=None, gt=0, le=1000)
    benchmark: str | None = Field(default="000300", pattern=r"^\d{6}$")
    codes: list[str] | None = None
    params: dict[str, Any] | None = None
    universe: UniverseSpecModel | None = None
    include_trades: bool = False


class SyncRequest(QuantModel):
    codes: list[str] | None = None
    limit: int = Field(default=0, ge=0, le=6000)
    workers: int = Field(default=4, ge=1, le=16)
    interval: float = Field(default=0.15, ge=0.0, le=5.0)
    force: bool = False
    refresh_instruments: bool = False


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
        "sync", "screen", "backtest", "compare", "optimize", "prune", "skill", "notify"
    ]
    cron: str = Field(default="", max_length=120)
    config: dict[str, Any] = Field(default_factory=dict)
    enabled: bool = True


class JobUpdate(QuantModel):
    name: str | None = Field(default=None, min_length=1, max_length=64)
    cron: str | None = Field(default=None, max_length=120)
    config: dict[str, Any] | None = None
    enabled: bool | None = None


class WecomSettingsUpdate(QuantModel):
    url: str = Field(default="", max_length=500)


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


class McpServerCreate(QuantModel):
    name: str = Field(min_length=1, max_length=64)
    url: str = Field(min_length=8, max_length=300)
    token: str | None = Field(default=None, max_length=500)
    proxy_url: str = Field(default="", max_length=300)
    note: str = Field(default="", max_length=500)
    verify: bool = True


class StrategyJobConfig(QuantModel):
    """每个战法对应的定时选股参数。"""

    cron: str = Field(default="", max_length=120)
    enabled: bool = True
    auto_review: bool = False
    trading_days: int = Field(default=60, ge=1, le=500)
    top_n: int = Field(default=3, ge=0, le=200)
    hold_days: int = Field(default=3, ge=1, le=250)
    stop_loss_pct: float | None = Field(default=-6.0, ge=-100, le=0)
    provider: str = Field(default="", max_length=64)
    model: str = Field(default="", max_length=120)
    thinking: str = Field(default="", max_length=16)
    use_ai_pick: bool = False


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
    entry_timing: Literal["open", "next_open"] = "next_open"
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
    """启用/禁用某家接入（只写 loci.config 开关，不含字段映射）。"""

    enabled: bool = True


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


# 兼容旧测试/导入名
_should_sync_today = should_sync_today
_bootstrap_snapshot = bootstrap_snapshot
_bootstrap_update = bootstrap_update
_missing_dependency = missing_dependency
