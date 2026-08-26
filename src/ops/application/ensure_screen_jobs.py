"""托管：全量引擎战法绑定定点选股。"""
from __future__ import annotations

from typing import Any

from src.ops.application.trading_schedule import compose_trading_cron

#: 盘后选股默认点（收盘后、日终同步前）
SCREEN_EOD_HOUR = 15
SCREEN_EOD_MINUTE = 30


def ensure_managed_screen_jobs(store: Any) -> dict[str, Any]:
    """为每个需要托管的引擎战法确保 ``screen:{slug}`` 任务。

    幂等：已有绑定只合并关键配置（保留 universe / 推送等用户自定义字段），
    不强制改 enabled；战法声明固定时点时同步其 cron，避免旧任务继续在错误时刻执行。
    ``screen_managed_job=False`` 的战法不建托管任务；残留 ``screen:{slug}`` 会按活动目录收缩删除。
    """
    from src.strategy import all_strategies

    default_cron = compose_trading_cron(
        "once", run_hour=SCREEN_EOD_HOUR, run_minute=SCREEN_EOD_MINUTE
    )
    default_schedule = {
        "mode": "once",
        "run_hour": SCREEN_EOD_HOUR,
        "run_minute": SCREEN_EOD_MINUTE,
        "interval_minutes": 10,
        "window_start_hour": 9,
        "window_start_minute": 30,
        "window_end_hour": SCREEN_EOD_HOUR,
        "window_end_minute": SCREEN_EOD_MINUTE,
    }
    created = 0
    updated = 0
    slugs: list[str] = []
    job_crons: dict[str, str] = {}
    for engine in all_strategies():
        slug = str(engine.slug)
        if not _manages_screen_job(engine):
            continue
        slugs.append(slug)
        engine_schedule = _schedule_for_engine(engine, default_schedule)
        job_name = f"screen:{slug}"
        existing = store.get_job_by_name(job_name)
        prev_cfg = (
            existing.get("config")
            if existing and isinstance(existing.get("config"), dict)
            else {}
        )
        # 战法声明了固定时点才覆盖；否则保留用户在详情页保存的 schedule。
        if _has_schedule_override(engine) or not isinstance(prev_cfg.get("schedule"), dict):
            schedule = engine_schedule
        else:
            schedule = {
                key: prev_cfg["schedule"].get(key, default_schedule[key])
                for key in default_schedule
            }
        cron = compose_trading_cron(
            schedule["mode"],
            run_hour=schedule["run_hour"],
            run_minute=schedule["run_minute"],
            interval_minutes=schedule["interval_minutes"],
            window_start_hour=schedule["window_start_hour"],
            window_start_minute=schedule["window_start_minute"],
            window_end_hour=schedule["window_end_hour"],
            window_end_minute=schedule["window_end_minute"],
        )
        job_crons[slug] = cron
        declared_hold_days = getattr(engine, "screen_hold_days", None)
        default_hold_days = (
            int(declared_hold_days)
            if declared_hold_days is not None
            else int(prev_cfg.get("hold_days") or 3)
        )
        default_stop_loss = getattr(engine, "screen_stop_loss_pct", -6.0)
        config: dict[str, Any] = {
            "strategy": slug,
            "record_candidates": bool(prev_cfg.get("record_candidates", True)),
            "top_n": _top_n_for_engine(engine, prev_cfg),
            "trading_days": int(prev_cfg.get("trading_days") or 60),
            "hold_days": default_hold_days,
            "stop_loss_pct": (
                prev_cfg["stop_loss_pct"]
                if "stop_loss_pct" in prev_cfg
                else default_stop_loss
            ),
            "provider": str(prev_cfg.get("provider") or ""),
            "model": str(prev_cfg.get("model") or ""),
            "thinking": str(prev_cfg.get("thinking") or ""),
            "use_ai_pick": bool(prev_cfg.get("use_ai_pick", False)),
            "push_wecom": bool(prev_cfg.get("push_wecom", True)),
            "schedule": schedule,
            # 未声明则写 False，清掉盘中定点实验残留的强制刷现价。
            "force_spot_refresh": bool(
                getattr(engine, "screen_force_spot_refresh", False)
            ),
        }
        if isinstance(prev_cfg.get("universe"), dict):
            config["universe"] = prev_cfg["universe"]
        else:
            default_universe = getattr(engine, "default_universe", None)
            if isinstance(default_universe, dict):
                config["universe"] = dict(default_universe)
        if existing is None:
            store.create_job(
                name=job_name, kind="screen", cron=cron, config=config, enabled=True
            )
            created += 1
        else:
            # 合并而非整体覆盖：params/codes/decision/mcp_servers 等用户自定义键保留
            update_fields: dict[str, Any] = {
                "config": {**prev_cfg, **config},
                "cron": cron,
            }
            store.update_job(existing["id"], **update_fields)
            updated += 1
    # ``screen:`` 是战法绑定任务的保留前缀。活动目录收缩后，旧任务不能继续
    # 被调度器执行或发送过时结果；只删这个前缀下且 kind=screen 的托管任务。
    active = set(slugs)
    removed_slugs: list[str] = []
    for job in store.list_jobs():
        name = str(job.get("name") or "")
        if job.get("kind") != "screen" or not name.startswith("screen:"):
            continue
        slug = name[len("screen:") :]
        if slug in active:
            continue
        if store.delete_job(
            str(job["id"]), expected_name=name, allowed_kinds={"screen"}
        ):
            removed_slugs.append(slug)
    return {
        "cron": default_cron,
        "default_cron": default_cron,
        "job_crons": job_crons,
        "slugs": slugs,
        "created": created,
        "updated": updated,
        "removed": len(removed_slugs),
        "removed_slugs": removed_slugs,
        "total": len(slugs),
    }


def _schedule_for_engine(
    engine: Any, default_schedule: dict[str, Any]
) -> dict[str, Any]:
    """读取战法的托管时点；未声明时沿用统一 15:30 默认值。"""
    override = getattr(engine, "screen_schedule", None)
    if not isinstance(override, dict):
        return dict(default_schedule)
    return {
        key: override.get(key, default_schedule[key])
        for key in default_schedule
    }


def _top_n_for_engine(engine: Any, previous: dict[str, Any]) -> int:
    """战法声明了上限时不允许托管配置放大输出数量。"""
    maximum = int(getattr(engine, "screen_top_n", 0) or 0)
    if maximum > 0:
        return maximum
    return int(previous.get("top_n") or 0)


def _has_schedule_override(engine: Any) -> bool:
    return isinstance(getattr(engine, "screen_schedule", None), dict)


def _manages_screen_job(engine: Any) -> bool:
    """未声明时默认托管；显式 ``screen_managed_job=False`` 的战法只留手跑。"""
    return bool(getattr(engine, "screen_managed_job", True))
