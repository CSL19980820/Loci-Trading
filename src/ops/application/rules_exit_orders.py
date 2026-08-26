"""持仓退出：相对 mark_cost / 预案阈值 / 竞价 revise 减仓。

两种档位由 ``position_exit_orders`` 分派：
- rules 路径：全套退出（止损 / 止盈 / 高抛 / revise 减仓）
- AI 全权路径：只补硬止损兜底。止盈与高抛属战法判断，留给模型；但模型失语、
  异常或漏看持仓时，亏损仓不能没人管。
"""
from __future__ import annotations

from typing import Any

from src.ops.application.paper_exec import PaperOrder
from src.ops.application.plan_build import _safe_float
from src.ops.application.scenario_gates import evaluate_auction_stance

#: AI 已自行处理该票时不再叠加兜底单，避免同一票两笔卖出。
SELL_LIKE_ACTIONS = frozenset(
    {"reduce", "close", "take_profit", "stop_cut", "trim_high"}
)


def _quote_price(quote: dict[str, Any]) -> float | None:
    for key in ("price", "current_price", "close"):
        val = _safe_float(quote.get(key))
        if val is not None and val > 0:
            return val
    return None


def _pnl_pct(mark_cost: float, price: float) -> float:
    return (price - mark_cost) / mark_cost * 100.0


def _resolve_stop_loss_pct(
    cfg: dict[str, Any],
    item: dict[str, Any] | None,
    *,
    slug: str = "",
) -> float:
    for src in (item or {}, cfg):
        val = _safe_float(src.get("stop_loss_pct"))
        if val is not None:
            return float(val)
    if slug:
        try:
            from src.strategy import get as get_strategy

            engine = get_strategy(slug)
            val = getattr(engine, "screen_stop_loss_pct", None)
            if val is not None:
                return float(val)
        except Exception:  # noqa: BLE001
            pass
    return -6.0


def _resolve_take_profit_pct(cfg: dict[str, Any], item: dict[str, Any] | None) -> float | None:
    for src in (item or {}, cfg):
        val = _safe_float(src.get("take_profit_pct"))
        if val is not None:
            return float(val)
    return None


def rules_position_exit_orders(
    *,
    positions: list[dict[str, Any]],
    plan_items: list[dict[str, Any]],
    quotes: dict[str, dict[str, Any]],
    cfg: dict[str, Any],
    slug: str = "",
    stances: list[dict[str, Any]] | None = None,
    flat_band_pct: float = 0.5,
) -> tuple[list[PaperOrder], str]:
    """为 rules 监测生成卖出类订单（每票至多一笔，优先级：止损 > 止盈 > 高抛 > revise 减仓）。"""
    if not cfg.get("rules_exit_enabled", True):
        return [], ""
    if not positions:
        return [], ""

    min_step = float(cfg.get("min_layer_step") or 0.5)
    trim_min = (
        float(cfg["trim_high_min_pnl_pct"])
        if cfg.get("trim_high_min_pnl_pct") is not None
        else 3.0
    )
    on_revise = bool(cfg.get("rules_exit_on_revise", True))
    item_by_code = {str(i.get("code")): i for i in plan_items if i.get("code")}
    stance_by_code = {
        str(s.get("code")): s for s in (stances or []) if isinstance(s, dict) and s.get("code")
    }

    orders: list[PaperOrder] = []
    notes: list[str] = []

    for pos in positions:
        code = str(pos.get("code") or "")
        if not code:
            continue
        layers = float(pos.get("layers") or 0)
        mark_cost = float(pos.get("mark_cost") or 0)
        if layers <= 0 or mark_cost <= 0:
            continue

        quote = quotes.get(code) or {}
        price = _quote_price(quote)
        if price is None:
            continue

        item = item_by_code.get(code)
        stop_pct = _resolve_stop_loss_pct(cfg, item, slug=slug)
        take_pct = _resolve_take_profit_pct(cfg, item)
        pnl = _pnl_pct(mark_cost, price)
        name = str(pos.get("name") or quote.get("name") or code)

        if pnl <= stop_pct + 1e-9:
            orders.append(
                PaperOrder(
                    code=code,
                    action="stop_cut",
                    layers=layers,
                    reason=f"rules 止损：浮盈 {pnl:.2f}% ≤ {stop_pct:g}%",
                    name=name,
                    decided_by="rules",
                )
            )
            notes.append(f"{code} 止损")
            continue

        if take_pct is not None and pnl >= take_pct - 1e-9:
            orders.append(
                PaperOrder(
                    code=code,
                    action="take_profit",
                    layers=layers,
                    reason=f"rules 止盈：浮盈 {pnl:.2f}% ≥ {take_pct:g}%",
                    name=name,
                    decided_by="rules",
                )
            )
            notes.append(f"{code} 止盈")
            continue

        if pnl >= trim_min - 1e-9 and layers >= min_step - 1e-9:
            sell_layers = min_step if layers >= min_step else layers
            orders.append(
                PaperOrder(
                    code=code,
                    action="trim_high",
                    layers=sell_layers,
                    reason=f"rules 高抛：浮盈 {pnl:.2f}% ≥ {trim_min:g}%",
                    name=name,
                    decided_by="rules",
                )
            )
            notes.append(f"{code} 高抛")
            continue

        if not on_revise:
            continue

        stance_row = stance_by_code.get(code)
        if stance_row is None and item is not None:
            stance_row = evaluate_auction_stance(item, quote, flat_band_pct=flat_band_pct)
        if not isinstance(stance_row, dict):
            continue
        if str(stance_row.get("stance") or "") != "revise":
            continue
        if str(stance_row.get("scenario") or "") != "gap_up":
            continue
        if layers < min_step - 1e-9:
            continue

        orders.append(
            PaperOrder(
                code=code,
                action="reduce",
                layers=min_step,
                reason=str(
                    stance_row.get("reason")
                    or "高开 revise：价位偏离预案，规则减仓"
                ),
                name=name,
                decided_by="rules",
            )
        )
        notes.append(f"{code} revise 减仓")

    if not orders:
        return [], ""
    note = f"rules 退出 {len(orders)} 笔（{'、'.join(notes[:6])}）"
    return orders, note


