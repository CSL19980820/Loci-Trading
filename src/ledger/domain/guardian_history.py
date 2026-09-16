"""按已记账成交重建指定日期账户，不使用后来的持仓或重新计算历史费用。"""
from typing import Any

from src.ledger.domain.guardian_account import new_guardian_account, check_guardian_account


def guardian_account_at(trades: list[dict[str, Any]], day: str, *, initial_cents: int) -> dict[str, Any]:
    state = new_guardian_account()
    state.update(initial_capital_cents=initial_cents, cash_cents=initial_cents)
    positions: dict[str, dict[str, Any]] = {}
    for fill in sorted(trades, key=lambda f: (f["occurred_at"], f.get("id", ""))):
        bought_on = fill["occurred_at"][:10]
        if bought_on > day:
            continue
        code = fill["code"]
        p = positions.setdefault(code, {"code": code, "name": fill["name"], "quantity": 0,
                                        "cost_cents": 0, "today_bought": 0, "bought_on": ""})
        if fill["side"] == "buy":
            if p["bought_on"] != bought_on:
                p["today_bought"] = 0
            p["bought_on"] = bought_on
            p["today_bought"] += fill["quantity"]
            p["quantity"] += fill["quantity"]
            p["cost_cents"] += fill["gross_cents"] + fill["fees_cents"]
            state["cash_cents"] -= fill["gross_cents"] + fill["fees_cents"]
        else:
            if p["bought_on"] != bought_on:
                p["today_bought"] = 0
            p["quantity"] -= fill["quantity"]
            p["cost_cents"] -= fill["allocated_cost_cents"]
            state["cash_cents"] += fill["gross_cents"] - fill["fees_cents"]
            state["realized_pnl_cents"] += fill["realized_pnl_cents"]
        state["fees_cents"] += fill["fees_cents"]
        if p["quantity"] != fill["after_quantity"] or state["cash_cents"] != fill["cash_after_cents"]:
            raise ValueError("历史成交流水未能对齐股数或现金，不能生成复盘收益")
        if p["quantity"] == 0:
            del positions[code]
    state["positions"] = list(positions.values())
    check_guardian_account(state)
    return state
