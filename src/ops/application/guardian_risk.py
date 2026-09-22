"""持仓风险合同：触发普通卖单，实际成交后才消费计划。"""
from __future__ import annotations

import copy
import hashlib
import json
from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from src.ledger import guardian_quantity_error
from src.ops.application.guardian_contract import ExecutionTerms, execution_error
from src.ops.application.guardian_quotes import SHANGHAI, quote_error


class RiskPlan(BaseModel):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False, revalidate_instances="always")

    action: Literal["stop_loss", "take_profit"]
    quantity: int = Field(gt=0, strict=True)
    trigger_price: float = Field(gt=0)
    execution: ExecutionTerms
    reason: str = Field(min_length=1)

    @field_validator("trigger_price", mode="before")
    @classmethod
    def real_trigger(cls, value: Any) -> Any:
        if isinstance(value, bool):
            raise ValueError("触发价不能是布尔值")
        return value

    @field_validator("reason")
    @classmethod
    def meaningful_reason(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("风险计划必须说明理由")
        return value

    @model_validator(mode="after")
    def reachable_execution(self) -> RiskPlan:
        if (self.action == "stop_loss" and self.execution.min_price is not None
                and self.execution.min_price > self.trigger_price):
            raise ValueError("止损触发价与成交价格下限没有交集")
        if (self.action == "take_profit" and self.execution.max_price is not None
                and self.execution.max_price < self.trigger_price):
            raise ValueError("止盈触发价与成交价格上限没有交集")
        return self


def _aware(now: datetime) -> datetime:
    return now.replace(tzinfo=SHANGHAI) if now.tzinfo is None else now


def _opened_at(position: dict[str, Any]) -> str:
    return str((position.get("entry_context") or {}).get("opened_at") or "")


def _plan_id(code: str, contract: dict[str, Any], opened_at: str) -> str:
    # 说明文案、安装时间和成交后的余额不能把同一个卖出授权重新激活。
    terms = {key: value for key, value in contract.items() if key != "reason"}
    # 新增可选字段不改变旧合同ID，否则升级会使已有风险合同无故失效。
    terms["execution"] = {key: value for key, value in terms["execution"].items()
                          if key != "reference_price" or value is not None}
    payload = json.dumps([code, opened_at, terms], sort_keys=True, ensure_ascii=False,
                         separators=(",", ":"))
    return "risk-" + hashlib.sha256(payload.encode("utf-8")).hexdigest()[:24]


def install_risk_plans(
    position: dict[str, Any], plans: list[RiskPlan | dict[str, Any]] | None, now: datetime,
) -> None:
    """原地替换合同；null 保留，空列表撤回，重复授权保留原基准和终态。"""
    if plans is None:
        return
    if not isinstance(plans, list):
        raise ValueError("risk_plans 必须是列表或 null")
    if not plans:
        position["risk_plans"] = []
        return
    quantity, code = position.get("quantity"), str(position.get("code") or "")
    if type(quantity) is not int or quantity <= 0:
        raise ValueError("风险计划只能安装到有效持仓")
    opened_at = _opened_at(position)
    existing = {row.get("plan_id"): row for row in position.get("risk_plans", [])
                if isinstance(row, dict)}
    installed: list[dict[str, Any]] = []
    seen: set[str] = set()
    for value in plans:
        plan = RiskPlan.model_validate(value)
        contract = plan.model_dump(mode="json")
        plan_id = _plan_id(code, contract, opened_at)
        if plan_id in seen:
            continue
        seen.add(plan_id)
        prior = existing.get(plan_id)
        if prior is not None:
            installed.append(copy.deepcopy(prior))
            continue
        # 可卖量随 T+1 变化；安装校验总持仓，触发后的可卖量交给撮合检查。
        problem = guardian_quantity_error(code, plan.quantity, True, quantity)
        if problem:
            raise ValueError(problem)
        installed.append({"plan_id": plan_id, "contract": contract,
                          "basis_quantity": quantity, "basis_opened_at": opened_at,
                          "installed_at": _aware(now).isoformat(), "status": "active"})
    position["risk_plans"] = installed


def _event(position: dict[str, Any], row: dict[str, Any], status: str, now: datetime,
           **details: Any) -> dict[str, Any]:
    contract = row.get("contract")
    contract = contract if isinstance(contract, dict) else {}
    return {"code": position["code"], "plan_id": row.get("plan_id", ""),
            "action": contract.get("action"), "quantity": contract.get("quantity"),
            "basis_quantity": row.get("basis_quantity"),
            "basis_opened_at": row.get("basis_opened_at"),
            "status": status, "at": now.isoformat(), **details}


def _execution(plan: RiskPlan, observed_price: float) -> dict[str, Any]:
    terms = plan.execution.model_dump(mode="json")
    terms["kind"] = "limit"
    if terms.get("reference_price") is None:
        terms["reference_price"] = observed_price
    if plan.action == "stop_loss":
        terms["max_price"] = min(plan.trigger_price, terms["max_price"] or plan.trigger_price)
    else:
        terms["min_price"] = max(plan.trigger_price, terms["min_price"] or plan.trigger_price)
    return ExecutionTerms.model_validate(terms).model_dump(mode="json")


def evaluate_risk_plans(
    state: dict[str, Any], quotes: dict[str, dict[str, Any]], now: datetime,
) -> tuple[dict[str, Any], list[dict[str, Any]], list[dict[str, Any]]]:
    """在状态副本中失效旧合同，每股最多生成一笔尚未消费的普通卖单。"""
    updated = copy.deepcopy(state)
    now = _aware(now)
    orders: list[dict[str, Any]] = []
    events: list[dict[str, Any]] = []
    selected: set[str] = set()
    for position in updated.get("positions", []):
        code = position["code"]
        valid: list[tuple[dict[str, Any], RiskPlan]] = []
        for row in position.get("risk_plans", []):
            if row.get("status") != "active":
                continue
            status, problem = "invalidated", ""
            try:
                plan = RiskPlan.model_validate(row["contract"])
                if (row.get("basis_quantity") != position["quantity"]
                        or row.get("basis_opened_at") != _opened_at(position)):
                    problem = "持仓数量或开仓批次已变化，须重新确认风险合同"
                elif now >= datetime.fromisoformat(plan.execution.valid_until):
                    status, problem = "expired", "风险合同已过有效期"
                elif row.get("plan_id") != _plan_id(code, plan.model_dump(mode="json"), _opened_at(position)):
                    problem = "风险合同标识不匹配"
            except (KeyError, TypeError, ValueError):
                problem = "风险合同格式无效"
            if problem:
                row.update(status=status, ended_at=now.isoformat(), status_reason=problem)
                events.append(_event(position, row, status, now, reason=problem))
            else:
                valid.append((row, plan))
        if not valid or code in selected:
            continue
        quote = quotes.get(code) or {}
        problem = quote_error(code, quote, now)
        if problem:
            events.extend(_event(position, row, "quote_unavailable", now, reason=problem)
                          for row, _ in valid)
            continue
        price = quote.get("price", quote.get("current_price"))
        for row, plan in sorted(valid, key=lambda item: item[1].action != "stop_loss"):
            triggered = price <= plan.trigger_price if plan.action == "stop_loss" else price >= plan.trigger_price
            if not triggered:
                continue
            order = {"code": code, "action": plan.action, "quantity": plan.quantity,
                     "reason": plan.reason, "execution": _execution(plan, price)}
            orders.append(order)
            events.append(_event(position, row, "triggered", now, order=copy.deepcopy(order),
                                 trigger_price=plan.trigger_price, observed_price=price))
            selected.add(code)
            break
    return updated, orders, events


def _matches_fill(event: dict[str, Any], fill: dict[str, Any]) -> bool:
    order = event.get("order") or {}
    if (fill.get("side") != "sell" or fill.get("reject_code")
            or type(fill.get("price_cents")) is not int or fill["price_cents"] <= 0
            or type(fill.get("quantity")) is not int
            or any(fill.get(key) != order.get(key) for key in ("code", "action", "quantity", "reason"))):
        return False
    if (type(fill.get("before_quantity")) is not int or type(fill.get("after_quantity")) is not int
            or fill["before_quantity"] != event.get("basis_quantity")
            or fill["after_quantity"] != fill["before_quantity"] - fill["quantity"]):
        return False
    try:
        terms = ExecutionTerms.model_validate(fill.get("execution"))
        occurred = datetime.fromisoformat(fill["occurred_at"])
        return (terms == ExecutionTerms.model_validate(order.get("execution"))
                and datetime.fromisoformat(event["at"]) <= occurred
                < datetime.fromisoformat(terms.valid_until)
                and not execution_error(terms, fill["price_cents"] / 100, occurred, required=True)[1])
    except (KeyError, TypeError, ValueError):
        return False


def consume_risk_plans(
    state: dict[str, Any], events: list[dict[str, Any]], fills: list[dict[str, Any]],
) -> None:
    """原地消费撮合后状态的已成交计划；全卖出时仍在事件中保留执行回执。"""
    used: set[int] = set()
    for event in events:
        if event.get("status") != "triggered":
            continue
        position = next((p for p in state.get("positions", []) if p["code"] == event["code"]), None)
        row = next((r for r in position.get("risk_plans", []) if r.get("plan_id") == event["plan_id"]), None) if position else None
        if position and (row is None or row.get("status") != "active"
                         or _opened_at(position) != event.get("basis_opened_at")):
            continue
        for index, fill in enumerate(fills):
            if index in used or not _matches_fill(event, fill):
                continue
            receipt = {"status": "executed", "executed_at": fill["occurred_at"],
                       "executed_quantity": fill["quantity"], "execution_price_cents": fill["price_cents"]}
            if row is not None:
                row.update(receipt)
            event.update(receipt)
            used.add(index)
            break


def resize_remaining_stops(state: dict[str, Any], fills: list[dict[str, Any]], now: datetime) -> list[dict]:
    """仅按本轮已证实的同批次纯减仓收缩止损授权，不扩大股数、价格或期限。"""
    events = []
    for position in state.get("positions", []):
        trades = [f for f in fills if f.get("code") == position["code"]]
        if not trades or any(f.get("side") != "sell" for f in trades):
            continue
        before = trades[0]["before_quantity"]
        balance = before
        for fill in trades:
            if fill["before_quantity"] != balance or fill["after_quantity"] != balance - fill["quantity"]:
                break
            balance = fill["after_quantity"]
        else:
            if balance != position["quantity"] or not 0 < balance < before:
                continue
            rows = position.get("risk_plans", [])
            for row in rows:
                if (row.get("status") != "active" or row.get("basis_quantity") != before
                        or row.get("basis_opened_at") != _opened_at(position)):
                    continue
                try:
                    plan = RiskPlan.model_validate(row["contract"])
                    if (plan.action != "stop_loss" or now >= datetime.fromisoformat(plan.execution.valid_until)
                            or row["plan_id"] != _plan_id(position["code"], plan.model_dump(mode="json"), _opened_at(position))):
                        continue
                    contract = plan.model_copy(update={"quantity": min(plan.quantity, balance)}).model_dump(mode="json")
                    if guardian_quantity_error(position["code"], contract["quantity"], True, balance):
                        continue
                    new_id = _plan_id(position["code"], contract, _opened_at(position))
                    if any(other is not row and other.get("plan_id") == new_id for other in rows):
                        continue  # 不能以缩量重新激活已消费或撤销的授权。
                except (ValueError, KeyError, TypeError):
                    continue
                prior = {k: copy.deepcopy(row[k]) for k in ("plan_id", "contract", "basis_quantity")}
                row.update(plan_id=new_id, contract=contract, basis_quantity=balance)
                row.setdefault("adjustments", []).append({"at": now.isoformat(), "previous": prior})
                events.append(_event(position, row, "adjusted", now, previous=prior,
                    reason=f"本轮减仓后止损保护收缩至{contract['quantity']}股，触发价、价格边界和有效期不变"))
    return events
