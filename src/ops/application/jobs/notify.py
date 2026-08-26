"""notify 任务执行器与企微附带推送。"""
from __future__ import annotations

import logging
from typing import Any

from src.ops.application.jobs.context import DEFAULT_PALACE_DB, JobContext, JobError
from src.ops.infrastructure.store import OpsStore

logger = logging.getLogger(__name__)


def execute_notify(config: dict[str, Any], context: JobContext) -> dict[str, Any]:
    """按模板经 notify_dispatch 出站（企微 / Bark；尊重安静时段）。"""
    from src.ops.application.notify import (
        format_screen_picks_text,
        format_sync_report,
        load_screen_template,
        resolve_kind_tag,
    )
    from src.ops.application.notify_dispatch import dispatch_text

    if context.ops_store is None:
        raise JobError("缺少运维库连接")

    template = str(config.get("template") or "alerts").strip()
    webhook = str(config.get("webhook") or "").strip()

    screen_tpl = load_screen_template(context.ops_store)
    skipped = False
    content = ""
    title = "Loci 推送"
    if template == "alerts":
        content = _notify_alerts_content(context)
        title = "触价提醒"
    elif template == "digest":
        content = _notify_digest_content(context)
        title = "日终简报"
    elif template == "screen_last":
        result = _latest_run_result(context.ops_store, kind="screen", status="success")
        if not result:
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
            title = "选股推送"
    elif template == "sync_fail":
        result = _latest_run_result(context.ops_store, kind="sync")
        if not result or int(result.get("failed") or 0) <= 0:
            return {"skipped": True, "template": template, "reason": "最近同步无失败"}
        content = format_sync_report(result)
        title = "同步失败"
    else:
        raise JobError(f"未知推送模板：{template}")

    if skipped:
        return {"skipped": True, "template": template, "content": content}

    outcome = dispatch_text(
        context.ops_store,
        title=title,
        body=content,
        webhook_override=webhook,
        bypass_quiet=bool(config.get("bypass_quiet")),
    )
    if outcome.get("skipped") == "quiet_hours":
        return {"skipped": True, "template": template, "reason": "quiet_hours"}
    if not outcome.get("sent") and outcome.get("error"):
        raise JobError(str(outcome.get("error")))
    if outcome.get("errors") and not outcome.get("sent"):
        raise JobError("; ".join(outcome["errors"]))
    return {
        "skipped": False,
        "template": template,
        "chars": len(content),
        "notify": outcome,
    }


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
        try:
            with context.market_hot() as store:
                return format_alerts(today_alerts_payload(palace, store))
        except Exception:
            logger.debug("触价推送热读库不可用，降级无报价", exc_info=True)
        return format_alerts(today_alerts_payload(palace, None))


