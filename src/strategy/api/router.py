"""策略 / 回测 / 选股历史 / 洞察 HTTP。"""
from __future__ import annotations

import logging
from copy import deepcopy
from datetime import date
from typing import Any, Literal

from fastapi import APIRouter, Depends, HTTPException, Query

from src.shared import api_deps as _api_deps
from src.shared.api_deps import (
    market_hot_store,
    market_store,
    missing_dependency,
    ops_store,
    palace_store,
)
from src.shared.screen_capacity import ScreenCapacityBusy, screen_capacity_permit
from src.strategy.api.schemas import (
    AnalysisRequest,
    ScreenRequest,
    StrategyDocUpsert,
    StrategyJobConfig,
)
from src.strategy.api.screen_universe import effective_screen_universe
from src.shared.paths import market_hot_db
from src.shared.tenancy import spawn_tenant_thread

logger = logging.getLogger(__name__)
# 兼容旧测试/导入；实际 /api/screen/today 由子 router 消费。
# 保留同名入口，避免外部扩展在路由拆分后失效；子路由使用自己的依赖注入。
should_sync_today = _api_deps.should_sync_today


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
    from src.strategy.api.screen_history_router import build_screen_history_router
    from src.strategy.api.version_router import build_strategy_version_router
    from src.strategy.api.screen_run_router import build_screen_run_router
    from src.strategy.api.screen_today_router import build_screen_today_router

    router.include_router(build_screen_history_router(palace_db=palace_db))
    router.include_router(
        build_screen_today_router(
            write_dependency=write_dependency,
            market_db=market_db,
            palace_db=palace_db,
        )
    )
    router.include_router(
        build_strategy_version_router(
            write_dependency=write_dependency, market_db=market_db, ops_db=ops_db
        )
    )
    router.include_router(
        build_screen_run_router(
            write_dependency=write_dependency,
            market_db=market_db,
            ops_db=ops_db,
            palace_db=palace_db,
        )
    )

    def _market():
        return market_store(market_db)

    def _hot():
        """选股读滚动热库（近 700 交易日窗口），与全量写库物理隔离。"""
        return market_hot_store(str(market_hot_db()))

    def _screen_capacity_label(strategy: str) -> str:
        """给同步 HTTP 选股的全局容量许可提供可追踪标签。"""
        from src.shared.tenancy import current_tenant, is_primary_tenant

        slug = str(strategy or "?")
        return f"http-sync:{slug}" if is_primary_tenant() else f"http-sync:[{current_tenant()}] {slug}"

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

    @router.post("/api/strategies/screen", tags=["strategy"])
    def run_screen(payload: ScreenRequest, _write: None = write_guard) -> dict[str, Any]:
        try:
            from src.market import DataQualityError
            from src.strategy import screen
            from src.strategy.application.persist import persist_screen_candidates
            from src.strategy.application.screen_dates import resolve_screen_window
            from src.strategy.domain.base import StrategyError
        except ImportError as exc:
            raise missing_dependency(exc) from exc

        win_start, win_end = resolve_screen_window(
            date=payload.date, start=payload.start, end=payload.end
        )
        if win_start and win_end and win_start != win_end:
            raise HTTPException(
                status_code=400,
                detail="多日选股请使用异步接口 POST /api/screen/run",
            )
        trade_date = win_end or payload.date
        universe = effective_screen_universe(
            payload.strategy, payload.universe, ops_db=ops_db
        )

        # 与 screen_run / job:screen 对齐：默认镜像后读热库；requires_full_history、
        # 镜像失败、或目标日的预热日历不在热库窗口内时回退全量库。
        engine = None
        try:
            from src.strategy import get as _get_strategy

            engine = _get_strategy(payload.strategy)
            needs_full = bool(getattr(engine, "requires_full_history", False))
        except Exception:
            needs_full = False

        # 预热长度**先算、算不出就 422**：那是战法定义的问题，不是「热库不可用」。混进
        # 下面那个 except 会把战法配置错误藏成一次「安静地慢一点」的全量库选股。
        warmup_bars = 0
        if engine is not None and not needs_full:
            from src.strategy.domain.base import signal_history_bars

            try:
                warmup_bars = signal_history_bars(engine, params=payload.params)
            except StrategyError as exc:
                raise HTTPException(status_code=422, detail=str(exc)) from exc

        from contextlib import ExitStack

        with ExitStack() as stack:
            try:
                # 同步端点不能把请求线程排在分钟级任务后面；容量已满时让调用方
                # 得到可重试的 429，异步入口才使用可取消的长队列。
                stack.enter_context(
                    screen_capacity_permit(
                        label=_screen_capacity_label(payload.strategy),
                        wait_sec=0,
                    )
                )
            except ScreenCapacityBusy as exc:
                raise HTTPException(
                    status_code=429,
                    detail=str(exc),
                    headers={"Retry-After": "5"},
                ) from exc
            full = stack.enter_context(_market())
            store = full
            # 取不到 engine 就算不出预热长度；宁可慢走全量库，也不静默少票。
            if engine is not None and not needs_full:
                try:
                    from src.market import hot_fallback_reason, mirror_recent_to_hot

                    hot = stack.enter_context(_hot())
                    mirror_recent_to_hot(full, hot)
                    # trade_date 允许是历史单日，旧判据只看相对今天的窗口深度与末日会一律放行；
                    # 本端点默认 record_candidates=true，静默少票会直接污染候选池的 T+N 胜率。
                    reason = hot_fallback_reason(
                        full,
                        hot,
                        trade_date=str(trade_date or date.today().isoformat()),
                        warmup_bars=warmup_bars,
                    )
                    if reason:
                        logger.warning("%s，回退全量库选股", reason)
                        store = full
                    else:
                        store = hot
                except Exception as exc:
                    logger.warning("镜像热库失败，回退全量库选股：%s", exc)
                    store = full
            try:
                result = screen(
                    store, payload.strategy, trade_date=trade_date,
                    params=payload.params, codes=payload.codes,
                    universe=universe,
                    health_check=not payload.skip_health_check,
                )
            except DataQualityError as exc:
                raise HTTPException(
                    status_code=422,
                    detail=f"数据体检未通过，已拒绝选股：{exc}",
                    headers={"X-Data-Health": "blocked"},
                ) from exc
            except StrategyError as exc:
                raise HTTPException(status_code=422, detail=str(exc)) from exc
            names = {
                item["code"]: item["name"] for item in store.list_instruments(status="")
            } if payload.record_candidates else {}

        body: dict[str, Any] = {
            "strategy": result.strategy_slug,
            "strategy_revision": result.strategy_revision,
            "trade_date": result.trade_date,
            "entry_timing": result.entry_timing,
            "universe_size": result.universe_size,
            "elapsed_seconds": round(result.elapsed_seconds, 3),
            "params": result.params,
            "effective_params": result.effective_params,
            "picks": result.picks,
            "watch_picks": result.watch_picks,
            "health": result.health,
            "universe": result.universe,
            "universe_funnel": result.universe_funnel,
            "data_snapshot": result.data_snapshot,
        }
        if payload.record_candidates:
            body["recorded"] = persist_screen_candidates(
                result,
                palace_db=palace_db,
                names=names,
                pool_id=payload.pool_id,
                top_n=payload.top_n,
                source="api:screen",
            )
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

        with _ops() as store:
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
            if job is None:
                raise HTTPException(status_code=500, detail="即时分析任务创建后无法读取")
            # worker 只能使用本次请求的快照，不能按可变 job_id 延迟读取下一次请求的配置。
            job_snapshot = deepcopy(job)
            run_id = store.start_run(job_snapshot, trigger="api")

        def worker() -> None:
            # 独立连接：SQLite 连接不能跨线程共享。
            with OpsStore(ops_db) as own:
                run_job(
                    own,
                    job_snapshot,
                    context=JobContext(
                        market_db=market_db,
                        market_hot_db=str(market_hot_db()),
                        ops_store=own,
                        palace_db=palace_db,
                    ),
                    trigger="api",
                    run_id=run_id,
                )

        try:
            # 必须走 spawn_tenant_thread：worker 里 run_job 会经 JobContext 落 job_runs、
            # 并按当前租户解析选股产物目录。裸 threading.Thread 丢掉 ContextVar 之后，
            # 即时对比 / 退出扫描的运行记录会写进**主租户**的运维库，发起人那边只看到
            # 一条永远停在 running 的 run（他的库里没有收口写入）。别改回去。
            spawn_tenant_thread(worker, name=f"analysis-{kind}-{run_id}")
        except Exception as exc:
            message = f"后台分析启动失败：{type(exc).__name__}: {exc}"
            logger.exception("即时分析任务 %s 无法启动", run_id)
            try:
                with _ops() as store:
                    store.finish_run(run_id, status="failed", error=message)
            except Exception:
                logger.exception("即时分析任务 %s 启动失败后无法收敛运行记录", run_id)
            raise HTTPException(status_code=503, detail=message) from exc
        return {
            "job_id": job_id,
            "run_id": run_id,
            "kind": kind,
            "status": "started",
            "poll": f"/api/jobs/runs?job_id={job_id}&run_id={run_id}",
        }

    @router.get("/api/strategies/{slug}/job", tags=["strategy"])
    def get_strategy_job(slug: str) -> dict[str, Any]:
        """读取某战法绑定的定时选股 job；没有则返回空配置。"""
        from src.ops.application.trading_schedule import preview_trading_runs

        job_name = f"screen:{slug}"
        with _ops() as store:
            job = store.get_job_by_name(job_name)
        if job is None:
            return {"slug": slug, "bound": False, "next_runs": []}
        cfg = job.get("config") if isinstance(job.get("config"), dict) else {}
        schedule = cfg.get("schedule") if isinstance(cfg.get("schedule"), dict) else {}
        mode = str(schedule.get("mode") or "off")
        next_runs: list[str] = []
        if mode in {"once", "interval"}:
            try:
                next_runs = preview_trading_runs(
                    mode,  # type: ignore[arg-type]
                    run_hour=int(schedule.get("run_hour", 15)),
                    run_minute=int(schedule.get("run_minute", 30)),
                    interval_minutes=int(schedule.get("interval_minutes", 10)),
                    window_start_hour=int(schedule.get("window_start_hour", 9)),
                    window_start_minute=int(schedule.get("window_start_minute", 30)),
                    window_end_hour=int(schedule.get("window_end_hour", 14)),
                    window_end_minute=int(schedule.get("window_end_minute", 50)),
                    limit=1 if mode == "once" else 5,
                )
            except Exception:
                next_runs = []
        return {"slug": slug, "bound": True, "next_runs": next_runs, **job}

    @router.put("/api/strategies/{slug}/job", tags=["strategy"])
    def upsert_strategy_job(
        slug: str, payload: StrategyJobConfig, _write: None = write_guard
    ) -> dict[str, Any]:
        """给战法绑定（或更新）一条定时选股任务。

        配置写进 job.config_json，execute_screen 已支持 top_n、universe 和
        record_candidates（= auto_review）。schedule_mode 非空时服务端合成 cron。
        """
        try:
            from src.ops import OpsError
            from src.ops import SchedulerError, validate_cron
            from src.ops.application.trading_schedule import (
                TradingScheduleError,
                compose_trading_cron,
                preview_trading_runs,
                schedule_dict_from_payload,
            )
        except ImportError as exc:
            raise missing_dependency(exc) from exc

        try:
            from src.strategy import get as get_strategy
        except ImportError as exc:
            raise missing_dependency(exc) from exc
        try:
            get_strategy(slug)
        except Exception as exc:
            raise HTTPException(status_code=404, detail=f"未知战法：{slug}") from exc

        job_name = f"screen:{slug}"
        # 关定时：剔除绑定，不留 enabled=false 尸位（工坊定时台只读展示绑定）
        if payload.schedule_mode == "off":
            with _ops() as store:
                existing = store.get_job_by_name(job_name)
                if existing is not None:
                    store.delete_job(existing["id"])
            _reload_scheduler()
            return {"slug": slug, "bound": False, "next_runs": []}

        cron = payload.cron.strip()
        enabled = payload.enabled
        schedule = schedule_dict_from_payload(payload)
        if payload.schedule_mode is not None:
            try:
                cron = compose_trading_cron(
                    payload.schedule_mode,
                    run_hour=payload.run_hour,
                    run_minute=payload.run_minute,
                    interval_minutes=payload.interval_minutes,
                    window_start_hour=payload.window_start_hour,
                    window_start_minute=payload.window_start_minute,
                    window_end_hour=payload.window_end_hour,
                    window_end_minute=payload.window_end_minute,
                )
            except TradingScheduleError as exc:
                raise HTTPException(status_code=422, detail=str(exc)) from exc
            enabled = True

        if cron:
            try:
                validate_cron(cron)
            except SchedulerError as exc:
                raise HTTPException(status_code=422, detail=str(exc)) from exc

        config: dict[str, Any] = {
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
            "push_wecom": bool(payload.push_wecom),
            "schedule": schedule,
        }
        if payload.universe is not None:
            config["universe"] = payload.universe.model_dump(exclude_none=True)

        with _ops() as store:
            existing = store.get_job_by_name(job_name)
            try:
                if existing is None:
                    job_id = store.create_job(
                        name=job_name,
                        kind="screen",
                        cron=cron,
                        config=config,
                        enabled=enabled,
                    )
                else:
                    job_id = existing["id"]
                    # 详情表单未承载快照门禁/参数覆盖等配置，保存时须保留。
                    config = {**(existing.get("config") or {}), **config}
                    store.update_job(
                        job_id, cron=cron, config=config, enabled=enabled,
                    )
            except OpsError as exc:
                raise HTTPException(status_code=422, detail=str(exc)) from exc
            job = store.get_job(job_id)

        _reload_scheduler()
        next_runs: list[str] = []
        if schedule.get("mode") in {"once", "interval"}:
            try:
                next_runs = preview_trading_runs(
                    schedule["mode"],
                    run_hour=int(schedule["run_hour"]),
                    run_minute=int(schedule["run_minute"]),
                    interval_minutes=int(schedule["interval_minutes"]),
                    window_start_hour=int(schedule["window_start_hour"]),
                    window_start_minute=int(schedule["window_start_minute"]),
                    window_end_hour=int(schedule["window_end_hour"]),
                    window_end_minute=int(schedule["window_end_minute"]),
                    limit=1 if schedule["mode"] == "once" else 5,
                )
            except TradingScheduleError:
                next_runs = []
        return {"slug": slug, "bound": True, "next_runs": next_runs, **(job or {})}

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
        with _palace() as palace, _market() as market:
            return [r.to_dict() for r in check_all_decay(
                palace, window=window, baseline_window=baseline, market=market
            )]

    @router.get("/api/insights/overlap", tags=["insights"])
    def strategy_overlap(days: int = Query(default=60, ge=10, le=250)) -> list[dict[str, Any]]:
        """选股信号重叠：多战法同日撞车（Jaccard + 常撞代码）。不算持仓风险。"""
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
