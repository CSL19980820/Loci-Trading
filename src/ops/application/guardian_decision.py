"""守护输出契约和模拟撮合；模型不能指定成交价格。"""
from __future__ import annotations

import copy
import json
from datetime import datetime, timedelta
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from src.ledger import (settle_guardian_order, mark_guardian_account,
                        guardian_position_policy, validate_guardian_close_plan)

from src.ops.application.guardian_contract import ExecutionTerms, execution_error, execution_cage, rejection_code
from src.ops.application.guardian_quotes import quote_error, validated_quotes
from src.ops.application.guardian_risk import RiskPlan, install_risk_plans

TRADE_ACTIONS = frozenset({"buy", "add", "reduce", "sell", "take_profit", "stop_loss"})
ACTION_LABELS = {"buy": "买入", "add": "加仓", "reduce": "减仓", "sell": "卖出",
                 "take_profit": "止盈", "stop_loss": "止损", "hold": "持股", "watch": "观察", "unwatch": "撤出观察"}


class GuardianOrder(BaseModel):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)
    code: str = Field(pattern=r"^\d{6}$")
    action: Literal["buy", "add", "reduce", "sell", "take_profit", "stop_loss", "hold", "watch", "unwatch"]
    name: str = Field(default="", max_length=64, description="股票名称，尤其用于自主观察股票")
    quantity: int = Field(default=0, ge=0, strict=True, description="本次买入或卖出的整数股数；hold 为 0，卖出必须明确股数")
    reason: str = Field(min_length=1)
    execution: ExecutionTerms | None = Field(default=None, description="买卖意图的价格授权及有效期；历史记录可缺省")
    risk_plans: list[RiskPlan] | None = Field(default=None, max_length=16,
        description="操作后持仓的结构化止损/止盈合同，最多16项；含触发价、股数、成交价限和有效期。null保留，[]撤回；watch/unwatch不可使用")
    holding_plan: str = Field(default="", description="自主决定的持有周期或持有/退出条件，不要求固定天数")
    take_profit_plan: str = Field(default="", description="持仓止盈条件与理由，每轮由模型复核，不是券商挂单")
    stop_loss_plan: str = Field(default="", description="持仓止损条件与理由，仍遵守T+1")
    entry_condition: str = Field(default="", description="观察标的等待什么条件才考虑买入")
    exit_condition: str = Field(default="", description="什么条件下撤出自主观察")
    exit_today_plan: str = Field(default="", description="已有可卖持仓今天计划完全退出、等待的卖点；仅当确实可卖时用于换仓过渡")
    replacement_for: str = Field(default="", pattern=r"^(|\d{6})$", description="可选换仓备注，记录参考替换股票；不是开仓准入条件")

    @model_validator(mode="after")
    def non_trade_has_no_quantity(self) -> GuardianOrder:
        if self.action not in TRADE_ACTIONS and self.quantity:
            raise ValueError("持股和观察动作的quantity必须为0")
        if self.action in ("watch", "unwatch") and self.risk_plans is not None:
            raise ValueError("观察动作不能安装或撤回持仓风险合同")
        return self


class GuardianDecision(BaseModel):
    model_config = ConfigDict(extra="forbid")
    summary: str
    orders: list[GuardianOrder]
    close_keep_codes: list[str] | None = Field(default=None, max_length=4,
        description="本轮交易后持仓超过4只时必须明确收盘保留的股票代码，最多4只且覆盖全部T+1锁定股票；模型可逐轮更新，14:50起按最后有效名单退出其他股票。空数组表示全部退出，null沿用当日有效名单")


def closing_decision(state: dict[str, Any], now: datetime) -> GuardianDecision | None:
    """尾盘执行模型已保存的留仓选择；程序不按涨跌或成本代替模型选股。"""
    policy = guardian_position_policy(state, now)
    if not policy["close_due"] or len(state["positions"]) <= policy["close_max"]:
        return None
    keep = validate_guardian_close_plan(state, None, now)
    return GuardianDecision(summary="按最后确认的收盘留仓名单完成尾盘收敛。", close_keep_codes=keep,
        orders=[GuardianOrder(code=p["code"], action="sell", quantity=p["quantity"],
                              execution=ExecutionTerms(kind="market", valid_until=(now + timedelta(minutes=5)).isoformat()),
                              reason="执行模型收盘留仓选择，退出未保留股票。")
                for p in state["positions"] if p["code"] not in keep])


