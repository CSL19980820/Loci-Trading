"""纸面资金视图：把「层」翻译成 AI 看得懂的金额与可用额度。

**纯推导，零建表**。仓位本来就以「层」为权威计量（10 层 = 100%），金额完全可由
`初始资金 × 层数 / 总层数` 算出——按 `src/AGENTS.md` §5.1「能从已有事实推导的
指标不入库」，落成第二套权威表只会制造双真相。

口径是**名义值**，不是真实净值：系统不记已实现盈亏、不计佣金滑点（见 ADR-008）。
所以 `available_cash` 回答的是「还能开几层、约合多少钱」，不是「账户里还剩多少钱」。
命名上一律带 nominal 语义，别让模型误以为这是可提现余额。

与预警的关系：**仓位满只约束下单，不影响任何扫描或推送**。扫描器根本不读持仓，
买点该报还是报——不然「满仓时看不见机会」会让人错过换仓时机。
"""
from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import asdict, dataclass, field
from typing import Any


def _num(value: Any) -> float:
    try:
        out = float(value)
    except (TypeError, ValueError):
        return 0.0
    return out if out == out else 0.0  # NaN → 0


def _price_of(quote: Mapping[str, Any]) -> float:
    for key in ("price", "current_price", "close", "last"):
        value = _num(quote.get(key))
        if value > 0:
            return value
    return 0.0


@dataclass(frozen=True)
class PositionView:
    code: str
    name: str
    layers: float
    mark_cost: float
    price: float
    cost_nominal: float
    market_nominal: float
    pnl_pct: float


@dataclass(frozen=True)
class CapitalView:
    """给 AI 的仓位与额度快照。字段名带 nominal 的都是名义口径。"""

    initial_capital: float
    max_layers: float
    used_layers: float
    free_layers: float
    layer_nominal: float
    deployed_nominal: float
    market_nominal: float
    available_cash_nominal: float
    unrealized_pnl_pct: float
    position_count: int
    max_positions: int
    free_slots: int
    #: 层数或只数任一打满即为满仓；满仓只挡开新仓，不挡减仓/换仓，更不挡预警。
    layers_full: bool
    slots_full: bool
    positions: list[dict[str, Any]] = field(default_factory=list)

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


def derive_capital_view(
    cabin: Mapping[str, Any] | None,
    positions: Sequence[Mapping[str, Any]] | None,
    quotes: Mapping[str, Mapping[str, Any]] | None = None,
    *,
    initial_capital: float = 200_000.0,
) -> CapitalView:
    """由舱配置 + 持仓 + 实时报价推出资金视图。不写库、不缓存。"""
    cabin_map = dict(cabin or {})
    raw_config = cabin_map.get("config") if isinstance(cabin_map.get("config"), dict) else {}
    # 舱配置有「嵌套在 paper_quant 下」与历史遗留的「扁平」两种形态，
    # 解法与 unified_monitor_pool._limits 保持一致，否则读不到任何用户设置。
    config = (
        raw_config.get("paper_quant")
        if isinstance(raw_config.get("paper_quant"), dict)
        else raw_config
    )
    capital = _num(config.get("initial_capital")) or _num(
        cabin_map.get("initial_capital")
    ) or float(initial_capital)
    max_layers = _num(cabin_map.get("max_layers")) or 10.0
    # max_positions 只存在于舱配置里，paper_cabins 表没有这一列。
    max_positions = int(_num(config.get("max_positions")) or 3)
    layer_nominal = capital / max_layers if max_layers > 0 else 0.0

    quote_map = dict(quotes or {})
    rows: list[PositionView] = []
    used_layers = 0.0
    deployed = 0.0
    market = 0.0
    for item in positions or []:
        code = str(item.get("code") or "").strip()
        layers = _num(item.get("layers"))
        if not code or layers <= 0:
            continue
        mark_cost = _num(item.get("mark_cost"))
        price = _price_of(dict(quote_map.get(code) or {})) or mark_cost
        cost_nominal = layers * layer_nominal
        pnl_pct = ((price - mark_cost) / mark_cost * 100.0) if mark_cost > 0 else 0.0
        market_nominal = cost_nominal * (1.0 + pnl_pct / 100.0)
        used_layers += layers
        deployed += cost_nominal
        market += market_nominal
        rows.append(
            PositionView(
                code=code,
                name=str(item.get("name") or code),
                layers=round(layers, 2),
                mark_cost=round(mark_cost, 3),
                price=round(price, 3),
                cost_nominal=round(cost_nominal, 2),
                market_nominal=round(market_nominal, 2),
                pnl_pct=round(pnl_pct, 2),
            )
        )

    free_layers = max(0.0, max_layers - used_layers)
    unrealized = ((market - deployed) / deployed * 100.0) if deployed > 0 else 0.0
    return CapitalView(
        initial_capital=round(capital, 2),
        max_layers=round(max_layers, 2),
        used_layers=round(used_layers, 2),
        free_layers=round(free_layers, 2),
        layer_nominal=round(layer_nominal, 2),
        deployed_nominal=round(deployed, 2),
        market_nominal=round(market, 2),
        available_cash_nominal=round(free_layers * layer_nominal, 2),
        unrealized_pnl_pct=round(unrealized, 2),
        position_count=len(rows),
        max_positions=max_positions,
        free_slots=max(0, max_positions - len(rows)),
        layers_full=free_layers <= 1e-9,
        slots_full=len(rows) >= max_positions,
        positions=[asdict(row) for row in rows],
    )


def capital_prompt_note(view: CapitalView) -> str:
    """喂给模型的一句话约束。说清满仓意味着什么，避免它「因为满仓所以什么都不做」。"""
    parts = [
        f"名义本金 {view.initial_capital:.0f} 元，每层约 {view.layer_nominal:.0f} 元",
        f"已用 {view.used_layers:g}/{view.max_layers:g} 层"
        f"（持股 {view.position_count}/{view.max_positions} 只）",
        f"可用约 {view.available_cash_nominal:.0f} 元",
    ]
    if view.layers_full or view.slots_full:
        parts.append(
            "当前已满仓：不能开新仓，但**仍应评估减仓/换仓/止盈止损**；"
            "若候选明显强于现有持仓，可先减弱票再开"
        )
    return "；".join(parts) + "。"


__all__ = [
    "CapitalView",
    "PositionView",
    "capital_prompt_note",
    "derive_capital_view",
]
