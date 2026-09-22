"""交易员当轮输入留痕和租户内历史取证；不以事后行情补造决策理由。"""
from __future__ import annotations

from copy import deepcopy
from datetime import date, datetime, time
import re
from typing import Any
from zoneinfo import ZoneInfo

from src.ledger import guardian_account_at, guardian_available_quantity, guardian_position_policy

TZ = ZoneInfo("Asia/Shanghai")
HISTORY_TOOL = "guardian_decision_history"
EVIDENCE_RULES = """【决策归因的证据边界】
回答为什么买、没买、加仓或卖出时，先查对应日期、股票和轮次的原始决策。咨询可用guardian_decision_history按日期、时段、股票分页查询；total和next_offset表示还有记录，不能只看最近几轮就称早盘原文不存在。
逐股reason、entry_condition和全局analysis是当时模型的判断，不是程序规则或经独立核验的行情。只有rejects中对应意图的拒绝记录，才证明该意图被程序拦截；没有提交买单时，不得把模型的“需额度”“不追高”说成程序拒单。
当前规则仅用于当前和未来，不回填历史。历史持仓额度读取当轮position_policy；未记录就明确规则快照缺失，不能用今天的提示词、页面文案、复盘或成交流水推定当时完整规则。账户快照区分研判前与成交后。
failed_cycles只统计failed，expired_cycles单独统计中断过期；failed为零不等于全天没有工程中断，两者均不能证明其他正常轮次没有作出判断。
按时间列出原始理由、条件变化及实际动作；未记录逐股理由就标明缺失，不补写“选择性放弃”等动机。输入中有该股票仅证明资料已提供，不证明模型读过所有行情；只有当时工具回执才能支持当时已取到某数据。
事后分时可评价决策质量，但不能冒充当时看到的数据；局部分钟、竞价成交或尾部分时不能证明整个早盘条件满足或不满足。放量、站稳等未量化条件应说明口径不完整，不能仅凭上涨就判已满足。
优先纠正与原始记录矛盾的旧答复。允许自主偏离策略，不能因为事后上涨就认定必须机械执行信号。事实、当时观点、事后评价和证据缺口分开表达。"""

OPPORTUNITY_RULES = """【可追溯决策】
对你本轮实际选定的重点机会记录动作和简短reason，不要求覆盖参考池或先处理旧观察。已经研究后决定等待时说明真实依据、条件及证据缺口；没有研究的对象不伪装成条件未满足或主动放弃。
修改entry_condition时说明真实判断依据：可以是新证据，也可以是重新理解已有证据或纠正旧判断。涉及市场强弱、净流入、放量和站稳等事实时注明比较口径与时点；不无依据追改条件，也不把旧条件固化成不可变规则。
修改持有、止盈、止损、当日退出计划或风险合同时，在reason中说明变更原因。文本条件计划不等于已安装的风险合同，提交合同不等于安装成功，安装也不等于成交；以落账状态及回执核实。文本计划空字符串保留原值，risk_plans为null保留、[]明确撤回。
逐股记录只保存本轮真实判断；未评价的候选由程序标记未记录，不能在复盘时补成主动放弃。"""


def decision_context(payload: dict[str, Any]) -> dict[str, Any]:
    as_of = datetime.fromisoformat(payload["as_of"])
    state = payload["portfolio"]
    return deepcopy({"version": 1, "as_of": payload["as_of"],
                     "account_before": state,
                     "position_policy": guardian_position_policy(state, as_of),
                     "candidates": payload.get("candidates", []),
                     "preopen_plan": payload.get("preopen_plan"),
                     "review_phase": payload.get("review_phase", "intraday"),
                     "pending_opening_plans": payload.get("pending_opening_plans", []),
                     "experience": payload.get("experience", ""),
                     "analysis_only": payload.get("analysis_only", False)})


def research_activity(payload: dict[str, Any], receipts: list[dict[str, Any]],
                      orders: list[dict[str, Any]] | None = None) -> dict[str, Any]:
    """描述实际工具请求及观察意图，不设配额，也不把返回的整份榜单算成已研究。"""
    account = payload.get("portfolio") or {}
    held = {row["code"] for row in account.get("positions", [])}
    watched = {row["code"] for row in account.get("watchlist", [])}
    references = {row["code"] for row in payload.get("candidates", []) if row.get("signals")}
    requested: set[str] = set()
    calls = []
    for index, receipt in enumerate(receipts):
        arguments = receipt.get("arguments") or {}
        codes: set[str] = set()
        for key in ("code", "codes", "symbol", "symbols"):
            value = arguments.get(key)
            values = value if isinstance(value, list) else [value]
            for item in values:
                if isinstance(item, str) and (match := re.fullmatch(r"(?:sh|sz|bj)?([0-9]{6})", item, re.I)):
                    codes.add(match[1])
        requested.update(codes)
        calls.append({"receipt_index": index, "name": receipt.get("name", ""),
                      "ok": bool(receipt.get("ok")), "requested_codes": sorted(codes)})
    intents = {row["code"] for row in orders or [] if row.get("action") == "watch"}
    return {"version": 1, "reference_count": len(references), "self_watch_count_before": len(watched),
            "tool_call_count": len(receipts), "failed_tool_call_count": sum(not call["ok"] for call in calls),
            "requested_codes": sorted(requested), "outside_workshop_requested_codes": sorted(requested - references),
            "outside_initial_context_requested_codes": sorted(requested - references - held - watched),
            "watch_intent_codes": sorted(intents), "new_watch_intent_codes": sorted(intents - watched),
            "calls": calls,
            "meaning": "仅统计工具参数明确请求的代码；无代码的全市场或主题搜索见calls及原始回执。"
                       "请求不等于取数成功或完成研究，观察意图不等于已落账；未统计到代码不证明未探索。"}


