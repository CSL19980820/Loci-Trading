"""仅生成复盘/计划，允许少量只读情报工具；不给报告模型交易执行入口。"""
import json
import time
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from src.ops.application.guardian_tools import agent_tools
from src.ops.application.guardian_config import REPLY_STYLE, POSITION_RULES
from src.ledger import guardian_quantity_error
from src.ops.application.guardian_evidence import EVIDENCE_RULES



class ReviewPlan(BaseModel):
    model_config = ConfigDict(extra="forbid")
    code: str = Field(pattern=r"^\d{6}$")
    action: Literal["buy", "add", "reduce", "sell", "hold", "watch", "take_profit", "stop_loss"]
    trigger: str = Field(max_length=180)
    invalidation: str = Field(max_length=140)
    quantity: int | None = Field(default=None, ge=0, strict=True)
    timing: str = Field(default="", max_length=120)


class ReviewLesson(BaseModel):
    model_config = ConfigDict(extra="forbid")
    hypothesis: str
    evidence_ids: list[str] = Field(min_length=1, max_length=8)
    validation_plan: str


class StockReview(BaseModel):
    model_config = ConfigDict(extra="forbid")
    code: str = Field(pattern=r"^\d{6}$")
    assessment: str = Field(min_length=1, max_length=240)


class ReviewAnalysis(BaseModel):
    model_config = ConfigDict(extra="forbid")
    summary: str = Field(min_length=1, max_length=400)
    assessments: list[str] = Field(default_factory=list, max_length=3)
    stock_reviews: list[StockReview] = Field(default_factory=list)
    operational_notes: list[str] = Field(default_factory=list, max_length=5)
    plans: list[ReviewPlan] = Field(default_factory=list)
    lessons: list[ReviewLesson] = Field(default_factory=list, max_length=5)


def normalize_plan_timing(analysis: dict) -> dict:
    """收盘条件的执行边界由程序给出，不能接受模型以盘中价代替收盘价。"""
    for plan in analysis.get('plans', []):
        trigger = plan['trigger']
        for intraday in ('不等收盘', '不等待收盘', '无需等待收盘', '收盘前'):
            trigger = trigger.replace(intraday, '')
        if plan.get('action') in ('reduce', 'sell', 'take_profit', 'stop_loss') and '收盘' in trigger:
            plan['timing'] = '计划日正式收盘后确认，最早在计划日之后的下一交易日开市轮次执行；另有盘中触发条件的，在盘中研判轮次独立核验。'
    return analysis


def validate_plan_quantities(analysis: dict, facts: dict) -> None:
    """条件计划复用成交股数规则，不让非法半手数量先发给用户再在成交时被拒。"""
    sellable = {p["code"]: p["quantity"] for p in facts.get("planning_sellable", [])}
    for plan in analysis.get("plans", []):
        quantity = plan.get("quantity")
        if quantity is None or plan["action"] in {"hold", "watch"}:
            continue
        selling = plan["action"] in {"sell", "reduce", "take_profit", "stop_loss"}
        error = guardian_quantity_error(plan["code"], quantity, selling, sellable.get(plan["code"], quantity))
        if error:
            raise ValueError(f"计划{plan['code']}的{quantity}股不符合申报规则：{error}；按计划日可卖股数选择合法数量，保留原条件，不改变事实")


