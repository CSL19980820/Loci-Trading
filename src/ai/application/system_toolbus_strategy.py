"""全局助手的只读战法执行工具。"""
from __future__ import annotations

from datetime import date
from typing import Any


def run_strategy_screen(owner: Any, args: dict[str, Any]) -> dict[str, Any]:
    from src.ai.application.system_toolbus import _ok
    from src.market import MarketStore
    from src.shared.screen_capacity import screen_capacity_permit
    from src.shared.tenancy import current_tenant, is_primary_tenant
    from src.strategy import screen

    strategy = str(args["strategy"]).strip()
    agent_id = f"strategy:{strategy}"
    tenant_label = (
        f"ai:{strategy}"
        if is_primary_tenant()
        else f"ai:[{current_tenant()}] {strategy}"
    )

    def progress(_: str, percent: float, detail: str) -> None:
        if owner.on_event:
            owner.on_event(
                {
                    "type": "subagent_progress",
                    "id": agent_id,
                    "name": strategy,
                    "progress": max(5, min(95, round(percent))),
                    "detail": detail,
                }
            )

    if owner.on_event:
        owner.on_event(
            {
                "type": "subagent_start",
                "id": agent_id,
                "name": strategy,
                "progress": 5,
                "detail": "开始运行战法",
            }
        )
    try:
        from src.strategy import get as get_strategy
        from src.strategy.domain.base import signal_history_bars

        engine = get_strategy(strategy)
        needs_full = bool(getattr(engine, "requires_full_history", False))
        if needs_full:
            store_cm = MarketStore(owner.market_db)
        else:
            from src.market import open_screen_store

            # 模型可以自己填任意 trade_date；只看窗口深度与末日的旧判据对历史日
            # 一律放行，静默少票的结果会经 candidate_verdict 产物进对话上下文，
            # 用户拿到的是「AI 说这天只有 3 只票」，不会想到去核对热库有没有那段历史。
            store_cm = open_screen_store(
                owner.market_db,
                getattr(owner, "market_hot_db", None),
                trade_date=str(args.get("trade_date") or date.today().isoformat()),
                warmup_bars=signal_history_bars(engine),
            )
        # AI 工具与 Job/HTTP 共用进程级面板容量。助手调用是同步 tool round，
        # 容量已满时快速返回错误，避免把模型回合和线程长期堵在队列里。
        with screen_capacity_permit(label=tenant_label, wait_sec=0):
            with store_cm as store:
                result = screen(
                    store,
                    strategy,
                    trade_date=args.get("trade_date") or None,
                    params=args.get("params") or None,
                    codes=args.get("codes") or None,
                    on_progress=progress,
                )
    except Exception as exc:
        if owner.on_event:
            owner.on_event(
                {
                    "type": "subagent_end",
                    "id": agent_id,
                    "name": strategy,
                    "ok": False,
                    "progress": 100,
                    "detail": f"{type(exc).__name__}: {exc}",
                }
            )
        raise

    picks = result.picks[:200]
    watch_picks = result.watch_picks[:200]
    payload = {
        "strategy": result.strategy_slug,
        "trade_date": result.trade_date,
        "entry_timing": result.entry_timing,
        "pick_count": len(result.picks),
        "watch_count": len(result.watch_picks),
        "universe_size": result.universe_size,
        "elapsed_seconds": round(result.elapsed_seconds, 3),
        "picks": picks,
        "watch_picks": watch_picks,
        "health": result.health,
    }
    owner._artifact("candidate_verdict", f"{result.strategy_slug} 选股结果", {"candidates": picks})
    if owner.on_event:
        owner.on_event(
            {
                "type": "subagent_end",
                "id": agent_id,
                "name": strategy,
                "ok": True,
                "progress": 100,
                "detail": (
                    f"正式 {len(result.picks)} 只"
                    f" · 低吸观察 {len(result.watch_picks)} 只"
                ),
            }
        )
    return _ok(payload)
