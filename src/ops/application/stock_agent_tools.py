"""每轮独立的账户工具适配器：不暴露其他智能体或旧交易员的历史。"""
from __future__ import annotations

import json
from datetime import datetime
from zoneinfo import ZoneInfo

from src.ledger import StockAgentStore
from src.ops.application.guardian_decision import bind_execution_references, parse_decision
from src.ops.application.guardian_research_tools import GuardianResearchTools
from src.ops.application.guardian_tools import agent_tools
from src.ops.application.stock_agent_policy import simulate_stock_agent

SYSTEM_READS = {"web_search", "web_fetch", "market_quote", "market_kline", "market_status",
                "strategy_catalog", "research_catalog", "research_profile"}
OWN_READS = {"guardian_account_read", "guardian_runtime", "guardian_quotes", "guardian_calculate", "guardian_scenario"}


def stock_agent_tools(protocol: str, *, profile: dict, payload: dict, palace_path: str,
                      deadline: float, checkpoint):
    workbench = GuardianResearchTools(protocol, payload=payload, palace_path=palace_path,
                                     deadline=deadline, check_cancelled=checkpoint)
    primary, primary_execute, source = agent_tools(protocol, read_only=True, deadline=deadline)
    # 外部工具已是只读白名单；系统回退进一步排除用户其他账户/日记。
    primary = [schema for schema in primary if source.get("wudao")
               and (schema.get("function") or schema)["name"] not in workbench.names
               and not any(word in (schema.get("function") or schema)["name"].lower()
                           for word in ("account", "portfolio", "journal", "position", "guardian", "watchlist"))]
    allowed = OWN_READS | {"system__" + name for name in SYSTEM_READS} | {"guardian_preflight", "guardian_decision_history"}
    own = [schema for schema in workbench.schemas if (schema.get("function") or schema)["name"] in allowed]
    for schema in own:
        body = schema.get("function") or schema
        if body["name"] == "guardian_preflight":
            body["description"] = "只预演本智能体账户和配置的每日入选、观察、持仓、费用及T+1约束，不产生真实成交。"
        elif body["name"] == "guardian_decision_history":
            body["description"] = "按日期分页查看本智能体自己的工作日记；不访问其他账户。"
    primary_names = {(schema.get("function") or schema)["name"] for schema in primary}

    def execute(name: str, arguments: dict) -> dict:
        checkpoint()
        if name == "guardian_quotes" and len(arguments.get("codes", [])) > 60:
            return {"is_error": True, "text": "单次最多核实60只股票，请分批查询"}
        if name == "guardian_decision_history":
            with StockAgentStore(palace_path) as store:
                result = store.history(profile["id"], start=arguments.get("date"), end=arguments.get("date"),
                                       limit=min(30, int(arguments.get("limit", 20))), offset=int(arguments.get("offset", 0)))
        elif name == "guardian_preflight":
            decision = parse_decision(json.dumps(arguments, ensure_ascii=False), require_execution_terms=True)
            codes = list(dict.fromkeys([p["code"] for p in payload["portfolio"]["positions"]] + [o.code for o in decision.orders]))
            quotes = workbench._snapshot(codes) if codes else {}
            now = datetime.now(ZoneInfo("Asia/Shanghai"))
            decision = bind_execution_references(decision, quotes, now)
            state, fills, rejects = simulate_stock_agent(payload["portfolio"], decision, quotes, now,
                                                         profile["config"], analysis_only=payload["analysis_only"])
            result = {"preflight_only": True, "ledger_committed": False, "projected_account": state,
                      "preflight_fills": fills, "rejects": rejects, "decision_with_fixed_references": decision.model_dump(mode="json")}
        elif name in allowed:
            return workbench.execute(name, arguments)
        elif name in primary_names:
            return primary_execute(name, arguments)
        else:
            return {"is_error": True, "text": "此智能体没有该工具权限"}
        checkpoint()
        return {"structured": result, "text": json.dumps(result, ensure_ascii=False, default=str)}
    return [*primary, *own], execute, source
