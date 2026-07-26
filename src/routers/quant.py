"""行情 / 策略 / 回测 / 技能 / 任务 / 供应商的 HTTP 接口。

单独成一个 router 而不是塞进 palace_api.py，有两个原因：

1. **可选依赖。** 这些能力依赖 pandas/akshare/apscheduler，而线上镜像
   一度只装 fastapi/uvicorn。所以所有重模块都在函数体内**懒导入**，
   缺依赖时对应接口返回 503 并说清缺什么，而不是让整个应用 import 失败、
   连账本都打不开。``GET /api/capabilities`` 用来一眼看清哪些能力可用。

2. **鉴权复用。** 写操作全部挂在 palace_api 传进来的 ``write_dependency``
   上，与账本写入走同一道门（浏览器会话或 Agent Bearer 令牌），
   不新开旁路。
"""
from __future__ import annotations

from pathlib import Path
import shutil
import tempfile
from typing import Any, Literal

from fastapi import APIRouter, Depends, File, HTTPException, Query, UploadFile
from pydantic import BaseModel, ConfigDict, Field

#: 上传技能包的体积上限。与 skills.MAX_ARCHIVE_BYTES 对齐，
#: 但要在读进内存之前就挡住，不能等解包时才发现。
MAX_UPLOAD_BYTES = 20 * 1024 * 1024


class QuantModel(BaseModel):
    """与账本写入同样的严格校验：多一个字段就 422，不静默忽略。"""

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)


class ScreenRequest(QuantModel):
    strategy: str = Field(min_length=1, max_length=64)
    date: str | None = Field(default=None, pattern=r"^\d{4}-\d{2}-\d{2}$")
    codes: list[str] | None = None
    params: dict[str, Any] | None = None


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
    include_trades: bool = False


class SyncRequest(QuantModel):
    codes: list[str] | None = None
    limit: int = Field(default=0, ge=0, le=6000)
    workers: int = Field(default=4, ge=1, le=16)
    interval: float = Field(default=0.15, ge=0.0, le=5.0)
    force: bool = False
    refresh_instruments: bool = False


class JobCreate(QuantModel):
    name: str = Field(min_length=1, max_length=64)
    kind: Literal["sync", "screen", "backtest", "skill"]
    cron: str = Field(default="", max_length=120)
    config: dict[str, Any] = Field(default_factory=dict)
    enabled: bool = True


class JobUpdate(QuantModel):
    name: str | None = Field(default=None, min_length=1, max_length=64)
    cron: str | None = Field(default=None, max_length=120)
    config: dict[str, Any] | None = None
    enabled: bool | None = None


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


def _missing_dependency(exc: ImportError) -> HTTPException:
    """缺依赖返回 503 而不是 500：这是环境没装齐，不是代码出错。"""
    return HTTPException(
        status_code=503,
        detail=(
            f"该能力所需的依赖未安装（{exc.name}）。"
            "线上镜像需要在 deploy/requirements-runtime.txt 中加入行情与分析依赖后重新发布。"
        ),
    )


