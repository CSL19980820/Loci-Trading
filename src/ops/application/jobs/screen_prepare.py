"""盘后完整候选准备：与常规选股共用闭市行情准备，不产生精选或推送。"""
from __future__ import annotations

from datetime import datetime
from typing import Any
from zoneinfo import ZoneInfo

from src.ops.application.jobs.context import JobContext, JobError, JobSkipped


def execute_screen_prepare(config: dict[str, Any], context: JobContext) -> dict[str, Any]:
    from src.market import calendar_trading_day, guard_market_health
    from src.market.application.screen_spot import ScreenSpotError, ensure_today_quotes_for_screen
    from src.shared.tenancy import is_primary_tenant
    from src.strategy import get
    from src.strategy.application.double_yin_realtime import prepare_double_yin_pool

    slug = str(config.get("strategy") or "")
    if not slug:
        raise JobError("候选准备任务必须指定 strategy")
    engine = get(slug)
    if not getattr(engine, "requires_realtime_inputs", False):
        raise JobError("候选准备任务仅支持声明实时候选流程的战法")
    if context.ops_store is not None:
        morning = context.ops_store.get_job_by_name(f"screen:{slug}")
        if context.ops_store.is_screen_job_opted_out(slug) or not morning or not morning.get("enabled"):
            raise JobSkipped("晨间筛选已停用，本轮不准备候选")
    clock = datetime.now(ZoneInfo("Asia/Shanghai"))
    today = clock.date().isoformat()
    as_of = str(config.get("as_of") or today)
    if as_of != today:
        raise JobError("托管盘后准备只能使用当天闭市行情，禁止把旧日样本标成今日")
    try:
        trading_day = calendar_trading_day(today)
    except Exception as exc:
        raise JobError(f"交易所日历不可用，保留原候选池：{exc}") from exc
    if not trading_day:
        raise JobSkipped(f"{today} 非交易日，本轮不准备候选")
    if clock.hour < 15:
        raise JobSkipped("尚未收盘，禁止以未完成日 K 准备盘后候选")
    context.check_cancelled()
    spot_refresh: dict[str, Any]
    if is_primary_tenant():
        try:
            with context.market() as store:
                instruments = store.list_instruments()
                codes = [item["code"] for item in instruments]
                if not codes:
                    raise JobError("证券名录为空，保留原候选池")
                spot_refresh = ensure_today_quotes_for_screen(
                    store, codes,
                    instrument_types={item["code"]: item["instrument_type"] for item in instruments},
                    trade_date=today,
                )
        except ScreenSpotError as exc:
            raise JobError(f"闭市行情尚未就绪，保留原候选池：{exc}") from exc
    else:
        from src.ops.application.jobs.screen import _await_shared_quotes
        spot_refresh = _await_shared_quotes(context, today)
    context.check_cancelled()
    with context.market() as store:
        health = guard_market_health(store, trade_date=today).to_dict()
        result = prepare_double_yin_pool(
            engine, store=store, as_of=as_of,
            params=config.get("params"), codes=config.get("codes"), universe=config.get("universe"),
        )
    context.check_cancelled()
    status = str(result.get("status") or "")
    if status.startswith("skipped"):
        raise JobSkipped(str(result.get("reason") or status))
    if status not in {"prepared", "prepared_empty", "prepared_with_warnings"}:
        raise JobError(str(result.get("error") or result.get("reason") or "候选准备未完整成功，保留原候选池"))
    return {**result, "strategy": slug, "strategy_name": engine.name,
            "health": health, "spot_refresh": spot_refresh,
            "record_candidates": False, "push_wecom": False}
