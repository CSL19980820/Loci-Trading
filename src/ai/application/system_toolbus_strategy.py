"""全局助手的只读战法执行工具。"""
from __future__ import annotations

from typing import Any


def run_strategy_screen(owner: Any, args: dict[str, Any]) -> dict[str, Any]:
    from src.ai.application.system_toolbus import _ok
    from src.market import MarketStore
    from src.strategy import screen

    strategy = str(args["strategy"]).strip()
    agent_id = f"strategy:{strategy}"

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

        needs_full = bool(
            getattr(get_strategy(strategy), "requires_full_history", False)
        )
        if needs_full:
            store_cm = MarketStore(owner.market_db)
        else:
            from src.market import open_screen_store

            store_cm = open_screen_store(
                owner.market_db, getattr(owner, "market_hot_db", None)
            )
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
