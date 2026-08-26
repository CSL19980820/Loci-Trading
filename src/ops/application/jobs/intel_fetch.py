"""intel_fetch 任务：确定性 MCP 调用（不走 LLM），默认走 structured 配额池。"""
from __future__ import annotations

import logging
from typing import Any

from src.ops.application.jobs.context import JobContext

logger = logging.getLogger(__name__)

#: 盘中托管 cron 是 ``*/15``（见 ops/application/ensure_intel_jobs.py）。TTL ≥ 间隔时
#: 下一次 run 会整轮命中缓存、一次真调用都不发，Job 却记绿——一半的 run 是空转，
#: 情绪/梯队数据实际还是上一轮的。留 3 分钟余量吸收调度抖动。
_INTRADAY_CACHE_MAX_AGE_MINUTES = 12
#: open / close 两档一天各跑一次，间隔远大于 TTL，维持原默认。
_DEFAULT_CACHE_MAX_AGE_MINUTES = 20

#: **分池按「谁发起的」定**：日常情报配方（本任务 open/intraday/close 三档）走
#: structured；战法盯盘 / tape lane 走 skill（见
#: `market/infrastructure/tape/wudao_provider.py`）。两边都不再把池名硬编码在调用
#: 点上：这里认 Job 配置键 ``pool``，那边认 TapeRequest.context 的 ``quota_pool``。
DEFAULT_INTEL_POOL = "structured"
QUOTA_POOLS = ("structured", "skill")

#: 会影响扇出的 Job 配置键；自检按这几个键还原「调度器实际会打多少次」。
_KNOB_KEYS = ("theme_top_n", "stock_flow_top_n", "screener_count", "intraday_theme_top_n")


def resolve_pool(value: Any = None) -> str:
    """Job 配置里的池名 → 合法池名；空或写错回落 ``DEFAULT_INTEL_POOL`` 并留日志。

    不静默接受未知池名：记到一个不存在的池等于这批调用不受任何预算约束。
    """
    pool = str(value or "").strip().lower()
    if not pool:
        return DEFAULT_INTEL_POOL
    if pool not in QUOTA_POOLS:
        logger.warning("intel_fetch 未知配额池 %s，回落 %s", pool, DEFAULT_INTEL_POOL)
        return DEFAULT_INTEL_POOL
    return pool


def _run_call_list(
    calls: list[dict[str, Any]],
    *,
    server: str,
    context: JobContext,
    cache_max_age_minutes: int,
    pool: str = DEFAULT_INTEL_POOL,
) -> tuple[list[dict[str, Any]], dict[str, dict[str, Any]], dict[str, Any]]:
    from src.intel import McpQuotaError, call_mcp_tool

    receipts: list[dict[str, Any]] = []
    prior: dict[str, dict[str, Any]] = {}
    stats = {"ok": 0, "failed": 0, "cached": 0, "quota_skipped": 0}

    with context.market() as market:
        for item in calls:
            tool = str(item.get("tool") or "").strip()
            if not tool:
                continue
            arguments = item.get("arguments") if isinstance(item.get("arguments"), dict) else {}
            use_cache = bool(item.get("cache", True))
            try:
                payload = call_mcp_tool(
                    tool,
                    arguments,
                    server=server,
                    pool=pool,
                    cache=use_cache,
                    cache_max_age_minutes=cache_max_age_minutes if use_cache else None,
                    market_store=market,
                )
            except McpQuotaError as exc:
                stats["quota_skipped"] += 1
                receipts.append({"tool": tool, "ok": False, "skipped": True, "error": str(exc)})
                logger.warning("intel_fetch 配额用尽，剩余调用跳过：%s", exc)
                break
            except Exception as exc:
                stats["failed"] += 1
                receipts.append({"tool": tool, "ok": False, "error": str(exc)})
                logger.warning("intel_fetch 调用失败 %s: %s", tool, exc)
                continue

            ok = not bool(payload.get("is_error"))
            if ok:
                stats["ok"] += 1
                prior[tool] = payload
            else:
                stats["failed"] += 1
            if payload.get("cached"):
                stats["cached"] += 1
            receipts.append(
                {
                    "tool": tool,
                    "ok": ok,
                    "cached": bool(payload.get("cached")),
                    "error": "" if ok else str(payload.get("text") or "")[:200],
                }
            )
    return receipts, prior, stats


def _managed_job_row(context: JobContext, name: str) -> dict[str, Any]:
    """读 ops.db 里那条托管任务；读不到（无 store / 测试桩 / 库忙）返回空表。

    自检失败不该拖垮采集，所以这里一律吞异常——但吞掉后会在 ``source`` 里标成
    ``defaults``，不让估算假装自己对齐了调度器。
    """
    store = getattr(context, "ops_store", None)
    if store is None:
        return {}
    try:
        row = store.get_job_by_name(name)
    except Exception:
        logger.debug("intel_fetch 读托管任务失败：%s", name, exc_info=True)
        return {}
    return dict(row) if isinstance(row, dict) else {}


