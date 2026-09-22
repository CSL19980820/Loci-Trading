"""股票智能体HTTP边界：租户私有路径、不在请求中等待模型、分页读取。"""
import logging
import sqlite3
from contextlib import contextmanager
from datetime import date
from typing import Annotated, Literal

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Query
from pydantic import BaseModel, ConfigDict, Field

from src.ledger import StockAgentStore, StockAgentConflict, GuardianDiaryStore, mark_guardian_account, guardian_position_policy
from src.ops.application.jobs.stock_agent import research_scope, run_manual
from src.ops.application.stock_agent_service import (
    agent_time, ensure_stock_agent_jobs, public_profile, validate_agent_config, stock_agent_templates,
)
from src.ops.domain.stock_agent import StockAgentConfig, DiaryRetention
from src.ops.infrastructure.store import OpsStore, OpsError
from src.shared.tenancy import current_tenant

logger = logging.getLogger(__name__)


class UpdateAgent(BaseModel):
    model_config = ConfigDict(extra="forbid")
    revision: int = Field(ge=1, strict=True)
    config: StockAgentConfig


class AgentFunds(BaseModel):
    model_config = ConfigDict(extra="forbid")
    amount_cents: int = Field(ge=1, le=100_000_000_000, strict=True)
    request_id: str = Field(min_length=8, max_length=80, pattern=r"^[a-zA-Z0-9_-]+$")


class AgentRun(BaseModel):
    model_config = ConfigDict(extra="forbid")
    phase: Literal["review", "premarket", "auction", "intraday"]
    research_date: date | None = None
    request_id: str = Field(min_length=8, max_length=80, pattern=r"^[a-zA-Z0-9_-]+$")


@contextmanager
def api_errors():
    try:
        yield
    except KeyError as exc:
        raise HTTPException(404, str(exc).strip("'")) from exc
    except StockAgentConflict as exc:
        raise HTTPException(409, str(exc)) from exc
    except (ValueError, LookupError) as exc:
        raise HTTPException(422, str(exc)) from exc
    except (sqlite3.Error, OpsError) as exc:
        logger.warning("智能体存储操作失败", exc_info=True)
        raise HTTPException(503, "智能体存储暂时不可用；未确认的操作请刷新核对，追加资金重试需沿用原请求号") from exc


