"""notify 任务执行器与企微附带推送。"""
from __future__ import annotations

import logging
from typing import Any

from src.ops.application.jobs.context import DEFAULT_PALACE_DB, JobContext, JobError
from src.ops.infrastructure.store import OpsStore

logger = logging.getLogger(__name__)


def execute_notify(config: dict[str, Any], context: JobContext) -> dict[str, Any]:
    """按模板推送到企业微信群机器人（仅 text）。"""
    from src.ops.application.notify import (
        NotifyError,
        format_screen_picks_text,
        format_sync_report,
        load_screen_template,
        resolve_kind_tag,
        send_wecom_text,
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

    screen_tpl = load_screen_template(context.ops_store)
    skipped = False
    content = ""
    if template == "alerts":
        content = _notify_alerts_content(context)
    elif template == "digest":
        content = _notify_digest_content(context)
    elif template == "screen_last":
        result = _latest_run_result(context.ops_store, kind="screen", status="success")
        if not result:
            # 再试最近一次带 picks 的 skill
            result = _latest_picks_run(context.ops_store)
        if not result:
            skipped = True
            content = "【选股推送】\n暂无成功的选股执行记录。"
        else:
            kind_key = "skills" if result.get("skill") or result.get("skill_name") else "quant"
            content = format_screen_picks_text(
                result,
                kind_tag=resolve_kind_tag(kind_key, screen_tpl),
                template=screen_tpl,
            )
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
        send_wecom_text(webhook, content)
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


def _latest_picks_run(store: OpsStore) -> dict[str, Any] | None:
    runs = store.list_runs(limit=30, status="success")
    for run in runs:
        result = run.get("result")
        if isinstance(result, dict) and result.get("picks"):
            return result
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
    """任务 config.push_wecom=true 时附带推送；失败只记日志不抛。仅 text。"""
    config = dict(job.get("config") or {})
    if not config.get("push_wecom"):
        return None
    if job.get("kind") == "notify":
        return None

    from src.ops.application.notify import (
        NotifyError,
        format_job_status,
        format_screen_picks_text,
        format_sync_report,
        load_screen_template,
        resolve_kind_tag,
        send_wecom_text,
    )

    webhook = str(config.get("webhook") or "").strip()
    if not webhook:
        stored = store.get_setting("wecom_webhook", {}) or {}
        webhook = str(stored.get("url") or "").strip()
    if not webhook:
        return {"push_error": "未配置企微 Webhook"}

    screen_tpl = load_screen_template(store)
    kind = str(job.get("kind") or "")
    job_name = str(job.get("name") or "")
    # sync：仅失败或 failed>0 时推
    if kind == "sync":
        failed_count = int((result or {}).get("failed") or 0)
        if status == "success" and failed_count <= 0:
            return {"push_skipped": True, "reason": "同步无失败"}
        content = format_sync_report(result or {}, job_name=job_name or "行情同步")
        if status == "failed" and error:
            content = format_job_status(
                job_name=job_name,
                kind=kind,
                status=status,
                error=error,
                result=result,
                template=screen_tpl,
            )
    elif kind == "screen" and status == "success" and isinstance(result, dict):
        from src.ops.application.wecom_push_mark import (
            adopt_push_mark_from_runs,
            is_screen_pushed,
            resolve_push_day,
        )

        push_day = resolve_push_day(result)
        job_id = str(job.get("id") or "")
        if job_id and (
            is_screen_pushed(store, job_id=job_id, day=push_day)
            or adopt_push_mark_from_runs(store, job_id=job_id, day=push_day)
        ):
            return {
                "push_skipped": True,
                "reason": "already_pushed",
                "push_day": push_day,
            }
        content = format_screen_picks_text(
            result,
            kind_tag=resolve_kind_tag("quant", screen_tpl),
            title=_screen_title(result, job_name),
            template=screen_tpl,
        )
    elif kind == "skill" and status == "success" and isinstance(result, dict):
        if result.get("picks"):
            from src.ops.application.wecom_push_mark import (
                adopt_push_mark_from_runs,
                is_screen_pushed,
                resolve_push_day,
            )

            push_day = resolve_push_day(result)
            job_id = str(job.get("id") or "")
            if job_id and (
                is_screen_pushed(store, job_id=job_id, day=push_day)
                or adopt_push_mark_from_runs(store, job_id=job_id, day=push_day)
            ):
                return {
                    "push_skipped": True,
                    "reason": "already_pushed",
                    "push_day": push_day,
                }
            content = format_screen_picks_text(
                result,
                kind_tag=resolve_kind_tag("skills", screen_tpl),
                title=_skill_title(result, job_name),
                template=screen_tpl,
            )
        else:
            content = format_job_status(
                job_name=job_name,
                kind=kind,
                status=status,
                error=error,
                result=result,
                template=screen_tpl,
            )
    else:
        content = format_job_status(
            job_name=job_name,
            kind=kind,
            status=status,
            error=error,
            result=result,
            template=screen_tpl,
        )

    try:
        send_wecom_text(webhook, content)
        if kind in {"screen", "skill"} and status == "success" and isinstance(result, dict):
            from src.ops.application.wecom_push_mark import mark_screen_pushed, resolve_push_day

            push_day = resolve_push_day(result)
            job_id = str(job.get("id") or "")
            if job_id and (kind == "screen" or result.get("picks")):
                mark_screen_pushed(
                    store,
                    job_id=job_id,
                    day=push_day,
                    meta={"title": _screen_title(result, job_name) if kind == "screen" else _skill_title(result, job_name)},
                )
            return {"pushed": True, "msgtype": "text", "push_day": push_day}
        return {"pushed": True, "msgtype": "text"}
    except NotifyError as exc:
        logger.warning("企微推送失败：%s", exc)
        return {"push_error": str(exc)}


def _screen_title(result: dict[str, Any], job_name: str) -> str:
    raw = str(result.get("strategy") or job_name or "选股").strip()
    if raw.startswith("screen:"):
        return raw[len("screen:") :]
    return raw


def _skill_title(result: dict[str, Any], job_name: str) -> str:
    return str(
        result.get("skill_name") or result.get("skill") or job_name or "技能"
    ).strip()
