"""交易员研究工作台：系统只读能力、实时批量报价、订单预演与情景计算。"""
from __future__ import annotations

import copy
import json
import time
from collections.abc import Callable
from datetime import datetime
from decimal import Decimal, ROUND_HALF_UP
from pathlib import Path
from threading import local
from typing import Any
from zoneinfo import ZoneInfo

from pydantic import BaseModel, ConfigDict, Field, field_validator

from src.ledger import GuardianStore, mark_guardian_account, guardian_available_quantity
from src.ops.application.guardian_contract import execution_cage
from src.ops.application.guardian_decision import (
    GuardianDecision, TRADE_ACTIONS, bind_execution_references, parse_decision, simulate,
)
from src.ops.application.guardian_evidence import HISTORY_TOOL, decision_history, history_schema
from src.ops.application.guardian_quotes import validated_quotes, quote_error
from src.ops.application.guardian_compute import calculate
from src.ops.application.session_clock import session_clock
from src.shared.paths import palace_db
from src.shared.tenancy import current_tenant

SHANGHAI = ZoneInfo("Asia/Shanghai")
SYSTEM_PREFIX = "system__"
PARALLEL_RESEARCH_TOOLS = frozenset({
    "guardian_account_read", "guardian_quotes", "guardian_preflight", "guardian_scenario",
    "guardian_runtime", "guardian_calculate", HISTORY_TOOL, "web_search", "web_fetch", "market_quote", "market_kline",
    "market_status", "strategy_catalog", "research_catalog", "research_profile",
})


class QuoteQuery(BaseModel):
    model_config = ConfigDict(extra="forbid")
    codes: list[str] = Field(min_length=1)

    @field_validator("codes")
    @classmethod
    def valid_codes(cls, values: list[str]) -> list[str]:
        if any(len(code) != 6 or not code.isascii() or not code.isdigit() for code in values):
            raise ValueError("股票代码须为六位数字")
        return list(dict.fromkeys(values))


class ScenarioShock(BaseModel):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)
    code: str = Field(pattern=r"^\d{6}$")
    change_pct: float = Field(ge=-100, description="相对当前估值的假设涨跌幅，单位为百分比；不是预测事实")

    @field_validator("change_pct", mode="before")
    @classmethod
    def numeric_change(cls, value: Any) -> Any:
        if isinstance(value, bool):
            raise ValueError("情景涨跌幅不能是布尔值")
        return value


class ScenarioQuery(BaseModel):
    model_config = ConfigDict(extra="forbid")
    shocks: list[ScenarioShock]


def _result(value: Any) -> dict[str, Any]:
    return {"text": json.dumps(value, ensure_ascii=False, default=str), "structured": value}


def account_exposure(state: dict[str, Any], now: datetime) -> dict[str, Any]:
    """描述现有集中度与锁仓，不另加单股、行业或亏损额度限制。"""
    equity = state["equity_cents"]
    positions = []
    for position in state["positions"]:
        available = guardian_available_quantity(position, now.date().isoformat())
        positions.append({"code": position["code"], "quantity": position["quantity"],
            "available_quantity": available, "locked_quantity": position["quantity"] - available,
            "market_value_cents": position.get("market_value_cents"),
            "weight_pct": round(position.get("market_value_cents", 0) / equity * 100, 4) if equity else None,
            "valuation_stale": position.get("valuation_stale", True),
            "active_risk_contracts": sum(p.get("status") == "active" for p in position.get("risk_plans", []))})
    return {"equity_cents": equity, "cash_cents": state["cash_cents"],
            "cash_weight_pct": round(state["cash_cents"] / equity * 100, 4) if equity else None,
            "positions": positions, "stale_codes": state.get("stale_codes", []),
            "risk_policy": "描述性指标与情景工具，不新增仓位或战法限制；是否承担风险由模型自主决定。"}


