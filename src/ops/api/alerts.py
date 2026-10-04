"""价格提醒 HTTP；与任何模拟交易引擎独立。"""
from __future__ import annotations
from typing import Any
from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, ConfigDict, Field
from src.shared.api_deps import ops_store

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


def build_alerts_router(*, write_dependency, ops_db: str | None = None, scheduler_getter=None) -> APIRouter:
    router = APIRouter()
    write_guard = Depends(write_dependency)

    def _ops():
        return ops_store(ops_db)

    @router.get("/api/ops/alert-rules", tags=["alerts"])
    def list_alert_rules() -> list[dict[str, Any]]:
        with _ops() as store:
            return store.list_alert_rules()

    @router.put("/api/ops/alert-rules", tags=["alerts"])
    def put_alert_rule(payload: AlertRuleIn, _write: None = write_guard) -> dict[str, Any]:
        with _ops() as store:
            return store.upsert_alert_rule(payload.model_dump())

    @router.delete("/api/ops/alert-rules/{rule_id}", tags=["alerts"])
    def delete_alert_rule(rule_id: str, _write: None = write_guard) -> dict[str, bool]:
        with _ops() as store:
            ok = store.delete_alert_rule(rule_id)
        if not ok:
            raise HTTPException(status_code=404, detail="规则不存在")
        return {"ok": True}

    @router.get("/api/ops/alert-hits", tags=["alerts"])
    def list_alert_hits(
        rule_id: str | None = Query(default=None),
        # 裸 int 的 limit 会被原样塞进 SQL 的 LIMIT ?：99999999 就是全表扫 +
        # 无界响应，-1 在 SQLite 里更是「不限行数」。与 jobs.py 的运行历史
        # 端点同口径钳到 1..500。
        limit: int = Query(default=50, ge=1, le=500),
    ) -> list[dict[str, Any]]:
        with _ops() as store:
            return store.list_alert_hits(rule_id=rule_id, limit=limit)

    @router.post("/api/ops/alert-rules/scan", tags=["alerts"])
    def scan_alerts(dry_run: bool = False, _write: None = write_guard) -> dict[str, Any]:
        from src.ops.application.alert_rules import scan_alert_rules

        with _ops() as store:
            return scan_alert_rules(store, dry_run=dry_run)

    return router