def _notify_digest_content(context: JobContext) -> str:
    from src.ops.application.notify import format_digest
    from src.ledger import PalaceStore

    with PalaceStore(context.palace_db or DEFAULT_PALACE_DB) as palace:
        candidates = palace.candidates_payload()
        summary = palace.candidate_day_summary(candidates)
    return format_digest(candidates=candidates, summary=summary)


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
        format_job_status,
        format_screen_picks_text,
        format_sync_report,
        load_screen_template,
        resolve_kind_tag,
    )
    from src.ops.application.notify_dispatch import dispatch_text

    webhook = str(config.get("webhook") or "").strip()
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
    elif kind == "skill_watch":
        from src.ops.application.skill_strategy_config import default_watch_push_wecom
        from src.ops.application.skill_watch.engine_registry import (
            push_only_when_actionable,
        )
        from src.ops.application.skill_watch.watch_labels import format_watch_status_push

        payload = result if isinstance(result, dict) else {}
        slug = str(payload.get("slug") or config.get("skill") or "")
        # 卫星线硬拦截：龙头地图/涨停动量永不刷企微
        if slug and not default_watch_push_wecom(slug):
            return {"push_skipped": True, "reason": "satellite_watch_no_push", "slug": slug}
        summary = str(payload.get("summary") or "").strip()
        picks_now = payload.get("picks") if isinstance(payload.get("picks"), list) else []
        # 高频引擎静默：无可执行候选就不推。**不能靠下面那条 `not summary` 兜底**——
        # runner 给 summary 配了 "无新信号" 的默认值，它永远非空，那条分支进不去，
        # 结果就是盘中每 10 分钟推一条"无新信号"。失败/跳过仍推原因。
        # 「仅观察」也不算可执行：二波引擎只出观察票，统一池缺 action 时默认
        # intent=observe，旧逻辑只要 picks 非空就刷「👀观察 N：…仅观察」。
        if status == "success" and slug and push_only_when_actionable(slug):
            from src.ops.application.paper_policy.eligibility import has_actionable_picks

            if not has_actionable_picks(picks_now):
                return {"push_skipped": True, "reason": "no_actionable_picks", "slug": slug}
        # success 且完全无正文/闸门才不推；跳过/失败仍推中文原因（不再甩英文 slug）
        if status == "success" and not summary and not payload.get("market_gate"):
            signals = payload.get("signals") if isinstance(payload.get("signals"), list) else []
            picks = payload.get("picks") if isinstance(payload.get("picks"), list) else []
            if not signals and not picks:
                return {"push_skipped": True, "reason": "no_signals"}
        job_name, content = format_watch_status_push(
            slug=slug,
            skill_name=str(payload.get("skill_name") or ""),
            job_name=job_name,
            status=status,
            summary=summary,
            reason=str(payload.get("reason") or ""),
            error=error,
            result=payload,
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

    dispatch_title = job_name or kind or "任务"
    prepend_title_to_wecom = True
    if kind == "screen":
        dispatch_title = _screen_title(result or {}, job_name)
        prepend_title_to_wecom = False
    elif kind == "skill":
        dispatch_title = _skill_title(result or {}, job_name)
        prepend_title_to_wecom = False

    outcome = dispatch_text(
        store,
        title=dispatch_title,
        body=content,
        webhook_override=webhook,
        prepend_title_to_wecom=prepend_title_to_wecom,
    )
    if outcome.get("skipped") == "quiet_hours":
        return {"push_skipped": True, "reason": "quiet_hours"}
    if not outcome.get("sent"):
        err = outcome.get("error") or "; ".join(outcome.get("errors") or []) or "推送失败"
        logger.warning("附带推送失败：%s", err)
        return {"push_error": str(err)}
    if kind in {"screen", "skill"} and status == "success" and isinstance(result, dict):
        from src.ops.application.wecom_push_mark import mark_screen_pushed, resolve_push_day

        push_day = resolve_push_day(result)
        job_id = str(job.get("id") or "")
        if job_id and (kind == "screen" or result.get("picks")):
            mark_screen_pushed(
                store,
                job_id=job_id,
                day=push_day,
                meta={
                    "title": _screen_title(result, job_name)
                    if kind == "screen"
                    else _skill_title(result, job_name)
                },
            )
        return {"pushed": True, "msgtype": "text", "push_day": push_day, "notify": outcome}
    return {"pushed": True, "msgtype": "text", "notify": outcome}


def _screen_title(result: dict[str, Any], job_name: str) -> str:
    explicit = str(result.get("strategy_name") or "").strip()
    if explicit:
        return explicit
    raw = str(result.get("strategy") or job_name or "选股").strip()
    if raw.startswith("screen:"):
        raw = raw[len("screen:") :]
    try:
        from src.strategy import get

        return str(get(raw).name or "选股")
    except Exception:
        return "选股" if "-" in raw or "_" in raw else (raw or "选股")


def _skill_title(result: dict[str, Any], job_name: str) -> str:
    explicit = str(result.get("skill_name") or "").strip()
    if explicit:
        return explicit
    raw = str(result.get("skill") or job_name or "技能").strip()
    if raw.startswith("skill:"):
        raw = raw[len("skill:") :]
    return "技能" if "-" in raw or "_" in raw else (raw or "技能")
