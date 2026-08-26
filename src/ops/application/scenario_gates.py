"""情景划分、竞价 stance 评估与开仓门闩。"""
from __future__ import annotations

from typing import Any, Literal

from src.ops.application.paper_exec import PaperOrder
from src.ops.application.plan_build import _safe_float
from src.ops.application.session_clock import SessionClock
from src.ops.application.paper_policy import (
    DEFAULT_ABANDON_GAP_PCT,
    DEFAULT_DOWNGRADE_GAP_PCT,
    classify_low_open_band,
)
from src.ops.application.paper_policy.eligibility import (
    is_observe_intent,
    scan_auction_block_reason,
)

ScenarioKey = Literal["gap_up", "flat", "gap_down"]
AuctionStance = Literal["follow", "revise", "abandon", "wait"]


def classify_open_scenario(
    *,
    ref_close: float | None,
    live_price: float | None,
    flat_band_pct: float = 0.5,
) -> tuple[ScenarioKey | None, float | None]:
    """相对昨收涨跌幅划分高开/平开/低开。返回 (scenario, gap_pct)。"""
    if ref_close is None or ref_close <= 0 or live_price is None or live_price <= 0:
        return None, None
    gap_pct = (live_price / ref_close - 1.0) * 100.0
    band = abs(float(flat_band_pct))
    if gap_pct >= band:
        return "gap_up", gap_pct
    if gap_pct <= -band:
        return "gap_down", gap_pct
    return "flat", gap_pct


def _scenario_of(item: dict[str, Any], key: ScenarioKey) -> dict[str, Any]:
    raw = (item.get("scenarios") or {}).get(key)
    return raw if isinstance(raw, dict) else {}


def price_in_entry_band(
    *,
    ref_close: float | None,
    live_price: float | None,
    scenario: dict[str, Any],
) -> bool:
    if ref_close is None or ref_close <= 0 or live_price is None:
        return False
    gap_pct = (live_price / ref_close - 1.0) * 100.0
    lo = _safe_float(scenario.get("entry_pct_min"))
    hi = _safe_float(scenario.get("entry_pct_max"))
    if lo is None or hi is None:
        return False
    return min(lo, hi) <= gap_pct <= max(lo, hi)