def _plan_evidence(result: dict[str, Any], saved: dict[str, Any], code: str) -> list[dict[str, Any]]:
    """只比对原始输入与提议，不由无拒单或单笔成交推导计划已落账。"""
    account = saved.get("account_before")
    positions = account.get("positions") if isinstance(account, dict) else None
    rows = []
    fields = ("holding_plan", "take_profit_plan", "stop_loss_plan", "exit_today_plan", "risk_plans")
    for index, order in enumerate(result.get("decisions", [])):
        if (code and order.get("code") != code) or order.get("action") in ("watch", "unwatch"):
            continue
        position = next((p for p in positions or [] if p.get("code") == order.get("code")), None)
        # 同股多意图不能仅凭股票代码把一笔拒单或成交归给某项计划。
        receipts = {kind: [row for row in result.get(kind, [])
                           if all(row.get(key) == order.get(key) for key in ("code", "action", "quantity"))]
                    for kind in ("fills", "rejects", "deferred")}
        comparisons = []
        for field in fields:
            if field not in order:
                continue
            proposed = order[field]
            preserve = proposed is None if field == "risk_plans" else not proposed
            before_known = position is not None and field in position
            before = position.get(field) if position is not None else None
            comparable = before
            if field == "risk_plans" and isinstance(before, list):
                comparable = [p.get("contract", p) if isinstance(p, dict) else p for p in before]
            operation = "preserve" if preserve else "withdraw" if field == "risk_plans" and proposed == [] else "replace"
            comparisons.append({"field": field,
                         "before": deepcopy(before), "after": deepcopy(proposed),
                         "before_evidence": "recorded_before_research" if before_known else
                             "not_held_before_research" if isinstance(positions, list) and position is None else "not_recorded",
                         "operation": operation,
                         "changed": False if preserve else proposed != comparable if before_known else None})
        if comparisons:
            rows.append({"code": order.get("code"), "order_index": index,
                         "recorded_reason": order.get("reason", ""), "fields": comparisons,
                         "related_receipts": deepcopy(receipts),
                         "receipt_matching": "code_action_quantity_only_not_unique_order_confirmation",
                         "evidence_kind": "proposal_not_installation_or_execution",
                         "note": "order_index定位未按股票过滤的原始decisions；before为研判前快照，不推算同股中间状态。关联回执不证明计划已落账。"})
    return rows


def cycle_evidence(cycle: dict[str, Any], code: str = "", *, include_inputs: bool = False) -> dict[str, Any]:
    result = cycle["result"]
    saved = result.get("decision_context") or {}
    candidates = saved.get("candidates", result.get("candidates", []))
    orders = result.get("decisions", [])
    selected = [d for d in orders if not code or d.get("code") == code]
    inputs = [c for c in candidates if not code or c.get("code") == code]
    # 对应股票没有订单只表示未记录逐股决策，不替模型发明放弃原因。
    assessment_codes = list(dict.fromkeys([c["code"] for c in inputs] + [d["code"] for d in selected]))
    assessments = [{"code": c, "status": "recorded" if any(d["code"] == c for d in selected) else "not_recorded"}
                   for c in assessment_codes]
    changes = []
    for item in inputs:
        previous = (item.get("watch") or {}).get("entry_condition")
        for order in selected:
            current = order.get("entry_condition")
            if item["code"] == order["code"] and previous and current and current != previous:
                changes.append({"code": item["code"], "before": previous, "after": current,
                                "recorded_reason": order.get("reason", "")})
    plans = _plan_evidence(result, saved, code)
    changes.extend({**{key: plan[key] for key in ("code", "order_index", "recorded_reason", "evidence_kind")},
                    **{key: field[key] for key in ("field", "before", "after")}}
                   for plan in plans for field in plan["fields"]
                   if field["operation"] != "preserve" and field["changed"] is not False)
    return {"id": f"cycle:{cycle['slot']}", "slot": cycle["slot"], "status": cycle["status"],
            "analysis": result.get("analysis"), "decisions": selected,
            "fills": result.get("fills", []), "rejects": result.get("rejects", []),
            "deferred": result.get("deferred", []), "error": result.get("error"),
            "other_trade_intents": [d for d in orders if code and d.get("code") != code and d.get("quantity", 0) > 0],
            "position_policy": saved.get("position_policy"),
            "policy_evidence": "recorded_before_research" if saved.get("position_policy") else "not_recorded",
            "account_before": saved.get("account_before"),
            "account_evidence": "recorded_before_research" if saved.get("account_before") else "not_recorded",
            "input_candidates": inputs if include_inputs else [
                {"code": c["code"], "name": c.get("name", ""), "signals": [
                    {k: s[k] for k in ("id", "date", "created_at", "timing", "strategy_slug", "strategy_revision") if k in s}
                    for s in c.get("signals", [])]} for c in inputs],
            "input_detail": "full" if include_inputs else "summary",
            "input_evidence_note": "输入默认只列代码及信号时点；核对完整指标和原始条件请按code并设include_inputs=true查询。所有原始输入均保留。",
            "candidate_assessments": assessments, "condition_changes": changes, "plan_evidence": plans,
            "interpretation": "analysis和reason是当轮观点；rejects才是程序拒绝回执。未记录原因不等于主动放弃。"}


