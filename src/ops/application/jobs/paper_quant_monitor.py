"""strategy_monitor：盘中盯盘 + 情景门闩 + 可选 AI + 纸面执行。"""
from __future__ import annotations

import json
import logging
import time
from datetime import datetime, timedelta
from typing import Any

from src.ops.application.jobs import paper_quant_support as support
from src.ops.application.jobs.context import JobContext, JobError
from src.ops.application.notify_dispatch import dispatch_text
from src.ops.application.paper_capital import capital_prompt_note, derive_capital_view
from src.ops.application.paper_exec import PaperOrder, execute_orders

logger = logging.getLogger(__name__)


# 定义已拆到 paper_monitor_llm（本文件贴 600 行上限）；**调用点仍留在本模块**，
# 否则 mock.patch("...paper_quant_monitor._call_monitor_llm") 会失效。
from src.ops.application.jobs.paper_monitor_llm import (  # noqa: E402
    MonitorLLMUnusableError,
    _call_monitor_llm,
    _parse_orders_from_text,
    record_ai_decision,
)


def execute_strategy_monitor(config: dict[str, Any], context: JobContext) -> dict[str, Any]:
    """盘中盯盘：TTL → 情景/竞价门闩 →（可选 AI）→ 纸面执行 → 可选企微跟随。"""
    from src.market.application.live_cache import build_monitor_snapshot
    from src.ops.application.nextday_plan import (
        evaluate_auction_stance,
        merge_ai_orders_with_gates,
        scenario_gated_open_orders,
        session_clock,
    )

    if context.ops_store is None:
        raise JobError("缺少运维库连接")
    store = context.ops_store
    slug = str(config.get("slug") or "").strip()
    if not slug:
        raise JobError("strategy_monitor 需要 slug")

    started = time.monotonic()
    started_at = datetime.now().astimezone().isoformat(timespec="seconds")
    from src.ops.application.retire_dragon_return import load_paper_cabin

    cabin = load_paper_cabin(store, slug)
    if not cabin:
        return {"skipped": True, "reason": "retired_paper_cabin", "slug": slug}
    cfg = support._paper_quant_config(cabin.get("config") or {})
    cfg = {**cfg, **{k: v for k, v in config.items() if k != "slug"}}
    if not cfg.get("enabled", True) and not config.get("force"):
        return {"skipped": True, "reason": "monitor_disabled", "slug": slug}

    trade_date = support._today()
    with support.market_calendar_store() as market:
        trading_gate = support.resolve_trading_day_gate(trade_date, market=market)
        if not trading_gate.get("is_trading_day"):
            logger.info(
                "strategy_monitor skip non-trading day %s (%s): %s",
                slug,
                trade_date,
                trading_gate.get("note"),
            )
            return {
                "skipped": True,
                "reason": "non_trading_day",
                "slug": slug,
                "trade_date": trade_date,
                "trading_day_gate": trading_gate,
                "notes": str(trading_gate.get("note") or ""),
            }

        market_gate = support._resolve_market_gate(slug, cfg, store=store)
        plan = store.get_nextday_plan(slug, support._today()) or store.get_nextday_plan(
            slug,
            support._next_trade_date(
                (datetime.now(support._TZ) - timedelta(days=1)).strftime("%Y-%m-%d"),
                market=market,
            ),
        )
    if plan is None:
        plan = store.get_nextday_plan(slug, support._today())

    from src.ops.application.unified_monitor_pool import get_unified_monitor_pool

    unified_pool = get_unified_monitor_pool(store, slug=slug, trade_date=trade_date)
    positions = [
        dict(item)
        for item in unified_pool.get("items") or []
        if isinstance(item, dict) and item.get("bucket") == "position"
    ]
    plan_items = [
        dict(item)
        for item in unified_pool.get("items") or []
        if isinstance(item, dict) and item.get("bucket") != "position"
    ]
    # 统一池缺失时，龙王继续 fail-closed；其它战法可使用已有次日预案兼容运行。
    if not plan_items and slug != "dragon-return":
        plan_items = list((plan or {}).get("items") or [])
    plan = {**(plan or {}), "items": plan_items, "source": "unified_monitor_pool"}
    strategy_gate_codes = {
        str(item.get("code") or "")
        for item in plan_items
        if str(item.get("market_gate_policy") or "") == "strategy_specific"
        and item.get("entry_confirmed") is True
        and item.get("code")
    }
    codes = list({*(str(p["code"]) for p in positions), *(str(i.get("code")) for i in plan_items)})
    if not codes:
        return {"skipped": True, "reason": "empty_universe", "slug": slug}

    # 热路径只用 quotes；分钟线默认关，需显式 cfg.include_minute=true。
    snap = build_monitor_snapshot(codes, include_minute=bool(cfg.get("include_minute", False)))
    quotes = snap.quotes
    # 补昨收到 quote 供门闩：item.ref_close 优先，否则 quote.prev_close
    for item in plan_items:
        code = str(item.get("code") or "")
        q = quotes.get(code)
        if not q:
            continue
        if item.get("ref_close") is None and q.get("prev_close") is not None:
            item["ref_close"] = q.get("prev_close")

    flat_band = float(cfg.get("flat_band_pct") or 0.5)
    clock = session_clock(auction_allow_open=bool(cfg.get("auction_allow_open", False)))
    from src.ops.application.skill_watch.paper_eligibility import scan_auction_block_reason

    auction_stances: list[dict[str, Any]] = []
    for item in plan_items:
        block = scan_auction_block_reason(item)
        if block:
            auction_stances.append(
                {
                    "code": item.get("code"),
                    "stance": "abandon",
                    "scenario": None,
                    "gap_pct": None,
                    "reason": block,
                }
            )
        else:
            auction_stances.append(
                evaluate_auction_stance(
                    item,
                    quotes.get(str(item.get("code")) or "") or {},
                    flat_band_pct=flat_band,
                )
            )

    ai_mode = str(cfg.get("ai_mode") or ("suggest" if cfg.get("model") else "rules")).lower()
    orders: list[PaperOrder] = []
    gate_rejects: list[dict[str, Any]] = []
    notes = ""
    llm_failed = False
    llm_unusable = False
    capital = derive_capital_view(cabin, positions, quotes)
    ai_driven = bool(ai_mode in {"suggest", "explain", "auto"} and cfg.get("model"))
    if not trading_gate.get("buy_execution_allowed"):
        notes = str(trading_gate.get("note") or "交易日历缺失，买入 fail-closed")
    if ai_driven:
        from src.ops.application.paper_style_memory import style_and_graph_prompt

        style_block = style_and_graph_prompt(store, slug)
        from src.ops.application.skill_watch.observe_pool import OBSERVE_MONITOR_AI_RULES
        from src.ops.application.skill_watch.paper_eligibility import is_observe_intent

        observe_rules = (
            f"\n{OBSERVE_MONITOR_AI_RULES}"
            if any(is_observe_intent(i) for i in plan_items)
            else ""
        )
        system = (
            "你是战法纸面量化执行助手。次日预案含高开/平开/低开情景与竞价纠偏，不是随便开仓。"
            "必须遵守本战法交易风格记忆与记忆知识图（教训边/规则边）；吸取过往教训，不要重复踩坑。"
            "只能基于快照/持仓/预案/竞价纠偏/风格记忆决策。"
            "若市场闸门不是“龙”，普通候选禁止开仓/加仓/低吸；"
            "但 market_gate_policy=strategy_specific 且 entry_confirmed=true 的候选，"
            "已通过本战法自己的市场宽度确认，不受全局闸门一票否决。"
            "已有持仓始终可按规则减仓或退出。"
            "竞价/开盘前(09:15-09:30)以纠偏为主：可输出持有与 notes，不要强行开仓。"
            "开仓须对应情景可买且价格落在介入区间；高开默认不追。"
            "输出 JSON：{\"orders\":[{\"code\",\"action\",\"layers\",\"reason\"}],\"notes\":\"\"}。"
            "action 仅限 open,add,reduce,close,take_profit,stop_cut,trim_high,buy_dip,hold（机器字段）；"
            "notes/reason 必须纯中文，禁止写出 gap_up、entry_allowed、intent=、stance= 等英文字段名。"
            "layers 为 0.5 的倍数；不得编造快照中没有的价格。"
            f"{observe_rules}"
            f"\n资金约束：{capital_prompt_note(capital)}"
            f"\n{style_block}"
        )
        user = json.dumps(
            {
                "slug": slug,
                "session": {"phase": clock.phase, "in_auction": clock.in_auction},
                "plan": plan,
                "auction_stances": auction_stances,
                "market_gate": market_gate,
                "positions": positions,
                # 名义资金视图：由层数推导，不是可提现余额（见 paper_capital）
                "capital": capital.as_dict(),
                "quotes": quotes,
                "fetched_at": snap.fetched_at,
                "config": {
                    "max_layers": cabin.get("max_layers"),
                    "min_layer_step": cfg.get("min_layer_step", 0.5),
                    "flat_band_pct": flat_band,
                    "trim_high_min_pnl_pct": cfg.get("trim_high_min_pnl_pct"),
                    "buy_dip_drawdown_pct": cfg.get("buy_dip_drawdown_pct"),
                },
            },
            ensure_ascii=False,
        )
        llm_started = time.monotonic()
        raw_output = ""
        llm_status = "ok"
        llm_error = ""
        try:
            text = _call_monitor_llm(
                store=store,
                model=str(cfg.get("model") or ""),
                thinking=str(cfg.get("thinking") or "medium"),
                system=system,
                user=user,
                timeout_seconds=support.paper_llm_timeout_sec(cfg),
            )
            raw_output = text
            ai_orders, notes = _parse_orders_from_text(text)
            orders, gate_rejects = merge_ai_orders_with_gates(
                ai_orders,
                plan_items=plan_items,
                quotes=quotes,
                clock=clock,
                flat_band_pct=flat_band,
            )
        except MonitorLLMUnusableError as exc:
            # 失语：不回退规则/情景门闩替 AI 下单；failed + 强制告警
            llm_unusable = True
            llm_failed = True
            llm_status, llm_error, raw_output = "unusable", str(exc), exc.snippet or ""
            orders = []
            notes = (
                "模型未产出可执行输出，本轮未执行任何操作"
                + (f"；片段={exc.snippet[:120]}" if exc.snippet else f"；{exc}")
            )
            logger.warning("monitor LLM unusable for %s: %s", slug, exc)
        except Exception as exc:  # noqa: BLE001
            llm_failed = True
            llm_status, llm_error = "failed", str(exc)
            logger.warning("monitor LLM failed for %s: %s", slug, exc)
            orders, auction_stances, notes = scenario_gated_open_orders(
                plan_items=plan_items,
                positions=positions,
                quotes=quotes,
                clock=clock,
                flat_band_pct=flat_band,
                stances=auction_stances,
            )
            notes = f"LLM 失败，回退情景门闩：{exc}；{notes}"
        # 留痕存「模型看到的报价数值 + prompt 原文 + 原始回复」，缺这三样事后
        # 无法复盘它凭什么这么判。写失败只记日志，绝不影响交易。
        record_ai_decision(
            store,
            {
                "slug": slug,
                "trade_date": str(trading_gate.get("trade_date") or ""),
                "session_phase": clock.phase,
                "model": str(cfg.get("model") or ""),
                "system_prompt": system,
                "user_payload": json.loads(user),
                "raw_output": raw_output,
                "parsed_orders": [o.as_dict() for o in orders],
                "quotes": quotes,
                "status": llm_status,
                "error_text": llm_error,
                "latency_ms": int((time.monotonic() - llm_started) * 1000),
            },
        )
    else:
        orders, auction_stances, notes = scenario_gated_open_orders(
            plan_items=plan_items,
            positions=positions,
            quotes=quotes,
            clock=clock,
            flat_band_pct=flat_band,
            stances=auction_stances,
        )

    # 退出兜底对两条路径都生效：AI 失语时 orders 会被清空，异常回退只产开仓单，
    # 没有这一层则亏损仓无人处理。
    from src.ops.application.rules_exit_orders import position_exit_orders

    exit_orders, exit_note = position_exit_orders(
        existing=orders,
        positions=positions,
        plan_items=plan_items,
        quotes=quotes,
        cfg=cfg,
        slug=slug,
        stances=auction_stances,
        flat_band_pct=flat_band,
        ai_driven=ai_driven,
    )
    if exit_orders:
        orders = exit_orders + orders
    if exit_note:
        notes = f"{exit_note}；{notes}" if notes else exit_note

    if not trading_gate.get("buy_execution_allowed") and orders:
        buy_blocked = [
            o
            for o in orders
            if str(o.action or "").lower() in {"open", "add", "buy_dip"}
        ]
        if buy_blocked:
            gate_rejects.extend(
                {
                    "code": o.code,
                    "action": o.action,
                    "reason": str(trading_gate.get("note") or "交易日历缺失，买入 fail-closed"),
                }
                for o in buy_blocked
            )
            orders = [
                o
                for o in orders
                if str(o.action or "").lower() not in {"open", "add", "buy_dip"}
            ]

    orders, market_gate_rejects = support._apply_market_gate(
        orders,
        market_gate,
        entry_exempt_codes=strategy_gate_codes,
    )
    gate_rejects.extend(market_gate_rejects)
    if market_gate and not market_gate.get("entry_allowed"):
        gate_note = f"龙空龙={market_gate.get('mode') or '空'}"
        if strategy_gate_codes:
            gate_note += "，普通候选禁开；已确认候选按本战法宽度执行"
        else:
            gate_note += "，本轮不新增纸面仓位"
        notes = f"{notes}；{gate_note}".strip("；")

    apply_paper = bool(cfg.get("ai_apply_paper", True))
    result_fills: list[dict[str, Any]] = []
    result_rejects: list[dict[str, Any]] = list(gate_rejects)
    if apply_paper and orders:
        exec_result = execute_orders(
            store,
            slug=slug,
            orders=orders,
            quotes=quotes,
            source="strategy_monitor",
            allow_actions=set(cfg["allow_actions"]) if cfg.get("allow_actions") else None,
            trim_high_min_pnl_pct=(
                float(cfg["trim_high_min_pnl_pct"])
                if cfg.get("trim_high_min_pnl_pct") is not None
                else None
            ),
            buy_dip_drawdown_pct=(
                float(cfg["buy_dip_drawdown_pct"])
                if cfg.get("buy_dip_drawdown_pct") is not None
                else None
            ),
        )
        result_fills = exec_result.fills
        result_rejects = result_rejects + exec_result.rejects
        unified_pool = get_unified_monitor_pool(store, slug=slug, trade_date=trade_date)

    follow = bool(cfg.get("follow_wecom"))
    collect_follow = bool(config.get("collect_follow"))
    emit_follow = config.get("emit_follow", True) is not False
    include_position_lines = config.get("include_position_lines", True) is not False
    follow_pushed = False
    follow_body = ""
    from src.ops.application.jobs.paper_follow_push import (
        format_position_lines,
        format_stance_line,
        phase_zh,
        should_push_hold_snapshot,
    )
    from src.ops.application.skill_watch.observe_lifecycle import (
        collect_observe_alerts,
        save_observe_alerts,
    )
    from src.ops.application.skill_watch.paper_eligibility import is_observe_intent
    from src.ops.application.skill_watch.tuning import load_tuning, section
    from src.ops.application.skill_watch.watch_labels import watch_short_name
    from src.ops.application.skill_watch.actionable_line import format_actionable_line

    short = watch_short_name(slug=slug)
    title = f"监测·{short}"
    stance_lines = [
        line
        for line in (format_stance_line(s) for s in auction_stances if isinstance(s, dict))
        if line
    ]
    # 刷新持仓（成交后）供摘要；观察票与持仓一样进 TTL 巡检
    open_positions = [
        dict(item)
        for item in unified_pool.get("items") or []
        if isinstance(item, dict) and item.get("bucket") == "position"
    ]
    observe_items = [i for i in plan_items if is_observe_intent(i)]
    scan_cfg = section(load_tuning(store, slug), "scan")
    observe_min_score = float(scan_cfg.get("observe_min_score") or 50)
    observe_alert_drop_pct = float(scan_cfg.get("observe_alert_drop_pct") or -5.0)
    observe_alerts, observe_alert_lines = collect_observe_alerts(
        observe_items,
        quotes,
        trade_date=trade_date,
        min_score=observe_min_score,
        drop_pct=observe_alert_drop_pct,
    )
    if observe_alerts:
        try:
            save_observe_alerts(
                store,
                slug=slug,
                trade_date=trade_date,
                alerts=observe_alerts,
            )
        except Exception as exc:  # noqa: BLE001 — 预警落盘失败不阻断盘中巡检
            logger.warning("observe alert persistence failed for %s: %s", slug, exc)
    observe_alert_fp = "|".join(sorted(observe_alert_lines))
    eventful = bool(result_fills or result_rejects or clock.in_auction or llm_unusable)
    hold_status = False
    if (follow or collect_follow) and not eventful and (open_positions or observe_alerts):
        hold_status = should_push_hold_snapshot(
            store,
            slug=slug,
            trade_date=support._today(),
            phase=str(clock.phase or ""),
            positions=open_positions,
            observe_items=observe_items,
            notes=notes,
            market_gate=market_gate if isinstance(market_gate, dict) else None,
            observe_alert_fp=observe_alert_fp,
        )
    # 失语强制告警；其他纸面跟随只在成交/拒单/持仓观察巡检时推。
    should_follow = llm_unusable or (
        (follow or collect_follow) and (bool(result_fills or result_rejects) or hold_status)
    )
    if should_follow:
        # 模型 notes 保留在 monitor_runs 审计，不再进入通知。自由散文会重复盘面、
        # 候选与纪律结论，且不能充当持仓/成交事实。
        lines = [f"📅{phase_zh(str(clock.phase or ''))} · {short}"]
        if llm_unusable:
            lines.append("⚠️模型失语：本轮未执行任何纸面操作，请人工确认")
        if hold_status and not eventful:
            if open_positions and include_position_lines:
                lines.append("👀持仓巡检")
            elif observe_alert_lines:
                lines.append("⚠️观察池变动")
        if stance_lines and (result_fills or result_rejects or hold_status):
            # 观察票的 wait 不刷屏；只带可买相关竞价行
            buy_stance = [
                format_stance_line(s)
                for s in auction_stances
                if isinstance(s, dict)
                and str(s.get("reason") or "") != "观察票：次日跟踪，不开仓"
            ]
            buy_stance = [x for x in buy_stance if x]
            if buy_stance:
                lines.append("🔔竞价/开盘：" + " | ".join(buy_stance[:6]))
        for fill in result_fills:
            action = str(fill.get("action") or "")
            action_zh = {
                "open": "开仓",
                "add": "加仓",
                "reduce": "减仓",
                "close": "清仓",
                "take_profit": "止盈",
                "stop_cut": "止损",
                "buy_dip": "低吸",
                "trim_high": "高抛",
            }.get(action, action)
            if action in {"open", "add", "buy_dip"}:
                lines.append(
                    format_actionable_line(
                        name=str(fill.get("name") or ""),
                        code=str(fill.get("code") or ""),
                        layers=fill.get("layers"),
                        buy_price=fill.get("mark_price"),
                        pnl_pct=cfg.get("pnl_pct"),
                        stop_loss_pct=cfg.get("stop_loss_pct"),
                        take_profit_pct=cfg.get("take_profit_pct"),
                    )
                    + (f" · {action_zh}" if action_zh else "")
                )
            else:
                lines.append(
                    f"✓{action_zh} {fill.get('name') or fill.get('code')} "
                    f"{fill.get('layers')}层 @ {fill.get('mark_price')}"
                )
        for reject in result_rejects[:6]:
            lines.append(
                f"✗拒单 {reject.get('name') or reject.get('code')}: {reject.get('reason')}"
            )
        if include_position_lines:
            pos_lines = format_position_lines(open_positions, quotes)
            if pos_lines:
                lines.extend(pos_lines)
        # 观察名单只在「监测·龙回头」出现；这里仅补异常，避免第二条消息再打一遍旧/新池。
        if observe_alert_lines:
            lines.extend(observe_alert_lines)
        body = "\n".join(line for line in lines if str(line).strip()).strip()
        if len(lines) == 1 and not llm_unusable:
            body = ""
        follow_body = body
        if body and emit_follow:
            outcome = dispatch_text(store, title=title, body=body)
            follow_pushed = bool(outcome.get("sent"))

    duration_ms = int((time.monotonic() - started) * 1000)
    run_status = "success"
    if llm_failed:
        run_status = "failed"
    elif not trading_gate.get("buy_execution_allowed") and any(
        str(o.action or "").lower() in {"open", "add", "buy_dip"} for o in orders
    ):
        run_status = "failed"

    run_id = store.insert_monitor_run(
        {
            "slug": slug,
            "status": run_status,
            "trigger_source": str(config.get("trigger") or "schedule"),
            "snapshot": {
                "fetched_at": snap.fetched_at,
                "codes": codes,
                "adapter_ids": snap.adapter_ids,
                "cache_hits": snap.cache_hits,
                "session_phase": clock.phase,
                "auction_stances": auction_stances,
                "market_gate": market_gate,
                "trading_day_gate": trading_gate,
            },
            "orders": [o.as_dict() for o in orders],
            "fills": result_fills,
            "rejects": result_rejects,
            "notes": notes,
            "follow_pushed": follow_pushed,
            "started_at": started_at,
            "finished_at": datetime.now().astimezone().isoformat(timespec="seconds"),
            "duration_ms": duration_ms,
        }
    )
    return {
        "run_id": run_id,
        "slug": slug,
        "status": run_status,
        "trading_day_gate": trading_gate,
        "session_phase": clock.phase,
        "auction_stances": auction_stances,
        "market_gate": market_gate,
        "fills": len(result_fills),
        "rejects": len(result_rejects),
        "follow_pushed": follow_pushed,
        "follow_body": follow_body,
        "notes": notes,
        "duration_ms": duration_ms,
    }
