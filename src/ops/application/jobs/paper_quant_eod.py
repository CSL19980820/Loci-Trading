"""paper_eod：日终总结、角色留痕消费、风格学习、滚动次日预案。"""
from __future__ import annotations

import logging
from typing import Any

from src.ops.application.jobs import paper_quant_support as support
from src.ops.application.jobs.context import JobContext, JobError
from src.ops.application.jobs.paper_quant_plan import generate_nextday_plan
from src.ops.application.notify_dispatch import dispatch_text
from src.ops.application.skill_watch.paper_eligibility import planned_layers_from_pick
from src.ops.application.skill_watch.observe_lifecycle import (
    format_observe_alert_follow_up,
)

logger = logging.getLogger(__name__)


def _ref_closes_for_eod(
    market: Any,
    codes: list[str],
    *,
    trade_date: str,
) -> dict[str, float]:
    """日终昨收：用日 K 收盘，禁止用持仓成本冒充。缺行情则缺省（监测回退 quote.prev_close）。"""
    if market is None or not codes:
        return {}
    out: dict[str, float] = {}
    try:
        bars = market.latest_bars(codes)
    except Exception as exc:  # noqa: BLE001 — 行情缺失不阻断日终滚动
        logger.warning("eod ref_close lookup failed: %s", exc)
        return {}
    for code, bar in (bars or {}).items():
        if not isinstance(bar, dict):
            continue
        close = bar.get("close")
        try:
            close_f = float(close) if close is not None else 0.0
        except (TypeError, ValueError):
            continue
        if close_f <= 0:
            continue
        bar_day = str(bar.get("trade_date") or "").strip()
        # 只要不晚于日终日即可；同步滞后时用最近一根收盘作参考
        if bar_day and bar_day > trade_date:
            continue
        out[str(code)] = close_f
    return out


def _refresh_suite_discoveries(
    store: Any,
    *,
    slug: str,
    previous_codes: set[str] | None = None,
) -> list[dict[str, Any]]:
    """日终重扫今日发现（可买+观察）；失败则空列表，不阻断滚动。"""
    from src.ops.application.skill_watch.engine_registry import eod_rescan_skill_for

    rescan_slug = eod_rescan_skill_for(slug)
    if not rescan_slug:
        return []
    try:
        from src.ops.application.skill_watch import run_skill_watch

        result = run_skill_watch(
            {"skill": rescan_slug, "slug": rescan_slug}, store=store
        )
        if result.get("skipped"):
            return []
        discoveries = [p for p in (result.get("picks") or []) if isinstance(p, dict)]
        if previous_codes:
            from src.ops.application.skill_watch.observe_lifecycle import (
                backfill_observe_rows,
            )

            discoveries.extend(
                backfill_observe_rows(result, previous_codes=set(previous_codes))
            )
        return discoveries
    except Exception as exc:  # noqa: BLE001
        logger.warning("eod suite discovery refresh failed for %s: %s", slug, exc)
        return []