class GuardianResearchTools:
    """每轮固定输入；每线程独立系统工具实例与每次独立账本连接。"""

    def __init__(self, protocol: str, *, payload: dict[str, Any] | None = None,
                 palace_path: str | Path | None = None, deadline: float | None = None,
                 check_cancelled: Callable[[], None] | None = None) -> None:
        from src.ai.application.tool_schema import tool_schema

        self.protocol = protocol
        self.payload = copy.deepcopy(payload or {})
        self.palace_path = str(palace_path or palace_db())
        self.tenant = current_tenant()
        self.deadline, self.check_cancelled = deadline, check_cancelled
        self.sessions = local()
        bus = self._bus()
        self.system_names = {(item.get("function") or item)["name"] for item in bus.schemas} - {"ask_user"}
        self.schemas = []
        for item in bus.schemas:
            schema = copy.deepcopy(item)
            body = schema.get("function") or schema
            if body["name"] not in self.system_names:
                continue
            body["name"] = SYSTEM_PREFIX + body["name"]
            self.schemas.append(schema)
        empty = {"type": "object", "properties": {}, "additionalProperties": False}
        specs = [
            ("guardian_account_read", "读取本轮模拟账户、费用、可卖/锁定股数及集中度；不修改资金。", empty),
            ("guardian_runtime", "读取当前市场时段与本轮剩余时间，协助安排研究与最终决策。", empty),
            ("guardian_quotes", "批量获取新鲜主备报价，返回每股时间、来源和失败原因；可查询策略池外股票。", QuoteQuery.model_json_schema()),
            ("guardian_preflight", "预演完整决策，精确计算费用、现金、股数、T+1及2%价格容差；可反复修改方案，不落账、不通知、不成交。入参就是完整GuardianDecision。", GuardianDecision.model_json_schema()),
            ("guardian_calculate", "50位精度的十进制算术，支持加减乘除、括号、余数和整数幂；不执行Python程序。",
             {"type": "object", "properties": {"expression": {"type": "string", "minLength": 1, "maxLength": 8192}},
              "required": ["expression"], "additionalProperties": False}),
            ("guardian_scenario", "按自主设定涨跌幅计算现有组合情景损益，非预测、非交易，不强加风险阈值。", ScenarioQuery.model_json_schema()),
        ]
        self.schemas.extend(tool_schema(protocol, name, description, schema) for name, description, schema in specs)
        self.schemas.append(history_schema(protocol))
        self.names = {(schema.get("function") or schema)["name"] for schema in self.schemas}
        self.handlers = {"guardian_account_read": self._read_account, "guardian_runtime": self._runtime,
                         "guardian_quotes": self._quotes, "guardian_preflight": self._preflight,
                         "guardian_scenario": self._scenario, HISTORY_TOOL: self._history,
                         "guardian_calculate": lambda args: calculate(args["expression"])}

    def _bus(self) -> Any:
        from src.ai.application.system_toolbus import SystemToolBus
        if not hasattr(self.sessions, "bus"):
            self.sessions.bus = SystemToolBus(palace_db=self.palace_path, market_db=None, ops_db=None,
                protocol=self.protocol, read_only=True, attach_mcp=False)
        return self.sessions.bus

    def _checkpoint(self) -> None:
        if current_tenant() != self.tenant:
            raise ValueError("交易员研究工具不可跨租户复用")
        if self.check_cancelled:
            self.check_cancelled()
        if self.deadline is not None and time.monotonic() >= self.deadline:
            raise TimeoutError("研究工具已超过本轮截止时间")

    def execute(self, name: str, arguments: dict[str, Any]) -> dict[str, Any]:
        self._checkpoint()
        if name not in self.names:
            return {"is_error": True, "text": "未注册的交易员研究工具"}
        if name.startswith(SYSTEM_PREFIX):
            result = self._bus().executor(name.removeprefix(SYSTEM_PREFIX), arguments)
            if not result.get("is_error") and isinstance(result.get("structured"), (dict, list)):
                result = {**result, "text": json.dumps(result["structured"], ensure_ascii=False, default=str)}
        else:
            result = _result(self.handlers[name](arguments))
        self._checkpoint()
        return result

    def _account(self, now: datetime) -> dict[str, Any]:
        state = self.payload.get("portfolio")
        if state is None:
            with GuardianStore(self.palace_path) as ledger:
                state = ledger.state()
        return mark_guardian_account(state, {}, now)

    def _read_account(self, _: dict[str, Any]) -> dict[str, Any]:
        now = datetime.now(SHANGHAI)
        state = self._account(now)
        return {"as_of": now.isoformat(), "basis_as_of": self.payload.get("as_of"),
                "portfolio": state, "exposure": account_exposure(state, now)}

    def _runtime(self, _: dict[str, Any]) -> dict[str, Any]:
        now = datetime.now(SHANGHAI)
        return {"as_of": now.isoformat(), "market_phase": session_clock(now).phase,
                "research_seconds_remaining": max(0, self.deadline - time.monotonic()) if self.deadline is not None else None,
                "execution_deadline": self.payload.get("execution_deadline"),
                "analysis_only": self.payload.get("analysis_only"), "execution_tolerance_pct": 2}

    def _snapshot(self, codes: list[str]) -> dict[str, dict[str, Any]]:
        from src.ops.application.guardian_tools import snapshot
        return snapshot(codes, force_refresh=True, check_cancelled=self._checkpoint, deadline=self.deadline).quotes

    def _quotes(self, arguments: dict[str, Any]) -> dict[str, Any]:
        query = QuoteQuery.model_validate(arguments)
        quotes = self._snapshot(query.codes)
        now = datetime.now(SHANGHAI)
        return {"as_of": now.isoformat(), "quotes": quotes,
                "valid_codes": list(validated_quotes(quotes, now)), "requested_codes": query.codes,
                "quote_errors": {code: error for code in query.codes
                                 if (error := quote_error(code, quotes.get(code, {}), now))}}

    def _preflight(self, arguments: dict[str, Any]) -> dict[str, Any]:
        decision = parse_decision(json.dumps(arguments, ensure_ascii=False), require_execution_terms=True)
        state = self._account(datetime.now(SHANGHAI))
        codes = list(dict.fromkeys([p["code"] for p in state["positions"]]
                    + [o.code for o in decision.orders if o.action in TRADE_ACTIONS]))
        quotes = self._snapshot(codes) if codes else {}
        now = datetime.now(SHANGHAI)
        decision = bind_execution_references(decision, quotes, now)
        projected, fills, rejects = simulate(state, decision, self.payload.get("candidates", []), quotes, now,
                                             require_execution_terms=True)
        return {"preflight_only": True, "ledger_committed": False, "as_of": now.isoformat(),
                "basis_as_of": self.payload.get("as_of"),
                "execution_allowed_now": session_clock(now).phase == "regular",
                "decision_with_fixed_references": decision.model_dump(mode="json"),
                "projected_account": projected, "projected_exposure": account_exposure(projected, now),
                "preflight_fills": fills, "rejects": rejects, "quotes": quotes,
                "execution_cages": [{"code": o.code, **execution_cage(o.execution)} for o in decision.orders if o.execution],
                "note": "仅预演，没有成交。正式提交仍核验新鲜报价、原固定基准、时段、配置和取消状态；预演不授权绕过任何检查。"}

    def _scenario(self, arguments: dict[str, Any]) -> dict[str, Any]:
        query = ScenarioQuery.model_validate(arguments)
        now = datetime.now(SHANGHAI)
        state = self._account(now)
        changes = {shock.code: shock.change_pct for shock in query.shocks}
        if len(changes) != len(query.shocks):
            raise ValueError("同一情景不能重复指定股票")
        held = {position["code"] for position in state["positions"]}
        if not set(changes) <= held:
            raise ValueError("情景含未持仓股票；新交易组合请使用guardian_preflight")
        rows = []
        for position in state["positions"]:
            change = changes.get(position["code"], 0)
            value = Decimal(position["market_value_cents"]) * (1 + Decimal(str(change)) / 100)
            value = int(value.quantize(Decimal("1"), rounding=ROUND_HALF_UP))
            rows.append({"code": position["code"], "assumed_change_pct": change,
                         "projected_market_value_cents": value,
                         "change_cents": value - position["market_value_cents"]})
        projected = state["cash_cents"] + sum(row["projected_market_value_cents"] for row in rows)
        return {"hypothetical": True, "as_of": now.isoformat(), "base_equity_cents": state["equity_cents"],
                "projected_equity_cents": projected, "change_cents": projected - state["equity_cents"],
                "positions": rows, "stale_codes": state.get("stale_codes", []),
                "note": "静态价格情景，不是收益预测；未假定能够卖出T+1锁仓，也未计入未来交易费用。"}

    def _history(self, arguments: dict[str, Any]) -> dict[str, Any]:
        params = dict(arguments)
        day = params.pop("date")
        with GuardianStore(self.palace_path) as ledger:
            return decision_history(ledger, day=day, **params)