def _scheduler_plan(
    config: dict[str, Any],
    context: JobContext,
    *,
    phase: str,
    live_knobs: dict[str, Any],
) -> dict[str, Any]:
    """按**调度器实况**还原三档估算入参：cron 与每档 config 都从 ops.db 读。

    估算器以前写死「盘中 20 轮」，而托管 cron ``*/15 9-14`` 每天真的会触发 24 轮——
    差的这 4 轮就是几百次配额。真相在 `ops/application/ensure_intel_jobs.py` 与用户
    自己改过的那条任务上，所以这里去读它，而不是再抄一个常量。
    """
    from src.ops.application.ensure_intel_jobs import (
        MANAGED_INTEL_CLOSE,
        MANAGED_INTEL_INTRADAY,
        MANAGED_INTEL_INTRADAY_CRON,
        MANAGED_INTEL_OPEN,
    )

    names = {
        "open": MANAGED_INTEL_OPEN,
        "intraday": MANAGED_INTEL_INTRADAY,
        "close": MANAGED_INTEL_CLOSE,
    }
    cron = str(config.get("intraday_cron") or "").strip()
    phase_params: dict[str, dict[str, Any]] = {}
    found: list[str] = []
    for job_phase, job_name in names.items():
        row = _managed_job_row(context, job_name)
        raw = row.get("config") if isinstance(row.get("config"), dict) else {}
        knobs = {key: raw[key] for key in _KNOB_KEYS if raw.get(key) is not None}
        if row:
            found.append(job_phase)
            if not bool(row.get("enabled", True)) and job_phase != phase:
                knobs["runs"] = 0
            if job_phase == "intraday" and not cron:
                cron = str(row.get("cron") or "").strip()
        phase_params[job_phase] = knobs
    phase_params[phase] = {**phase_params.get(phase, {}), **live_knobs}
    phase_params[phase].pop("runs", None)
    return {
        "phase_params": phase_params,
        "intraday_cron": cron or MANAGED_INTEL_INTRADAY_CRON,
        "source": "ops_db" if found else "defaults",
        "managed_found": found,
    }


def _quota_preflight(
    config: dict[str, Any],
    context: JobContext,
    *,
    phase: str,
    live_knobs: dict[str, Any],
    pool: str,
    quota: dict[str, Any],
) -> tuple[dict[str, Any], dict[str, Any] | None]:
    """开跑前先算一遍全天扇出；超预算就出一条中文告警。

    **不做静默截断**：算出来超了也照配方跑完这一轮，只把「超了多少、该拧哪个旋钮」
    写进日志和 job payload。悄悄少拿数据会让下游把「只扫了前 N 只」当成「全市场就
    这些」，那是比超配额更贵的错。
    """
    from src.intel.application.daily_recipe import (
        estimate_daily_calls,
        structured_budget_alert,
    )

    plan = _scheduler_plan(config, context, phase=phase, live_knobs=live_knobs)
    limits = quota.get("limits") if isinstance(quota.get("limits"), dict) else {}
    budget = int(limits.get(pool) or 0)
    kwargs: dict[str, Any] = {
        "intraday_cron": plan["intraday_cron"],
        "phase_params": plan["phase_params"],
        "pool": pool,
    }
    if budget > 0:
        kwargs["structured_budget"] = budget
    if limits.get("skill"):
        kwargs["skill_reserve"] = int(limits["skill"])
    estimate = estimate_daily_calls(**kwargs)
    estimate["scheduler_source"] = plan["source"]
    alert = structured_budget_alert(estimate)
    if alert is not None:
        logger.warning("intel_fetch 配额自检：%s", alert["message"])
    return estimate, alert


def _within_budget_summary(estimate: dict[str, Any]) -> str:
    """没超预算时的一句话回执（超了走 ``structured_budget_alert`` 的中文告警）。"""
    total = int(estimate.get("estimated_total") or 0)
    budget = int(estimate.get("structured_budget") or 0)
    pool = str(estimate.get("pool") or "structured")
    runs = int(estimate.get("intraday_runs") or 0)
    return (
        f"悟道 {pool} 池预估日耗 {total} 次（盘中 {runs} 轮/日），"
        f"日预算 {budget} 次，已压在预算内。"
    )


