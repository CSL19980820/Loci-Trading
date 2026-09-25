"""守护输出契约和模拟撮合；模型不能指定成交价格。"""
from __future__ import annotations

import copy
import re
from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from src.ledger import settle_guardian_order, mark_guardian_account

from src.ops.application.guardian_contract import ExecutionTerms, execution_error, execution_cage, rejection_code
from src.ops.application.guardian_quotes import executable_quote, quote_error, validated_quotes
from src.ops.application.guardian_risk import RiskPlan, install_risk_plans
from src.ops.application.guardian_output import load_json_response

TRADE_ACTIONS = frozenset({"buy", "add", "reduce", "sell", "take_profit", "stop_loss"})
_EXCHANGE_CODE = re.compile(r"^(?:(SH|SZ|BJ)\.?(\d{6})|(\d{6})\.(SH|SS|SZ|BJ|XSHG|XSHE))$", re.IGNORECASE)
_EXCHANGE_ALIASES = {"SS": "SH", "XSHG": "SH", "XSHE": "SZ"}
_EXCHANGE_PREFIXES = {"SH": ("5", "6", "900"), "SZ": ("0", "1", "2", "3"), "BJ": ("4", "8", "92")}


def normalize_stock_code(value: Any) -> Any:
    """模型常写 ``SH600519`` / ``600519.SH`` / ``000001.XSHE``；去掉交易所标记只留6位代码。

    仅当交易所与代码段一致时才去掉（如 ``000001.SH`` 是上证指数而非平安银行，原样保留、
    由契约校验拒绝），不会把一只股票悄悄换成另一只。
    """
    if not isinstance(value, str):
        return value
    text = value.strip()
    match = _EXCHANGE_CODE.match(text)
    if not match:
        return text
    exchange = (match[1] or match[4]).upper()
    code = match[2] or match[3]
    exchange = _EXCHANGE_ALIASES.get(exchange, exchange)
    return code if code.startswith(_EXCHANGE_PREFIXES[exchange]) else value
ACTION_LABELS = {"buy": "买入", "add": "加仓", "reduce": "减仓", "sell": "卖出",
                 "take_profit": "止盈", "stop_loss": "止损", "hold": "持股", "watch": "观察", "unwatch": "撤出观察"}


class GuardianOrder(BaseModel):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)
    code: str = Field(pattern=r"^\d{6}$")
    action: Literal["buy", "add", "reduce", "sell", "take_profit", "stop_loss", "hold", "watch", "unwatch"]
    name: str = Field(default="", max_length=64, description="股票名称，尤其用于自主观察股票")
    quantity: int = Field(default=0, ge=0, strict=True, description="本次买入或卖出的整数股数；hold 为 0，卖出必须明确股数")
    reason: str = Field(min_length=1)
    opening_plan_id: str | None = Field(default=None, description="承接竞价计划时填写该计划id；其余订单留空")
    execution: ExecutionTerms | None = Field(default=None, description="买卖意图的价格授权及有效期；历史记录可缺省")
    risk_plans: list[RiskPlan] | None = Field(default=None,
        description="操作后持仓的结构化止损/止盈合同；含触发价、股数、成交价限和有效期。null保留，[]撤回；watch/unwatch不可使用")
    holding_plan: str = Field(default="", description="自主决定的持有周期或持有/退出条件，不要求固定天数")
    take_profit_plan: str = Field(default="", description="持仓止盈条件与理由，每轮由模型复核，不是券商挂单")
    stop_loss_plan: str = Field(default="", description="持仓止损条件与理由，仍遵守T+1")
    entry_condition: str = Field(default="", description="观察标的等待什么条件才考虑买入")
    exit_condition: str = Field(default="", description="什么条件下撤出自主观察")
    exit_today_plan: str = Field(default="", description="已有可卖持仓今天计划完全退出、等待的卖点；仅当确实可卖时用于换仓过渡")
    replacement_for: str = Field(default="", pattern=r"^(|\d{6})$", description="可选换仓备注，记录参考替换股票；不是开仓准入条件")

    @field_validator("code", "replacement_for", mode="before")
    @classmethod
    def plain_code(cls, value: Any) -> Any:
        return normalize_stock_code(value)

    @model_validator(mode="after")
    def non_trade_has_no_quantity(self) -> GuardianOrder:
        if self.action not in TRADE_ACTIONS and self.quantity:
            raise ValueError("持股和观察动作的quantity必须为0")
        if self.action in ("watch", "unwatch") and self.risk_plans is not None:
            raise ValueError("观察动作不能安装或撤回持仓风险合同")
        return self


