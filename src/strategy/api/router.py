"""策略 / 回测 / 选股历史 / 洞察 HTTP。"""
from __future__ import annotations

import logging
import threading
from typing import Any, Literal

from fastapi import APIRouter, Depends, HTTPException, Query

from src.app.legacy.quant_common import (
    AnalysisRequest,
    BacktestRequest,
    ScreenRequest,
    StrategyDocUpsert,
    StrategyJobConfig,
    market_store,
    missing_dependency,
    ops_store,
    palace_store,
    should_sync_today,
)

logger = logging.getLogger(__name__)


def build_strategy_router(
    *,
    write_dependency,
    market_db: str | None = None,
    ops_db: str | None = None,
    palace_db: str | None = None,
    scheduler_getter=None,
) -> APIRouter:
    router = APIRouter()
    write_guard = Depends(write_dependency)

    def _market():
        return market_store(market_db)

    def _ops():
        return ops_store(ops_db)

    def _palace():
        return palace_store(palace_db)

    def _reload_scheduler() -> None:
        if scheduler_getter is None:
            return
        scheduler = scheduler_getter()
        if scheduler is not None and scheduler.running:
            scheduler.reload()

    @router.get("/api/strategies", tags=["strategy"])
    def list_strategies() -> list[dict[str, Any]]:
        try:
            from src.strategy import describe_all
        except ImportError as exc:
            raise missing_dependency(exc) from exc
        return describe_all()

    @router.post("/api/strategies/screen", tags=["strategy"])
    def run_screen(payload: ScreenRequest) -> dict[str, Any]:
        try:
            from src.market import DataQualityError
            from src.strategy import screen
            from src.strategy.domain.base import StrategyError
        except ImportError as exc:
            raise missing_dependency(exc) from exc
        with _market() as store:
            try:
                result = screen(
                    store, payload.strategy, trade_date=payload.date,
                    params=payload.params, codes=payload.codes,
                    universe=payload.universe.model_dump(exclude_none=True) if payload.universe else None,
                    health_check=not payload.skip_health_check,
                )
            except DataQualityError as exc:
                # 422 而不是 500：这不是代码出错，是数据不合格。前端要能
                # 原样展示体检报告，让人知道该去补哪份数据。
                raise HTTPException(
                    status_code=422,
                    detail=f"数据体检未通过，已拒绝选股：{exc}",
                    headers={"X-Data-Health": "blocked"},
                ) from exc
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
            "health": result.health,
            "universe": result.universe,
            "universe_funnel": result.universe_funnel,
        }

    @router.post("/api/backtest", tags=["strategy"])
    def run_backtest_api(payload: BacktestRequest) -> dict[str, Any]:
        try:
            from src.backtest import BacktestConfig, backtest_strategy
            from src.strategy.domain.base import StrategyError
        except ImportError as exc:
            raise missing_dependency(exc) from exc

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
                    universe=payload.universe.model_dump(exclude_none=True) if payload.universe else None,
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

    # ---- 分析任务（异步）---------------------------------------------
    # 横向对比与退出扫描都是分钟级的：对比 8 个战法 × 2 个持有期要跑 16 次
    # 全市场回测，扫描 48 组更久。同步返回必然被 Nginx 的 60s 超时掐断，
    # 所以做成后台任务，接口只回 run_id，前端轮询 /api/jobs/runs 拿结果。

    @router.post("/api/analysis/{kind}", tags=["strategy"], status_code=202)
    def start_analysis(
        kind: Literal["compare", "optimize"],
        payload: AnalysisRequest,
        _write: None = write_guard,
    ) -> dict[str, Any]:
        try:
            from src.ops import JobContext, OpsStore, run_job
        except ImportError as exc:
            raise missing_dependency(exc) from exc

        config = {k: v for k, v in payload.model_dump().items() if v is not None}
        if kind == "optimize" and not config.get("strategy"):
            raise HTTPException(status_code=422, detail="退出规则扫描必须指定 strategy")

        store = _ops()
        # 用固定名字的一次性任务：重复触发会复用同一条 job 记录，
        # 执行历史仍然逐次留痕，不会积累一堆同类型的僵尸任务。
        name = f"[即时] {kind}" + (f" {config['strategy']}" if config.get("strategy") else "")
        job = store.get_job_by_name(name)
        if job is None:
            job_id = store.create_job(name=name, kind=kind, config=config, enabled=False)
        else:
            job_id = job["id"]
            store.update_job(job_id, config=config)
        job = store.get_job(job_id)

        def worker() -> None:
            # 独立连接：SQLite 连接不能跨线程共享。
            with OpsStore(ops_db) as own:
                run_job(
                    own, job_id,
                    context=JobContext(market_db=market_db, ops_store=own, palace_db=palace_db),
                    trigger="api",
                )

        run_id = store.start_run(job or {"id": job_id, "name": name, "kind": kind}, trigger="api")
        # start_run 只是占位，真正的记录由 run_job 自己写；把占位标成 skipped
        # 免得它永远停在 running 状态污染历史。
        store.finish_run(run_id, status="skipped", result={"note": "已转入后台执行"})
        store.close()

        threading.Thread(target=worker, name=f"analysis-{kind}", daemon=True).start()
        return {
            "job_id": job_id,
            "kind": kind,
            "status": "started",
            "poll": f"/api/jobs/runs?job_id={job_id}&limit=1",
        }

    @router.get("/api/strategies/{slug}/job", tags=["strategy"])
    def get_strategy_job(slug: str) -> dict[str, Any]:
        """读取某战法绑定的定时选股 job；没有则返回空配置。"""
        job_name = f"screen:{slug}"
        with _ops() as store:
            job = store.get_job_by_name(job_name)
        if job is None:
            return {"slug": slug, "bound": False}
        return {"slug": slug, "bound": True, **job}

    @router.put("/api/strategies/{slug}/job", tags=["strategy"])
    def upsert_strategy_job(
        slug: str, payload: StrategyJobConfig, _write: None = write_guard
    ) -> dict[str, Any]:
        """给战法绑定（或更新）一条定时选股任务。

        配置写进 job.config_json，execute_screen 已支持 top_n 和
        record_candidates（= auto_review）。trading_days 用于回测范围，
        不影响实时选股，留在 config 里供将来的自动验证任务消费。
        """
        try:
            from src.ops import OpsError
            from src.ops import SchedulerError, validate_cron
        except ImportError as exc:
            raise missing_dependency(exc) from exc

        # 先校验战法存在
        try:
            from src.strategy import get as get_strategy
        except ImportError as exc:
            raise missing_dependency(exc) from exc
        try:
            get_strategy(slug)
        except Exception as exc:
            raise HTTPException(status_code=404, detail=f"未知战法：{slug}") from exc

        if payload.cron:
            try:
                validate_cron(payload.cron)
            except SchedulerError as exc:
                raise HTTPException(status_code=422, detail=str(exc)) from exc

        job_name = f"screen:{slug}"
        config = {
            "strategy": slug,
            "record_candidates": payload.auto_review,
            "top_n": payload.top_n,
            "trading_days": payload.trading_days,
            "hold_days": payload.hold_days,
            "stop_loss_pct": payload.stop_loss_pct,
            "provider": payload.provider.strip(),
            "model": payload.model.strip(),
            "thinking": payload.thinking.strip(),
            "use_ai_pick": payload.use_ai_pick,
        }

        with _ops() as store:
            existing = store.get_job_by_name(job_name)
            try:
                if existing is None:
                    job_id = store.create_job(
                        name=job_name, kind="screen",
                        cron=payload.cron, config=config, enabled=payload.enabled,
                    )
                else:
                    job_id = existing["id"]
                    store.update_job(
                        job_id, cron=payload.cron, config=config, enabled=payload.enabled,
                    )
            except OpsError as exc:
                raise HTTPException(status_code=422, detail=str(exc)) from exc
            job = store.get_job(job_id)

        _reload_scheduler()
        return {"slug": slug, "bound": True, **(job or {})}

    @router.delete("/api/strategies/{slug}/job", tags=["strategy"])
    def unbind_strategy_job(slug: str, _write: None = write_guard) -> dict[str, bool]:
        """解除战法的定时选股绑定。"""
        job_name = f"screen:{slug}"
        with _ops() as store:
            job = store.get_job_by_name(job_name)
            if job is None:
                raise HTTPException(status_code=404, detail=f"战法 {slug} 没有绑定定时任务")
            store.delete_job(job["id"])
        _reload_scheduler()
        return {"removed": True}

    @router.get("/api/screen/history", tags=["strategy"])
    def screen_history(
        strategy: str = Query(min_length=1, max_length=64),
        start: str | None = Query(default=None, pattern=r"^\d{4}-\d{2}-\d{2}$"),
        end: str | None = Query(default=None, pattern=r"^\d{4}-\d{2}-\d{2}$"),
        limit: int = Query(default=200, ge=1, le=1000),
    ) -> dict[str, Any]:
        """按战法查历史选股记录（从账本候选池读取）。"""
        with _palace() as palace:
            items = palace.candidates_by_strategy(
                strategy, start=start, end=end, limit=limit
            )
        # 按日期分组，前端方便展示
        by_date: dict[str, list[dict]] = {}
        for item in items:
            by_date.setdefault(item["date"], []).append(item)
        return {
            "strategy": strategy,
            "total": len(items),
            "dates": sorted(by_date.keys(), reverse=True),
            "by_date": by_date,
        }

    @router.get("/api/screen/today", tags=["strategy"])
    def screen_today(
        strategy: str = Query(min_length=1, max_length=64),
        force_sync: bool = Query(default=False),
    ) -> dict[str, Any]:
        """取当天最新选股结果（准实时）。

        工作流：先看行情仓最新日期，如果今天（或最近交易日）的行情已有
        且本地 screen 可运行，就直接 screen；否则先触发一次轻量同步（
        limit=200，空仓时先刷新证券列表）再 screen。
        慢 1-2 分钟可接受。
        """
        try:
            from src.market import DataQualityError
            from src.strategy import screen as run_screen
            from src.strategy.domain.base import StrategyError
        except ImportError as exc:
            raise missing_dependency(exc) from exc

        # 如果 force_sync 或行情仓数据陈旧 / 空仓，先做轻量同步
        synced = False
        sync_note = ""
        if force_sync or should_sync_today(market_db):
            try:
                from src.ops.application.jobs import JobContext, execute_sync

                ctx = JobContext(market_db=market_db)
                refresh_instruments = force_sync
                with ctx.market() as store:
                    if not store.list_instruments():
                        refresh_instruments = True
                report = execute_sync(
                    {
                        "workers": 6,
                        "interval": 0.1,
                        "with_factors": True,
                        "refresh_instruments": refresh_instruments,
                        # 请求内不做全市场同步，避免 nginx 60s 超时；
                        # 全量交给运维页 / 定时任务。
                        "limit": 200,
                    },
                    ctx,
                )
                synced = True
                sync_note = (
                    f"同步 {report.get('succeeded', 0)} 只，"
                    f"跳过 {report.get('skipped', 0)} 只"
                )
            except Exception as exc:
                sync_note = f"同步失败（{exc}），使用本地数据"

        with _market() as store:
            try:
                result = run_screen(
                    store,
                    strategy,
                    universe=None,  # 默认 default_a_share：剔 ST、无北交
                )
            except DataQualityError as exc:
                raise HTTPException(
                    status_code=422,
                    detail=f"数据体检未通过，已拒绝选股：{exc}",
                    headers={"X-Data-Health": "blocked"},
                ) from exc
            except StrategyError as exc:
                raise HTTPException(status_code=422, detail=str(exc)) from exc

        return {
            "strategy": result.strategy_slug,
            "trade_date": result.trade_date,
            "entry_timing": result.entry_timing,
            "universe_size": result.universe_size,
            "elapsed_seconds": round(result.elapsed_seconds, 3),
            "picks": result.picks,
            "universe": result.universe,
            "universe_funnel": result.universe_funnel,
            "synced": synced,
            "sync_note": sync_note,
        }

    @router.get("/api/strategies/{slug}/doc", tags=["strategy"])
    def get_strategy_doc(slug: str) -> dict[str, Any]:
        with _ops() as store:
            doc = store.get_strategy_doc(slug)
        return doc or {}

    @router.put("/api/strategies/{slug}/doc", tags=["strategy"])
    def upsert_strategy_doc(slug: str, payload: StrategyDocUpsert, _write: None = write_guard) -> dict[str, Any]:
        with _ops() as store:
            store.upsert_strategy_doc(slug, **payload.model_dump())
            return store.get_strategy_doc(slug) or {}

    @router.get("/api/insights/decay", tags=["insights"])
    def strategy_decay(window: int = Query(default=20, ge=5, le=100),
                       baseline: int = Query(default=100, ge=20, le=500)) -> list[dict[str, Any]]:
        """各战法滚动胜率 vs 历史基线，发现正在失效的策略。"""
        try:
            from src.review.application.decay import check_all_decay
        except ImportError as exc:
            raise missing_dependency(exc) from exc
        with _palace() as palace:
            return [r.to_dict() for r in check_all_decay(palace, window=window, baseline_window=baseline)]

    @router.get("/api/insights/overlap", tags=["insights"])
    def strategy_overlap(days: int = Query(default=60, ge=10, le=250)) -> list[dict[str, Any]]:
        """战法两两 Jaccard 重叠度——发现隐性加杠杆。"""
        try:
            from src.review.application.overlap import compute_overlap
        except ImportError as exc:
            raise missing_dependency(exc) from exc
        with _palace() as palace:
            return [r.to_dict() for r in compute_overlap(palace, days=days)]

    @router.get("/api/strategies/{slug}/audit", tags=["strategy"])
    def audit_strategy_api(slug: str) -> dict[str, Any]:
        """对策略做静态前视偏差审计（AST 层）。"""
        try:
            from src.strategy import audit_strategy, get
            from src.strategy.domain.base import StrategyError
        except ImportError as exc:
            raise missing_dependency(exc) from exc
        try:
            engine = get(slug)
        except StrategyError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        return audit_strategy(engine).to_dict()

    return router
