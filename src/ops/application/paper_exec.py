"""纸面按层执行引擎：建/加/减/平/止盈/止损/高抛/低吸。

不计佣金；标记价由调用方传入（通常来自 Live TTL）。永不写 palace.db。
"""
from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import datetime
from typing import Any, Literal

PaperAction = Literal[
    "open",
    "add",
    "reduce",
    "close",
    "take_profit",
    "stop_cut",
    "trim_high",
    "buy_dip",
    "hold",
]

BUY_ACTIONS = frozenset({"open", "add", "buy_dip"})
SELL_ACTIONS = frozenset({"reduce", "close", "take_profit", "stop_cut", "trim_high"})
ALL_ACTIONS = BUY_ACTIONS | SELL_ACTIONS | frozenset({"hold"})


@dataclass
class PaperOrder:
    code: str
    action: str
    layers: float = 0.0
    reason: str = ""
    mark_price: float | None = None
    name: str = ""
    #: 决策归因：ai / rules / scenario_gate（观测用，不改变执行语义）
    decided_by: str = ""

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class PaperExecResult:
    fills: list[dict[str, Any]] = field(default_factory=list)
    rejects: list[dict[str, Any]] = field(default_factory=list)
    positions: list[dict[str, Any]] = field(default_factory=list)


def _is_half_step(value: float, step: float = 0.5) -> bool:
    if step <= 0:
        return False
    scaled = round(value / step)
    return abs(value - scaled * step) < 1e-9