class OpeningPlanReview(BaseModel):
    model_config = ConfigDict(extra="forbid")
    plan_id: str
    decision: Literal['execute', 'wait', 'abandon']
    reason: str = Field(min_length=1)


class GuardianDecision(BaseModel):
    model_config = ConfigDict(extra="forbid")
    summary: str
    opening_plan_reviews: list[OpeningPlanReview] = Field(default_factory=list,
        description="逐笔复核pending_opening_plans：执行、继续观察或主动放弃并说明原因；execute须有绑定该计划id的新订单")
    orders: list[GuardianOrder]



class OrderPolicyError(ValueError):
    """完整且合契约的决策里，个别订单违反账户买入权限（如科创板/北交所）。

    完整性修复仍先让模型自行替换；修复后仍违规（或修复本身失败）时，决策照样
    可执行：``simulate`` 只把这些订单按 ``board_not_allowed`` 拒掉并作为受阻意图
    展示，其余意图（尤其是止损/减仓卖单）照常核价撮合，不再整轮作废。
    """

    def __init__(self, message: str, decision: GuardianDecision) -> None:
        super().__init__(message)
        self.decision = decision


def parse_decision(text: str, *, require_execution_terms: bool = False,
                   decision_type: type[GuardianDecision] = GuardianDecision) -> GuardianDecision:
    decision = decision_type.model_validate(load_json_response(text))
    if require_execution_terms:
        missing = [o.code for o in decision.orders if o.action in TRADE_ACTIONS and o.execution is None]
        if missing:
            raise ValueError("买卖意图必须提供execution价格授权和失效时间：" + "、".join(missing))
    return decision


def bind_execution_references(decision: GuardianDecision, quotes: dict[str, dict[str, Any]],
                              now: datetime) -> GuardianDecision:
    """市价授权锁定首次有效执行报价；后续取价及预检修正不得重置基准。"""
    bound = decision.model_copy(deep=True)
    for item in bound.orders:
        terms = item.execution
        if item.action not in TRADE_ACTIONS or terms is None or terms.kind != "market" or terms.reference_price is not None:
            continue
        quote = quotes.get(item.code, {})
        if quote_error(item.code, quote, now) is None:
            item.execution = terms.model_copy(update={"reference_price": quote.get("price", quote.get("current_price"))})
    return bound


