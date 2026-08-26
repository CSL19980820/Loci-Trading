"""次日情景预案构建：模板、条目 enrich、正文格式化。"""
from __future__ import annotations

from typing import Any


def _safe_float(value: Any) -> float | None:
    try:
        if value is None or value == "":
            return None
        return float(value)
    except (TypeError, ValueError):
        return None


def resolve_entry_mode(slug: str, cabin_cfg: dict[str, Any] | None = None) -> str:
    """预案入场模式：cabin 显式配置优先，否则跟战法 entry_timing。

    - next_open：基线统一开盘接；各情景用层数/价位带做动态调仓择位（过高可减层或等回踩）
    - scenario：分情景调仓择位（过高可暂缓或浅接，不是对错）
    """
    cfg = cabin_cfg if isinstance(cabin_cfg, dict) else {}
    explicit = str(cfg.get("entry_mode") or "").strip().lower()
    if explicit in {"next_open", "scenario"}:
        return explicit
    try:
        from src.strategy import get as get_strategy

        engine = get_strategy(slug)
        timing = str(getattr(engine, "entry_timing", "") or "").strip()
        if timing == "next_open":
            return "next_open"
    except Exception:  # noqa: BLE001
        pass
    return "scenario"


def default_scenarios(
    *,
    planned_layers: float = 1.0,
    flat_band_pct: float = 0.5,
    gap_up_chase: bool = False,
    entry_mode: str = "scenario",
) -> dict[str, Any]:
    """情景模板：层数=仓位调整，价位带=择位；buy=本情景是否接（非对错）。"""
    layers = max(0.5, float(planned_layers))
    # 浅接固定半层，不随计划层数缩放（原写法 max(0.5, min(layers, 0.5)) 因
    # layers >= 0.5 恒等于 0.5，看着像缩放其实不是）。
    shallow = 0.5
    if entry_mode == "next_open":
        # 基线：开盘接；高开用「舒适带」提示过高时减层/等回踩，一字仍放弃
        comfort_hi = max(flat_band_pct, 3.0)
        return {
            "gap_up": {
                "buy": True,
                "entry_pct_min": flat_band_pct,
                "entry_pct_max": 9.5,
                "comfort_pct_max": comfort_hi,
                "layers": layers,
                "layers_if_stretched": shallow,
                "note": (
                    f"高开：开盘可按 {layers} 层接；若过高（>{comfort_hi}%）先减到 "
                    f"{shallow} 层或等回踩到舒适带再补；近涨停/一字放弃——动态择位，不是『高开=错』"
                ),
            },
            "flat": {
                "buy": True,
                "entry_pct_min": -flat_band_pct,
                "entry_pct_max": flat_band_pct,
                "layers": layers,
                "note": f"平开：按计划 {layers} 层开盘接",
            },
            "gap_down": {
                "buy": True,
                "entry_pct_min": -9.5,
                "entry_pct_max": -flat_band_pct,
                "layers": layers,
                "note": f"低开：开盘仍按 {layers} 层接；深砸可等稳住再跟，属仓位时机调整",
            },
        }
    return {
        "gap_up": {
            "buy": bool(gap_up_chase),
            "entry_pct_min": flat_band_pct,
            "entry_pct_max": 3.0 if gap_up_chase else flat_band_pct,
            "layers": shallow if gap_up_chase else 0.0,
            "note": (
                "高开过高：本情景暂缓或仅浅接半层；可等回踩到平开带再接——"
                "调仓择位，不是『高开=错误』"
                if not gap_up_chase
                else "高开：允许浅接半层；再高则等回踩，动态减仓/择位"
            ),
        },
        "flat": {
            "buy": True,
            "entry_pct_min": -flat_band_pct,
            "entry_pct_max": flat_band_pct,
            "layers": layers,
            "note": f"平开：按计划 {layers} 层接",
        },
        "gap_down": {
            "buy": True,
            "entry_pct_min": -4.0,
            "entry_pct_max": -flat_band_pct,
            "layers": max(0.5, min(layers, 1.0)),
            "note": "低开：仅低吸带内接；深砸本情景暂缓另议——仓位与价位调整",
        },
    }


