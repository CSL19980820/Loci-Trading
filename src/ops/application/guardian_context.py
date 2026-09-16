"""把当前已开启的战法及参数交给守护，不替模型决定交易策略。"""
from __future__ import annotations

from typing import Any
from copy import deepcopy


def premarket_plan_context(report: dict[str, Any] | None, state: dict[str, Any]) -> dict[str, Any] | None:
    """成交后旧计划数量作废，条件仍供模型参考；原报告保持不变。"""
    if not report or report['status'] != 'success':
        return None
    result = report['result']
    analysis = deepcopy(result.get('analysis'))
    if not analysis:
        return None
    baseline = {p['code']: p for p in result.get('facts', {}).get('account', {}).get('positions', [])}
    current = {p['code']: p for p in state['positions']}
    for plan in analysis.get('plans', []):
        if plan['code'] not in baseline or plan.get('quantity') is None:
            continue
        before, after = baseline[plan['code']], current.get(plan['code'], {})
        if any(before.get(key) != after.get(key) for key in ('quantity', 'available_quantity', 'cost_cents')):
            plan.update(snapshot_quantity=plan['quantity'], quantity=None,
                        quantity_status='replan_from_current_position',
                        current_quantity=after.get('quantity', 0),
                        current_available=after.get('available_quantity', 0))
    analysis['execution_note'] = '各条件是同一持仓快照下的备选计划，不是累计卖单。成交后旧数量失效；以当前持仓和可卖股数重新生成本轮订单，不能照搬原计划股数。'
    return analysis


def observation_snapshot(state: dict[str, Any]) -> dict[str, Any]:
    from datetime import datetime
    from zoneinfo import ZoneInfo
    from src.ledger import PalaceStore
    from src.market import MarketStore
    from src.shared.paths import palace_db
    today = datetime.now(ZoneInfo("Asia/Shanghai")).date().isoformat()
    with MarketStore() as market, PalaceStore(palace_db()) as palace:
        days = market.trading_days(end=today)[-5:]
        return {"watchlist": observe(palace, days, state, []), "watchlist_as_of": today,
                "watchlist_note": "行情日历尚未准备好" if not days else ""}


def active_strategies(store: Any) -> list[dict[str, Any]]:
    from src.strategy import describe_all
    from src.ops.application.skills import resolve_skill
    catalog = {item["slug"]: item for item in describe_all()}
    active: dict[str, dict[str, Any]] = {}
    for job in store.list_jobs(enabled_only=True):
        if job.get("kind") not in {"screen", "skill", "skill_watch", "strategy_monitor"}:
            continue
        cfg = job.get("config") or {}
        slug = str(cfg.get("strategy") or cfg.get("skill") or cfg.get("slug") or "")
        if not slug:
            continue
        if slug not in active:
            item = {**catalog.get(slug, {}), "slug": slug, "jobs": []}
            if slug not in catalog:
                try:
                    skill = resolve_skill(slug)
                except (ValueError, RuntimeError, FileNotFoundError):
                    skill = None
                if skill:
                    item.update(name=skill.get("name", slug), instructions=skill.get("instructions", ""))
                else:
                    item.update(name=slug, instructions_unavailable=True)
            active[slug] = item
        active[slug]["jobs"].append({"name": job["name"], "kind": job["kind"], "cron": job.get("cron", ""),
                                    "params": cfg.get("params", {}), "universe": cfg.get("universe")})
    return list(active.values())


def observe(palace: Any, days: list[str], state: dict[str, Any], strategies: list[str]) -> list[dict[str, Any]]:
    by_code: dict[str, dict[str, Any]] = {}
    for day in days:
        for item in palace.candidates_payload(day):
            slug = item.get("strategy_slug") or item.get("rule_version") or ""
            if item["decision"] != "精选" or (strategies and slug not in strategies):
                continue
            row = by_code.setdefault(item["code"], {"code": item["code"], "name": item["name"], "signals": [], "strategies": []})
            row["signals"].append(item)
            if slug not in row["strategies"]:
                row["strategies"].append(slug)
    for position in state["positions"]:
        row = by_code.setdefault(position["code"], {"code": position["code"], "name": position["name"], "signals": [], "strategies": position.get("strategies", [])})
        row["position"] = position
    for watched in state.get("watchlist", []):
        row = by_code.setdefault(watched["code"], {"code": watched["code"], "name": watched["name"], "signals": [], "strategies": []})
        row["watch"] = watched
    return list(by_code.values())