RESEARCH_WORKBENCH_RULES = """【可自主调用的研究工作台】
悟道与system__前缀的本地系统工具同时可用，不是二选一。可自主查询全市场、网页资讯、历史行情、策略与研究证据，不必遵循固定工具调用次序。
guardian_account_read提供实际现金、费用、可卖与锁定股数和集中度；guardian_quotes提供带来源和时点的主备报价；guardian_scenario按你设定的情景算组合损益，不替你决定可接受风险。
guardian_preflight使用真实账本算法在副本上预演完整决策：费用、股数、现金、价格容差、T+1及收盘留仓；不产生任何成交。可以自主调整股票、方向、股数和组合后再次预演，不受最终一次修正的收缩限制。
预演回传decision_with_fixed_references；保留相同意图的reference_price，最终JSON沿用该固定基准，不把新报价重新当成基准叠加2%。预演有错误时自主修改，不必盲目提交再等拒单。
guardian_calculate可核对费用、收益比例与仓位算术，数值来源仍须有证据。
历史疑问可用guardian_decision_history分页核对原始理由，长材料用guardian_context_read取回全文；缺失证据不能自行补造。
guardian_runtime提供真实剩余时间。研究不设固定轮数或单轮工具总次数上限；并发是资源调度而非研究范围限制。成交仍必须在本轮市场有效时间内，旧意图不得假装成新鲜可执行结论。
"""