def build_plan_item(
    pick: dict[str, Any],
    *,
    flat_band_pct: float = 0.5,
    gap_up_chase: bool = False,
    entry_mode: str = "scenario",
) -> dict[str, Any] | None:
    from src.ops.application.skill_watch.paper_eligibility import (
        is_auction_abandoned,
        is_auction_downgraded,
        is_observe_intent,
    )

    code = str(pick.get("code") or "").strip()
    if not code or is_auction_abandoned(pick):
        return None
    intent = "observe" if is_observe_intent(pick) else "buy"
    # planned_layers_max 是 enrich 后权威键；与 EOD 对齐 max 优先
    layers = float(
        pick.get("planned_layers_max")
        or pick.get("planned_layers")
        or pick.get("layers")
        or (0.0 if intent == "observe" else 1.0)
    )
    ref_close = _safe_float(pick.get("ref_close") or pick.get("last_close") or pick.get("close"))
    scenarios = pick.get("scenarios") if isinstance(pick.get("scenarios"), dict) else None
    auction = pick.get("auction") if isinstance(pick.get("auction"), dict) else {}
    if is_auction_downgraded(pick) or auction.get("downgraded"):
        layers = min(layers, 0.5)
        gap_up_chase = False
    if intent == "observe":
        layers = 0.0
        scenarios = {
            key: {
                "buy": False,
                "entry_pct_min": sc.get("entry_pct_min"),
                "entry_pct_max": sc.get("entry_pct_max"),
                "layers": 0,
                "note": "观察票：次日跟踪，不开仓",
            }
            for key, sc in (
                default_scenarios(
                    planned_layers=1.0,
                    flat_band_pct=flat_band_pct,
                    gap_up_chase=False,
                    entry_mode=entry_mode,
                ).items()
            )
        }
    elif not scenarios:
        scenarios = default_scenarios(
            planned_layers=layers,
            flat_band_pct=flat_band_pct,
            gap_up_chase=gap_up_chase,
            entry_mode=entry_mode,
        )
    # next_open：开盘价即成交价，不要求落在窄情景带；仍保留近涨停 abandon
    follow_requires = bool(auction.get("follow_requires_band", entry_mode != "next_open"))
    return {
        "code": code,
        "name": pick.get("name") or code,
        "ref_close": ref_close,
        "thesis": str(pick.get("thesis") or pick.get("note") or pick.get("reason") or ""),
        "planned_layers_max": layers,
        "entry_mode": entry_mode,
        "intent": intent,
        "suite": pick.get("suite"),
        "suite_layer": pick.get("suite_layer"),
        "role_label": pick.get("role_label"),
        "score": pick.get("score"),
        "scenarios": scenarios,
        # 透传调用方多带的字段，但归一后的值必须压在最后——放前面会被原始
        # auction 整体覆盖掉，float() 强转与上面算出的 follow_requires 全作废。
        "auction": {
            **{k: v for k, v in auction.items() if k != "window"},
            "window": "09:15-09:30",
            "revise_allowed": bool(auction.get("revise_allowed", True)),
            "abandon_gap_up_limit": bool(auction.get("abandon_gap_up_limit", True)),
            "abandon_gap_pct": float(auction.get("abandon_gap_pct", -5.0)),
            "downgrade_gap_pct": float(auction.get("downgrade_gap_pct", -2.0)),
            "follow_requires_band": follow_requires,
        },
        "veto": list(pick.get("veto") or ["一字涨停不开", "竞价失控砸盘放弃"]),
        "auction_stance": pick.get("auction_stance"),
        "auction_reason": pick.get("auction_reason"),
        "open_blocked": pick.get("open_blocked"),
        "role": pick.get("role"),
        "role_basis": pick.get("role_basis"),
        "stop_loss_pct": _safe_float(pick.get("stop_loss_pct")),
        "take_profit_pct": _safe_float(pick.get("take_profit_pct")),
    }


def format_plan_body(
    slug: str,
    plan_date: str,
    items: list[dict[str, Any]],
    *,
    observe_changes: dict[str, Any] | None = None,
) -> str:
    """企微/入库情景段：可买情景一行化；观察一行一条；有变更则汇报。"""
    from src.ops.application.skill_watch.observe_pool import (
        format_observe_change_report,
        format_observe_line,
    )
    from src.ops.application.skill_watch.paper_eligibility import is_observe_intent
    from src.ops.application.skill_watch.watch_labels import suite_short_name, watch_short_name

    label = suite_short_name(slug=slug) or watch_short_name(slug=slug)
    buy_items = [i for i in items if not is_observe_intent(i)]
    observe_items = [i for i in items if is_observe_intent(i)]
    mode = ""
    if buy_items and str(buy_items[0].get("entry_mode") or "") == "next_open":
        mode = " · ⛳开盘接"
    lines = [
        f"📋【次日情景预案】{label} · {plan_date}{mode}",
        f"🛒可买 {len(buy_items)} · 👀观察 {len(observe_items)} · ⚡竞价纠偏",
    ]

    if buy_items:
        lines.append("🛒【可买】")
        for idx, item in enumerate(buy_items[:8], start=1):
            head = f"{idx}、🎯 {item.get('name') or ''} {item.get('code') or ''}".strip()
            if item.get("ref_close") is not None:
                head += f"，昨收{item['ref_close']}"
            lines.append(head)
            scenarios = item.get("scenarios") or {}
            bits: list[str] = []
            for key, sc_label, emoji in (
                ("gap_up", "高开", "📈"),
                ("flat", "平开", "➡️"),
                ("gap_down", "低开", "📉"),
            ):
                sc = scenarios.get(key) if isinstance(scenarios.get(key), dict) else {}
                if not sc:
                    continue
                try:
                    layers = float(sc.get("layers") or 0)
                except (TypeError, ValueError):
                    layers = 0.0
                if not sc.get("buy") or layers <= 0:
                    # 不接就别再打价格带和「0 层」：那既是噪音，也会被读成「还能接一点」
                    bits.append(f"{emoji}{sc_label}暂缓")
                    continue
                lo, hi = sc.get("entry_pct_min"), sc.get("entry_pct_max")
                band = ""
                if lo is not None and hi is not None:
                    band = f"{lo}%" if lo == hi else f"{lo}%~{hi}%"
                bits.append(
                    f"{emoji}{sc_label}接{band}·{layers:g}层"
                    if band
                    else f"{emoji}{sc_label}接{layers:g}层"
                )
            if bits:
                lines.append("  " + "｜".join(bits))
    if observe_items:
        lines.append("👀【观察】")
        for idx, item in enumerate(observe_items[:8], start=1):
            lines.append(format_observe_line(item, index=idx))
    change_txt = format_observe_change_report(observe_changes)
    if change_txt:
        lines.append(change_txt)
    return "\n".join(lines)


def enrich_plan_items(
    picks: list[dict[str, Any]] | None,
    *,
    flat_band_pct: float = 0.5,
    gap_up_chase: bool = False,
    entry_mode: str = "scenario",
) -> list[dict[str, Any]]:
    items: list[dict[str, Any]] = []
    for pick in picks or []:
        if not isinstance(pick, dict):
            continue
        item = build_plan_item(
            pick,
            flat_band_pct=flat_band_pct,
            gap_up_chase=gap_up_chase,
            entry_mode=entry_mode,
        )
        if item:
            items.append(item)
    return items
