"""独立智能体的财务提交不变量；金额全部为整数分。"""
from __future__ import annotations

from datetime import datetime


def pending_watchlist(state: dict) -> list[dict]:
    """观察池只保留尚未持仓的对象；持仓按真实正股数判断。"""
    held = {p["code"] for p in state.get("positions", []) if p.get("quantity", 0) > 0}
    return [w for w in state.get("watchlist", []) if w["code"] not in held]


def validate_falcon_candidate_transition(previous: dict, state: dict, fills: list[dict],
                                          scope: dict | None, now: datetime) -> None:
    """最后提交防线只信独立候选快照，不信模型写在账户中的候选名单。"""
    prior_watch = {row["code"] for row in previous.get("watchlist", [])}
    new_watch = {row["code"] for row in state.get("watchlist", [])} - prior_watch
    buying = {row["code"] for row in fills if row.get("side") == "buy"}
    old_quantities = {row["code"]: row["quantity"] for row in previous.get("positions", [])}
    buying |= {row["code"] for row in state.get("positions", [])
               if row["quantity"] > old_quantities.get(row["code"], 0)}
    if not (new_watch | buying):
        return  # 来源不可用或已移出池，不阻断已有持仓的减仓/退出及撤观察。
    if not isinstance(scope, dict) or not scope.get("complete"):
        raise ValueError("猎隼新增观察/买入缺少完整的系统候选快照")
    try:
        stamp = datetime.fromisoformat(str(scope.get("as_of") or ""))
    except ValueError as exc:
        raise ValueError("猎隼候选快照时点无效") from exc
    if stamp.tzinfo is None or stamp > now:
        raise ValueError("猎隼候选快照必须有已核实且不晚于提交的时点")
    declared = scope.get("candidate_codes")
    if not isinstance(declared, list) or any(not isinstance(code, str) for code in declared):
        raise ValueError("猎隼系统候选资格名单无效")
    evidenced = {row["code"] for row in scope.get("candidates", [])
                 if isinstance(row, dict) and row.get("entry_eligible") is True and row.get("evidence_id") and row.get("code")}
    if not (new_watch | buying) <= set(declared) & evidenced:
        raise ValueError("猎隼只能新增系统已输出且具有入选/观察证据的个股；持仓不能自行授权加仓")


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