def simulate(state: dict[str, Any], decision: GuardianDecision, candidates: list[dict[str, Any]],
             quotes: dict[str, dict[str, Any]], now: datetime, *,
             require_execution_terms: bool = False, risk_only: bool = False,
             guardian_policy: bool = True) -> tuple[dict[str, Any], list[dict], list[dict]]:
    updated = copy.deepcopy(state)
    references = {item["code"]: item for item in candidates}
    fills, rejects = [], []
    used_depth: dict[tuple[str, str], int] = {}
    risk_seen: set[str] = set()
    for item in decision.orders:
        if risk_only:
            if item.action not in ("stop_loss", "take_profit") or item.risk_plans is not None or item.code in risk_seen:
                rejects.append({**item.model_dump(mode="json"), "reject_code": "risk_only",
                                "reason": "风险执行轮仅允许每股一次止损或止盈减仓，不修改风险合同"})
                continue
            risk_seen.add(item.code)
        before = next((p for p in updated["positions"] if p["code"] == item.code), None)
        if item.action == "hold":
            if before:
                proposed = copy.deepcopy(before)
                try:
                    install_risk_plans(proposed, item.risk_plans, now)
                except ValueError as exc:
                    rejects.append({**item.model_dump(mode="json"), "reason": str(exc), "reject_code": "risk_plan"})
                    continue
                before.update(proposed)
                for key in ("holding_plan", "take_profit_plan", "stop_loss_plan", "exit_today_plan"):
                    if getattr(item, key):
                        before[key] = getattr(item, key)
                if item.exit_today_plan:
                    before["exit_plan_date"] = now.date().isoformat()
                before["last_review"] = {"action": "hold", "reason": item.reason, "at": now.isoformat()}
            else:
                rejects.append({**item.model_dump(), "reason": "未持仓，请使用观察动作"})
            continue
        if item.action in ("watch", "unwatch"):
            from src.ledger.domain.guardian_watchlist import update_watchlist
            update_watchlist(updated, item.model_dump(), now.isoformat(),
                             name=item.name or references.get(item.code, {}).get("name", ""), source='intraday')
            continue
        quote = quotes.get(item.code) or {}
        error_code = "quote_unavailable"
        try:
            if guardian_policy:
                from src.ledger.domain.guardian_account import guardian_buy_error
                error_code = "board_not_allowed"
                problem = guardian_buy_error(item.code, item.action)
                if problem:
                    raise ValueError(problem)
            error_code = "quote_unavailable"
            problem = quote_error(item.code, quote, now)
            if problem:
                raise ValueError(problem)
            error_code = "liquidity_unconfirmed"
            depth_key = (item.code, "ask" if item.action in {"buy", "add"} else "bid")
            execution_quote = executable_quote(item.code, item.action, item.quantity, quote, now,
                                              used_quantity=used_depth.get(depth_key, 0), paper=guardian_policy)
            price = execution_quote["price"]
            error_code, problem = execution_error(item.execution, price, now, required=require_execution_terms)
            if problem:
                raise ValueError(problem)
            proposed = copy.deepcopy(updated)
            fill = settle_guardian_order(proposed, item.model_dump(mode="json"), execution_quote, now,
                                         references.get(item.code, {}), guardian_policy=guardian_policy)
            # 预检必须与提交使用同一个按分成交价，不能到整批提交才发现取整越界。
            error_code, problem = execution_error(item.execution, fill["price_cents"] / 100, now,
                                                   required=require_execution_terms)
            if problem:
                raise ValueError(problem)
            after = next((p for p in proposed["positions"] if p["code"] == item.code), None)
            error_code = "risk_plan"
            if after is not None:
                install_risk_plans(after, item.risk_plans, now)
            elif item.risk_plans:
                raise ValueError("清仓后没有持仓，不能安装风险合同")
            if item.execution is not None:
                fill["execution_cage"] = execution_cage(item.execution)
            updated = proposed
            fill["execution_evidence"] = execution_quote["execution_evidence"]
            used_depth[depth_key] = used_depth.get(depth_key, 0) + item.quantity
            fills.append(fill)
        except ValueError as exc:
            rejects.append({**item.model_dump(mode="json"), "reason": str(exc), "reject_code": error_code or rejection_code(str(exc))})
    valid_quotes = validated_quotes(quotes, now)
    return mark_guardian_account(updated, valid_quotes, now), fills, rejects



def fresh_quote(quote: dict[str, Any], now: datetime) -> bool:
    from src.ops.application.guardian_quotes import fresh_quote as is_fresh
    return is_fresh(quote, now)


def render_positions(state: dict[str, Any]) -> str:
    if not state["positions"]:
        return "持仓 · 空仓"
    lines = ["持仓成本（含买入费用）"]
    for p in state["positions"]:
        average = p["cost_cents"] / 100 / p["quantity"]
        lines.append(f"{p['name']} {p['code']}｜{p['quantity']}股（可卖{p.get('available_quantity', 0)}）\n"
                     f"成本 {average:.4f}元/股｜成本总额 {p['cost_cents']/100:,.2f}元")
    return "\n".join(lines)


def render_digest(summary: str, fills: list[dict], rejects: list[dict], state: dict[str, Any]) -> str:
    """Account overview plus this cycle's executions only; full analysis stays in the run."""
    from src.ops.application.guardian_notification import render_account_overview, notice_reason
    money = lambda value: f"{value / 100:,.2f}"
    lines = [render_account_overview(state)]
    if fills:
        lines.append(f"本轮变动 · 成交 {len(fills)} 笔")
    for fill in fills:
        label = ACTION_LABELS.get(fill.get("action"), "卖出" if fill["side"] == "sell" else "买入")
        lines.append(f"{label} · {fill['name']} {fill['code']} · {fill['quantity']} 股 × {money(fill['price_cents'])} 元\n"
                     f"剩余 {fill['after_quantity']} 股 · 费用 {money(fill['fees_cents'])} 元"
                     + (f" · 本笔盈亏 {fill['realized_pnl_cents'] / 100:+,.2f} 元" if fill["side"] == "sell" else ""))
    for item in rejects:
        label = ACTION_LABELS.get(item.get("action"), "操作")
        stock = " ".join(str(item.get(k) or "") for k in ("name", "code")).strip() or "组合"
        quantity = f" {item['quantity']} 股" if item.get("quantity") else ""
        lines.append(f"暂未执行 · {label} · {stock}{quantity}：{notice_reason(item.get('reason'))}")
    if not fills and not rejects:
        lines.append("本轮无成交")
    return "\n\n".join(lines)
