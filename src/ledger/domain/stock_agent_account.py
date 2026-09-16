"""独立智能体的财务提交不变量；金额全部为整数分。"""
from __future__ import annotations


def validate_stock_agent_transition(previous: dict, state: dict, fills: list[dict]) -> None:
    """拒绝有账无单、有单无账、凭空加钱和持仓数量错配。"""
    cash_delta = realized_delta = fees_delta = 0
    quantities = {p["code"]: p["quantity"] for p in previous["positions"]}
    for fill in fills:
        if fill.get("side") not in {"buy", "sell"}:
            raise ValueError("模拟成交方向无效")
        for key in ("quantity", "price_cents", "gross_cents", "fees_cents", "realized_pnl_cents"):
            if type(fill.get(key)) is not int:
                raise ValueError("模拟成交金额和股数必须为整数")
        if fill["quantity"] <= 0 or fill["price_cents"] <= 0 or fill["fees_cents"] < 0:
            raise ValueError("模拟成交股数、价格或费用无效")
        if fill["gross_cents"] != fill["quantity"] * fill["price_cents"]:
            raise ValueError("成交金额与成交价格、数量不一致")
        direction = 1 if fill["side"] == "buy" else -1
        cash_delta += -direction * fill["gross_cents"] - fill["fees_cents"]
        realized_delta += fill["realized_pnl_cents"]
        fees_delta += fill["fees_cents"]
        quantities[fill["code"]] = quantities.get(fill["code"], 0) + direction * fill["quantity"]
    if (state["cash_cents"] != previous["cash_cents"] + cash_delta
            or state["realized_pnl_cents"] != previous["realized_pnl_cents"] + realized_delta
            or state["fees_cents"] != previous["fees_cents"] + fees_delta):
        raise ValueError("模拟成交流水与账户资金变化不一致")
    if {code: quantity for code, quantity in quantities.items() if quantity} != {p["code"]: p["quantity"] for p in state["positions"]}:
        raise ValueError("模拟成交流水与持仓股数变化不一致")
