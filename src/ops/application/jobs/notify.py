"""notify 任务执行器与企微附带推送。"""
from __future__ import annotations

from datetime import datetime
import logging
from typing import Any
from zoneinfo import ZoneInfo

from src.ops.application.jobs.context import default_palace_db, JobContext, JobError
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
    if outcome.get("skipped") == "rate_limited":
        #  刻意没发（60s 内同指纹已出过声），不是失败：这里若 raise JobError，
        #  一个每 5 分钟跑一次的推送任务会在运维页刷出一整列红叉。
        return {"skipped": True, "template": template, "reason": "rate_limited"}
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

    with PalaceStore(context.palace_db or default_palace_db()) as palace:
        try:
            with context.market_hot() as store:
                return format_alerts(today_alerts_payload(palace, store))
        except Exception:
            logger.debug("触价推送热读库不可用，降级无报价", exc_info=True)
        return format_alerts(today_alerts_payload(palace, None))


def _notify_digest_content(context: JobContext) -> str:
    from src.ops.application.notify import format_digest
    from src.ledger import PalaceStore

    with PalaceStore(context.palace_db or default_palace_db()) as palace:
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
            compute_push_fingerprint,
            is_screen_pushed,
            resolve_push_day,
        )

        push_day = resolve_push_day(result)
        job_id = str(job.get("id") or "")
        strat_slug = str(result.get("strategy") or job_name or "")
        time_slot = datetime.now(ZoneInfo("Asia/Shanghai")).strftime("%H:%M")
        picks_list = result.get("picks") if isinstance(result.get("picks"), list) else []
        fingerprint = compute_push_fingerprint(
            day=push_day,
            job_id=job_id,
            strategy=strat_slug,
            time_slot=time_slot,
            picks=picks_list,
        )
        if job_id and (
            is_screen_pushed(store, job_id=job_id, day=push_day, fingerprint=fingerprint)
            or adopt_push_mark_from_runs(store, job_id=job_id, day=push_day, fingerprint=fingerprint)
        ):
            return {
                "push_skipped": True,
                "reason": "already_pushed",
                "push_day": push_day,
                "push_fingerprint": fingerprint,
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
        # 「仅观察」也不算可执行：只出观察票的引擎会刷屏，统一池缺 action 时默认
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
                compute_push_fingerprint,
                is_screen_pushed,
                resolve_push_day,
            )

            push_day = resolve_push_day(result)
            job_id = str(job.get("id") or "")
            strat_slug = str(result.get("skill") or job_name or "")
            time_slot = datetime.now(ZoneInfo("Asia/Shanghai")).strftime("%H:%M")
            picks_list = result.get("picks") if isinstance(result.get("picks"), list) else []
            fingerprint = compute_push_fingerprint(
                day=push_day,
                job_id=job_id,
                strategy=strat_slug,
                time_slot=time_slot,
                picks=picks_list,
            )
            if job_id and (
                is_screen_pushed(store, job_id=job_id, day=push_day, fingerprint=fingerprint)
                or adopt_push_mark_from_runs(store, job_id=job_id, day=push_day, fingerprint=fingerprint)
            ):
                return {
                    "push_skipped": True,
                    "reason": "already_pushed",
                    "push_day": push_day,
                    "push_fingerprint": fingerprint,
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
    elif kind == "intel_brief":
        # 简报正文由执行器自己按字节分片推（`jobs/intel_brief.py`），这里再推一条
        # 「任务状态」就是纯噪音：四档 × 每档三个触发点 = 一天最多 12 条
        # 「【任务✓ 简报推送】状态 已跳过」。这与 data_quality 全绿闭嘴、skill_watch
        # 无信号闭嘴是同一条纪律：天天响的通知等于没有通知。
        #
        # **失败仍要推**：`status=failed` 只有两种来路——执行器整个抛异常，或简报取回来
        # 了却一条都没发出去（`push_error`，见 registry 的状态判定）。两者都值得知道。
        if status != "failed":
            # 用 `push_reason` 而不是各分支惯用的 `reason`：执行器已经把「为什么跳过」
            # （not_published / stale_briefing / already_pushed）写进 `reason`，而
            # run_job 会把这份 push_meta 合并进 result——同名键会把那条取证信息盖掉。
            return {"push_skipped": True, "push_reason": "brief_pushes_its_own_body"}
        content = format_job_status(
            job_name=job_name,
            kind=kind,
            status=status,
            error=error,
            result=result,
            template=screen_tpl,
        )
    elif kind == "data_quality":
        # 体检：``blocked`` 或有 ``alert`` 才出声，正文直接用体检自己写的中文
        # 告警（``build_alert`` 已经带上【阻断】/【提醒】分级与处置建议）。
        #
        # **全绿必须不推**。体检是天天跑的托管任务，每天推一条「一切正常」，
        # 两周之后没有人会再点开它——真出事那天的告警也一起被当噪音划过去。
        # 这是本模块反复交过学费的失效模式（见 skill_watch 的
        # ``push_only_when_actionable``、sync 的「仅失败才推」）。
        #
        # ``status != success`` 仍要推：体检自己不抛异常，能走到这里的失败是
        # 打不开行情库之类的真故障，比任何一条判据都值得知道。
        payload = result if isinstance(result, dict) else {}
        alert = str(payload.get("alert") or "").strip()
        if status == "success" and not alert and not payload.get("blocked"):
            return {"push_skipped": True, "reason": "quality_all_green"}
        content = alert or format_job_status(
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

    try:
        outcome = dispatch_text(
            store,
            title=dispatch_title,
            body=content,
            webhook_override=webhook,
            prepend_title_to_wecom=prepend_title_to_wecom,
        )
    except Exception as exc:
        # 本函数的契约是「失败只记日志不抛」，但此前只兜住了 ``sent=False``：
        # ``dispatch_text`` 自己抛出来（webhook 配置坏、底层 requests 抛的不是
        # HTTPError、安静时段配置读崩）会一路穿出去。``run_job`` 调用它的那一行
        # **不在**任何 try 里，异常会让这次运行卡在 ``running`` 上收不了尾——
        # 一条推送顺带把它本该通知的那次体检记录也毁了。
        logger.warning("附带推送异常：%s", exc, exc_info=True)
        return {"push_error": str(exc)}
    if outcome.get("skipped") == "quiet_hours":
        return {"push_skipped": True, "reason": "quiet_hours"}
    if outcome.get("skipped") == "rate_limited":
        #  同上：被限流是降噪的**成功**，记 push_skipped。记成 push_error 会让
        #  「告警太吵」在运维页伪装成「推送坏了」，下一个人就去关限流。
        #  注意这条路径**不**写 wecom_push_mark：这次压根没发出去，同日重跑仍应尝试。
        return {"push_skipped": True, "reason": "rate_limited"}
    if not outcome.get("sent"):
        err = outcome.get("error") or "; ".join(outcome.get("errors") or []) or "推送失败"
        logger.warning("附带推送失败：%s", err)
        return {"push_error": str(err)}
    if kind in {"screen", "skill"} and status == "success" and isinstance(result, dict):
        from src.ops.application.wecom_push_mark import (
            compute_push_fingerprint,
            mark_screen_pushed,
            resolve_push_day,
        )

        push_day = resolve_push_day(result)
        job_id = str(job.get("id") or "")
        strat_slug = str(result.get("strategy" if kind == "screen" else "skill") or job_name or "")
        time_slot = datetime.now(ZoneInfo("Asia/Shanghai")).strftime("%H:%M")
        picks_list = result.get("picks") if isinstance(result.get("picks"), list) else []
        fingerprint = compute_push_fingerprint(
            day=push_day,
            job_id=job_id,
            strategy=strat_slug,
            time_slot=time_slot,
            picks=picks_list,
        )
        if job_id and (kind == "screen" or result.get("picks")):
            mark_screen_pushed(
                store,
                job_id=job_id,
                day=push_day,
                fingerprint=fingerprint,
                meta={
                    "title": _screen_title(result, job_name)
                    if kind == "screen"
                    else _skill_title(result, job_name)
                },
            )
        return {
            "pushed": True,
            "msgtype": "text",
            "push_day": push_day,
            "push_fingerprint": fingerprint,
            "notify": outcome,
        }
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