def consultation_day(question: str, today: str) -> str:
    match = re.search(r"(\d{4})[-年](\d{1,2})[-月](\d{1,2})(?:日)?", question)
    if match:
        try:
            return date(*map(int, match.groups())).isoformat()
        except ValueError:
            pass
    return today


def decision_history(ledger: Any, *, day: str, code: str = "", start_time: str = "00:00",
                     end_time: str = "23:59", offset: int = 0, limit: int = 5,
                     include_inputs: bool = False) -> dict[str, Any]:
    date.fromisoformat(day)
    if code and not re.fullmatch(r"\d{6}", code):
        raise ValueError("股票代码须为六位数字")
    start, end = time.fromisoformat(start_time), time.fromisoformat(end_time)
    if start > end or offset < 0 or not 1 <= limit <= 10:
        raise ValueError("历史查询时段或分页参数无效")
    rows = sorted(ledger.cycles_between(day, day), key=lambda c: c["slot"])
    rows = [c for c in rows if start <= datetime.fromisoformat(c["slot"]).astimezone(TZ).time() <= end]
    trades = ledger.all_trades(day)
    items = []
    for cycle in rows[offset:offset + limit]:
        item = cycle_evidence(cycle, code, include_inputs=include_inputs)
        if item["account_before"] is None:
            stamp = datetime.fromisoformat(cycle["slot"])
            before = [t for t in trades if datetime.fromisoformat(t["occurred_at"]) < stamp]
            try:
                state = guardian_account_at(before, day, initial_cents=ledger.state()["initial_capital_cents"])
                item["account_before"] = {"cash_cents": state["cash_cents"], "positions": [
                    {**{k: p.get(k) for k in ("code", "name", "quantity", "cost_cents")},
                     "available_quantity": guardian_available_quantity(p, day)}
                    for p in state["positions"]]}
                item["account_evidence"] = "reconstructed_from_trades_before_slot"
            except ValueError as exc:
                item["account_error"] = str(exc)
        items.append(item)
    report = ledger.report("premarket", day)
    return {"date": day, "code": code, "total": len(rows), "offset": offset, "items": items,
            "next_offset": offset + limit if offset + limit < len(rows) else None,
            "premarket_plan": {"id": report["report_key"], "analysis": report["result"].get("analysis")}
            if report and report["status"] == "success" else None,
            "evidence_boundary": "仅当前租户的实际保存记录。历史规则未留快照时不作推定；记录提到的行情是当时观点，不是本次重新核验的行情。"}


def history_schema(protocol: str) -> dict[str, Any]:
    from src.ai.application.tool_schema import tool_schema
    return tool_schema(protocol, HISTORY_TOOL, "查询本租户指定日期的交易员原始决策、股票理由、条件变更、研判前账户、已记录规则及拒单回执；按next_offset读取后续轮次。",
        {"type": "object", "properties": {"date": {"type": "string", "description": "YYYY-MM-DD"},
         "code": {"type": "string", "description": "可选六位股票代码"},
         "start_time": {"type": "string", "description": "HH:MM，含起点"},
         "end_time": {"type": "string", "description": "HH:MM，含终点"},
         "include_inputs": {"type": "boolean", "description": "默认false提供输入摘要；核对完整原始信号时设true，建议同时指定code"},
         "offset": {"type": "integer", "minimum": 0}, "limit": {"type": "integer", "minimum": 1, "maximum": 10}},
         "required": ["date"], "additionalProperties": False})