def evaluate_auction_stance(
    item: dict[str, Any],
    quote: dict[str, Any],
    *,
    flat_band_pct: float = 0.5,
) -> dict[str, Any]:
    """竞价/开盘对照预案：follow / revise / abandon / wait。"""
    ref = _safe_float(item.get("ref_close")) or _safe_float(quote.get("prev_close"))
    current_price = _safe_float(
        quote.get("price") if quote.get("price") is not None else quote.get("close")
    )
    # 09:30 后高开/平开/低开已经成为固定事实，不能随盘中现价每轮漂移。
    # 竞价阶段 open 通常仍为 0，此时才退回当前撮合价。
    open_price = _safe_float(quote.get("open"))
    scenario_price = open_price if open_price is not None and open_price > 0 else current_price
    scenario_key, gap_pct = classify_open_scenario(
        ref_close=ref, live_price=scenario_price, flat_band_pct=flat_band_pct
    )
    if scenario_key is None:
        return {
            "code": item.get("code"),
            "stance": "wait",
            "scenario": None,
            "gap_pct": None,
            "reason": "缺昨收或现价，继续观察",
        }

    scenario = _scenario_of(item, scenario_key)
    auction_cfg = item.get("auction") if isinstance(item.get("auction"), dict) else {}
    # 情景认开盘价；真正下单仍须检查此刻价格是否还在该情景的介入区间。
    entry_price = current_price if current_price is not None else scenario_price
    in_band = price_in_entry_band(ref_close=ref, live_price=entry_price, scenario=scenario)
    buy = bool(scenario.get("buy"))

    # 高开接近涨停：默认放弃
    if (
        scenario_key == "gap_up"
        and auction_cfg.get("abandon_gap_up_limit", True)
        and gap_pct is not None
        and gap_pct >= 9.5
    ):
        return {
            "code": item.get("code"),
            "stance": "abandon",
            "scenario": scenario_key,
            "gap_pct": gap_pct,
            "reason": "高开接近涨停，按否决放弃",
        }

    # 与扫描侧 auction_confirm 对齐：深低开直接放弃 / 降级带半层
    abandon_gap = _safe_float(auction_cfg.get("abandon_gap_pct"))
    if abandon_gap is None:
        abandon_gap = DEFAULT_ABANDON_GAP_PCT
    downgrade_gap = _safe_float(auction_cfg.get("downgrade_gap_pct"))
    if downgrade_gap is None:
        downgrade_gap = DEFAULT_DOWNGRADE_GAP_PCT
    low_open_band = None
    if scenario_key == "gap_down" and gap_pct is not None:
        low_open_band = classify_low_open_band(
            gap_pct,
            abandon_gap_pct=float(abandon_gap),
            downgrade_gap_pct=float(downgrade_gap),
        )
        if low_open_band == "abandon":
            return {
                "code": item.get("code"),
                "stance": "abandon",
                "scenario": scenario_key,
                "gap_pct": gap_pct,
                "reason": (
                    f"低开 {gap_pct:.2f}% ≤ 放弃线 {abandon_gap}%（与扫描竞价确认对齐）"
                ),
            }

    if not buy:
        return {
            "code": item.get("code"),
            "stance": "abandon",
            "scenario": scenario_key,
            "gap_pct": gap_pct,
            "reason": f"{scenario_key} 情景预案不买",
        }

    if auction_cfg.get("follow_requires_band", True) and not in_band:
        if auction_cfg.get("revise_allowed", True):
            return {
                "code": item.get("code"),
                "stance": "revise",
                "scenario": scenario_key,
                "gap_pct": gap_pct,
                "reason": "落在情景外，需改区间或继续等",
            }
        return {
            "code": item.get("code"),
            "stance": "wait",
            "scenario": scenario_key,
            "gap_pct": gap_pct,
            "reason": "未进买点区间，继续观察",
        }

    layers = float(scenario.get("layers") or 0.5)
    reason = f"竞价/开盘符合{scenario_key}买点，可按预案执行"

    if low_open_band == "downgrade":
        layers = min(layers, 0.5)
        reason = (
            f"低开 {gap_pct:.2f}% 落入降级带（≤ {downgrade_gap}%）："
            f"强制半层（与扫描 downgrade 对齐）"
        )

    comfort = _safe_float(scenario.get("comfort_pct_max"))
    stretched = _safe_float(scenario.get("layers_if_stretched"))
    if (
        scenario_key == "gap_up"
        and comfort is not None
        and stretched is not None
        and gap_pct is not None
        and gap_pct > float(comfort)
    ):
        layers = max(0.5, float(stretched))
        reason = (
            f"高开 {gap_pct:.2f}% 超舒适带 {comfort}%："
            f"按预案减至 {layers} 层（layers_if_stretched）"
        )

    return {
        "code": item.get("code"),
        "stance": "follow",
        "scenario": scenario_key,
        "gap_pct": gap_pct,
        "layers": layers,
        "reason": reason,
    }