def compose_research_tools(protocol: str, *, primary_loader: Callable[..., Any],
                           payload: dict[str, Any] | None = None, palace_path: str | Path | None = None,
                           deadline: float | None = None, read_only: bool = False) -> tuple[list[dict], Any, dict]:
    """保留原行情工具，并叠加本地工作台；外部发现失败不卸载本地能力。"""
    workbench = GuardianResearchTools(protocol, payload=payload, palace_path=palace_path, deadline=deadline)
    try:
        primary, execute_primary, source = primary_loader(protocol, read_only=read_only, deadline=deadline)
    except (ValueError, RuntimeError, OSError) as exc:
        from src.ai.application.agent_execution import reraise_stop
        reraise_stop(exc)
        primary, execute_primary = [], None
        source = {"label": "系统研究工作台", "wudao": False, "primary_error": str(exc)}
    # 一些系统回退已提供同名本地工具；本轮专用账户工具以不可变快照为准。
    primary = [schema for schema in primary if (schema.get("function") or schema).get("name") not in workbench.names]
    schemas = [*primary, *workbench.schemas]
    source = {**source, "research_workbench": True, "available_tool_count": len(schemas)}
    def execute(name: str, arguments: dict[str, Any]) -> dict[str, Any]:
        if name in workbench.names:
            return workbench.execute(name, arguments)
        if execute_primary is None:
            return {"is_error": True, "text": "该外部工具不可用；可使用system__工具或guardian_quotes核对替代数据。"}
        return execute_primary(name, arguments)
    return schemas, execute, source
