"""纸面量化 + 价格提醒 HTTP。"""
from __future__ import annotations

import logging
import os
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, ConfigDict, Field

from src.shared.api_deps import ops_store

logger = logging.getLogger(__name__)


def _refuse_retired_cabin(slug: str) -> None:
    from src.ops.application.retire_dragon_return import is_retired_paper_cabin

    if is_retired_paper_cabin(slug):
        raise HTTPException(status_code=410, detail="该纸面舱已退役")


def _allow_bypass_gates() -> bool:
    """生产默认禁 bypass；临时开闸需 LOCI_PAPER_ALLOW_BYPASS_GATES=1。"""
    env = (os.environ.get("PALACE_ENV") or "local").strip().lower()
    if env != "production":
        return True
    return os.environ.get("LOCI_PAPER_ALLOW_BYPASS_GATES", "").strip().lower() in {
        "1",
        "true",
        "yes",
        "on",
    }


class AlertRuleIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    id: str | None = None
    code: str
    name: str = ""
    enabled: bool = True
    condition_group: dict[str, Any] = Field(default_factory=dict)
    market_hours_mode: str = "session"
    cooldown_minutes: int = 5
    max_triggers_per_day: int = 10
    repeat_mode: str = "repeat"
    expire_at: str = ""
    plan_id_optional: str = ""
    channel_ids: list[str] = Field(default_factory=list)


class PaperCabinConfigIn(BaseModel):
    model_config = ConfigDict(extra="allow")
    enabled: bool = True
    interval: str = "*/15 9-14 * * mon-fri"
    model: str = ""
    thinking: str = "medium"
    llm_timeout_sec: int = Field(default=1800, ge=120, le=1800)
    follow_wecom: bool = False
    max_layers: float = 4
    min_layer_step: float = 0.5
    ai_apply_paper: bool = True
    ai_mode: str = "suggest"
    allow_actions: list[str] | None = None
    trim_high_min_pnl_pct: float | None = 3.0
    buy_dip_drawdown_pct: float | None = 2.0
    flat_band_pct: float | None = 0.5
    gap_up_chase: bool = False
    auction_allow_open: bool = False
    eod_lookback_days: int = 5
    eod_include_capital_flow: bool = False


class PaperOrderIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    code: str
    action: str
    layers: float = 0.5
    reason: str = ""
    mark_price: float | None = None
    name: str = ""


class ManualOrdersIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    orders: list[PaperOrderIn]
    #: True 时跳过情景/竞价门闩（显式风险自负）；默认过同一套闸门
    bypass_gates: bool = False


class PaperStyleIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    style_md: str = ""
    watch_hints: list[str] = Field(default_factory=list)
    buy_rules: dict[str, Any] = Field(default_factory=dict)