def _position_map(positions: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    return {str(p.get("code")): dict(p) for p in positions}


def _used_layers(positions: list[dict[str, Any]]) -> float:
    return sum(float(p.get("layers") or 0) for p in positions)


def validate_and_normalize_order(
    order: PaperOrder,
    *,
    positions: list[dict[str, Any]],
    max_layers: float,
    max_layers_per_name: float = 0.0,
    max_positions: int = 0,
    min_step: float = 0.5,
    allow_actions: set[str] | None = None,
    trim_high_min_pnl_pct: float | None = None,
    buy_dip_drawdown_pct: float | None = None,
    day_high: float | None = None,
) -> tuple[PaperOrder | None, str | None]:
    """返回 (规范化订单, 拒单原因)。hold 返回 (None, None)。"""
    action = str(order.action or "").strip().lower()
    code = str(order.code or "").strip()
    if not code:
        return None, "缺少 code"
    if action not in ALL_ACTIONS:
        return None, f"未知动作: {action}"
    if allow_actions is not None and action not in allow_actions:
        return None, f"动作未授权: {action}"
    if action == "hold":
        return None, None

    layers = float(order.layers or 0)
    pos = _position_map(positions).get(code)
    current = float(pos.get("layers") or 0) if pos else 0.0
    mark_cost = float(pos.get("mark_cost") or 0) if pos else 0.0
    price = order.mark_price

    if action == "close":
        if current <= 0:
            return None, "无持仓可清仓"
        layers = current
    elif action in SELL_ACTIONS:
        if current <= 0:
            return None, "无持仓不可卖出类动作"
        if layers <= 0:
            layers = min(min_step, current)
        if layers > current + 1e-9:
            return None, "减仓层数超过持仓"
        if not _is_half_step(layers, min_step):
            return None, f"层数须为 {min_step} 的倍数"
    else:  # buy family
        if action == "add" and current <= 0:
            action = "open"
        if action == "open" and current > 0:
            action = "add"
        if layers < min_step - 1e-9:
            return None, f"买入至少 {min_step} 层"
        if current <= 0 and max_positions > 0 and len(_position_map(positions)) >= max_positions:
            return None, f"持股已达 {max_positions} 只上限"
        if not _is_half_step(layers, min_step):
            return None, f"层数须为 {min_step} 的倍数"
        remaining = max_layers - _used_layers(positions)
        if remaining < min_step - 1e-9:
            return None, "舱内剩余层不足"
        if layers > remaining + 1e-9:
            layers = remaining  # 梭哈剩余
            if not _is_half_step(layers, min_step):
                layers = (layers // min_step) * min_step
            if layers < min_step - 1e-9:
                return None, "舱内剩余层不足"
        if max_layers_per_name > 0 and current + layers > max_layers_per_name + 1e-9:
            return None, "超过单票层数上限"

    # 高抛 / 低吸门闩（有参数才检查）
    if action == "trim_high" and trim_high_min_pnl_pct is not None and price and mark_cost > 0:
        pnl_pct = (float(price) - mark_cost) / mark_cost * 100
        if pnl_pct < float(trim_high_min_pnl_pct):
            return None, f"浮盈未达高抛门槛 {trim_high_min_pnl_pct}%"
    if action == "buy_dip" and buy_dip_drawdown_pct is not None and price:
        ref = day_high if day_high and day_high > 0 else mark_cost
        if ref and ref > 0:
            dd = (ref - float(price)) / ref * 100
            if dd < float(buy_dip_drawdown_pct):
                return None, f"回撤未达低吸门槛 {buy_dip_drawdown_pct}%"

    if price is None or float(price) <= 0:
        return None, "缺少有效标记价"

    return (
        PaperOrder(
            code=code,
            action=action,
            layers=round(layers, 4),
            reason=order.reason,
            mark_price=float(price),
            name=order.name or (str(pos.get("name") or "") if pos else ""),
            decided_by=str(order.decided_by or ""),
        ),
        None,
    )


def apply_order_to_positions(
    positions: list[dict[str, Any]],
    order: PaperOrder,
) -> list[dict[str, Any]]:
    """纯函数：返回新持仓列表。"""
    by_code = _position_map(positions)
    pos = by_code.get(order.code)
    current = float(pos.get("layers") or 0) if pos else 0.0
    mark_cost = float(pos.get("mark_cost") or 0) if pos else 0.0
    price = float(order.mark_price or 0)
    name = order.name or (str(pos.get("name") or order.code) if pos else order.code)

    if order.action in BUY_ACTIONS:
        new_layers = current + float(order.layers)
        if current <= 0:
            new_cost = price
        else:
            new_cost = (mark_cost * current + price * float(order.layers)) / new_layers
        by_code[order.code] = {
            "code": order.code,
            "name": name,
            "layers": round(new_layers, 4),
            "mark_cost": round(new_cost, 6),
        }
    else:
        new_layers = max(0.0, current - float(order.layers))
        if new_layers <= 1e-9:
            by_code.pop(order.code, None)
        else:
            by_code[order.code] = {
                "code": order.code,
                "name": name,
                "layers": round(new_layers, 4),
                "mark_cost": mark_cost,
            }
    return list(by_code.values())


def execute_orders(
    store: Any,
    *,
    slug: str,
    orders: list[PaperOrder],
    quotes: dict[str, dict[str, Any]],
    source: str = "ai_monitor",
    allow_actions: set[str] | None = None,
    trim_high_min_pnl_pct: float | None = None,
    buy_dip_drawdown_pct: float | None = None,
) -> PaperExecResult:
    """校验并落库执行。"""
    from src.ops.application.unified_monitor_pool import (
        ensure_dragon_cabin_policy,
        reconcile_unified_monitor_pool,
    )

    cabin = ensure_dragon_cabin_policy(store, slug)
    if not cabin:
        from src.ops.infrastructure.store import OpsError

        raise OpsError("纸面舱不存在或已退役")
    cabin_id = cabin["id"]
    max_layers = float(cabin.get("max_layers") or 4)
    max_per = float(cabin.get("max_layers_per_name") or 0)
    raw_cfg = cabin.get("config") if isinstance(cabin.get("config"), dict) else {}
    cfg = (
        raw_cfg.get("paper_quant")
        if isinstance(raw_cfg.get("paper_quant"), dict)
        else raw_cfg
    )
    if not isinstance(cfg, dict):
        cfg = {}
    min_step = float(cfg.get("min_layer_step") or 0.5)
    max_positions = int(cfg.get("max_positions") or 0)
    if allow_actions is None and cfg.get("allow_actions"):
        allow_actions = {str(x) for x in cfg["allow_actions"]}
    if trim_high_min_pnl_pct is None and cfg.get("trim_high_min_pnl_pct") is not None:
        trim_high_min_pnl_pct = float(cfg["trim_high_min_pnl_pct"])
    if buy_dip_drawdown_pct is None and cfg.get("buy_dip_drawdown_pct") is not None:
        buy_dip_drawdown_pct = float(cfg["buy_dip_drawdown_pct"])

    positions = store.list_paper_positions(cabin_id)
    result = PaperExecResult()

    for raw in orders:
        order = raw
        if order.mark_price is None:
            quote = quotes.get(order.code) or {}
            price = quote.get("price")
            if price is None:
                price = quote.get("current_price")
            try:
                order.mark_price = float(price) if price is not None else None
            except (TypeError, ValueError):
                order.mark_price = None
        if not order.name:
            quote = quotes.get(order.code) or {}
            order.name = str(quote.get("name") or order.code)

        day_high = None
        quote = quotes.get(order.code) or {}
        if quote.get("high") is not None:
            try:
                day_high = float(quote["high"])
            except (TypeError, ValueError):
                day_high = None

        normalized, reject_reason = validate_and_normalize_order(
            order,
            positions=positions,
            max_layers=max_layers,
            max_layers_per_name=max_per,
            max_positions=max_positions,
            min_step=min_step,
            allow_actions=allow_actions,
            trim_high_min_pnl_pct=trim_high_min_pnl_pct,
            buy_dip_drawdown_pct=buy_dip_drawdown_pct,
            day_high=day_high,
        )
        if reject_reason:
            reject = {
                "cabin_id": cabin_id,
                "code": order.code,
                "action": order.action,
                "layers": order.layers,
                "reason": reject_reason,
            }
            store.insert_paper_reject(reject)
            result.rejects.append(reject)
            continue
        if normalized is None:
            continue

        positions = apply_order_to_positions(positions, normalized)
        fill = {
            "cabin_id": cabin_id,
            "code": normalized.code,
            "action": normalized.action,
            "layers": normalized.layers,
            "mark_price": normalized.mark_price,
            "source": source,
            "reason": normalized.reason,
            "decided_by": str(getattr(normalized, "decided_by", "") or ""),
        }
        # 成交与该票最新仓位同事务落库，避免留下「有成交、仓位没动」的半条记录
        pos = _position_map(positions).get(normalized.code)
        fill_id = store.apply_paper_fill(
            fill,
            code=normalized.code,
            name=normalized.name or normalized.code,
            layers=float(pos["layers"]) if pos else 0.0,
            mark_cost=float(pos["mark_cost"]) if pos else 0.0,
        )
        fill["id"] = fill_id
        result.fills.append(fill)

    result.positions = store.list_paper_positions(cabin_id)
    reconcile_unified_monitor_pool(
        store,
        slug=slug,
        trade_date=datetime.now().astimezone().date().isoformat(),
        actions=[*result.fills, *result.rejects],
        source=source,
    )
    return result
