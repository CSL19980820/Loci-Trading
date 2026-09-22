"""独立研究工具：仅原始公开市场资料与本智能体账户，不注入工坊或其他账户。"""
from __future__ import annotations

import copy
import json
from datetime import datetime
from zoneinfo import ZoneInfo

from src.ai.application.tool_schema import tool_schema
from src.ledger import StockAgentStore
from src.market import query_agent_market
from src.ops.application.guardian_decision import bind_execution_references
from src.ops.application.guardian_research_tools import GuardianResearchTools
from src.ops.application.guardian_tools import agent_tools
from src.ops.application.stock_agent_decision import StockAgentDecision, parse_stock_agent_decision
from src.ops.application.stock_agent_policy import simulate_stock_agent, leader_research_codes, leader_holdings_only

SYSTEM_READS = {"web_search", "web_fetch", "market_quote", "market_kline", "market_status"}
OWN_READS = {"guardian_account_read", "guardian_runtime", "guardian_quotes", "guardian_calculate", "guardian_scenario"}
PRIVATE_NAMES = ("account", "portfolio", "journal", "position", "guardian", "watchlist", "strategy", "workshop", "candidate", "research_catalog", "research_profile")
DATE_FIELDS = {"date", "trade_date", "end_date", "endDate", "as_of"}
LEADER_STOCK_READS = {"kline", "minute_data", "auction_data", "valuation_snapshot", "financial_summary",
                      "shareholder_structure", "stock_event_calendar", "unlock_events", "margin_trading",
                      "northbound_holdings", "intraday_main_flow"}


def _body(schema: dict) -> dict:
    return schema.get("function") or schema


