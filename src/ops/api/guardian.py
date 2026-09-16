"""守护设置与统一状态；不在 HTTP 请求内等待模型。"""
from typing import Annotated
from typing import Literal

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Query
from pydantic import BaseModel, ConfigDict, Field

from src.ledger import GuardianStore, mark_guardian_account
from src.ops.application.guardian_config import DEFAULT_PROMPT, get_job, get_config, save_config
from src.ops.application.guardian_tools import data_source
from src.ops.application.guardian_context import active_strategies, observation_snapshot
from src.ops.infrastructure.store import OpsError, OpsStore
from src.shared.tenancy import current_tenant, tenant_scope


def run_guardian_once(tenant: str) -> None:
    from src.ops.application.jobs import JobContext, run_job
    with tenant_scope(tenant), OpsStore(None) as store:
        job = get_job(store)
        if job and job["enabled"]:
            run_job(store, job, context=JobContext(ops_store=store), trigger="api")


class GuardianConfigIn(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    enabled: bool = False
    provider: str = Field(default="", max_length=200)
    model: str = Field(default="", max_length=200)
    prompt: str = Field(default=DEFAULT_PROMPT, min_length=1, max_length=16000)
    strategies: list[str] = Field(default_factory=list, max_length=100)
    notify: bool = True


def run_guardian_review_once(tenant: str, period: str, day: str | None) -> None:
    from src.ops.application.jobs import JobContext, run_job
    from src.ops.application.ensure_guardian_review_jobs import ensure_guardian_review_jobs, REVIEW_JOBS
    with tenant_scope(tenant), OpsStore(None) as store:
        ensure_guardian_review_jobs(store)
        job = store.get_job_by_name(REVIEW_JOBS[period][0])
        if job:
            job = {**job, "config": {**job["config"], **({"date": day} if day else {})}}
            run_job(store, job, context=JobContext(ops_store=store), trigger="api")


class GuardianReviewIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    period: Literal["premarket", "daily", "weekly"]
    date: str | None = None


def build_guardian_router(*, write_dependency, scheduler_getter=None) -> APIRouter:
    router = APIRouter(prefix="/api/ops/guardian", tags=["guardian"])
    from src.ops.api.guardian_consult import build_consult_router
    router.include_router(build_consult_router(write_dependency))

    @router.get("")
    def get_guardian() -> dict:
        # 不接收组合根的主租户 db 路径，始终由请求租户惰性解析。
        with OpsStore(None) as store, GuardianStore() as ledger:
            job = get_job(store)
            recent = ledger.recent()
            for run in recent:
                run.pop("result_json", None)
                run["result"].pop("usage", None)
            from datetime import datetime
            from zoneinfo import ZoneInfo
            state = mark_guardian_account(ledger.state(), {}, datetime.now(ZoneInfo("Asia/Shanghai")))
            reports = [{"report_key": r["report_key"], "period": r["period"], "trade_date": r["trade_date"], "status": r["status"],
                        "summary": r["result"].get("analysis", {}).get("summary"), "error": r["result"].get("error"),
                        "created_at": r["result"].get("created_at"), "notify": r["result"].get("notify")}
                       for r in ledger.reports()]
            from src.ops.application.notify_calendar import notification_silence_reason
            return {"config": get_config(store), "default_prompt": DEFAULT_PROMPT, "data_source": data_source(), "notification_silence": notification_silence_reason(),
                    "active_strategies": [{"slug": row["slug"], "name": row.get("name", row["slug"])} for row in active_strategies(store)],
                    "job_id": job["id"] if job else None, "state": state, "runs": recent,
                    "delivery": ledger.notice_backlog(),
                    "trades": ledger.trades(), "performance": ledger.performance(), "reports": reports,
                    **observation_snapshot(state)}

    @router.get("/trades")
    def get_trades(limit: int = Query(default=50, ge=1, le=200), offset: int = Query(default=0, ge=0)) -> dict:
        with GuardianStore() as ledger:
            return ledger.trades(limit=limit, offset=offset)

    @router.get("/reviews/{period}/{day}")
    def get_review(period: str, day: str) -> dict:
        with GuardianStore() as ledger:
            report = ledger.report(period, day)
            if report is None:
                raise HTTPException(404, "尚无该报告")
            report["result"].pop("tool_evidence", None)
            report["result"].pop("_notify_started", None)
            result = report["result"]
            if result.get('facts') and result.get('analysis'):
                from src.market import MarketStore
                from src.shared.paths import market_db
                from src.ops.application.guardian_review_format import report_sections, report_body
                codes = [p['code'] for p in result['analysis'].get('plans', [])]
                if codes:
                    with MarketStore(market_db()) as market:
                        result['facts']['stock_names'] = {code: row['name'] for code, row in market.instruments_meta(codes).items()}
                result['sections'] = report_sections(result['facts'], result['analysis'])
                result['body'] = report_body(result['facts'], result['analysis'])
            return report

    @router.post("/reviews/run", status_code=202)
    def generate_review(payload: GuardianReviewIn, background: BackgroundTasks, _write: Annotated[object, Depends(write_dependency)]) -> dict:
        from datetime import datetime
        from zoneinfo import ZoneInfo
        from src.ops.application.guardian_review_data import report_window
        with OpsStore(None) as store:
            if not get_config(store)["enabled"]:
                raise HTTPException(409, "请先启动自主交易员")
        now = datetime.now(ZoneInfo("Asia/Shanghai"))
        try:
            from src.market import calendar_trading_day
            if not calendar_trading_day(payload.date or now.date().isoformat()):
                raise ValueError('交易所休市，系统静默')
            report_window(payload.period, payload.date or now.date().isoformat(), now)
        except (ValueError, LookupError) as exc:
            raise HTTPException(409, str(exc)) from exc
        background.add_task(run_guardian_review_once, current_tenant(), payload.period, payload.date)
        return {"status": "accepted", "report_key": f"{payload.period}:{payload.date or now.date().isoformat()}"}

    @router.put("")
    def put_guardian(payload: GuardianConfigIn, _write: Annotated[object, Depends(write_dependency)]) -> dict:
        try:
            with OpsStore(None) as store:
                save_config(store, payload.model_dump(exclude_unset=True))
        except OpsError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        scheduler = scheduler_getter() if scheduler_getter else None
        if scheduler is not None and getattr(scheduler, "running", False):
            scheduler.reload()
        return get_guardian()

    @router.post("/scan", status_code=202)
    def scan_guardian(background: BackgroundTasks, _write: Annotated[object, Depends(write_dependency)]) -> dict:
        with OpsStore(None) as store:
            if not get_config(store)["enabled"]:
                raise HTTPException(status_code=409, detail="请先启动并保存交易员设置")
        from src.ops.application.guardian_session import in_review_window
        from src.market import calendar_trading_day
        from datetime import datetime
        from zoneinfo import ZoneInfo
        try:
            if not calendar_trading_day(datetime.now(ZoneInfo('Asia/Shanghai')).date().isoformat()):
                raise HTTPException(409, '交易所休市，系统静默')
        except ValueError as exc:
            raise HTTPException(409, str(exc)) from exc
        if not in_review_window(datetime.now(ZoneInfo('Asia/Shanghai'))):
            raise HTTPException(status_code=409, detail="当前非交易时段，自主交易员将在开市后继续")
        background.add_task(run_guardian_once, current_tenant())
        return {"status": "accepted"}

    return router
