"""独立研究工具与猎隼候选边界；仅猎隼可读其候选来源定义，不执行工坊。"""
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
from src.ops.application.falcon_candidates import falcon_research_codes, falcon_research_scope, read_falcon_strategy

SYSTEM_READS = {"web_search", "web_fetch", "market_quote", "market_kline", "market_status"}
OWN_READS = {"guardian_account_read", "guardian_runtime", "guardian_quotes", "guardian_calculate", "guardian_scenario"}
PRIVATE_NAMES = ("account", "portfolio", "journal", "position", "guardian", "watchlist", "strategy", "workshop", "candidate", "research_catalog", "research_profile")
DATE_FIELDS = {"date", "trade_date", "end_date", "endDate", "as_of"}
LEADER_STOCK_READS = {"kline", "minute_data", "auction_data", "valuation_snapshot", "financial_summary",
                      "shareholder_structure", "stock_event_calendar", "unlock_events", "margin_trading",
                      "northbound_holdings", "intraday_main_flow"}
FALCON_CONTEXT_READS = {"system__market_status"}
CODE_FIELDS = {"code", "codes", "stock_code", "stock_codes", "symbol", "symbols", "security_code", "ts_code"}


def _body(schema: dict) -> dict:
    return schema.get("function") or schema


def stock_agent_tools(protocol: str, *, profile: dict, payload: dict, palace_path: str,
                      deadline: float, checkpoint):
    is_falcon = profile["config"].get("kind") == "falcon"
    candidate_scope = copy.deepcopy(payload.get("candidate_scope") or {})
    research_scope = falcon_research_scope(payload) if is_falcon else candidate_scope
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
    research_codes = (falcon_research_codes(payload) if is_falcon else
                      leader_research_codes(payload["portfolio"], profile["config"], payload.get("phase")))
    holdings_only = leader_holdings_only(profile["config"], payload.get("phase"))
    scope_label = ("系统已产出候选及现有持仓" if is_falcon else
                   "当前实际持仓" if holdings_only else "本轮观察池及现有持仓")
    scoped_reads = {"guardian_quotes", "system__market_quote", "system__market_kline"}
    if research_codes is not None:
        # 盘中不提供全市场SQL、筛选器或通用网页搜索；只保留本池个股查询及账户管理。
        local_reads = OWN_READS | {"guardian_preflight", "guardian_decision_history"}
        schemas = [schema for schema in schemas if _body(schema)["name"] in local_reads | scoped_reads
                   or _body(schema)["name"].split("__")[-1] in LEADER_STOCK_READS
                   or (is_falcon and _body(schema)["name"] in FALCON_CONTEXT_READS)]
        for schema in schemas:
            body = _body(schema)
            if body["name"] in scoped_reads or body["name"].split("__")[-1] in LEADER_STOCK_READS:
                body["description"] = "仅可查询" + scope_label + "：" + ("、".join(sorted(research_codes)) or "无") + "。" + body.get("description", "")
                if body["name"] == "guardian_quotes":
                    body["description"] = "仅查询" + scope_label + "的新鲜报价和盘口，禁止查询范围外股票。"
    if is_falcon:
        # 允许读取已存在的选股定义以质疑评分，不提供筛选/预览/回测执行能力。
        schemas.extend([
            tool_schema(protocol, "falcon_candidates_read", "分页读取本轮完整系统候选及来源、评分、判分证据；不会重新选股。明确落选只供研究，不授权买入。",
                        {"type": "object", "properties": {"offset": {"type": "integer", "minimum": 0, "default": 0},
                         "limit": {"type": "integer", "minimum": 1, "maximum": 500, "default": 100}}, "additionalProperties": False}),
            tool_schema(protocol, "falcon_strategy_read", "只读本轮候选来源策略/技能的公式、源码、参数与说明，供提出可验证的优化建议；不执行筛选、不修改策略。历史复盘只返回当时候选证据。",
                        {"type": "object", "properties": {"slug": {"type": "string"}}, "required": ["slug"], "additionalProperties": False}),
            tool_schema(protocol, "falcon_market_context", "读取截至允许日期的市场涨跌广度、成交额与行业聚合环境；不返回个股或榜单，不接受筛选SQL，不产生新候选。",
                        {"type": "object", "properties": {"days": {"type": "integer", "minimum": 1, "maximum": 20, "default": 5}}, "additionalProperties": False}),
        ])
        if not payload.get("historical_review"):
            schemas.append(tool_schema(protocol, "falcon_market_emotion",
                "读取当前系统盘面情绪线路的市场聚合统计及来源时点，不返回上游个股/热点榜单；缺失或陈旧明确标注，不发掘新股票。",
                {"type": "object", "properties": {}, "additionalProperties": False}))
    historical = bool(payload.get("historical_review"))
    day = str(payload.get("market_history_cutoff") or payload.get("research_date") or payload["as_of"][:10])
    # 无历史日期参数的实时外部接口不伪装成历史资料。历史日线仍可自由查询全市场。
    def supports_history(schema):
        body = _body(schema)
        name = body["name"]
        if name in OWN_READS - {"guardian_quotes"} or name in {"guardian_preflight", "guardian_decision_history", "agent_market_query", "system__web_search", "system__web_fetch", "falcon_candidates_read", "falcon_strategy_read", "falcon_market_context"}:
            return True
        properties = (body.get("parameters") or body.get("input_schema") or {}).get("properties", {})
        return bool(DATE_FIELDS & set(properties))
    if historical:
        schemas = [schema for schema in schemas if supports_history(schema)]
        if is_falcon:
            current_account_reads = {"guardian_account_read", "guardian_runtime", "guardian_preflight", "guardian_scenario"}
            schemas = [schema for schema in schemas if _body(schema)["name"] not in current_account_reads]
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
            for field in CODE_FIELDS if is_falcon else ("code", "codes"):
                value = args.get(field)
                if isinstance(value, str):
                    requested.extend(value.split(","))
                elif isinstance(value, list):
                    requested.extend(value)
                elif value is not None:
                    return {"is_error": True, "text": "股票代码格式无效；只允许查询" + scope_label + "。"}
            if not requested or any(not isinstance(code, str) or code.strip() not in research_codes for code in requested):
                return {"is_error": True, "text": ("猎隼" if is_falcon else "龙头选手") + "本轮只查询" + scope_label + "，不查询范围外股票。"}
        if historical and name not in {"agent_market_query", "guardian_decision_history"}:
            properties = (available[name].get("parameters") or available[name].get("input_schema") or {}).get("properties", {})
            for field in DATE_FIELDS & set(properties):
                value = str(args.get(field) or day)
                compact = "-" not in value and len(value) == 8
                maximum = day.replace("-", "") if compact else day
                args[field] = min(value, maximum)
        audit.append({"name": name, "arguments": args})
        if name == "falcon_candidates_read":
            rows = research_scope.get("candidates") or []
            offset, limit = max(0, int(args.get("offset", 0))), max(1, min(500, int(args.get("limit", 100))))
            result = {**{key: value for key, value in research_scope.items() if key != "candidates"},
                      "items": copy.deepcopy(rows[offset:offset + limit]), "total": len(rows), "offset": offset,
                      "limit": limit, "next_offset": offset + limit if offset + limit < len(rows) else None}
        elif name == "falcon_market_emotion":
            from src.ops.application.falcon_market_context import read_falcon_market_emotion
            if args:
                return {"is_error": True, "text": "盘面情绪不接受个股、榜单或筛选参数。"}
            result = read_falcon_market_emotion(as_of=payload["as_of"], checkpoint=checkpoint, deadline=deadline)
        elif name == "falcon_market_context":
            from src.ops.application.falcon_market_context import read_falcon_market_context
            if set(args) - {"days"}:
                return {"is_error": True, "text": "市场环境仅接受days，不能传入股票代码或市场筛选SQL。"}
            result = read_falcon_market_context(cutoff=day, days=args.get("days", 5), checkpoint=checkpoint, deadline=deadline)
        elif name == "falcon_strategy_read":
            try:
                result = read_falcon_strategy(str(args.get("slug") or ""), research_scope, historical_review=historical)
            except ValueError as exc:
                return {"is_error": True, "text": str(exc)}
        elif name == "agent_market_query":
            result = query_agent_market(**args, cutoff=day, checkpoint=checkpoint, deadline=deadline)
        elif name == "guardian_decision_history":
            with StockAgentStore(palace_path) as store:
                requested_day = str(args.get("date") or "")[:10] or None
                end_day = min(requested_day or day, str(payload.get("research_date") or day)) if is_falcon and historical else requested_day
                start_day = min(requested_day, end_day) if requested_day and end_day else requested_day
                cutoff = str(payload.get("research_cutoff") or payload["as_of"]) if is_falcon and historical else None
                result = store.history(profile["id"], start=start_day, end=end_day, cutoff=cutoff,
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
                                                         profile["config"], analysis_only=payload["analysis_only"], phase=payload.get("phase"),
                                                         candidate_codes=candidate_scope.get("candidate_codes", []) if is_falcon else None,
                                                         auto_observe_codes=candidate_scope.get("auto_observe_codes", []) if is_falcon else None)
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

    return schemas, execute, {**source, "independent_research": True, "workshop_access": is_falcon, "workshop_execution": False,
                               "leader_watch_only": research_codes is not None and not is_falcon,
                               "system_candidates_only": is_falcon,
                               "candidate_codes": candidate_scope.get("candidate_codes", []) if is_falcon else None,
                               "research_codes": sorted(research_codes) if research_codes is not None else None,
                               "historical_review": historical, "available_tools": list(available), "tool_audit": audit}
