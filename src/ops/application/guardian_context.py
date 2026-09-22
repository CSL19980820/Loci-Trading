"""量化候选来源与自主观察上下文。"""
from __future__ import annotations

from typing import Any
from copy import deepcopy


def reference_days(target_day: str) -> list[str]:
    """目标交易日前最近三个已结束交易日，不把目标日占作一个名额。"""
    from datetime import date, timedelta
    from src.market import scheduled_trading_days
    target = date.fromisoformat(target_day)
    return scheduled_trading_days((target - timedelta(days=40)).isoformat(),
                                  (target - timedelta(days=1)).isoformat())[-3:]


def reference_target_day(as_of) -> str:
    from datetime import timedelta, time
    from src.market import scheduled_trading_days
    day = as_of.date()
    if as_of.time().replace(tzinfo=None) >= time(15):
        day += timedelta(days=1)
    return scheduled_trading_days(day.isoformat(), (day + timedelta(days=40)).isoformat())[0]


def quant_reference_candidates(candidates: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """只向自主模型提供量化候选出处，不携带策略的交易要求。"""
    fields = ('id', 'date', 'code', 'name', 'strategy_slug', 'strategy_revision', 'created_at', 'source')
    return [{**deepcopy(row), 'signals': [{key: signal[key] for key in fields if key in signal}
                                        for signal in row.get('signals', [])]}
            for row in candidates]


def strategy_sources(store: Any) -> list[dict[str, str]]:
    return [{'slug': row['slug'], 'name': row.get('name', row['slug'])} for row in active_strategies(store)]


def premarket_plan_context(report: dict[str, Any] | None, state: dict[str, Any]) -> dict[str, Any] | None:
    """成交后旧计划数量作废，条件仍供模型参考；原报告保持不变。"""
    if not report or report['status'] != 'success':
        return None
    result = report['result']
    from src.ops.application.guardian_memory import MEMORY_NOTE
    analysis = deepcopy(result.get('analysis'))
    if not analysis:
        return None
    # The current bounded snapshot has its own port; old snapshots are audit only.
    analysis.pop('experience', None)
    analysis['memory_note'] = MEMORY_NOTE
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
    from src.shared.paths import palace_db
    today = datetime.now(ZoneInfo("Asia/Shanghai")).date().isoformat()
    with PalaceStore(palace_db()) as palace:
        days = reference_days(reference_target_day(datetime.now(ZoneInfo("Asia/Shanghai"))))
        candidates = observe(palace, days, state, [])
        return {"watchlist": candidates, "watchlist_as_of": today,
                **observation_groups(candidates, state),
                "watchlist_note": "行情日历尚未准备好" if not days else "工坊仅为参考；自主观察以模型明确选择为准"}


def review_memory_context(reports: list[dict[str, Any]], state: dict[str, Any], as_of) -> list[dict[str, Any]]:
    """交接完整研究，而不把复盘观点升级为交易指令或重用过期股数。"""
    from src.ops.application.guardian_review_data import _report_available_as_of

    memory = []
    for report in reports:
        if report.get('period') == 'premarket' or not _report_available_as_of(report, as_of):
            continue
        analysis = premarket_plan_context(report, state)
        if analysis is None:
            continue
        result = report['result']
        planning = result.get('facts', {}).get('planning_trade_date', '')
        for plan in analysis.get('plans', []):
            if plan.get('quantity') is not None and (not planning or planning < as_of.date().isoformat()):
                plan.update(snapshot_quantity=plan['quantity'], quantity=None,
                            quantity_status='replan_from_current_position')
        memory.append({**analysis, 'date': report['trade_date'], 'period': report['period'],
                       'report_key': report.get('report_key', f"{report['period']}:{report['trade_date']}"),
                       'revision': result.get('revision', 1), 'created_at': result.get('created_at'),
                       'planning_trade_date': planning, 'status': 'research_reference_not_instruction',
                       'usage_note': '研究材料供当前判断参考，各经验保留原验证状态；交易需当前决策与执行回执。'})
    return memory


def observation_groups(candidates: list[dict[str, Any]], state: dict[str, Any]) -> dict[str, Any]:
    """兼容旧参考池接口，同时明确自主观察与工坊来源；不改变任何账户状态。"""
    references = [{key: row[key] for key in ("code", "name", "signals", "strategies") if key in row}
                  for row in candidates if row.get("signals")]
    watched = state.get("watchlist", [])
    return deepcopy({"self_watchlist": watched, "reference_pool": references,
                     "pool_counts": {"held": len(state.get("positions", [])),
                                     "self_watched": len(watched), "workshop_references": len(references)},
                     "watchlist_semantics": "legacy_combined_reference_pool"})


def active_strategies(store: Any) -> list[dict[str, Any]]:
    from src.strategy import describe_all
    from src.ops.application.retired_slugs import is_retired_strategy_slug
    from src.ops.application.skills import resolve_skill
    catalog = {item["slug"]: item for item in describe_all()}
    active: dict[str, dict[str, Any]] = {}
    for job in store.list_jobs(enabled_only=True):
        if job.get("kind") not in {"screen", "skill", "skill_watch", "strategy_monitor"}:
            continue
        cfg = job.get("config") or {}
        slug = str(cfg.get("strategy") or cfg.get("skill") or cfg.get("slug") or "")
        if not slug or is_retired_strategy_slug(slug):
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
    from src.ops.application.retired_slugs import is_retired_strategy_slug
    by_code: dict[str, dict[str, Any]] = {}
    for day in days:
        for item in palace.candidates_payload(day):
            slug = item.get("strategy_slug") or item.get("rule_version") or ""
            if (is_retired_strategy_slug(slug) or item["decision"] != "精选"
                    or (strategies and slug not in strategies)):
                continue
            dismissed = state.get('reference_dismissals', {}).get(item['code'], {})
            if str(item.get('date') or day) <= dismissed.get('through_date', ''):
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
