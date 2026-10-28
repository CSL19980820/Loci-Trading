"""竞价输入就绪检查：先完成同日同槽选股，再认领猎隼账户快照。"""
from __future__ import annotations

from datetime import datetime

from src.ops.application.falcon_candidates import _active_formula_sources
from src.ops.application.trading_schedule import is_interval_run_allowed
from src.ops.infrastructure.store_runs import _parse_run_started_at


def falcon_auction_inputs(ops, *, now: datetime) -> dict[str, list[str]]:
    """只读本租户真实来源和执行终态；成功的零候选结果同样就绪。"""
    # 延迟导入：scheduler 的执行器注册也依赖本模块。
    from src.ops.infrastructure.scheduler import validate_cron

    opening = now.replace(hour=9, minute=25, second=0, microsecond=0)
    result: dict[str, list[str]] = {"pending": [], "failed": []}
    for source in _active_formula_sources(ops):
        job = ops.get_job(source["job_id"])
        config = (job or {}).get("config") or {}
        if not job or not job.get("cron") or not config.get("record_candidates"):
            continue
        triggers = validate_cron(job["cron"])
        triggers = triggers if isinstance(triggers, list) else [triggers]
        slots = []
        for trigger in triggers:
            slot = trigger.get_next_fire_time(None, opening)
            while slot is not None and slot <= now:
                if is_interval_run_allowed(config.get("schedule"), now=slot):
                    slots.append(slot)
                slot = trigger.get_next_fire_time(slot, slot)
        if not slots:
            continue
        # 最新应触发槽必须已有真正完成的执行；昨天成功、今天尚未开始均不能放行。
        runs = ops.list_runs(job_id=job["id"], limit=1)
        run = runs[0] if runs else {}
        started = _parse_run_started_at(run.get("started_at", ""))
        if started is None or not max(slots) <= started <= now or run.get("status") == "running":
            result["pending"].append(job["name"])
        elif run.get("status") != "success":
            result["failed"].append(f"{job['name']}（{run.get('status') or '未知状态'}）")
    return result


def auction_inputs_reason(inputs: dict[str, list[str]]) -> str:
    if inputs["failed"]:
        return "竞价选股来源未成功，本轮不认领旧候选快照：" + "、".join(inputs["failed"])
    if inputs["pending"]:
        return "等待竞价选股完成并同步观察池：" + "、".join(inputs["pending"])
    return ""
