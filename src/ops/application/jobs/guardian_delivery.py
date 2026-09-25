"""Retry durable execution notices without running research or account settlement."""
from __future__ import annotations

from typing import Any

from src.ledger import GuardianStore
from src.ops.application.guardian_config import get_config, managed_guardian_job
from src.ops.application.guardian_delivery import deliver_pending
from src.ops.application.jobs.context import JobContext, JobError, JobSkipped
from src.ops.application.notify_calendar import notification_silence_reason
from src.ops.application.notify_dispatch import dispatch_text

MANAGED_GUARDIAN_DELIVERY = "天才交易员 · 通知补发"
_PREVIOUS_GUARDIAN_DELIVERY = "自主交易员 · 通知补发"


def ensure_guardian_delivery_job(store: Any) -> dict[str, list[str]]:
    cfg = get_config(store)
    job = managed_guardian_job(store, name=MANAGED_GUARDIAN_DELIVERY,
                               previous_name=_PREVIOUS_GUARDIAN_DELIVERY,
                               kind="guardian_delivery")
    if not cfg["enabled"]:
        return {"created": []}
    if job is not None:
        if job["kind"] != "guardian_delivery":
            raise ValueError("交易员通知补发任务名被其他任务占用")
        return {"created": []}
    store.create_job(name=MANAGED_GUARDIAN_DELIVERY, kind="guardian_delivery",
                     cron="*/5 8-20 * * mon-fri", config={}, enabled=True)
    return {"created": [MANAGED_GUARDIAN_DELIVERY]}


def execute_guardian_delivery(config: dict[str, Any], context: JobContext) -> dict[str, Any]:
    store = context.ops_store
    if store is None:
        raise JobError("缺少运维库")
    cfg = get_config(store)
    if not cfg["enabled"] or not cfg["notify"]:
        raise JobSkipped("交易员或通知已停用")
    silence = notification_silence_reason()
    if silence:
        raise JobSkipped(silence)
    context.check_cancelled()
    with GuardianStore(context.palace_db) as ledger:
        before = ledger.notice_backlog()
        if not before["total"]:
            raise JobSkipped("没有待发交易员通知")
        receipts = deliver_pending(ledger, store, dispatch_text)
        after = ledger.notice_backlog()
    failed = sum(not receipt.get("success") for receipt in receipts.values())
    return {"status": "failed" if failed else "success", "delivered": len(receipts) - failed,
            "attempted": len(receipts), "unsent_attempts": failed,
            "backlog_before": before, "backlog_after": after,
            "research_calls": 0, "trade_count": 0}