def build_paper_quant_router(
    *,
    write_dependency,
    ops_db: str | None = None,
    scheduler_getter=None,
) -> APIRouter:
    router = APIRouter()
    write_guard = Depends(write_dependency)

    def _ops():
        return ops_store(ops_db)

    def _reload_scheduler() -> None:
        if scheduler_getter is None:
            return
        scheduler = scheduler_getter()
        if scheduler is not None and getattr(scheduler, "running", False):
            try:
                scheduler.reload()
            except Exception:
                logger.exception("reload scheduler after paper cabin config failed")

    @router.get("/api/ops/alert-rules", tags=["paper-quant"])
    def list_alert_rules() -> list[dict[str, Any]]:
        with _ops() as store:
            return store.list_alert_rules()

    @router.put("/api/ops/alert-rules", tags=["paper-quant"])
    def put_alert_rule(payload: AlertRuleIn, _write: None = write_guard) -> dict[str, Any]:
        with _ops() as store:
            return store.upsert_alert_rule(payload.model_dump())

    @router.delete("/api/ops/alert-rules/{rule_id}", tags=["paper-quant"])
    def delete_alert_rule(rule_id: str, _write: None = write_guard) -> dict[str, bool]:
        with _ops() as store:
            ok = store.delete_alert_rule(rule_id)
        if not ok:
            raise HTTPException(status_code=404, detail="规则不存在")
        return {"ok": True}

    @router.get("/api/ops/alert-hits", tags=["paper-quant"])
    def list_alert_hits(
        rule_id: str | None = Query(default=None),
        # 裸 int 的 limit 会被原样塞进 SQL 的 LIMIT ?：99999999 就是全表扫 +
        # 无界响应，-1 在 SQLite 里更是「不限行数」。与 jobs.py 的运行历史
        # 端点同口径钳到 1..500。
        limit: int = Query(default=50, ge=1, le=500),
    ) -> list[dict[str, Any]]:
        with _ops() as store:
            return store.list_alert_hits(rule_id=rule_id, limit=limit)

    @router.post("/api/ops/alert-rules/scan", tags=["paper-quant"])
    def scan_alerts(dry_run: bool = False, _write: None = write_guard) -> dict[str, Any]:
        from src.ops.application.alert_rules import scan_alert_rules

        with _ops() as store:
            return scan_alert_rules(store, dry_run=dry_run)

    @router.get("/api/ops/paper-cabins/{slug}", tags=["paper-quant"])
    def get_cabin(slug: str) -> dict[str, Any]:
        with _ops() as store:
            from src.ops.application.paper_style_memory import ensure_style
            from src.ops.application.retire_dragon_return import is_retired_paper_cabin
            from src.ops.application.unified_monitor_pool import (
                ensure_dragon_cabin_policy,
                get_unified_monitor_pool,
            )

            if is_retired_paper_cabin(slug) and store.get_paper_cabin(slug) is None:
                raise HTTPException(status_code=410, detail="该纸面舱已退役")
            cabin = ensure_dragon_cabin_policy(store, slug)
            if not cabin:
                raise HTTPException(status_code=404, detail="纸面舱不存在")
            positions = store.list_paper_positions(cabin["id"])
            fills = store.list_paper_fills(cabin["id"], limit=40)
            runs = store.list_monitor_runs(slug, limit=20)
            from src.ops.application.jobs.paper_quant_support import _today

            today = _today()
            plan = store.get_nextday_plan(slug, today)
            unified_pool = get_unified_monitor_pool(store, slug=slug, trade_date=today)
            style = ensure_style(store, slug)
            lessons = store.list_paper_lessons(slug, limit=30)
            from src.ops.application.paper_memory_graph import explore_memory

            memory = explore_memory(store, slug, "", max_nodes=30, hops=1)
            return {
                "cabin": cabin,
                "positions": positions,
                "fills": fills,
                "monitor_runs": runs,
                "nextday_plan": plan,
                "unified_pool": unified_pool,
                "style": style,
                "lessons": lessons,
                "memory_graph": {
                    "stats": memory.get("stats"),
                    "summary": memory.get("summary"),
                    "nodes": memory.get("nodes"),
                    "edges": memory.get("edges"),
                },
            }

    @router.get(
        "/api/ops/paper-cabins/{slug}/unified-pool",
        tags=["paper-quant"],
    )
    def get_unified_pool(slug: str) -> dict[str, Any]:
        from src.ops.application.jobs.paper_quant_support import _today
        from src.ops.application.unified_monitor_pool import get_unified_monitor_pool

        with _ops() as store:
            return get_unified_monitor_pool(store, slug=slug, trade_date=_today())

    @router.put("/api/ops/paper-cabins/{slug}/style", tags=["paper-quant"])
    def put_cabin_style(
        slug: str, payload: PaperStyleIn, _write: None = write_guard
    ) -> dict[str, Any]:
        _refuse_retired_cabin(slug)
        with _ops() as store:
            store.ensure_paper_cabin(slug)
            return store.upsert_paper_style(
                slug,
                style_md=payload.style_md,
                watch_hints=payload.watch_hints,
                buy_rules=payload.buy_rules,
                bump_revision=True,
            )

    @router.post("/api/ops/paper-cabins/{slug}/style/absorb", tags=["paper-quant"])
    def absorb_style(slug: str, _write: None = write_guard) -> dict[str, Any]:
        from src.ops.application.paper_style_memory import absorb_lessons_into_style

        _refuse_retired_cabin(slug)
        with _ops() as store:
            store.ensure_paper_cabin(slug)
            return absorb_lessons_into_style(store, slug)

    @router.get("/api/ops/paper-cabins/{slug}/memory/explore", tags=["paper-quant"])
    def explore_cabin_memory(slug: str, q: str = "", max_nodes: int = 24) -> dict[str, Any]:
        from src.ops.application.paper_memory_graph import explore_memory

        _refuse_retired_cabin(slug)
        with _ops() as store:
            store.ensure_paper_cabin(slug)
            return explore_memory(store, slug, q, max_nodes=max(4, min(max_nodes, 60)), hops=1)

    @router.post("/api/ops/paper-cabins/{slug}/memory/rebuild", tags=["paper-quant"])
    def rebuild_cabin_memory(slug: str, _write: None = write_guard) -> dict[str, Any]:
        from src.ops.application.paper_memory_graph import rebuild_graph_from_cabin

        _refuse_retired_cabin(slug)
        with _ops() as store:
            store.ensure_paper_cabin(slug)
            return rebuild_graph_from_cabin(store, slug)

    @router.put("/api/ops/paper-cabins/{slug}/config", tags=["paper-quant"])
    def put_cabin_config(
        slug: str, payload: PaperCabinConfigIn, _write: None = write_guard
    ) -> dict[str, Any]:
        from src.ops.application.ensure_paper_monitor_jobs import ensure_paper_monitor_jobs

        _refuse_retired_cabin(slug)
        with _ops() as store:
            data = payload.model_dump()
            from src.ops.application.unified_monitor_pool import (
                DRAGON_MAX_LAYERS,
                DRAGON_SLUG,
                ensure_dragon_cabin_policy,
            )

            requested_layers = float(data.pop("max_layers", 4) or 4)
            max_layers = DRAGON_MAX_LAYERS if slug == DRAGON_SLUG else requested_layers
            store.update_paper_cabin_limits(slug, max_layers=max_layers)
            updated = store.update_paper_cabin_config(slug, {"paper_quant": data})
            if slug == DRAGON_SLUG:
                updated = ensure_dragon_cabin_policy(store, slug)
            ensure_paper_monitor_jobs(
                store,
                slug,
                enabled=bool(data.get("enabled", True)),
                interval=str(data.get("interval") or "*/15 9-14 * * mon-fri"),
            )
        _reload_scheduler()
        return updated

    @router.post("/api/ops/paper-cabins/{slug}/orders", tags=["paper-quant"])
    def post_manual_orders(
        slug: str, payload: ManualOrdersIn, _write: None = write_guard
    ) -> dict[str, Any]:
        _refuse_retired_cabin(slug)
        from src.market.application.live_cache import get_cached_quotes
        from src.ops.application.nextday_plan import (
            merge_ai_orders_with_gates,
            session_clock,
        )
        from src.ops.application.paper_exec import PaperOrder, execute_orders
        from src.ops.application.jobs.paper_quant_support import (
            _apply_market_gate,
            _paper_quant_config,
            _resolve_market_gate,
            _today,
            resolve_trading_day_gate,
        )

        if payload.bypass_gates and not _allow_bypass_gates():
            raise HTTPException(
                status_code=403,
                detail=(
                    "生产环境禁止 bypass_gates；"
                    "临时开闸请设 LOCI_PAPER_ALLOW_BYPASS_GATES=1"
                ),
            )
        if payload.bypass_gates:
            logger.warning("paper manual orders bypass_gates slug=%s", slug)

        codes = [o.code for o in payload.orders]
        quotes, _, _ = get_cached_quotes(codes)
        raw_orders = [
            PaperOrder(
                code=o.code,
                action=o.action,
                layers=o.layers,
                reason=o.reason or "manual",
                mark_price=o.mark_price,
                name=o.name,
            )
            for o in payload.orders
        ]
        with _ops() as store:
            gate_rejects: list[dict[str, Any]] = []
            orders = raw_orders
            if not payload.bypass_gates:
                today = _today()
                trading_gate = resolve_trading_day_gate(today)
                if not trading_gate.get("is_trading_day"):
                    raise HTTPException(
                        status_code=409,
                        detail=str(
                            trading_gate.get("note")
                            or f"{today} 非交易日，拒绝纸面下单"
                        ),
                    )
                from src.ops.application.paper_exec import BUY_ACTIONS

                # 纯买入且日历缺失 fail-closed：整单 409，便于前端/测试可见
                buy_only = all(
                    str(o.action or "").lower() in BUY_ACTIONS for o in raw_orders
                )
                if (
                    buy_only
                    and raw_orders
                    and not trading_gate.get("buy_execution_allowed")
                ):
                    raise HTTPException(
                        status_code=409,
                        detail=str(
                            trading_gate.get("note")
                            or f"{today} 交易日历缺失，买入 fail-closed"
                        ),
                    )
                plan = store.get_nextday_plan(slug, today) or {}
                items = [
                    item
                    for item in (plan.get("items") or [])
                    if isinstance(item, dict)
                ]
                cabin = store.get_paper_cabin(slug) or {}
                raw_cfg = cabin.get("config")
                cfg = _paper_quant_config(
                    raw_cfg if isinstance(raw_cfg, dict) else {}
                )
                clock = session_clock(
                    auction_allow_open=bool(cfg.get("auction_allow_open"))
                )
                orders, gate_rejects = merge_ai_orders_with_gates(
                    orders,
                    plan_items=items,
                    quotes=quotes,
                    clock=clock,
                    flat_band_pct=float(cfg.get("flat_band_pct") or 0.5),
                )
                if not trading_gate.get("buy_execution_allowed"):
                    kept = []
                    for order in orders:
                        action = str(order.action or "").lower()
                        if action in {"open", "add", "buy_dip"}:
                            gate_rejects.append(
                                {
                                    "code": order.code,
                                    "action": action,
                                    "reason": str(
                                        trading_gate.get("note")
                                        or "交易日历缺失，买入 fail-closed"
                                    ),
                                }
                            )
                        else:
                            kept.append(order)
                    orders = kept
                market_gate = _resolve_market_gate(slug, cfg, store=store)
                orders, mg_rejects = _apply_market_gate(orders, market_gate)
                gate_rejects.extend(mg_rejects)
            result = execute_orders(
                store,
                slug=slug,
                orders=orders,
                quotes=quotes,
                source="manual",
            )
            return {
                "fills": result.fills,
                "rejects": [*gate_rejects, *result.rejects],
                "positions": result.positions,
                "bypass_gates": bool(payload.bypass_gates),
            }

    @router.post("/api/ops/paper-cabins/{slug}/monitor", tags=["paper-quant"])
    def run_monitor_now(slug: str, _write: None = write_guard) -> dict[str, Any]:
        _refuse_retired_cabin(slug)
        from src.ops.application.jobs.context import JobContext
        from src.ops.application.jobs.paper_quant import execute_strategy_monitor

        with _ops() as store:
            return execute_strategy_monitor(
                {"slug": slug, "force": True, "trigger": "api"},
                JobContext(ops_store=store),
            )

    @router.post("/api/ops/paper-cabins/{slug}/eod", tags=["paper-quant"])
    def run_eod_now(slug: str, _write: None = write_guard) -> dict[str, Any]:
        _refuse_retired_cabin(slug)
        from src.ops.application.jobs.context import JobContext
        from src.ops.application.jobs.paper_quant import execute_paper_eod

        with _ops() as store:
            return execute_paper_eod({"slug": slug}, JobContext(ops_store=store))

    @router.post("/api/ops/paper-cabins/{slug}/nextday-plan", tags=["paper-quant"])
    def seed_plan(
        slug: str,
        picks: list[dict[str, Any]] | None = None,
        _write: None = write_guard,
    ) -> dict[str, Any]:
        _refuse_retired_cabin(slug)
        from src.ops.application.jobs.paper_quant import generate_nextday_plan

        with _ops() as store:
            return generate_nextday_plan(
                store, slug=slug, picks=picks or [], source="api"
            )

    return router