def execute_intel_fetch(config: dict[str, Any], context: JobContext) -> dict[str, Any]:
    """按 phase 配方批量拉取外部情报并写入 market.db 缓存。

    悟道未装配时**软跳过**（不抛错、不拖垮调度/主体功能）。
    """
    from src.intel import quota_snapshot, wudao_availability
    from src.intel.application.daily_recipe import (
        INTRADAY_THEME_TOP_N,
        build_followup_calls,
        build_static_calls,
    )

    phase = str(config.get("phase") or "intraday").strip().lower()
    if phase not in {"open", "intraday", "close", "estimate"}:
        raise ValueError(f"未知 intel_fetch phase：{phase}")

    # 日常情报配方默认记 structured；``pool`` 配置键留给「换池跑一档」这类运维动作。
    pool = resolve_pool(config.get("pool"))

    if phase == "estimate":
        estimate, alert = _quota_preflight(
            config,
            context,
            phase="intraday",
            live_knobs={},
            pool=pool,
            quota=quota_snapshot(),
        )
        return {
            "estimate": estimate,
            "pool": pool,
            "quota_alert": alert,
            "summary": alert["message"] if alert else _within_budget_summary(estimate),
        }

    server = str(config.get("server") or "wudao").strip()
    availability = wudao_availability()
    if not availability.get("available"):
        reason = str(availability.get("reason") or "悟道 MCP 不可用")
        logger.info("intel_fetch 软跳过：%s", reason)
        return {
            "skipped": True,
            "reason": "mcp_unavailable",
            "phase": phase,
            "server": server,
            "pool": pool,
            "unavailable_reason": reason,
            "summary": f"悟道未装配，情报采集已跳过：{reason}",
            "stats": {
                "ok": 0,
                "failed": 0,
                "cached": 0,
                "quota_skipped": 0,
                "planned": 0,
                "executed": 0,
            },
            "receipts": [],
            "quota": quota_snapshot(),
        }

    theme_top_n = int(config.get("theme_top_n") or 120)
    stock_flow_top_n = int(config.get("stock_flow_top_n") or 160)
    screener_count = int(config.get("screener_count") or 10)
    # 盘中题材扇出单独设上限（默认 40）：盘中榜十几分钟不会翻天，而这一档一天要跑
    # 二十多轮，题材数是唯一会被轮次放大的旋钮。open / close 仍用完整 theme_top_n。
    intraday_theme_top_n = int(
        config.get("intraday_theme_top_n") or INTRADAY_THEME_TOP_N
    )
    # 盘中一律钳到 cron 间隔以内：用户把 close 档调成 120 分钟是合理的（收盘后
    # 数据已定稿），盘中调成 20 分钟只会让 */15 的 run 空转，所以这里不认。
    default_age = (
        _INTRADAY_CACHE_MAX_AGE_MINUTES if phase == "intraday" else _DEFAULT_CACHE_MAX_AGE_MINUTES
    )
    cache_max_age = int(config.get("cache_max_age_minutes") or default_age)
    if phase == "intraday" and cache_max_age > _INTRADAY_CACHE_MAX_AGE_MINUTES:
        logger.info(
            "intel_fetch 盘中缓存 TTL %s 分钟 ≥ 采集间隔，钳到 %s 分钟",
            cache_max_age,
            _INTRADAY_CACHE_MAX_AGE_MINUTES,
        )
        cache_max_age = _INTRADAY_CACHE_MAX_AGE_MINUTES

    # 启动自检：先按调度器实况算一遍全天扇出，超预算就报警（不改这一轮的配方）。
    live_knobs = {
        "theme_top_n": theme_top_n,
        "stock_flow_top_n": stock_flow_top_n,
        "screener_count": screener_count,
        "intraday_theme_top_n": intraday_theme_top_n,
    }
    estimate, alert = _quota_preflight(
        config,
        context,
        phase=phase,
        live_knobs=live_knobs,
        pool=pool,
        quota=quota_snapshot(),
    )

    static_calls = build_static_calls(phase, screener_count=screener_count)  # type: ignore[arg-type]
    wave1_receipts, prior, stats1 = _run_call_list(
        static_calls,
        server=server,
        context=context,
        cache_max_age_minutes=cache_max_age,
        pool=pool,
    )

    followup_calls = build_followup_calls(
        phase,  # type: ignore[arg-type]
        prior,
        theme_top_n=theme_top_n,
        stock_flow_top_n=stock_flow_top_n,
        intraday_theme_top_n=intraday_theme_top_n,
    )
    wave2_receipts, _, stats2 = _run_call_list(
        followup_calls,
        server=server,
        context=context,
        cache_max_age_minutes=cache_max_age,
        pool=pool,
    )

    stats = {
        "ok": stats1["ok"] + stats2["ok"],
        "failed": stats1["failed"] + stats2["failed"],
        "cached": stats1["cached"] + stats2["cached"],
        "quota_skipped": stats1["quota_skipped"] + stats2["quota_skipped"],
        "planned": len(static_calls) + len(followup_calls),
        "executed": len(wave1_receipts) + len(wave2_receipts),
    }
    result: dict[str, Any] = {
        "phase": phase,
        "server": server,
        "pool": pool,
        "stats": stats,
        "quota": quota_snapshot(),
        "receipts": wave1_receipts + wave2_receipts,
        "estimate": estimate,
    }
    if alert is not None:
        result["quota_alert"] = alert
        result["summary"] = alert["message"]
    return result