def stop_loss_safety_net(
    *,
    existing: list[PaperOrder],
    positions: list[dict[str, Any]],
    plan_items: list[dict[str, Any]],
    quotes: dict[str, dict[str, Any]],
    cfg: dict[str, Any],
    slug: str = "",
) -> tuple[list[PaperOrder], str]:
    """AI 全权路径的硬止损兜底。

    只补止损：止盈/高抛/减仓是战法判断，交给模型。但模型失语时本轮 orders 会被
    清空，异常回退路径也只产开仓单——没有这一层，亏损仓会一直挂着无人处理。
    """
    if not positions:
        return [], ""
    handled = {
        str(order.code)
        for order in existing
        if str(order.action or "").lower() in SELL_LIKE_ACTIONS
    }
    item_by_code = {str(i.get("code")): i for i in plan_items if i.get("code")}

    orders: list[PaperOrder] = []
    hit: list[str] = []
    for pos in positions:
        code = str(pos.get("code") or "")
        if not code or code in handled:
            continue
        layers = float(pos.get("layers") or 0)
        mark_cost = float(pos.get("mark_cost") or 0)
        if layers <= 0 or mark_cost <= 0:
            continue
        quote = quotes.get(code) or {}
        price = _quote_price(quote)
        if price is None:
            continue
        stop_pct = _resolve_stop_loss_pct(cfg, item_by_code.get(code), slug=slug)
        pnl = _pnl_pct(mark_cost, price)
        if pnl > stop_pct + 1e-9:
            continue
        orders.append(
            PaperOrder(
                code=code,
                action="stop_cut",
                layers=layers,
                reason=f"兜底止损：浮盈 {pnl:.2f}% ≤ {stop_pct:g}%，AI 未处理",
                name=str(pos.get("name") or quote.get("name") or code),
                decided_by="rules",
            )
        )
        hit.append(code)

    if not orders:
        return [], ""
    return orders, f"兜底止损 {len(orders)} 笔（{'、'.join(hit[:6])}）"


def position_exit_orders(
    *,
    existing: list[PaperOrder],
    positions: list[dict[str, Any]],
    plan_items: list[dict[str, Any]],
    quotes: dict[str, dict[str, Any]],
    cfg: dict[str, Any],
    slug: str = "",
    stances: list[dict[str, Any]] | None = None,
    flat_band_pct: float = 0.5,
    ai_driven: bool = False,
) -> tuple[list[PaperOrder], str]:
    """按路径分派退出档位；两条路径都不会让亏损仓裸奔。"""
    if not cfg.get("rules_exit_enabled", True):
        return [], ""
    if ai_driven:
        return stop_loss_safety_net(
            existing=existing,
            positions=positions,
            plan_items=plan_items,
            quotes=quotes,
            cfg=cfg,
            slug=slug,
        )
    return rules_position_exit_orders(
        positions=positions,
        plan_items=plan_items,
        quotes=quotes,
        cfg=cfg,
        slug=slug,
        stances=stances,
        flat_band_pct=flat_band_pct,
    )