def generate_review(store: Any, cfg: dict[str, Any], facts: dict[str, Any], *,
                    check_cancelled=None, deadline: float | None = None, palace_path: str | None = None) -> tuple[dict, dict, list]:
    from src.ai import ChatMessage, resolve_config
    from src.ops.application.guardian_completion import run_accounted_agent
    from src.ops.application.guardian_research_tools import compose_research_tools
    from src.ai.application.agent_messages import messages_from_json
    deadline = min(deadline, time.monotonic() + 900) if deadline is not None else time.monotonic() + 900
    def checkpoint(event=None):
        if check_cancelled:
            check_cancelled()
        if time.monotonic() >= deadline:
            raise TimeoutError("本次报告研究已超过执行期限，保留诊断后重新生成")
    checkpoint()
    provider = resolve_config(store, cfg["provider"], model=cfg["model"], timeout=max(0.001, deadline - time.monotonic()))
    if provider.model != cfg["model"]:
        raise ValueError("复盘所选模型已停用")
    schemas, executor = [], None
    source_evidence: list[dict] = []
    if facts["trade_date"] == facts["created_at"][:10]:
        try:
            candidates, call, _ = compose_research_tools(provider.protocol, primary_loader=agent_tools,
                payload={"portfolio": facts.get("account"), "as_of": facts["created_at"]},
                palace_path=palace_path, read_only=True, deadline=deadline)
            def tool_name(item: dict) -> str:
                return (item.get("function") or item).get("name", "")
            schemas = candidates
            allowed = {tool_name(item) for item in schemas}
            def executor(name: str, arguments: dict) -> dict:
                if name not in allowed:
                    return {"is_error": True, "text": "报告只允许只读情报工具"}
                result = call(name, arguments)
                evidence_id = f"tool:{len(source_evidence) + 1}"
                source_evidence.append({"id": evidence_id, "name": name, "arguments": arguments,
                                        "result": result.get("text", ""), "is_error": bool(result.get("is_error"))})
                return {**result, "text": json.dumps({"evidence_id": evidence_id, "result": result.get("text", "")}, ensure_ascii=False)}
        except (ValueError, RuntimeError) as exc:
            from src.ai.application.agent_execution import reraise_stop
            reraise_stop(exc)
            schemas, executor = [], None
    system = """你是自主交易员的盘前计划与复盘模块。面向用户的文字使用简体中文完整句子，字段名保持接口原样，不把字段名、证据编号或英文枚举写进叙述。
【阅读结构】summary只写全局结论，最多150字，不复述账务表。assessments只写市场与组合层面的分析，最多3条。每只股票的当日/本周回顾或盘前判断统一写入stock_reviews，不能散落到全局段落。全部动作继续用plans按代码关联，由程序把同一股票的持股、加减仓、止盈止损合并展示。工程错误、缺数据与口径放operational_notes，最多3条；待验证经验只放lessons，最多3条。每只股票的回顾不超过120字，单项计划触发不超过90字，避免同义重复和长篇堆砌。
盘前固定顺序：账户昨收→全局盘前策略→每只持仓的预案→池外机会→经验与运行说明。
日复盘固定顺序：账户收盘→全天市场/组合评价→每只股票的今日回顾及明日计划→观察机会→经验与运行说明。
周复盘固定顺序：本周账户表现→本周市场/组合评价→每只交易股票的周回顾及下周计划→下周机会→经验与运行说明。
合格个股回顾示例：买入后强势未能保持，收盘回落；次日重点核对反包逻辑是否延续。
个股名称和代码由程序生成标题，assessment正文不重复股票标题，不放Markdown链接或外部股票网址。持仓达到4只仅表示达到常态数量，盘中仍可临时到8只；不能把仍有现金的账户写成资金满仓，也不能说因此没有换仓或池外机会。
禁止写法：execution_facts显示failed_cycles=9，所以全部交易被迫延迟。
账户金额、每笔成交、期间收益和回撤由程序计算，必须服从facts，不能重新编造数字。origin=legacy_conversion是旧层数仓位经用户确认折算股数，不是新现金账户的原始精确下单；不能假装它从未由旧模型选择，也不能借“迁入”回避当前持仓亏损的复盘，损益仍全部计入账户。
premarket：结合昨日收盘、当前持仓/可卖股数、观察池、最近复盘与必要隔夜信息，提前准备买入/加仓/减仓/持股/止盈/止损/观察的条件化计划。
strategy_reference_pool中的收盘后新精选供下一交易日规划，不能反过来声称当天白天就应知道；结合active_strategies的真实规则和参数做策略总结，但它们不是交易白名单。
逐一评价本期各策略选出的股票，包括杨氏尾盘等所有已提供策略，而非只写你最想交易的几个。盘前评价上一交易日信号、日复盘评价当日信号、周复盘评价本周信号。每只至少给stock_reviews或plans；若不参与写出依据，禁止漏掉后让读者误以为没有选股结果。程序会另外列出完整策略覆盖，未评价的会明确标注。
execution_facts给出程序核实的时点、笔数与当前约束。若has_premarket_report=false，必须承认当日没有本程序盘前计划，不能把盘中判断写成盘前计划兑现。历史“观察范围拒单”是已取消的旧约束，只能作为历史工程问题，不能当成当前准入限制，也不能归纳出“入观察池后才允许买”的经验。
不要自行重新统计失败轮数或把收盘净值采样回撤说成盘中最大回撤。报告的账户数字和个股贡献已由程序列出，assessments重点解释原因，不重复堆砌账务数字。盘后资讯只用于后续计划，不能倒推当时应知道。
失败轮次的具体时点、首次成功与首次买入意图以execution_facts为准，不能把全天失败总数塞进某个早盘时段。成交时间读取occurred_at，不能拿轮次ID当成交时间。不同题材不等于收益不相关；早盘买入仍是T+1，分时建仓不能获得当天卖出纠错能力。信号有效期按各策略规则，不能统一把早于昨天的信号判为失效。
计划必须匹配现有执行能力：每5分钟决策一次，不能承诺实时成交；只有15:00收盘才能确认的信号，动作只能安排在下一交易日，不得安排闭市后卖出或假装有券商条件单。明确股数必须符合实际申报规则：普通A股整手持仓不能拆出新零股，4500股减半应明确选择2200或2300股而非2250股；已有零股可一次性卖出，或与整手一起卖出。科创板和北交所沿用对应起报与递增规则。股数未确定可用null并写清条件。
daily：逐项评价今天的实际操作、持仓表现、未成交原因及计划兑现情况；区分执行错误与正常风险，给下一交易日计划。
weekly：综合本周每日收盘净值、成交和日复盘，评价盈利、费用、收盘净值回撤和行为偏差，形成下周待验证改进。
保持进取，允许有依据的试错，但不为了活跃而强行交易。T+1、资金规则、4只常态/8只盘中上限/收盘最多4只不能修改。计划不是委托，不产生任何成交。
结合trading_preferences理解用户的交易偏好，但输出仍使用报告契约。planning_trade_date与planning_sellable给出规划时点和按T+1预计可卖股数；日/周复盘的期末可卖股数是当日口径，不能误认为下一交易日仍锁定。
lessons只写有evidence_ids支持的待验证假设，禁止把单日得失当成已验证规则或宣称已经自我进化；没有证据就留空。证据ID必须来自facts.evidence_ids或实际只读工具返回的evidence_id。
优先用已提供的事实，必要时才调用只读工具。历史报告禁止用未来数据；盘前尚未开盘，不把昨日价格冒称今日实时价。外部资讯的时间、覆盖和缺失应如实标注。
最终仅输出合法JSON，使用下列报告契约，不输出交易orders：
""" + json.dumps(ReviewAnalysis.model_json_schema(), ensure_ascii=False)
    system += "\n各行动计划基于同一报告持仓快照，是条件分支，不是累计委托。减仓/止盈的数量是本项单独触发的首笔数量；任一成交后其余旧数量失效，后续按最新剩余持仓重评。清仓按当时全部可卖，不能在先减仓后仍卖报告原总股数。\n" + POSITION_RULES + "\n" + REPLY_STYLE
    final_checks = "\n输出自检：盘前计划在08:50，应否生成与09:30之后的故障没有因果证据，缺失原因未知就写未知。不同题材不能称收益不相关；上午买入也不能当天卖出。失败、观望、旧约束拒单分别归因。经验仅做样本记录，不擅自推出同一股票一天只许一次买入意图等新限制。全局段落不重复账务数字与个股回顾，自然语言使用简体中文。"
    system += "\n" + EVIDENCE_RULES
    # 推理和正文共用输出预算；原来的8192会在多股票报告中途耗尽。
    max_tokens = provider.max_output_tokens or 328000
    prompt = json.dumps(facts, ensure_ascii=False, default=str) + final_checks
    usage = {"model": provider.model, "input_tokens": 0, "output_tokens": 0,
             "rounds": 0, "tool_calls": 0, "max_tokens": max_tokens, "attempts": [],
             "thinking_requested": cfg.get("thinking") or "provider_default"}
    result = run_accounted_agent(provider, store, usage, system=system, user_prompt=prompt,
                       tool_schemas=schemas, tool_executor=executor, max_rounds=None, max_calls_per_round=None,
                       max_tokens=max_tokens, max_tool_result_chars=None, temperature=0.2,
                       thinking=cfg.get("thinking", ""), deadline=deadline, check_cancelled=checkpoint, on_event=checkpoint)
    for attempt in range(2):
        diagnostic = {"stopped_reason": result.stopped_reason, "finish_reason": result.finish_reason,
                      "output_chars": len(result.text), "output_tokens": result.output_tokens}
        usage["attempts"].append(diagnostic)
        try:
            if result.stopped_reason != "completed":
                raise ValueError(f"复盘模型未完成：{result.stopped_reason}")
            if result.finish_reason in {"length", "max_tokens"}:
                raise ValueError(f"复盘输出预算耗尽：{result.finish_reason}，拒绝保存不完整报告")
            if result.finish_reason not in {"", "stop", "end_turn"}:
                raise ValueError(f"复盘模型未正常结束：{result.finish_reason}")
            text = result.text.strip()
            if text.startswith("```") and text.endswith("```"):
                text = text.split("\n", 1)[-1][:-3].strip()
            analysis = normalize_plan_timing(ReviewAnalysis.model_validate(json.loads(text)).model_dump())
            validate_plan_quantities(analysis, facts)
            valid_ids = set(facts["evidence_ids"]) | {e["id"] for e in source_evidence if not e.get("is_error")}
            if any(ref not in valid_ids for lesson in analysis["lessons"] for ref in lesson["evidence_ids"]):
                raise ValueError("复盘引用了不存在的证据，拒绝保存虚构经验")
            return analysis, usage, source_evidence
        except ValueError as exc:
            # 校验错误只给字段和原因，不把供应商/工具原文再写进日志。
            detail = (json.dumps(exc.errors(include_input=False, include_url=False), ensure_ascii=False)
                      if isinstance(exc, ValidationError) else str(exc))[:1500]
            diagnostic["error"] = detail
            if attempt or result.stopped_reason != "completed" or result.finish_reason not in {"", "stop", "end_turn", "length", "max_tokens"}:
                error = ValueError(f"报告生成失败（尝试{attempt + 1}次，结束原因{result.finish_reason or result.stopped_reason}）：{detail}")
                error.usage = usage
                raise error from exc
            # 保留已有事实、只读证据和推理上下文；修复阶段不能重跑工具。
            messages = messages_from_json(result.messages) or [ChatMessage(role="user", content=prompt)]
            if not messages or messages[-1].role != "assistant" or messages[-1].content != result.text:
                messages.append(ChatMessage(role="assistant", content=result.text))
            messages.append(ChatMessage(role="user", content=f"上次报告未通过完整性/JSON契约校验：{detail}。基于已有事实和工具证据重新输出一个完整JSON对象，不要续接残片，不调用工具。保留全部股票覆盖、条件与证据，精简重复叙述；经验无有效证据则留空。"))
            result = run_accounted_agent(provider, store, usage, system=system, messages=messages, max_rounds=1,
                               max_calls_per_round=0, max_tokens=max_tokens, temperature=0,
                               thinking=cfg.get("thinking", ""), deadline=deadline, check_cancelled=checkpoint, on_event=checkpoint)
    raise AssertionError("报告校验循环未返回结果")