def scenario_gated_open_orders(
    *,
    plan_items: list[dict[str, Any]],
    positions: list[dict[str, Any]],
    quotes: dict[str, dict[str, Any]],
    clock: SessionClock,
    flat_band_pct: float = 0.5,
    stances: list[dict[str, Any]] | None = None,
) -> tuple[list[PaperOrder], list[dict[str, Any]], str]:
    """按情景门闩生成开仓单；竞价窗默认不下开仓成交。"""
    held = {str(p.get("code")) for p in positions}
    orders: list[PaperOrder] = []
    decisions: list[dict[str, Any]] = []
    stance_by_code = {
        str(s.get("code")): s for s in (stances or []) if isinstance(s, dict) and s.get("code")
    }

    for item in plan_items:
        code = str(item.get("code") or "")
        if not code or code in held:
            continue
        block = scan_auction_block_reason(item)
        if block:
            decisions.append(
                {
                    "code": code,
                    "stance": "abandon",
                    "scenario": None,
                    "gap_pct": None,
                    "reason": block,
                }
            )
            continue
        if is_observe_intent(item):
            decisions.append(
                {
                    "code": code,
                    "stance": "wait",
                    "scenario": None,
                    "gap_pct": None,
                    "reason": "观察票：次日跟踪，不开仓",
                }
            )
            continue
        quote = quotes.get(code) or {}
        decision = stance_by_code.get(code) or evaluate_auction_stance(
            item, quote, flat_band_pct=flat_band_pct
        )
        decisions.append(decision)
        stance = str(decision.get("stance") or "wait")

        if not clock.allow_open_fill:
            continue
        if stance != "follow":
            continue

        layers = float(decision.get("layers") or 0.5)
        if layers < 0.5:
            continue
        orders.append(
            PaperOrder(
                code=code,
                action="open",
                layers=layers,
                reason=str(decision.get("reason") or "按次日情景预案开仓"),
                name=str(item.get("name") or code),
                decided_by="scenario_gate",
            )
        )

    if not clock.allow_open_fill:
        if clock.in_auction or clock.phase in {"pre_auction", "open", "closed"}:
            note = "非连续竞价时段：只纠偏不落开仓，对照预案持续判断 follow/revise/abandon"
        else:
            note = "竞价/开盘前 09:15-09:30：只纠偏不落开仓，对照预案持续判断 follow/revise/abandon"
    elif not orders:
        note = "情景门闩：无符合买点的开仓（高开不追/未进区间/放弃/已有仓）"
    else:
        note = f"情景门闩开仓 {len(orders)} 笔"
    return orders, decisions, note


def merge_ai_orders_with_gates(
    ai_orders: list[PaperOrder],
    *,
    plan_items: list[dict[str, Any]],
    quotes: dict[str, dict[str, Any]],
    clock: SessionClock,
    flat_band_pct: float = 0.5,
) -> tuple[list[PaperOrder], list[dict[str, Any]]]:
    """AI 提议仍须过情景门闩；非 allow_open_fill 时段拦截 open/add/buy_dip。"""
    item_by_code = {str(i.get("code")): i for i in plan_items}
    kept: list[PaperOrder] = []
    rejects: list[dict[str, Any]] = []
    for order in ai_orders:
        action = str(order.action or "").lower()
        if action == "hold":
            continue
        if action in {"open", "add", "buy_dip"}:
            item = item_by_code.get(order.code)
            if item is not None:
                block = scan_auction_block_reason(item)
                if block:
                    rejects.append(
                        {
                            "code": order.code,
                            "action": action,
                            "reason": block,
                        }
                    )
                    continue
                if is_observe_intent(item):
                    rejects.append(
                        {
                            "code": order.code,
                            "action": action,
                            "reason": "观察票：次日跟踪，不开仓",
                        }
                    )
                    continue
            if not clock.allow_open_fill:
                reason = (
                    "竞价窗仅纠偏，暂不落买入成交"
                    if clock.in_auction
                    else "非连续竞价时段，暂不落买入成交"
                )
                rejects.append(
                    {
                        "code": order.code,
                        "action": action,
                        "reason": reason,
                    }
                )
                continue
            item = item_by_code.get(order.code)
            if item is None:
                # 无预案的加仓类动作拒绝，防止随便买
                rejects.append(
                    {
                        "code": order.code,
                        "action": action,
                        "reason": "不在次日预案关注池，拒绝开/加仓",
                    }
                )
                continue
            quote = quotes.get(order.code) or {}
            decision = evaluate_auction_stance(item, quote, flat_band_pct=flat_band_pct)
            if decision.get("stance") != "follow":
                rejects.append(
                    {
                        "code": order.code,
                        "action": action,
                        "reason": f"情景门闩拦截：{decision.get('reason')}",
                        "decision": decision,
                    }
                )
                continue
            # 情景层数上限：AI 不得突破预案 decision.layers
            max_layers = float(decision.get("layers") or 0.5)
            ai_layers = float(order.layers or 0)
            if ai_layers > max_layers + 1e-9:
                order = PaperOrder(
                    code=order.code,
                    action=order.action,
                    layers=max_layers,
                    reason=(
                        f"{order.reason or 'AI'}；层数钳制 "
                        f"{ai_layers:g}→{max_layers:g}"
                    ),
                    mark_price=order.mark_price,
                    name=order.name,
                    decided_by=order.decided_by or "ai",
                )
        kept.append(order)
    return kept, rejects