def build_stock_agents_router(*, write_dependency, scheduler_getter=None) -> APIRouter:
    router = APIRouter(prefix="/api/ops/stock-agents", tags=["stock-agents"])
    Write = Annotated[object, Depends(write_dependency)]

    def sync_jobs(ops, ledger, profile):
        try:
            ensure_stock_agent_jobs(ops, palace_path=str(ledger.db_path))
            scheduler = scheduler_getter() if scheduler_getter else None
            if scheduler is not None and getattr(scheduler, "running", False):
                scheduler.reload()
        except Exception as exc:
            logger.warning("智能体日程同步失败", exc_info=True)
            if profile["config"]["enabled"]:
                ledger.update_config(profile["id"], {**profile["config"], "enabled": False}, revision=profile["revision"])
            raise HTTPException(503, "配置已保存，但日程同步失败；智能体保持暂停，请刷新后重新启用") from exc

    @router.get("/options")
    def options():
        with api_errors(), OpsStore(None) as ops:
            return {"templates": stock_agent_templates(ops), "strategies": [], "timezone": "Asia/Shanghai"}

    @router.get("")
    def list_agents(include_archived: bool = False):
        with api_errors(), StockAgentStore() as ledger:
            return {"items": [public_profile(row, summary=True) for row in ledger.list_profiles(include_archived=include_archived)],
                    "as_of": agent_time().isoformat()}

    @router.post("", status_code=201)
    def create_agent(payload: StockAgentConfig, _write: Write):
        with api_errors(), OpsStore(None) as ops, StockAgentStore() as ledger:
            config = validate_agent_config(ops, payload)
            profile = ledger.create(config)
            sync_jobs(ops, ledger, profile)
            return public_profile(profile)

    @router.get("/guardian/overview")
    def guardian_overview(compact: bool = False):
        from src.ops.application.guardian_config import get_config
        with api_errors(), OpsStore(None) as ops, GuardianDiaryStore() as diary:
            config = get_config(ops)
            state = mark_guardian_account(diary.ledger.state(), {}, agent_time())
            if compact:
                return {"config": {key: config.get(key) for key in ("enabled", "provider", "model")},
                        "state": {key: state.get(key) for key in ("equity_cents", "total_pnl_cents", "valuation_at", "stale_codes")},
                        "position_count": len(state["positions"]), "runs": diary.latest()}
            return {"config": {key: config.get(key) for key in ("enabled", "provider", "model")},
                    "state": state, "runs": diary.latest(), "stats": diary.stats(),
                    "position_policy": guardian_position_policy(state, agent_time())}

    @router.get("/guardian/storage")
    def guardian_storage():
        with api_errors(), GuardianDiaryStore() as diary:
            return diary.stats()

    @router.put("/guardian/storage")
    def guardian_storage_save(payload: DiaryRetention, _write: Write):
        with api_errors(), GuardianDiaryStore() as diary:
            diary.save_preferences(payload.model_dump())
            return diary.stats()

    @router.post("/guardian/cleanup")
    def guardian_cleanup(_write: Write, dry_run: bool = True):
        with api_errors(), GuardianDiaryStore() as diary:
            return diary.compact(force=True, dry_run=dry_run)

    @router.get("/{agent_id}")
    def get_agent(agent_id: str):
        with api_errors(), StockAgentStore() as ledger:
            return public_profile(ledger.get(agent_id))

    @router.put("/{agent_id}")
    def update_agent(agent_id: str, payload: UpdateAgent, _write: Write):
        with api_errors(), OpsStore(None) as ops, StockAgentStore() as ledger:
            current = public_profile(ledger.get(agent_id))["config"]
            # 旧客户端没有分场景字段；缺省保留，显式空字符串才表示回退或清空。
            preserved = {key: current.get(key, "") for key in ("common_prompt", "premarket_prompt", "review_prompt")
                         if key not in payload.config.model_fields_set}
            config = validate_agent_config(ops, payload.config.model_copy(update=preserved))
            profile = ledger.update_config(agent_id, config, revision=payload.revision)
            sync_jobs(ops, ledger, profile)
            return public_profile(profile)

    @router.post("/{agent_id}/funds")
    def deposit(agent_id: str, payload: AgentFunds, _write: Write):
        with api_errors(), StockAgentStore() as ledger:
            return public_profile(ledger.deposit(agent_id, payload.amount_cents, payload.request_id))

    @router.post("/{agent_id}/archive")
    def archive(agent_id: str, revision: Annotated[int, Query(ge=1)], _write: Write):
        with api_errors(), OpsStore(None) as ops, StockAgentStore() as ledger:
            ledger.archive(agent_id, revision=revision)
            profile = ledger.get(agent_id)
            sync_jobs(ops, ledger, profile)
            return {"archived": True, "financial_history_preserved": True}

    @router.get("/{agent_id}/history")
    def history(agent_id: str, kind: Literal["runs", "trades", "funding"] = "runs",
                limit: Annotated[int, Query(ge=1, le=100)] = 20,
                offset: Annotated[int, Query(ge=0)] = 0, start: date | None = None, end: date | None = None):
        with api_errors(), StockAgentStore() as ledger:
            ledger.get(agent_id)
            if start and end and start > end:
                raise ValueError("开始日期不能晚于结束日期")
            return ledger.history(agent_id, kind=kind, limit=limit, offset=offset,
                                  start=start.isoformat() if start else None, end=end.isoformat() if end else None)

    @router.get("/{agent_id}/runs/{run_id}")
    def run_detail(agent_id: str, run_id: str):
        with api_errors(), StockAgentStore() as ledger:
            from src.ops.application.trading_report_content import trading_run_sections
            row = ledger.run_detail(agent_id, run_id)
            return {**row, "sections": trading_run_sections(row['detail'], summary=row.get('summary', ''), status=row.get('status', ''))}

    @router.get("/{agent_id}/equity")
    def equity(agent_id: str, limit: Annotated[int, Query(ge=1, le=2000)] = 365):
        with api_errors(), StockAgentStore() as ledger:
            ledger.get(agent_id)
            return ledger.equity(agent_id, limit=limit)

    @router.post("/{agent_id}/cleanup")
    def cleanup(agent_id: str, _write: Write, dry_run: bool = True):
        with api_errors(), StockAgentStore() as ledger:
            return ledger.prune_diary(agent_id, force=True, dry_run=dry_run)

    @router.post("/{agent_id}/run", status_code=202)
    def run(agent_id: str, payload: AgentRun, background: BackgroundTasks, _write: Write):
        with api_errors(), StockAgentStore() as ledger:
            now = agent_time()
            target = payload.research_date.isoformat() if payload.research_date else None
            research_scope(payload.phase, now, target)
            slot = f"{now.date().isoformat()}:manual:{payload.phase}:{target or 'live'}:{payload.request_id}"
            profile = ledger.claim_run(agent_id, slot, payload.phase, now=now)
            if profile is None:
                raise StockAgentConflict("请先启用智能体；本轮可能已存在、正在运行或并发名额已满")
            background.add_task(run_manual, current_tenant(), profile, payload.phase, str(ledger.db_path), target)
            return {"status": "accepted", "run_id": profile["run_id"]}

    return router
