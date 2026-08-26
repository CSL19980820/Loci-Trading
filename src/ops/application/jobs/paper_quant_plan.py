"""次日情景预案：选股/技能/日终成功后写入 nextday_plans。"""
from __future__ import annotations

from typing import Any

from src.ops.application.jobs import paper_quant_support as support
from src.ops.application.notify_dispatch import dispatch_text


def generate_nextday_plan(
    store: Any,
    *,
    slug: str,
    picks: list[dict[str, Any]] | None = None,
    source: str = "screen",
    body_text: str = "",
    plan_date: str | None = None,
    notify: bool | None = None,
    observe_changes: dict[str, Any] | None = None,
) -> dict[str, Any]:
    from src.ops.application.nextday_plan import (
        enrich_plan_items,
        format_plan_body,
        resolve_entry_mode,
    )
    from src.ops.application.retire_dragon_return import load_paper_cabin
    from src.ops.application.skill_watch.paper_eligibility import filter_openable_picks

    cabin = load_paper_cabin(store, slug)
    if not cabin:
        return {"skipped": True, "reason": "retired_paper_cabin", "slug": slug}
    cfg = support._paper_quant_config(cabin.get("config") or {})
    day = plan_date or support._next_trade_date()
    flat_band = float(cfg.get("flat_band_pct") or 0.5)
    entry_mode = resolve_entry_mode(slug, cfg)
    openable, excluded = filter_openable_picks(picks if isinstance(picks, list) else None)

    # 把战法调参里的竞价段（abandon/downgrade）写入预案项，监测与扫描同口径
    from src.ops.application.skill_watch.tuning import load_tuning, section

    tuning = load_tuning(store, slug)
    auction_defaults = section(tuning, "auction")
    seeded: list[dict[str, Any]] = []
    for row in openable:
        if not isinstance(row, dict):
            continue
        pick = dict(row)
        existing = pick.get("auction") if isinstance(pick.get("auction"), dict) else {}
        pick["auction"] = {**auction_defaults, **existing}
        seeded.append(pick)

    items = enrich_plan_items(
        seeded,
        flat_band_pct=flat_band,
        gap_up_chase=bool(cfg.get("gap_up_chase", False)),
        entry_mode=entry_mode,
    )

    change_report = observe_changes
    if source != "paper_eod":
        from src.ops.application.unified_monitor_pool import reconcile_unified_monitor_pool

        # 观察池粘性与淘汰参数由统一池上游扫描集中执行：
        # observe_max_same_theme / observe_max_age_days / observe_max_miss_days。
        unified = reconcile_unified_monitor_pool(
            store,
            slug=slug,
            trade_date=day,
            candidates=items,
            source="nextday_plan",
            preserve_existing=True,
        )
        items = [dict(item) for item in unified.get("items") or []]
        if change_report is None:
            change_report = unified.get("changes")

    plan_section = format_plan_body(
        slug, day, items, observe_changes=change_report
    )
    # 尝试补昨收：从 picks 已有字段；缺则保持 None，竞价时用 quote.prev_close
    if not body_text:
        body_text = plan_section
    elif items and "【次日情景预案】" not in body_text:
        # 日终总结正文常含「情景」字样，不能据此跳过真正的次日预案段
        body_text = body_text.rstrip() + "\n\n" + plan_section

    from src.ops.application.paper_style_memory import ensure_style, style_and_graph_prompt

    # 仅显式开启风格学习时注入/播种人设；默认预案正文不带风格 dump
    inject_style = bool(cfg.get("eod_style_learn", False) or cfg.get("inject_style_memory", False))
    style = (
        ensure_style(store, slug, entry_mode=entry_mode)
        if inject_style
        else store.get_paper_style(slug)
    )
    if inject_style:
        style_block = style_and_graph_prompt(store, slug)
        if style_block and "交易风格" not in body_text:
            body_text = body_text.rstrip() + "\n\n" + style_block

    plan = store.upsert_nextday_plan(
        {
            "slug": slug,
            "plan_date": day,
            "body_text": body_text,
            "items": items,
            "config_snapshot": {
                **cfg,
                "entry_mode": entry_mode,
                "plan_semantics": "scenario_v1",
                "auction_window": "09:15-09:30",
                "style_revision": style.get("revision"),
                "observe_changes": change_report or {},
                "auction_excluded": [
                    str(row.get("code"))
                    for row in excluded
                    if isinstance(row, dict) and row.get("code")
                ],
            },
            "source": source,
        }
    )
    # 盘后复盘链显式 notify=False；直接调用仍可按原契约单独推预案。
    should_notify = bool(notify) if notify is not None else source != "paper_eod"
    if should_notify and (cfg.get("follow_wecom") or cfg.get("notify_plan", True)):
        from src.ops.application.skill_watch.watch_labels import watch_short_name

        dispatch_text(
            store,
            title=f"次日预案·{watch_short_name(slug=slug)}",
            body=plan_section,
        )
    plan["plan_section"] = plan_section
    plan["observe_changes"] = change_report or {}
    return plan