def build_quant_router(
    *,
    write_dependency,
    market_db: str | None = None,
    ops_db: str | None = None,
    scheduler_getter=None,
) -> APIRouter:
    """构造 router。依赖由 palace_api 注入，便于测试时整体替换。"""
    router = APIRouter()
    # 注意：不能用 Annotated 局部别名。本模块有 from __future__ import annotations，
    # 注解全是字符串，而 FastAPI 在**模块全局**里解析它们——局部别名找不到，
    # 会被当成必填查询参数，接口直接 422。用显式 Depends 默认值最稳。
    write_guard = Depends(write_dependency)

    # ---- 能力探测 ---------------------------------------------------

    @router.get("/api/capabilities", tags=["system"])
    def capabilities() -> dict[str, Any]:
        """哪些能力当前可用。前端据此决定隐藏哪些入口。"""
        def probe(module: str) -> bool:
            try:
                __import__(module)
                return True
            except ImportError:
                return False

        has_pandas = probe("pandas")
        has_akshare = probe("akshare")
        has_scheduler = probe("apscheduler")
        has_yaml = probe("yaml")
        has_crypto = probe("cryptography")
        return {
            "market": has_pandas,
            "quotes_sync": has_pandas and has_akshare,
            "strategies": has_pandas,
            "backtest": has_pandas,
            "skills": has_yaml,
            "scheduler": has_scheduler,
            "llm": has_crypto,
            "missing": [
                name
                for name, ok in (
                    ("pandas", has_pandas), ("akshare", has_akshare),
                    ("apscheduler", has_scheduler), ("PyYAML", has_yaml),
                    ("cryptography", has_crypto),
                )
                if not ok
            ],
        }

    # ---- 行情 -------------------------------------------------------

    def _market():
        try:
            from src.market import MarketStore
        except ImportError as exc:
            raise _missing_dependency(exc) from exc
        return MarketStore(market_db)

    @router.get("/api/market/coverage", tags=["market"])
    def market_coverage() -> dict[str, Any]:
        with _market() as store:
            return store.coverage()

    @router.get("/api/market/search", tags=["market"])
    def market_search(
        q: str = Query(min_length=1, max_length=32),
        limit: int = Query(default=20, ge=1, le=100),
    ) -> list[dict[str, Any]]:
        """代码或名称模糊搜索，供前端全局搜索框与命令面板用。"""
        needle = q.strip().lower()
        with _market() as store:
            rows = store.list_instruments(status="")
        matched = [
            row
            for row in rows
            if needle in row["code"] or needle in str(row["name"]).lower()
        ]
        return matched[:limit]

    @router.get("/api/market/quotes/{code}", tags=["market"])
    def market_quotes(
        code: str,
        start: str | None = Query(default=None, pattern=r"^\d{4}-\d{2}-\d{2}$"),
        end: str | None = Query(default=None, pattern=r"^\d{4}-\d{2}-\d{2}$"),
        adjust: Literal["qfq", "hfq", "none"] = "qfq",
    ) -> dict[str, Any]:
        with _market() as store:
            try:
                frame = store.history(code, start=start, end=end, adjust=adjust)
            except Exception as exc:
                raise HTTPException(status_code=422, detail=str(exc)) from exc
        return {
            "code": code,
            "adjust": adjust,
            "rows": len(frame),
            "bars": frame.to_dict("records"),
        }

    @router.post("/api/market/sync", tags=["market"], status_code=202)
    def market_sync(payload: SyncRequest, _write: None = write_guard) -> dict[str, Any]:
        """同步行情。同步执行——单用户场景下等几十秒可以接受，
        真要长跑就建一个 sync 任务交给调度器。"""
        try:
            from src.ops.jobs import JobContext, execute_sync
        except ImportError as exc:
            raise _missing_dependency(exc) from exc
        context = JobContext(market_db=market_db)
        try:
            return execute_sync(payload.model_dump(), context)
        except Exception as exc:
            raise HTTPException(status_code=502, detail=f"同步失败：{exc}") from exc

    # ---- 策略与回测 -------------------------------------------------

    @router.get("/api/strategies", tags=["strategy"])
    def list_strategies() -> list[dict[str, Any]]:
        try:
            from src.strategies import describe_all
        except ImportError as exc:
            raise _missing_dependency(exc) from exc
        return describe_all()

    @router.post("/api/strategies/screen", tags=["strategy"])
    def run_screen(payload: ScreenRequest) -> dict[str, Any]:
        try:
            from src.strategies import screen
            from src.strategies.base import StrategyError
        except ImportError as exc:
            raise _missing_dependency(exc) from exc
        with _market() as store:
            try:
                result = screen(
                    store, payload.strategy, trade_date=payload.date,
                    params=payload.params, codes=payload.codes,
                )
            except StrategyError as exc:
                raise HTTPException(status_code=422, detail=str(exc)) from exc
        return {
            "strategy": result.strategy_slug,
            "trade_date": result.trade_date,
            "entry_timing": result.entry_timing,
            "universe_size": result.universe_size,
            "elapsed_seconds": round(result.elapsed_seconds, 3),
            "params": result.params,
            "picks": result.picks,
        }

    @router.post("/api/backtest", tags=["strategy"])
    def run_backtest_api(payload: BacktestRequest) -> dict[str, Any]:
        try:
            from src.backtest import BacktestConfig, backtest_strategy
            from src.strategies.base import StrategyError
        except ImportError as exc:
            raise _missing_dependency(exc) from exc

        config = BacktestConfig(
            hold_days=payload.hold_days,
            stop_loss_pct=payload.stop_loss_pct,
            take_profit_pct=payload.take_profit_pct,
            benchmark=payload.benchmark,
        )
        with _market() as store:
            try:
                result = backtest_strategy(
                    store, payload.strategy, start=payload.start, end=payload.end,
                    params=payload.params, config=config, codes=payload.codes,
                )
            except StrategyError as exc:
                raise HTTPException(status_code=422, detail=str(exc)) from exc

        body: dict[str, Any] = {
            "strategy": result.strategy_slug,
            "config": result.config,
            "metrics": result.metrics,
            "skipped": result.skipped,
        }
        if payload.include_trades:
            body["trades"] = [
                {**trade.__dict__, "alpha_pct": trade.alpha_pct} for trade in result.trades
            ]
        return body

    # ---- 技能包 -----------------------------------------------------

    def _ops():
        try:
            from src.ops import OpsStore
        except ImportError as exc:
            raise _missing_dependency(exc) from exc
        return OpsStore(ops_db)

    @router.get("/api/skills", tags=["skills"])
    def list_skills() -> list[dict[str, Any]]:
        with _ops() as store:
            return [
                {key: value for key, value in skill.items() if key != "instructions"}
                for skill in store.list_skills()
            ]

    @router.get("/api/skills/{slug}", tags=["skills"])
    def get_skill(slug: str) -> dict[str, Any]:
        with _ops() as store:
            skill = store.get_skill(slug)
        if skill is None:
            raise HTTPException(status_code=404, detail=f"未安装的技能：{slug}")
        return skill

    @router.post("/api/skills", tags=["skills"], status_code=201)
    async def install_skill_api(
        file: UploadFile = File(...), _write: None = write_guard
    ) -> dict[str, Any]:
        """上传并安装技能包 zip。

        先落到临时文件再交给安装器：安装器要做的 Zip Slip / 符号链接 /
        zip 炸弹检查都需要一个真实的 zip 文件句柄，而且边读边校验体积
        才能在超限时立刻中断，不会把几百 MB 读进内存。
        """
        try:
            from src.ops import install_skill
            from src.ops.skills import SkillError
        except ImportError as exc:
            raise _missing_dependency(exc) from exc

        if not (file.filename or "").lower().endswith(".zip"):
            raise HTTPException(status_code=422, detail="技能包必须是 .zip 文件")

        with tempfile.TemporaryDirectory(prefix="skill-upload-") as tmp:
            target = Path(tmp) / "package.zip"
            written = 0
            with open(target, "wb") as handle:
                while chunk := await file.read(1024 * 256):
                    written += len(chunk)
                    if written > MAX_UPLOAD_BYTES:
                        raise HTTPException(
                            status_code=413,
                            detail=f"技能包超过 {MAX_UPLOAD_BYTES // (1024 * 1024)}MB 上限",
                        )
                    handle.write(chunk)
            try:
                package = install_skill(target)
            except SkillError as exc:
                raise HTTPException(status_code=422, detail=str(exc)) from exc

        record = package.to_record()
        with _ops() as store:
            store.upsert_skill(record)
        return {key: value for key, value in record.items() if key != "instructions"}

    @router.delete("/api/skills/{slug}", tags=["skills"])
    def remove_skill(slug: str, _write: None = write_guard) -> dict[str, bool]:
        try:
            from src.ops import uninstall_skill
            from src.ops.skills import SkillError
        except ImportError as exc:
            raise _missing_dependency(exc) from exc
        with _ops() as store:
            removed_db = store.delete_skill(slug)
        try:
            removed_fs = uninstall_skill(slug)
        except SkillError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        if not (removed_db or removed_fs):
            raise HTTPException(status_code=404, detail=f"未安装的技能：{slug}")
        return {"removed": True}

    # ---- 定时任务 ---------------------------------------------------

    def _reload_scheduler() -> None:
        """任务表变了就让调度器重新装载，否则改完 cron 要重启才生效。"""
        if scheduler_getter is None:
            return
        scheduler = scheduler_getter()
        if scheduler is not None and scheduler.running:
            scheduler.reload()

    @router.get("/api/jobs", tags=["jobs"])
    def list_jobs() -> list[dict[str, Any]]:
        with _ops() as store:
            return store.list_jobs()

    @router.post("/api/jobs", tags=["jobs"], status_code=201)
    def create_job(payload: JobCreate, _write: None = write_guard) -> dict[str, Any]:
        try:
            from src.ops import OpsError
            from src.ops.scheduler import SchedulerError, validate_cron
        except ImportError as exc:
            raise _missing_dependency(exc) from exc
        if payload.cron:
            try:
                validate_cron(payload.cron)
            except SchedulerError as exc:
                raise HTTPException(status_code=422, detail=str(exc)) from exc
        with _ops() as store:
            try:
                job_id = store.create_job(
                    name=payload.name, kind=payload.kind, cron=payload.cron,
                    config=payload.config, enabled=payload.enabled,
                )
            except OpsError as exc:
                raise HTTPException(status_code=422, detail=str(exc)) from exc
            job = store.get_job(job_id)
        _reload_scheduler()
        return job or {}

    @router.patch("/api/jobs/{job_id}", tags=["jobs"])
    def update_job(job_id: str, payload: JobUpdate, _write: None = write_guard) -> dict[str, Any]:
        try:
            from src.ops import OpsError
            from src.ops.scheduler import SchedulerError, validate_cron
        except ImportError as exc:
            raise _missing_dependency(exc) from exc
        fields = {k: v for k, v in payload.model_dump().items() if v is not None}
        if not fields:
            raise HTTPException(status_code=422, detail="没有要更新的字段")
        if fields.get("cron"):
            try:
                validate_cron(fields["cron"])
            except SchedulerError as exc:
                raise HTTPException(status_code=422, detail=str(exc)) from exc
        with _ops() as store:
            if store.get_job(job_id) is None:
                raise HTTPException(status_code=404, detail=f"未知任务：{job_id}")
            try:
                store.update_job(job_id, **fields)
            except OpsError as exc:
                raise HTTPException(status_code=422, detail=str(exc)) from exc
            job = store.get_job(job_id)
        _reload_scheduler()
        return job or {}

    @router.delete("/api/jobs/{job_id}", tags=["jobs"])
    def delete_job(job_id: str, _write: None = write_guard) -> dict[str, bool]:
        with _ops() as store:
            if not store.delete_job(job_id):
                raise HTTPException(status_code=404, detail=f"未知任务：{job_id}")
        _reload_scheduler()
        return {"removed": True}

    @router.post("/api/jobs/{job_id}/run", tags=["jobs"])
    def trigger_job(job_id: str, _write: None = write_guard) -> dict[str, Any]:
        try:
            from src.ops import JobContext, OpsError, run_job
        except ImportError as exc:
            raise _missing_dependency(exc) from exc
        with _ops() as store:
            try:
                return run_job(
                    store, job_id,
                    context=JobContext(market_db=market_db, ops_store=store),
                    trigger="api",
                )
            except OpsError as exc:
                raise HTTPException(status_code=404, detail=str(exc)) from exc

    @router.get("/api/jobs/runs", tags=["jobs"])
    def list_runs(
        job_id: str | None = Query(default=None),
        status: str | None = Query(default=None, pattern="^(success|failed|running|skipped)$"),
        limit: int = Query(default=50, ge=1, le=500),
    ) -> list[dict[str, Any]]:
        with _ops() as store:
            return store.list_runs(job_id=job_id, status=status, limit=limit)

    @router.get("/api/jobs/schedule", tags=["jobs"])
    def schedule_status() -> dict[str, Any]:
        """调度器到底在不在跑、下次什么时候触发。

        没有这个接口，"我的定时任务配好了吗"只能靠等到点看结果。
        """
        if scheduler_getter is None:
            return {"running": False, "reason": "本进程未启用调度器", "jobs": []}
        scheduler = scheduler_getter()
        if scheduler is None:
            return {"running": False, "reason": "调度器未初始化", "jobs": []}
        return {"running": scheduler.running, "jobs": scheduler.upcoming()}

    # ---- LLM 供应商 -------------------------------------------------

    @router.get("/api/providers", tags=["llm"])
    def list_providers() -> list[dict[str, Any]]:
        """只返回末四位，永不回显明文或密文。"""
        with _ops() as store:
            return store.list_providers()

    @router.post("/api/providers", tags=["llm"], status_code=201)
    def save_provider_api(payload: ProviderCreate, _write: None = write_guard) -> dict[str, Any]:
        try:
            from src.ai.crypto import CryptoError
            from src.ai.providers import save_provider
            from src.ops import OpsError
        except ImportError as exc:
            raise _missing_dependency(exc) from exc
        with _ops() as store:
            try:
                return save_provider(
                    store,
                    name=payload.name, protocol=payload.protocol,
                    base_url=payload.base_url, api_key=payload.api_key,
                    model=payload.model, proxy_url=payload.proxy_url,
                    note=payload.note, validate=payload.validate_key,
                    discover_models=payload.discover_models,
                )
            except (OpsError, CryptoError) as exc:
                raise HTTPException(status_code=422, detail=str(exc)) from exc

    @router.post("/api/providers/{name}/models", tags=["llm"])
    def refresh_provider_models(name: str, _write: None = write_guard) -> dict[str, Any]:
        try:
            from src.ai.crypto import CryptoError
            from src.ai.providers import refresh_models
            from src.ops import OpsError
        except ImportError as exc:
            raise _missing_dependency(exc) from exc
        with _ops() as store:
            try:
                models = refresh_models(store, name)
            except (OpsError, CryptoError) as exc:
                raise HTTPException(status_code=422, detail=str(exc)) from exc
        return {"models": models, "count": len(models)}

    @router.delete("/api/providers/{name}", tags=["llm"])
    def delete_provider(name: str, _write: None = write_guard) -> dict[str, bool]:
        with _ops() as store:
            if not store.delete_provider(name):
                raise HTTPException(status_code=404, detail=f"未配置的供应商：{name}")
        return {"removed": True}

    return router