def stock_agent_tools(protocol: str, *, profile: dict, payload: dict, palace_path: str,
                      deadline: float, checkpoint):
    workbench = GuardianResearchTools(protocol, payload=payload, palace_path=palace_path,
                                     deadline=deadline, check_cancelled=checkpoint)
    try:
        primary, primary_execute, source = agent_tools(protocol, read_only=True, deadline=deadline)
    except (ValueError, RuntimeError, OSError) as exc:
        from src.ai.application.agent_execution import reraise_stop
        reraise_stop(exc)
        primary, primary_execute = [], None
        source = {"wudao": False, "primary_error": str(exc), "label": "系统公开行情"}
    primary = [copy.deepcopy(schema) for schema in primary if source.get("wudao")
               and _body(schema)["name"] not in workbench.names
               and not any(word in _body(schema)["name"].lower() for word in PRIVATE_NAMES)]
    allowed = OWN_READS | {"system__" + name for name in SYSTEM_READS} | {"guardian_preflight", "guardian_decision_history"}
    own = [copy.deepcopy(schema) for schema in workbench.schemas if _body(schema)["name"] in allowed]
    for schema in own:
        body = _body(schema)
        if body["name"] == "guardian_preflight":
            body["description"] = "预演本智能体的模拟账户决策；校验现金、报价、费用、股数、T+1和用户明确配置的仓位约束，不提交成交。"
            body["input_schema" if protocol == "anthropic" else "parameters"] = StockAgentDecision.model_json_schema()
        elif body["name"] == "guardian_decision_history":
            body["description"] = "按日期分页查看本智能体自己的日记，不访问其他账户；日期指实际运行日。"
    market_schema = tool_schema(protocol, "agent_market_query",
        "自由查询全市场原始行情。空sql返回字段；可用SELECT/CTE/窗口函数比较、统计、筛选daily_prices、securities、calendar、adjustments。日线截至本轮指定日期；不是工坊候选，分页可持续读取。",
        {"type": "object", "properties": {"sql": {"type": "string", "default": ""},
         "limit": {"type": "integer", "minimum": 1, "maximum": 1000, "default": 200},
         "offset": {"type": "integer", "minimum": 0, "default": 0}}, "additionalProperties": False})
    schemas = [*primary, *own, market_schema]
    research_codes = leader_research_codes(payload["portfolio"], profile["config"], payload.get("phase"))
    holdings_only = leader_holdings_only(profile["config"], payload.get("phase"))
    scope_label = "当前实际持仓" if holdings_only else "本轮观察池及现有持仓"
    scoped_reads = {"guardian_quotes", "system__market_quote", "system__market_kline"}
    if research_codes is not None:
        # 盘中不提供全市场SQL、筛选器或通用网页搜索；只保留本池个股查询及账户管理。
        local_reads = OWN_READS | {"guardian_preflight", "guardian_decision_history"}
        schemas = [schema for schema in schemas if _body(schema)["name"] in local_reads | scoped_reads
                   or _body(schema)["name"].split("__")[-1] in LEADER_STOCK_READS]
        for schema in schemas:
            body = _body(schema)
            if body["name"] in scoped_reads or body["name"].split("__")[-1] in LEADER_STOCK_READS:
                body["description"] = "仅可查询" + scope_label + "：" + ("、".join(sorted(research_codes)) or "无") + "。" + body.get("description", "")
                if body["name"] == "guardian_quotes":
                    body["description"] = "仅查询" + scope_label + "的新鲜报价和盘口，禁止查询范围外股票。"
    historical = bool(payload.get("historical_review"))
    day = str(payload.get("market_history_cutoff") or payload.get("research_date") or payload["as_of"][:10])
    # 无历史日期参数的实时外部接口不伪装成历史资料。历史日线仍可自由查询全市场。
    def supports_history(schema):
        body = _body(schema)
        name = body["name"]
        if name in OWN_READS - {"guardian_quotes"} or name in {"guardian_preflight", "guardian_decision_history", "agent_market_query", "system__web_search", "system__web_fetch"}:
            return True
        properties = (body.get("parameters") or body.get("input_schema") or {}).get("properties", {})
        return bool(DATE_FIELDS & set(properties))
    if historical:
        schemas = [schema for schema in schemas if supports_history(schema)]
    available = {_body(schema)["name"]: _body(schema) for schema in schemas}
    primary_names = {_body(schema)["name"] for schema in primary}
    audit = []

    def execute(name: str, arguments: dict) -> dict:
        checkpoint()
        if name not in available:
            return {"is_error": True, "text": "此轮未提供该接口；不能读取工坊、其他账户或用实时接口冒充历史数据。"}
        args = dict(arguments)
        if research_codes is not None and (name in scoped_reads or name.split("__")[-1] in LEADER_STOCK_READS):
            requested = []
            for field in ("code", "codes"):
                value = args.get(field)
                if isinstance(value, str):
                    requested.extend(value.split(","))
                elif isinstance(value, list):
                    requested.extend(value)
                elif value is not None:
                    return {"is_error": True, "text": "股票代码格式无效；只允许查询" + scope_label + "。"}
            if not requested or any(not isinstance(code, str) or code.strip() not in research_codes for code in requested):
                return {"is_error": True, "text": "龙头选手本轮只查询" + scope_label + "，不查询范围外股票。"}
        if historical and name not in {"agent_market_query", "guardian_decision_history"}:
            properties = (available[name].get("parameters") or available[name].get("input_schema") or {}).get("properties", {})
            for field in DATE_FIELDS & set(properties):
                value = str(args.get(field) or day)
                compact = "-" not in value and len(value) == 8
                maximum = day.replace("-", "") if compact else day
                args[field] = min(value, maximum)
        audit.append({"name": name, "arguments": args})
        if name == "agent_market_query":
            result = query_agent_market(**args, cutoff=day, checkpoint=checkpoint, deadline=deadline)
        elif name == "guardian_decision_history":
            with StockAgentStore(palace_path) as store:
                result = store.history(profile["id"], start=args.get("date"), end=args.get("date"),
                                       limit=min(100, int(args.get("limit", 20))), offset=int(args.get("offset", 0)))
        elif name == "guardian_preflight":
            decision = parse_stock_agent_decision(json.dumps(args, ensure_ascii=False), require_execution_terms=True)
            codes = list(dict.fromkeys([p["code"] for p in payload["portfolio"]["positions"]] + [o.code for o in decision.orders]))
            if research_codes is not None:
                codes = [code for code in codes if code in research_codes]
            quotes = workbench._snapshot(codes) if codes and not payload["analysis_only"] else {}
            now = datetime.now(ZoneInfo("Asia/Shanghai"))
            decision = bind_execution_references(decision, quotes, now)
            state, fills, rejects = simulate_stock_agent(payload["portfolio"], decision, quotes, now,
                                                         profile["config"], analysis_only=payload["analysis_only"], phase=payload.get("phase"))
            result = {"preflight_only": True, "ledger_committed": False, "projected_account": state,
                      "preflight_fills": fills, "rejects": rejects, "decision_with_fixed_references": decision.model_dump(mode="json")}
        elif name in allowed:
            return workbench.execute(name, args)
        elif name in primary_names and primary_execute is not None:
            return primary_execute(name, args)
        else:
            return {"is_error": True, "text": "公开行情接口暂时不可用"}
        checkpoint()
        return {"structured": result, "text": json.dumps(result, ensure_ascii=False, default=str)}

    return schemas, execute, {**source, "independent_research": True, "workshop_access": False,
                               "leader_watch_only": research_codes is not None,
                               "research_codes": sorted(research_codes) if research_codes is not None else None,
                               "historical_review": historical, "available_tools": list(available), "tool_audit": audit}
