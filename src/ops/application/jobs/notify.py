"""notify 任务执行器与企微附带推送。"""
from __future__ import annotations

import logging
from typing import Any

from src.ops.application.jobs.context import DEFAULT_PALACE_DB, JobContext, JobError
from src.ops.infrastructure.store import OpsStore

logger = logging.getLogger(__name__)


def execute_notify(config: dict[str, Any], context: JobContext) -> dict[str, Any]:
    """按模板推送到企业微信群机器人。"""
    from src.ops.application.notify import (
        NotifyError,
        format_screen_result,
        format_sync_report,
        send_wecom_markdown,
    )

    if context.ops_store is None:
        raise JobError("缺少运维库连接")

    template = str(config.get("template") or "alerts").strip()
    webhook = str(config.get("webhook") or "").strip()
    if not webhook:
        stored = context.ops_store.get_setting("wecom_webhook", {}) or {}
        webhook = str(stored.get("url") or "").strip()
    if not webhook:
        raise JobError("未配置企业微信 Webhook，请先到运维「推送」页填写")

    skipped = False
    content = ""
    if template == "alerts":
        content = _notify_alerts_content(context)
    elif template == "digest":
        content = _notify_digest_content(context)
    elif template == "screen_last":
        result = _latest_run_result(context.ops_store, kind="screen", status="success")
        if not result:
            skipped = True
            content = "### 选股推送\n暂无成功的选股执行记录。"
        else:
            content = format_screen_result(result)
    elif template == "sync_fail":
        result = _latest_run_result(context.ops_store, kind="sync")
        if not result or int(result.get("failed") or 0) <= 0:
            return {"skipped": True, "template": template, "reason": "最近同步无失败"}
        content = format_sync_report(result)
    else:
        raise JobError(f"未知推送模板：{template}")

    if skipped:
        return {"skipped": True, "template": template, "content": content}

    try:
        send_wecom_markdown(webhook, content)
    except NotifyError as exc:
        raise JobError(str(exc)) from exc
    return {"skipped": False, "template": template, "chars": len(content)}


def _latest_run_result(
    store: OpsStore, *, kind: str, status: str | None = None
) -> dict[str, Any] | None:
    runs = store.list_runs(limit=30, status=status)
    for run in runs:
        if run.get("kind") != kind:
            continue
        result = run.get("result")
        return result if isinstance(result, dict) else {}
    return None


def _notify_alerts_content(context: JobContext) -> str:
    from src.ops.application.notify import format_alerts
    from src.ledger import PalaceStore
    from src.review.application.alerts import today_alerts_payload

    with PalaceStore(context.palace_db or DEFAULT_PALACE_DB) as palace:
        market = None
        market_path = context.market_db
        if market_path:
            try:
                from src.market import MarketStore

                with MarketStore(market_path) as store:
                    return format_alerts(today_alerts_payload(palace, store))
            except Exception:
                logger.debug("触价推送行情不可用，降级无报价", exc_info=True)
        return format_alerts(today_alerts_payload(palace, market))


def _notify_digest_content(context: JobContext) -> str:
    from src.ops.application.notify import format_digest
    from src.ledger import PalaceStore

    with PalaceStore(context.palace_db or DEFAULT_PALACE_DB) as palace:
        return format_digest(palace.dashboard_payload())


def _maybe_push_wecom(
    *,
    store: OpsStore,
    job: dict[str, Any],
    status: str,
    result: dict[str, Any] | None,
    error: str = "",
) -> dict[str, Any] | None:
    """任务 config.push_wecom=true 时附带推送；失败只记日志不抛。"""
    config = dict(job.get("config") or {})
    if not config.get("push_wecom"):
        return None
    if job.get("kind") == "notify":
        return None

    from src.ops.application.notify import (
        NotifyError,
        format_job_status,
        format_screen_result,
        format_sync_report,
        send_wecom_markdown,
    )

    webhook = str(config.get("webhook") or "").strip()
    if not webhook:
        stored = store.get_setting("wecom_webhook", {}) or {}
        webhook = str(stored.get("url") or "").strip()
    if not webhook:
        return {"push_error": "未配置企微 Webhook"}

    kind = str(job.get("kind") or "")
    # sync：仅失败或 failed>0 时推
    if kind == "sync":
        failed_count = int((result or {}).get("failed") or 0)
        if status == "success" and failed_count <= 0:
            return {"push_skipped": True, "reason": "同步无失败"}
        content = format_sync_report(result or {}, job_name=str(job.get("name") or "行情同步"))
        if status == "failed" and error:
            content = format_job_status(
                job_name=str(job.get("name") or ""),
                kind=kind,
                status=status,
                error=error,
                result=result,
            )
    elif kind == "screen" and status == "success" and isinstance(result, dict):
        content = format_screen_result(result)
    else:
        content = format_job_status(
            job_name=str(job.get("name") or ""),
            kind=kind,
            status=status,
            error=error,
            result=result,
        )

    try:
        send_wecom_markdown(webhook, content)
        return {"pushed": True}
    except NotifyError as exc:
        logger.warning("企微推送失败：%s", exc)
        return {"push_error": str(exc)}