def _nextday_picks_after_eod(
    store: Any,
    *,
    slug: str,
    trade_date: str,
    positions: list[dict[str, Any]],
    market: Any = None,
    plan_date: str | None = None,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """次日滚动：持仓 → 可买发现 → 观察池（粘性合并）。返回 (picks, observe_changes)。"""
    from src.ops.application.skill_watch.observe_pool import (
        merge_observe_pool,
        split_observe_upgraded_to_buy,
    )
    from src.ops.application.skill_watch.paper_eligibility import (
        is_auction_abandoned,
        is_observe_intent,
    )
    from src.ops.application.skill_watch.observe_lifecycle import (
        ROLE_REFRESH_MARKER,
        apply_observe_alert_review,
        clear_observe_alerts,
        load_observe_alerts,
    )
    from src.ops.application.skill_watch.tuning import load_tuning, section

    # 龙王只消费统一监察池；旧的观察池合并逻辑保留给历史非龙王舱兼容。
    raw_unified = (
        store.get_setting(f"unified_monitor_pool:{slug}", None)
        if slug == "dragon-return" and hasattr(store, "get_setting")
        else None
    )
    if (
        isinstance(raw_unified, dict)
        and str(raw_unified.get("trade_date") or "") == trade_date
    ):
        from src.ops.application.unified_monitor_pool import get_unified_monitor_pool

        unified = get_unified_monitor_pool(store, slug=slug, trade_date=trade_date)
        pool_items = [
            dict(item)
            for item in unified.get("items") or []
            if isinstance(item, dict) and str(item.get("code") or "").strip()
        ]
        codes = [str(item.get("code") or "").strip() for item in pool_items]
        closes = _ref_closes_for_eod(market, sorted(set(codes)), trade_date=trade_date)
        picks: list[dict[str, Any]] = []
        for item in pool_items:
            row = dict(item)
            code = str(row.get("code") or "").strip()
            action = str(row.get("action") or row.get("intent") or "observe")
            row["intent"] = action if action in {"buy", "observe", "holding"} else "observe"
            if row.get("bucket") == "position":
                row["planned_layers"] = row.get("layers") or 0.5
                row["thesis"] = row.get("thesis") or "持仓续盯"
            if closes.get(code) is not None:
                row["ref_close"] = closes[code]
            picks.append(row)
        alerts = load_observe_alerts(store, slug=slug, trade_date=trade_date)
        changes = unified.get("changes") if isinstance(unified.get("changes"), dict) else {}
        changes = apply_observe_alert_review(
            dict(changes),
            alerts=alerts,
            observe_pool=[row for row in pool_items if row.get("bucket") != "position"],
        )
        clear_observe_alerts(store, slug=slug)
        return picks, changes

    today_plan = store.get_nextday_plan(slug, trade_date) or {}
    plan_items = [
        item for item in (today_plan.get("items") or []) if isinstance(item, dict)
    ]
    # 优先沿用「次日预案」旧观察池，其次今日预案
    prev_by_code: dict[str, dict[str, Any]] = {}
    for src in (plan_items,):
        for item in src:
            code = str(item.get("code") or "").strip()
            if code and is_observe_intent(item):
                prev_by_code.setdefault(code, item)
    if plan_date:
        next_existing = store.get_nextday_plan(slug, plan_date) or {}
        for item in next_existing.get("items") or []:
            if not isinstance(item, dict):
                continue
            code = str(item.get("code") or "").strip()
            if code and is_observe_intent(item):
                prev_by_code[code] = item  # 次日旧池覆盖

    alerts = load_observe_alerts(store, slug=slug, trade_date=trade_date)
    discoveries = _refresh_suite_discoveries(
        store,
        slug=slug,
        previous_codes=set(prev_by_code),
    )
    # 盘中唯一池是当日事实源；盘后复盘优先消费它，移出不再被旧次日预案粘回来。
    live_pool = support.load_live_pool(store, slug=slug, trade_date=trade_date)
    if live_pool is not None:
        discoveries = live_pool
        prev_by_code = {}
    scan_cfg = section(load_tuning(store, slug), "scan")
    observe_min = float(scan_cfg.get("observe_min_score") or 50)
    max_observe_pool = int(scan_cfg.get("max_observe_pool") or 5)
    max_daily_adds = int(scan_cfg.get("max_observe") or 2)
    replace_margin = float(scan_cfg.get("observe_replace_margin") or 8)
    max_miss_days = int(scan_cfg.get("observe_max_miss_days") or 2)
    max_same_theme = int(scan_cfg.get("observe_max_same_theme") or 2)
    max_age_days = int(scan_cfg.get("observe_max_age_days") or 10)

    pos_codes = [
        str(pos.get("code") or "").strip()
        for pos in positions
        if str(pos.get("code") or "").strip()
    ]
    held = set(pos_codes)
    buy_discoveries = [
        d
        for d in discoveries
        if isinstance(d, dict)
        and not is_observe_intent(d)
        and not is_auction_abandoned(d)
    ]
    fresh_observes = [
        d
        for d in discoveries
        if isinstance(d, dict) and is_observe_intent(d) and not is_auction_abandoned(d)
    ]
    # 角色回填优先于 miss_days：当日地图判为走弱/破位时立即让 merge 看到坏角色。
    for row in discoveries:
        if not isinstance(row, dict) or not row.get(ROLE_REFRESH_MARKER):
            continue
        code = str(row.get("code") or "").strip()
        if code not in prev_by_code:
            continue
        refreshed = dict(prev_by_code[code])
        refreshed.update({key: value for key, value in row.items() if not key.startswith("_")})
        refreshed["intent"] = "observe"
        prev_by_code[code] = refreshed

    prev_observe = list(prev_by_code.values())
    prev_for_merge, upgraded = split_observe_upgraded_to_buy(prev_observe, buy_discoveries)
    observe_pool, observe_changes = merge_observe_pool(
        held_codes=held,
        fresh_observes=fresh_observes,
        previous_items=prev_for_merge,
        min_score=observe_min,
        max_pool=max_observe_pool,
        max_daily_adds=max_daily_adds,
        replace_margin=replace_margin,
        trade_date=trade_date,
        max_miss_days=max_miss_days,
        max_same_theme=max_same_theme,
        max_age_days=max_age_days,
    )
    if upgraded:
        observe_changes["upgraded"] = upgraded
        observe_changes["changed"] = True
    observe_changes = apply_observe_alert_review(
        observe_changes,
        alerts=alerts,
        observe_pool=observe_pool,
    )
    clear_observe_alerts(store, slug=slug)

    roll_codes = [
        str(item.get("code") or "").strip()
        for item in [*buy_discoveries, *observe_pool, *plan_items]
        if str(item.get("code") or "").strip()
    ]
    closes = _ref_closes_for_eod(
        market, sorted({*pos_codes, *roll_codes}), trade_date=trade_date
    )
    picks: list[dict[str, Any]] = []
    seen: set[str] = set()
    for pos in positions:
        code = str(pos.get("code") or "").strip()
        if not code or code in seen:
            continue
        seen.add(code)
        picks.append(
            {
                "code": code,
                "name": pos.get("name") or code,
                "intent": "buy",
                "planned_layers": pos.get("layers") or 0.5,
                # 禁止 mark_cost→ref_close：成本当昨收会把次日高低开判错
                "ref_close": closes.get(code),
                "thesis": "持仓续盯",
            }
        )
    for item in buy_discoveries:
        code = str(item.get("code") or "").strip()
        if not code or code in seen:
            continue
        seen.add(code)
        fresh = dict(item)
        if closes.get(code) is not None:
            fresh["ref_close"] = closes[code]
        picks.append(fresh)
    # 未成交可买预案项继续滚（观察改走池合并）
    for item in plan_items:
        code = str(item.get("code") or "").strip()
        if not code or code in seen or is_observe_intent(item):
            continue
        if is_auction_abandoned(item):
            continue
        seen.add(code)
        rolled: dict[str, Any] = {
            "code": code,
            "name": item.get("name") or code,
            "intent": "buy",
            "planned_layers": planned_layers_from_pick(item, default=1.0),
            "ref_close": closes.get(code, item.get("ref_close")),
            "thesis": "可买未成交，续滚",
        }
        for key in (
            "auction_stance",
            "auction_reason",
            "open_blocked",
            "role",
            "role_label",
            "role_basis",
            "auction",
            "suite",
            "suite_layer",
            "score",
        ):
            if key in item and item.get(key) is not None:
                rolled[key] = item.get(key)
        picks.append(rolled)
    for item in observe_pool:
        code = str(item.get("code") or "").strip()
        if not code or code in seen:
            continue
        seen.add(code)
        obs = dict(item)
        obs["intent"] = "observe"
        obs.pop(ROLE_REFRESH_MARKER, None)
        if closes.get(code) is not None:
            obs["ref_close"] = closes[code]
        picks.append(obs)
    return picks, observe_changes


def _eod_role_review(
    store: Any,
    *,
    slug: str,
    trade_date: str,
    positions: list[dict[str, Any]],
    persist_memory: bool = False,
) -> dict[str, Any]:
    """日终把角色留痕读出来：演进摘要 + 持仓角色告警。

    仅 ``persist_memory``（舱 ``eod_style_learn``）时把告警落成教训。读失败不阻断日终。
    """
    from src.ops.application.skill_watch.role_stats import (
        format_role_review,
        format_tuning_suggestions,
        position_role_alerts,
        role_lessons,
        suggest_tuning_adjustments,
        summarize_role_history,
    )
    from src.ops.application.skill_watch.tuning import load_tuning

    try:
        history = store.list_leader_roles(slug, limit=2000)
    except Exception as exc:  # noqa: BLE001 — 归档读失败不该毁掉日终
        logger.warning("eod role review failed for %s: %s", slug, exc)
        return {"text": "", "alerts": [], "lessons": 0, "suggestions": []}
    if not history:
        return {"text": "", "alerts": [], "lessons": 0, "suggestions": []}

    summary = summarize_role_history(history)
    alerts = position_role_alerts(positions=positions, history=history)
    suggestions = suggest_tuning_adjustments(history, current_tuning=load_tuning(store, slug))
    lessons = role_lessons(slug=slug, trade_date=trade_date, alerts=alerts)
    if persist_memory:
        for lesson in lessons:
            store.add_paper_lesson(lesson)
    text = format_role_review(summary, alerts)
    suggestion_text = format_tuning_suggestions(suggestions)
    if suggestion_text:
        text = f"{text}\n\n{suggestion_text}" if text else suggestion_text
    return {
        "text": text,
        "summary": summary,
        "alerts": alerts,
        "lessons": len(lessons),
        "suggestions": suggestions,
    }


def execute_paper_eod(config: dict[str, Any], context: JobContext) -> dict[str, Any]:
    """日终总结 + 评头论足/吸取教训 + 滚动次日预案。"""
    if context.ops_store is None:
        raise JobError("缺少运维库连接")
    store = context.ops_store
    slug = str(config.get("slug") or "").strip()
    if not slug:
        raise JobError("paper_eod 需要 slug")
    from src.ops.application.retire_dragon_return import load_paper_cabin

    cabin = load_paper_cabin(store, slug)
    if not cabin:
        return {"skipped": True, "reason": "retired_paper_cabin", "slug": slug}
    positions = store.list_paper_positions(cabin["id"])
    fills = store.list_paper_fills(cabin["id"], limit=50)
    today = support._today()

    market = None
    try:
        market = context.market_hot()
    except Exception:  # noqa: BLE001
        try:
            market = context.market()
        except Exception:  # noqa: BLE001
            market = None

    trading_gate = support.resolve_trading_day_gate(today, market=market)
    if not trading_gate.get("is_trading_day"):
        logger.info(
            "paper_eod skip non-trading day %s (%s): %s",
            slug,
            today,
            trading_gate.get("note"),
        )
        return {
            "skipped": True,
            "reason": "non_trading_day",
            "slug": slug,
            "trade_date": today,
            "trading_day_gate": trading_gate,
            "notes": str(trading_gate.get("note") or ""),
        }

    # list_paper_fills 是 created_at DESC；日终必须按时间正序讲，否则「开仓→止盈→开仓」
    # 会被读反，持仓成本对不上最后一笔流水，整段总结自相矛盾。
    today_fills = sorted(
        (f for f in fills if str(f.get("created_at") or "").startswith(today)),
        key=lambda row: str(row.get("created_at") or ""),
    )
    from src.ops.application.paper_copy_zh import FILL_ACTION_ZH
    from src.ops.application.skill_watch.watch_labels import watch_short_name

    label = watch_short_name(slug=slug)
    lines = [
        f"📒【日终总结】{label} · {today}",
        f"📦持仓 {len(positions)} 只 · ✍️今日成交 {len(today_fills)} 笔",
    ]
    for pos in positions:
        lines.append(
            f"- {pos.get('name') or pos.get('code')} {pos.get('code')} "
            f"{pos.get('layers')}层 成本 {pos.get('mark_cost')}"
        )
    for fill in today_fills[:15]:
        action = str(fill.get("action") or "").strip().lower()
        action_zh = FILL_ACTION_ZH.get(action, action or "成交")
        clock = str(fill.get("created_at") or "")[11:16]
        stamp = f"{clock} " if len(clock) == 5 and ":" in clock else ""
        lines.append(
            f"· {stamp}{action_zh} {fill.get('code')} "
            f"{fill.get('layers')} @ {fill.get('mark_price')}"
        )
    cfg = support._paper_quant_config(cabin.get("config") or {})
    # 默认不每日形成人设；显式 eod_style_learn=true 才落教训/吸入风格
    persist_memory = bool(cfg.get("eod_style_learn", False))
    role_review = _eod_role_review(
        store,
        slug=slug,
        trade_date=today,
        positions=positions,
        persist_memory=persist_memory,
    )
    if role_review["text"]:
        lines.append("")
        lines.append(role_review["text"])
    body = "\n".join(lines)

    from src.ops.application.paper_style_memory import run_eod_learning

    learning = run_eod_learning(
        store,
        slug=slug,
        trade_date=today,
        positions=positions,
        fills_today=today_fills,
        model=str(cfg.get("model") or ""),
        thinking=str(cfg.get("thinking") or "medium"),
        market=market,
        lookback=int(cfg.get("eod_lookback_days") or 5),
        include_capital_flow=bool(cfg.get("eod_include_capital_flow", False)),
        persist_memory=persist_memory,
        llm_timeout_sec=support.paper_llm_timeout_sec(cfg),
    )
    critique = str(learning.get("critique") or "")
    lookback_digest = str(learning.get("lookback_digest") or "")
    # 推送/入库摘要：短评 + 回看 digest；完整风格记忆不进企微
    for block in (critique, lookback_digest):
        if block:
            body = body + "\n\n" + block

    # 必须复用已打开的 market/hot：再 open 全量 market.db 会与桌面同步抢锁，日终挂死数十分钟。
    next_day = support._next_trade_date(today, market=market)
    items, observe_changes = _nextday_picks_after_eod(
        store,
        slug=slug,
        trade_date=today,
        positions=positions,
        market=market,
        plan_date=next_day,
    )
    alert_follow_up = format_observe_alert_follow_up(
        observe_changes.get("alert_follow_up") if isinstance(observe_changes, dict) else None
    )
    if alert_follow_up:
        body = f"{body}\n\n{alert_follow_up}"
    plan = generate_nextday_plan(
        store,
        slug=slug,
        picks=items,
        source="paper_eod",
        body_text=body,
        plan_date=next_day,
        notify=False,
        observe_changes=observe_changes,
    )
    notify_result: dict[str, Any] | None = None
    if cfg.get("follow_wecom") or config.get("push", True):
        # 盘后只保留一条复盘：总结与次日预案合并，避免用户面对两套名单。
        review_body = body[:2200]
        plan_section = str(plan.get("plan_section") or "").strip()
        if plan_section and (plan.get("items") or []):
            review_body = f"{review_body}\n\n{plan_section[:1800]}"
        notify_result = dispatch_text(
            store,
            title=f"盘后复盘·{label}",
            body=review_body,
        )
    return {
        "slug": slug,
        "plan_date": plan.get("plan_date"),
        "positions": len(positions),
        "fills_today": len(today_fills),
        "lessons": len(learning.get("lessons") or []),
        "absorbed": learning.get("absorbed", 0),
        "style_revision": (learning.get("style") or {}).get("revision"),
        "critique": critique,
        "lookback": learning.get("lookback"),
        "nextday_items": len(plan.get("items") or []),
        "notify": notify_result,
        "role_review": {
            "summary": role_review.get("summary"),
            "alerts": role_review.get("alerts"),
            "lessons": role_review.get("lessons", 0),
        },
    }