def parse_decision(text: str, *, require_execution_terms: bool = False) -> GuardianDecision:
    raw = text.strip()
    if raw.startswith("```json\n") and raw.endswith("```"):
        raw = raw[8:-3].strip()
    decision = GuardianDecision.model_validate(json.loads(raw))
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
             require_execution_terms: bool = False, risk_only: bool = False) -> tuple[dict[str, Any], list[dict], list[dict]]:
    updated = copy.deepcopy(state)
    references = {item["code"]: item for item in candidates}
    fills, rejects = [], []
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
            watched = updated.setdefault("watchlist", [])
            existing = next((w for w in watched if w["code"] == item.code), None)
            if item.action == "unwatch":
                if existing:
                    watched.remove(existing)
            else:
                entry = {"code": item.code, "name": item.name or references.get(item.code, {}).get("name") or item.code,
                         "reason": item.reason, "entry_condition": item.entry_condition,
                         "exit_condition": item.exit_condition, "updated_at": now.isoformat(),
                         "added_at": (existing or {}).get("added_at", now.isoformat())}
                if existing:
                    existing.update(entry)
                else:
                    watched.append(entry)
            continue
        quote = quotes.get(item.code) or {}
        error_code = "quote_unavailable"
        try:
            problem = quote_error(item.code, quote, now)
            if problem:
                raise ValueError(problem)
            price = quote.get("price", quote.get("current_price"))
            error_code, problem = execution_error(item.execution, price, now, required=require_execution_terms)
            if problem:
                raise ValueError(problem)
            proposed = copy.deepcopy(updated)
            fill = settle_guardian_order(proposed, item.model_dump(mode="json"), quote, now, references.get(item.code, {}))
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
            fills.append(fill)
        except ValueError as exc:
            rejects.append({**item.model_dump(mode="json"), "reason": str(exc), "reject_code": error_code or rejection_code(str(exc))})
    valid_quotes = validated_quotes(quotes, now)
    held = {p["code"] for p in updated["positions"]}
    closed = {f["code"] for f in fills if f["side"] == "sell" and f["after_quantity"] == 0} - held
    if updated.get("close_plan_date") == now.date().isoformat() and isinstance(updated.get("close_keep_codes"), list):
        updated["close_keep_codes"] = [code for code in updated["close_keep_codes"] if code not in closed]
    if len(updated["positions"]) > guardian_position_policy(updated, now)["close_max"]:
        try:
            keep = validate_guardian_close_plan(updated, None if risk_only else decision.close_keep_codes, now)
        except ValueError as exc:
            if risk_only:
                rejects.append({"code": "", "quantity": 0, "action": "close_plan",
                                "reason": str(exc), "reject_code": "close_plan"})
                return mark_guardian_account(updated, valid_quotes, now), fills, rejects
            # 本函数尚未落账，整组意图在预检失败时不产生半套换仓成交。
            rejects = [{**item.model_dump(), "reason": f"本轮交易组合未成交：{exc}", "reject_code": "close_plan"}
                       for item in decision.orders if item.action in TRADE_ACTIONS]
            if not rejects:
                rejects = [{"code": "", "quantity": 0, "reason": str(exc)}]
            return mark_guardian_account(state, valid_quotes, now), [], rejects
        updated.update(close_keep_codes=keep, close_plan_date=now.date().isoformat())
    elif updated.get("close_plan_date") != now.date().isoformat():
        updated.pop("close_keep_codes", None)
        updated.pop("close_plan_date", None)
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
    money = lambda value: f"{value / 100:,.2f}"
    lines = [f"账户 · 总资产 {money(state['equity_cents'])} 元 · 现金 {money(state['cash_cents'])} 元",
             f"累计盈亏 {money(state['total_pnl_cents'])} 元（已实现 {money(state['realized_pnl_cents'])} / 浮动 {money(state['unrealized_pnl_cents'])}）"]
    lines.append(render_positions(state))
    for fill in fills:
        label = ACTION_LABELS.get(fill.get("action"), "卖出" if fill["side"] == "sell" else "买入")
        lines.append(f"{label} · {fill['name']} {fill['code']} · {fill['quantity']} 股 × {money(fill['price_cents'])} 元\n"
                     f"成交额 {money(fill['gross_cents'])} · 费用 {money(fill['fees_cents'])} · 持仓 {fill['after_quantity']} 股"
                     + (f" · 本笔盈亏 {money(fill['realized_pnl_cents'])}" if fill["side"] == "sell" else ""))
    for item in rejects:
        lines.append(f"暂未执行 · {item['code']} {item['quantity']} 股：{item['reason']}")
    if not fills and not rejects:
        lines.append("本轮无成交")
    if state.get("stale_codes"):
        lines.append("估值含旧报价：" + "、".join(state["stale_codes"]))
    if state.get("watchlist"):
        lines.append("自主观察 · " + "；".join(f"{w['name']} {w['code']}：{w.get('entry_condition') or w['reason']}" for w in state["watchlist"]))
    if summary and summary != "无动作":
        lines.append(f"研判 · {summary}")
    return "\n\n".join(lines)
