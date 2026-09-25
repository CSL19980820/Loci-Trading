"""Evidence-backed planning and reviews; reports never execute trades."""
from copy import deepcopy
from datetime import date
import json
import re
from threading import RLock
import time
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from src.ledger import guardian_quantity_error
from src.ops.application.guardian_compute import CALCULATE_TOOL, calculate, calculation_schema
from src.ops.application.guardian_tools import agent_tools
from src.ops.application.guardian_review_history import REVIEW_HISTORY_TOOL, ReviewHistory
from src.ops.application.guardian_review_prompts import REPORT_PROMPT_VERSION, review_system
from src.ledger.domain.guardian_experience import ExperienceEntry, experience_text, validate_experience
from src.ops.application.guardian_output import load_json_response, failed_response


class ReviewPlan(BaseModel):
    model_config = ConfigDict(extra="forbid")
    code: str = Field(pattern=r"^\d{6}$")
    action: Literal["buy", "add", "reduce", "sell", "hold", "watch", "take_profit", "stop_loss"]
    rationale: str = Field(min_length=1, description="本轮自主选择该动作或方法的研究依据；股票被量化选中只说明来源，不是采纳理由")
    trigger: str
    invalidation: str
    quantity: int | None = Field(default=None, ge=0, strict=True)
    timing: str = ""
    confirmation: Literal["unspecified", "intraday", "planning_close"] = Field(default="unspecified",
        description="仅本次触发依赖计划日正式收盘时选择planning_close；昨日收盘价不是该条件")
    execution_note: str = Field(default="", description="由程序补充的执行时间边界；模型可留空")


class ReviewLesson(BaseModel):
    model_config = ConfigDict(extra="forbid")
    hypothesis: str = Field(min_length=1)
    evidence_ids: list[str] = Field(default_factory=list)
    validation_plan: str = Field(min_length=1)
    status: Literal["proposed", "supported", "refuted", "inconclusive", "corrected"] = "proposed"


class StockReview(BaseModel):
    model_config = ConfigDict(extra="forbid")
    code: str = Field(pattern=r"^\d{6}$")
    assessment: str = Field(min_length=1)


class ReviewHighlight(BaseModel):
    model_config = ConfigDict(extra="forbid")
    title: str = Field(min_length=1, description="判断的短标题，不是章节用途说明")
    detail: str = Field(min_length=1, description="一句必要依据和重要限定，不重复summary或assessments")


class ReviewWatchUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    code: str = Field(pattern=r"^\d{6}$")
    action: Literal["watch", "unwatch"]
    reason: str = Field(min_length=1)
    entry_condition: str = ""
    exit_condition: str = ""


class ReviewAnalysis(BaseModel):
    model_config = ConfigDict(extra="forbid")
    summary: str = Field(min_length=1, description="一句全局结论，不抄账户数据或候选池")
    highlights: list[ReviewHighlight] = Field(default_factory=list, description="通常为空；只写其他字段未表达的独立要点")
    notification_summary: str = Field(default="", description="从同一正文提炼一两句话，保留关键限定，不新增判断或声称计划已成交；可留空。其他文字字段也应简练。")
    assessments: list[str] = Field(default_factory=list)
    next_steps: list[str] = Field(default_factory=list, description="行动或变化简报，保留对象、触发和失效条件")
    stock_reviews: list[StockReview] = Field(default_factory=list)
    operational_notes: list[str] = Field(default_factory=list)
    research_notes: list[str] = Field(default_factory=list, description="有进展的精炼发现、必要证据引用与待核验问题；不写长篇研究流水或重复其他字段")
    watchlist_updates: list[ReviewWatchUpdate] = Field(default_factory=list, description="自主观察名单的增量修改：watch纳入或继续保留，unwatch移除；保存成功即生效，不产生买卖。无变化为空。对象不限于量化候选。")
    plans: list[ReviewPlan] = Field(default_factory=list)
    lessons: list[ReviewLesson] = Field(default_factory=list)
    experience: list[ExperienceEntry] | None = Field(default=None, max_length=8,
        description="长期经验的完整替换列表，最多8条且含编号、状态、验证方法及引用合计1600字符。周复盘必须归集每日发现后给出；日复盘可修订、合并、撤回，null保持原库，[]明确清空。沿用稳定id；premarket必须null。")


def validate_brief(analysis: dict, period: str) -> dict:
    """Compatibility entry: measure presentation without rejecting or truncating it."""
    visible = [analysis['summary'], *analysis.get('assessments', []),
               *analysis.get('next_steps', []), *[r['hypothesis'] for r in analysis.get('lessons', [])]]
    return {"period": period, "visible_characters": sum(map(len, visible)),
            "lesson_count": len(analysis.get("lessons", [])), "presentation_only": True}


def normalize_plan_timing(analysis: dict) -> dict:
    """Annotate explicit confirmation semantics, preserving the model's original text."""
    result = deepcopy(analysis)
    for plan in result.get('plans', []):
        plan['execution_note'] = ''
        if plan.get('confirmation') == 'planning_close' and plan.get('action') not in {'hold', 'watch'}:
            plan['execution_note'] = '计划日正式收盘后确认，最早在计划日之后的下一交易日开市轮次执行；届时仍需重新核验。'
    return result


def validate_plan_quantities(analysis: dict, facts: dict) -> None:
    """Use existing settlement quantity rules for conditional plans."""
    sellable = {p["code"]: p["quantity"] for p in facts.get("planning_sellable", [])}
    for plan in analysis.get("plans", []):
        quantity = plan.get("quantity")
        if quantity is None or plan["action"] in {"hold", "watch"}:
            continue
        selling = plan["action"] in {"sell", "reduce", "take_profit", "stop_loss"}
        error = guardian_quantity_error(plan["code"], quantity, selling, sellable.get(plan["code"], quantity))
        if error:
            raise ValueError(f"计划{plan['code']}的{quantity}股不符合申报规则：{error}；按计划日可卖股数选择合法数量，保留原条件，不改变事实")


_BOARD_GUARD_FAILURE = re.compile(
    r"(?:前置|板块|权限).{0,10}(?:校验|拦截).{0,10}(?:失效|失败|未生效|未.{0,5}拦截)"
    r"|未被(?:板块|权限|前置).{0,5}(?:校验)?拦截"
    r"|(?:不可|禁止).{0,5}(?:买入|加仓).{0,12}(?:却|仍).{0,8}(?:成交|买入)"
)
_PRICE_RANGE = re.compile(r"(?<![\d.])(\d+(?:\.\d+)?)\s*[-~—–至]\s*(\d+(?:\.\d+)?)(?![\d.])")
_PRICE_POINT = re.compile(r"(?:冲至|涨至|跌破|触及|到达|升至|下破)\s*(\d+(?:\.\d+)?)")
_DAY_REFERENCE = re.compile(r"(?<!\d)(?:(20\d{2})[-/])?(\d{1,2})[-/](\d{1,2})(?!\d)")
_AUCTION_VOID_CAUSE = re.compile(r"09:30.{0,15}(?:失败|错误).{0,12}(?:作废|失效|取消)")
_AUCTION_CAUSE_DENIAL = re.compile(
    r'(?:不能|不可|不应|无法|未能)(?:据此)?(?:判定|认定|断定|判断|证明|说明|确认|认为|判|因)'
    r'|不会因|并非|不是|不意味着|不代表|未必|尚未证实'
)


def _review_claims(analysis: dict) -> list[str]:
    claims = [analysis.get('summary', ''), *analysis.get('assessments', []),
              *analysis.get('operational_notes', []), *analysis.get('research_notes', [])]
    claims.extend(row.get('assessment', '') for row in analysis.get('stock_reviews', []) if isinstance(row, dict))
    claims.extend(row.get('hypothesis', '') for field in ('lessons', 'experience')
                  for row in analysis.get(field) or [] if isinstance(row, dict))
    return [str(claim) for claim in claims if claim]


def validate_historical_board_claims(analysis: dict, facts: dict) -> None:
    """A fill alone cannot prove that a later board restriction failed earlier."""
    buys = [row for row in facts.get('trades', []) if row.get('side') == 'buy']
    if not buys:
        return
    counts: dict[str, int] = {}
    for row in buys:
        code = row.get('code', '')
        if not code:
            continue
        counts[code] = counts.get(code, 0) + 1
    proven: dict[str, int] = {}
    for cycle in facts.get('cycles', []):
        policy = cycle.get('position_policy') or {}
        prefixes = policy.get('buyable_code_prefixes')
        if not isinstance(prefixes, list) or not prefixes:
            continue
        for fill in cycle.get('fills', []):
            code = fill.get('code', '')
            if fill.get('side') == 'buy' and code in counts and not any(code.startswith(p) for p in prefixes):
                proven[code] = proven.get(code, 0) + 1
    unproven = {code for code, count in counts.items() if proven.get(code, 0) < count}
    if not unproven:
        return
    for claim in _review_claims(analysis):
        if (_BOARD_GUARD_FAILURE.search(claim)
                and any(code in claim or code[:3] in claim for code in unproven)):
            raise ValueError('历史买入前置板块校验失效的断言缺少对应轮次的禁买规则快照；成交只能证明当时已撮合，不能把当前权限倒用于历史。请改为按当时规则证据评价。')


def _prior_dates(text: str, today: str) -> set[str]:
    current = date.fromisoformat(today)
    found = set()
    for match in _DAY_REFERENCE.finditer(text):
        try:
            value = date(int(match[1] or current.year), int(match[2]), int(match[3]))
        except ValueError:
            continue
        if value < current:
            found.add(value.isoformat())
    return found


def _dated_claim_sections(text: str, today: str) -> list[tuple[str, str]]:
    """Bind a dated narrative to its own span, not every date in the paragraph."""
    references = []
    for match in _DAY_REFERENCE.finditer(text):
        try:
            value = date(int(match[1] or today[:4]), int(match[2]), int(match[3]))
        except ValueError:
            continue
        references.append((match, value.isoformat()))
    sections = []
    for index, (match, day) in enumerate(references):
        if day >= today:
            continue
        start = match.start() if index else 0
        end = references[index + 1][0].start() if index + 1 < len(references) else len(text)
        sections.append((day, text[start:end]))
    return sections


def _asserts_auction_void_cause(text: str) -> bool:
    for sentence in re.split(r'[。！？\n]', text):
        for time_ref in re.finditer('09:30', sentence):
            match = _AUCTION_VOID_CAUSE.match(sentence, time_ref.start())
            if match is None:
                continue
            # Scope denial to this assertion. A denial in an earlier clause must
            # not exempt a later affirmative assertion in the same paragraph.
            prefix = re.split(r'[，,；;]|但是|但|然而', sentence[:match.start()])[-1]
            if not _AUCTION_CAUSE_DENIAL.search(prefix[-18:] + match.group()):
                return True
    return False


def validate_prior_auction_handoff_claims(analysis: dict, facts: dict) -> None:
    """A failed 09:30 cycle cannot void an 09:25 plan that was never saved."""
    day = facts.get('trade_date')
    if not day:
        return
    auctions = {row['slot'][:16]: row for row in facts.get('prior_auction_cycles', []) if row.get('slot')}
    for claim in _review_claims(analysis):
        for prior_day, section in _dated_claim_sections(claim, day):
            if (not _asserts_auction_void_cause(section)
                    or not any(word in section for word in ('09:25', '竞价', 'deferred', '意图'))):
                continue
            opening = auctions.get(f'{prior_day}T09:25')
            if opening is not None and opening.get('opening_plans') == 0:
                raise ValueError(f'{prior_day} 09:25轮没有保存opening_plans；09:30失败不能使未结转的竞价意图作废。请分别描述09:25 deferred与09:30原始回执。')


def _raw_prior_receipts(facts: dict, sources: list[dict]) -> dict[str, set[str]]:
    by_day: dict[str, set[str]] = {}
    for row in facts.get('prior_auction_cycles', []):
        if row.get('slot') and row.get('id'):
            by_day.setdefault(row['slot'][:10], set()).add(row['id'])
    for row in facts.get('cycles', []):
        if row.get('slot') and row.get('id'):
            by_day.setdefault(row['slot'][:10], set()).add(row['id'])
    for receipt in sources:
        if receipt.get('is_error') or not receipt.get('id'):
            continue
        name = str(receipt.get('name', '')).split('__')[-1]
        args = receipt.get('arguments') or {}
        try:
            result = json.loads(str(receipt.get('result') or '{}'))
        except ValueError:
            continue
        if not isinstance(result, dict):
            continue
        items = result.get('items')
        if not isinstance(items, list):
            continue
        if name == 'guardian_decision_history':
            day = str(args.get('date') or '')
            if day and any(str(item.get('slot', '')).startswith(day)
                           for item in items if isinstance(item, dict)):
                by_day.setdefault(day, set()).add(receipt['id'])
        elif name == REVIEW_HISTORY_TOOL and 'facts' in (args.get('fields') or []):
            for item in items:
                if (isinstance(item, dict) and (item.get('facts') or {}).get('cycles')
                        and item.get('date')):
                    by_day.setdefault(item['date'], set()).add(receipt['id'])
    return by_day


def _cited_auction_slots(day: str, refs: list[str], facts: dict, sources: list[dict]) -> set[str]:
    slots = {row['slot'][:16] for row in facts.get('prior_auction_cycles', [])
             if row.get('id') in refs and row.get('slot', '').startswith(day + 'T')}
    for receipt in sources:
        if receipt.get('is_error') or receipt.get('id') not in refs:
            continue
        name = str(receipt.get('name', '')).split('__')[-1]
        if name not in {'guardian_decision_history', REVIEW_HISTORY_TOOL}:
            continue
        try:
            result = json.loads(str(receipt.get('result') or '{}'))
        except ValueError:
            continue
        items = result.get('items') if isinstance(result, dict) else None
        if not isinstance(items, list):
            continue
        for item in items:
            if not isinstance(item, dict):
                continue
            rows = ((item.get('facts') or {}).get('cycles', [])
                    if name == REVIEW_HISTORY_TOOL else [item])
            for row in rows:
                if isinstance(row, dict) and str(row.get('slot', '')).startswith(day + 'T'):
                    slots.add(row['slot'][:16])
    return slots


def validate_cross_day_verified_claims(analysis: dict, facts: dict, sources: list[dict]) -> None:
    """A prior report's analysis is not a receipt for a verified prior-cycle cause."""
    day = facts.get('trade_date')
    if not day:
        return
    receipts = _raw_prior_receipts(facts, sources)
    claims = [(str(row.get('hypothesis') or ''), row.get('evidence_ids') or [])
              for field in ('lessons', 'experience') for row in analysis.get(field) or []
              if isinstance(row, dict) and row.get('status') == 'corrected']
    claims.extend((str(claim), None) for claim in _review_claims({**analysis, 'lessons': [], 'experience': None})
                  if '已核实' in claim or '已证实' in claim)
    for claim, refs in claims:
        for prior_day in _prior_dates(claim, day):
            # A dated market high/low is supported by market evidence, not an
            # account cycle. Require cycle receipts only for dated execution claims.
            dated = []
            for section_day, section in _dated_claim_sections(claim, day):
                if section_day != prior_day:
                    continue
                reference = _DAY_REFERENCE.search(section)
                after = section[reference.end():] if reference else section
                dated.append(re.split(r'[。；;，,\n]', after, maxsplit=1)[0])
            if not any(re.search(r'\d{2}:\d{2}|轮次|竞价|deferred|回执|买入|买单|卖出|成交|加仓|减仓|开仓|平仓', text)
                       for text in dated):
                continue
            available = receipts.get(prior_day, set())
            if not available or refs is not None and not available.intersection(refs):
                raise ValueError(f'{prior_day}轮次的已核实因果缺少本轮原始轮次回执引用；previous_reviews和旧经验不是原始证据。请读取prior_auction_cycles或历史决策/报告facts，无法核实时降为待验证。')
            if refs is not None and any(
                    section_day == prior_day and '09:25' in section and '09:30' in section
                    for section_day, section in _dated_claim_sections(claim, day)):
                auction_ids = {row['id'] for row in facts.get('prior_auction_cycles', [])
                               if row.get('slot', '')[:10] == prior_day
                               and row.get('slot', '')[11:16] in {'09:25', '09:30'}}
                required = {f'{prior_day}T09:25', f'{prior_day}T09:30'}
                if len(auction_ids) == 2 and not required.issubset(_cited_auction_slots(prior_day, refs, facts, sources)):
                    raise ValueError(f'{prior_day}竞价到开盘的已核实因果须同时引用09:25和09:30原始轮次。')


def validate_contract_plan_claims(analysis: dict, facts: dict) -> None:
    """Do not label a different price range as an installed contract trigger."""
    snapshot = facts.get('risk_contracts') or {}
    if not snapshot.get('available'):
        return
    contracts = {row['code']: [p['contract'] for p in row.get('risk_plans', [])
                               if p.get('status') == 'active' and isinstance(p.get('contract'), dict)]
                 for row in snapshot.get('positions', [])}
    for plan in analysis.get('plans', []):
        text = '\n'.join(str(plan.get(key) or '') for key in ('rationale', 'trigger', 'invalidation'))
        for clause in re.split(r'[。；\n]', text):
            marker = clause.find('按合同')
            if marker < 0 or not any(word in clause[marker:] for word in ('了结', '止盈', '止损', '卖出', '减仓', '清仓', '执行', '触发')):
                continue
            before = clause[:marker]
            ranges = list(_PRICE_RANGE.finditer(before))
            points = list(_PRICE_POINT.finditer(before))
            if ranges and (not points or ranges[-1].end() >= points[-1].end()):
                low, high = (float(value) for value in ranges[-1].groups())
            elif points:
                low = high = float(points[-1].group(1))
            else:
                continue
            kinds = ({'stop_loss'} if '止损' in clause or '跌破' in before else
                     {'take_profit'} if any(word in clause for word in ('了结', '止盈', '冲至', '涨至')) else
                     {'stop_loss', 'take_profit'})
            active = [p for p in contracts.get(plan['code'], []) if p.get('action') in kinds]
            if not any(low - 0.005 <= float(p.get('trigger_price', -1)) <= high + 0.005 for p in active):
                raise ValueError(f"计划{plan['code']}把{low:g}-{high:g}元描述为按已安装合同执行，但有效合同无此触发价；请核对risk_contracts，提前卖出应写为届时重新研判并提交新意图。")


def validate_lessons(analysis: dict, valid_ids: set[str]) -> None:
    for lesson in analysis.get("lessons", []):
        refs = lesson.get("evidence_ids", [])
        if any(ref not in valid_ids for ref in refs):
            raise ValueError("复盘引用了不存在的证据，拒绝保存虚构经验")
        if lesson.get("status", "proposed") != "proposed" and not refs:
            raise ValueError("假设进展需要真实证据；尚无证据的新想法可标记proposed并说明验证方法")


def validate_experience_update(analysis: dict, facts: dict, valid_ids: set[str],
                               sources: list[dict] | None = None) -> None:
    items = analysis.get('experience')
    period = facts.get('period')
    if period == 'weekly' and items is None:
        raise ValueError('周复盘必须归集daily_learning，输出完整experience列表；无可保留经验时输出[]')
    if period == 'premarket' and items is not None:
        raise ValueError('盘前仅参考经验，不改写经验库，请将experience设为null')
    old = {item['id']: item for item in facts.get('experience', {}).get('items', [])}
    if items is None:
        try:
            validate_historical_board_claims({'experience': list(old.values())}, facts)
            validate_prior_auction_handoff_claims({'experience': list(old.values())}, facts)
        except ValueError:
            raise ValueError('已有经验含未经原始轮次证明的历史归因；本次须输出更正后的完整经验列表，不能用null沿用。') from None
        return
    changed = [item for item in items if isinstance(item, dict) and old.get(item.get('id')) != item]
    # Report independent violations together. Otherwise three repair attempts can
    # be spent discovering three different constraints without ever fixing the last.
    errors = []
    for check in (
        lambda: validate_historical_board_claims({'experience': items}, facts),
        lambda: validate_prior_auction_handoff_claims({'experience': items}, facts),
        lambda: validate_cross_day_verified_claims({'experience': changed}, facts, sources or []),
    ):
        try:
            check()
        except ValueError as error:
            errors.append(str(error))
    try:
        normalized = validate_experience(items)
    except ValueError as error:
        detail = str(error)
        normalized = []
        from src.ledger.domain.guardian_experience import MAX_EXPERIENCE_CHARACTERS
        if '字符' in detail:
            normalized = [ExperienceEntry.model_validate(item).model_dump() for item in items]
            size = len(experience_text(normalized))
            detail += (f'；当前实际{size}字符，超出{size - MAX_EXPERIENCE_CHARACTERS}字符。'
                       '总额包含证据编号，不能只数正文；合并重复内容或撤回低价值条目，'
                       '本日完整发现已保留在报告中，无需全部进入长期经验。')
        errors.append(detail)
    for item in normalized:
        # Unchanged entries retain their original evidence. New claims need current
        # evidence, not unscoped tool IDs copied from another report.
        if old.get(item['id']) == item:
            continue
        try:
            validate_lessons({'lessons': [item]}, valid_ids)
        except ValueError as error:
            errors.append(str(error))
    if errors:
        raise ValueError('；'.join(dict.fromkeys(errors)))


class ForwardPlan(BaseModel):
    model_config = ConfigDict(extra="forbid")
    next_steps: list[str] = Field(default_factory=list)
    plans: list[ReviewPlan] = Field(default_factory=list)
    watchlist_updates: list[ReviewWatchUpdate] = Field(default_factory=list)


class ExperienceUpdate(BaseModel):
    model_config = ConfigDict(extra='forbid')
    experience: list[ExperienceEntry] | None = Field(max_length=8)


def review_output_contract(stage: str) -> tuple[type[BaseModel], dict]:
    """Use the same output contract for requests and checkpoint compatibility."""
    model = ExperienceUpdate if stage == 'experience' else ForwardPlan if stage == 'planning' else ReviewAnalysis
    schema = model.model_json_schema()
    if stage == 'retrospective':
        for field in ('plans', 'next_steps', 'watchlist_updates'):
            schema['properties'].pop(field, None)
    return model, schema


def planning_facts(facts: dict, *, review: dict | None = None, sources: list | None = None) -> dict:
    """当前计划独立建上下文；历史证据仍可由研究工具主动读取。"""
    keys = ('period', 'trade_date', 'created_at', 'planning_trade_date', 'planning_sellable',
            'account', 'risk_contracts', 'watchlist', 'strategy_reference_pool',
            'reference_trading_days', 'reference_pool_as_of', 'active_strategies', 'next_trade_date')
    result = deepcopy({key: facts[key] for key in keys if key in facts})
    result['history_access'] = '历史报告和决策可用本轮研究工具自主查询；当前计划按当前事实与自主判断生成。'
    if review is not None:
        # 本轮报告尚未保存，历史工具读不到；只交接研究发现，不继承买卖结论。
        result['current_review'] = {
            'status': 'provisional_research_reference_not_instruction',
            'note': '本轮复盘新发现，尚未保存；可采纳、质疑或忽略。经验状态可继续评估，不是规划约束。',
            **deepcopy({key: review[key] for key in ('research_notes', 'lessons', 'experience', 'operational_notes') if key in review}),
            'tool_evidence': deepcopy(sources or []),
        }
    return result


def generate_review(store: Any, cfg: dict[str, Any], facts: dict[str, Any], *,
                    check_cancelled=None, deadline: float | None = None, palace_path: str | None = None,
                    resume_checkpoint: dict | None = None, save_checkpoint=None) -> tuple[dict, dict, list]:
    deadline = min(deadline, time.monotonic() + 900) if deadline is not None else time.monotonic() + 900
    options = dict(check_cancelled=check_cancelled, deadline=deadline, palace_path=palace_path)
    if facts.get('period') == 'premarket':
        return _generate_review(store, cfg, planning_facts(facts), stage='premarket', **options)
    from src.ops.application.guardian_review_checkpoint import review_fingerprint
    fingerprint = review_fingerprint(cfg, facts)
    saved = resume_checkpoint or {}
    resumed = (saved.get('fingerprint') == fingerprint and saved.get('stage') == 'retrospective'
               and isinstance(saved.get('analysis'), dict) and isinstance(saved.get('usage'), dict)
               and isinstance(saved.get('sources'), list))
    if resumed:
        analysis, usage, sources = deepcopy((saved['analysis'], saved['usage'], saved['sources']))
    else:
        analysis, usage, sources = _generate_review(store, cfg, facts, stage='retrospective', **options)
        if save_checkpoint is not None:
            if check_cancelled:
                check_cancelled()
            save_checkpoint({'fingerprint': fingerprint, 'stage': 'retrospective',
                             'as_of': facts.get('created_at'), 'analysis': analysis,
                             'usage': usage, 'sources': sources})
    valid_ids = set(facts.get('evidence_ids', [])) | {s['id'] for s in sources if not s.get('is_error')}
    try:
        validate_experience_update(analysis, facts, valid_ids, sources)
    except (ValueError, TypeError) as error:
        usage['experience_validation'] = {'error': str(error), 'original_experience': deepcopy(analysis.get('experience'))}
        repair_facts = {**facts, 'evidence_ids': sorted(valid_ids),
                        'experience_repair': {'error': str(error), 'original': deepcopy(analysis.get('experience'))},
                        'current_review': planning_facts(facts, review=analysis, sources=sources)['current_review']}
        patch, repair_usage, repair_sources = _generate_review(store, cfg, repair_facts, stage='experience', **options)
        analysis['experience'] = patch['experience']
        sources = [*sources, *repair_sources]
        usage['experience_repair'] = repair_usage
        for key in ('input_tokens', 'output_tokens', 'rounds', 'tool_calls'):
            usage[key] = usage.get(key, 0) + repair_usage.get(key, 0)
        if save_checkpoint is not None:
            save_checkpoint({'fingerprint': fingerprint, 'stage': 'retrospective',
                             'as_of': saved.get('as_of') if resumed else facts.get('created_at'),
                             'analysis': analysis, 'usage': usage, 'sources': sources})
    try:
        plan, plan_usage, plan_sources = _generate_review(store, cfg, planning_facts(facts, review=analysis, sources=sources), stage='planning', **options)
    except BaseException as exc:
        exc.usage = {'review': usage, 'planning': getattr(exc, 'usage', {})}
        raise
    analysis.update(plan)
    total = {**usage, 'stages': {'retrospective': usage, 'planning': plan_usage}}
    total['checkpoint_resumed'] = resumed
    if resumed:
        total['retrospective_as_of'] = saved.get('as_of')
    for key in ('input_tokens', 'output_tokens', 'rounds', 'tool_calls'):
        total[key] = usage.get(key, 0) + plan_usage.get(key, 0)
    return analysis, total, [*sources, *plan_sources]


def _generate_review(store: Any, cfg: dict[str, Any], facts: dict[str, Any], *,
                    check_cancelled=None, deadline: float | None = None, palace_path: str | None = None, stage: str) -> tuple[dict, dict, list]:
    from src.ai import ChatMessage, resolve_config
    from src.ai.application.agent_messages import messages_from_json
    from src.ai.application.agent_execution import reraise_stop
    from src.ops.application.guardian_completion import run_accounted_agent
    from src.ops.application.guardian_research_context import ResearchContext
    from src.ops.application.guardian_research_tools import compose_research_tools

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
    protocol = getattr(provider, "protocol", "openai_compatible")
    period = facts.get("period", "daily")
    archive = ResearchContext()
    history = ReviewHistory(palace_path=palace_path, as_of=facts["created_at"],
                            trade_date=facts["trade_date"], exclude_key=f"{period}:{facts['trade_date']}")
    schemas, external = [], None
    source_status: dict[str, Any] = {"historical_report": facts["trade_date"] != facts["created_at"][:10]}
    if not source_status["historical_report"]:
        try:
            schemas, external, source = compose_research_tools(protocol, primary_loader=agent_tools,
                payload={"portfolio": facts.get("account"), "as_of": facts["created_at"],
                         "account_basis": "reconstructed_from_trades", "risk_contracts": facts.get("risk_contracts")},
                palace_path=palace_path, read_only=True, deadline=deadline)
            source_status.update(source)
        except (ValueError, RuntimeError, OSError) as exc:
            reraise_stop(exc)
            source_status["discovery_error"] = f"{type(exc).__name__}: {exc}"
    # Historical boundaries remove live data, not computation over existing evidence.
    local_names = {"guardian_context_read", REVIEW_HISTORY_TOOL, CALCULATE_TOOL}
    schemas = [s for s in schemas if (s.get("function") or s).get("name") not in local_names]
    external_names = {(s.get("function") or s)["name"] for s in schemas}
    schemas.extend([archive.schema(protocol), history.schema(protocol), calculation_schema(protocol)])
    source_evidence: list[dict] = []
    evidence_lock = RLock()

    def executor(name: str, arguments: dict) -> dict:
        if name not in local_names | external_names:
            return {"is_error": True, "text": "报告只允许本轮已注册的只读研究工具"}
        # Worker threads do not use the job thread's SQLite connection.
        if time.monotonic() >= deadline:
            raise TimeoutError("本次报告工具已超过执行期限")
        try:
            if name == "guardian_context_read":
                result = archive.read(arguments)
            elif name == REVIEW_HISTORY_TOOL:
                result = history.read(arguments)
            elif name == CALCULATE_TOOL:
                result = {"text": json.dumps(calculate(arguments["expression"]), ensure_ascii=False)}
            else:
                result = external(name, arguments)
        except Exception as exc:
            reraise_stop(exc)
            result = {"is_error": True, "text": f"{type(exc).__name__}: {exc}"}
        text = str(result.get("text", ""))
        with evidence_lock:
            evidence_id = f"{stage + ':' if stage in ('planning', 'experience') else ''}tool:{len(source_evidence) + 1}"
            source_evidence.append({"id": evidence_id, "name": name, "arguments": deepcopy(arguments),
                                   "result": text, "is_error": bool(result.get("is_error"))})
        visible: Any = text
        if len(text) > 80000 and name != "guardian_context_read":
            visible = archive.store(text, f"{evidence_id}:{name}", preview=1200)
        return {"is_error": bool(result.get("is_error")),
                "text": json.dumps({"evidence_id": evidence_id, "result": visible,
                                    "seconds_remaining": max(0, round(deadline - time.monotonic(), 1))}, ensure_ascii=False)}

    model_facts = {k: v for k, v in facts.items() if k != "trading_preferences"}
    if 'current_review' in model_facts:
        handoff = deepcopy(model_facts['current_review'])
        evidence = handoff.pop('tool_evidence', [])
        if evidence:
            handoff['tool_evidence'] = archive.store(evidence, '本轮复盘研究原始回执', preview=0)
        model_facts['current_review'] = handoff
    memory = facts.get('experience') or {}
    from src.ops.application.guardian_memory import MEMORY_NOTE
    for field in ('daily_learning', 'current_plans', 'watchlist'):
        if field in model_facts:
            model_facts[field] = deepcopy(model_facts[field])
    model_facts['historical_material_note'] = MEMORY_NOTE
    if 'account' in model_facts:
        model_facts['account'] = deepcopy(model_facts['account'])
    retained_memory, disputed_memory = [], []
    for item in memory.get('items', []):
        try:
            validate_historical_board_claims({'experience': [item]}, facts)
            validate_prior_auction_handoff_claims({'experience': [item]}, facts)
        except ValueError:
            disputed_memory.append(item.get('id', ''))
        else:
            retained_memory.append(item)
    model_facts['experience'] = {'revision': memory.get('revision', 0),
                                 'text': experience_text(retained_memory) if disputed_memory else memory.get('text', ''),
                                 'disputed_historical_policy_ids': disputed_memory,
                                 'note': '争议项因缺少成交时的禁买规则快照未作为已有结论输入；本轮须修正或撤回，不能用null沿用。' if disputed_memory else ''}
    model_facts['previous_reviews'] = [
        {**report, 'analysis': deepcopy({k: v for k, v in (report.get('analysis') or {}).items() if k != 'experience'})}
        for report in facts.get('previous_reviews', [])]
    cycles = model_facts.get("cycles")
    if isinstance(cycles, list):
        # 保留每个轮次的定位信息；账户/计划/回执原文只存一次，按路径精确回读。
        # 不修改facts：报告保存和历史审计继续使用完整原始轮次。
        model_facts["cycles"] = {
            "count": len(cycles), "source": archive.store(cycles, "报告期间完整轮次证据", preview=0),
            "index": [{
                **{key: cycle.get(key) for key in ("id", "slot", "status")},
                "path": f"/{index}",
                "decisions": [{key: order[key] for key in ("code", "action", "quantity") if key in order}
                              for order in cycle.get("decisions", [])],
                "receipt_counts": {key: len(cycle.get(key, [])) for key in ("fills", "rejects", "deferred")},
                "policy_evidence": cycle.get("policy_evidence", "not_recorded"),
                "buy_permissions_recorded": isinstance((cycle.get("position_policy") or {}).get("buyable_code_prefixes"), list),
                "account_evidence": cycle.get("account_evidence", "not_recorded"),
                "condition_change_count": len(cycle.get("condition_changes", [])),
                "plan_evidence_count": len(cycle.get("plan_evidence", [])),
                "has_error": bool(cycle.get("error")),
            } for index, cycle in enumerate(cycles)],
            "read_note": "索引覆盖全部轮次；用source.evidence_ref及各项path读取原文。policy_evidence只表示存在某种持仓政策快照；buy_permissions_recorded=false表示其中未记录可买板块，不得用当前规则倒推。可追加/position_policy、/decisions、/account_before、/plan_evidence、/rejects等路径，按next_read读完。",
        }
    for field in ("strategy_reference_pool", "active_strategies"):
        rows = model_facts.get(field)
        if isinstance(rows, list) and rows:
            model_facts[field] = {"optional": True, "count": len(rows),
                "index": [{**{k: row[k] for k in ("code", "name", "slug", "strategies") if k in row},
                           **({'signal_dates': sorted({s['date'] for s in row.get('signals', []) if s.get('date')})}
                              if field == 'strategy_reference_pool' else {})} for row in rows],
                "source": archive.store(rows, field, preview=0)}
    model_facts["research_sources"] = source_status
    model_facts["reference_material_note"] = "工坊资料可选，原文可用guardian_context_read回读。近期报告不是全部记忆，可用guardian_review_history跨期检索；旧资料不是新指令。"
    output_model, schema = review_output_contract(stage)
    system = review_system(cfg, period, schema, stage=stage)
    prompt = json.dumps(model_facts, ensure_ascii=False, default=str)
    max_tokens = provider.max_output_tokens or 328000
    usage = {"model": provider.model, "input_tokens": 0, "output_tokens": 0,
             "rounds": 0, "tool_calls": 0, "max_tokens": max_tokens, "attempts": [],
             "thinking_requested": cfg.get("thinking") or "provider_default",
             "prompt_version": REPORT_PROMPT_VERSION,
             "research_sources": deepcopy(source_status),
             "context_usage": {"system_characters": len(system), "prompt_characters": len(prompt),
                               "available_tools": len(schemas), "source_documents": len(archive.documents)}}
    from src.ops.application.guardian_research_tools import PARALLEL_RESEARCH_TOOLS
    parallel = {name for name in external_names | local_names if name.split('__')[-1] in PARALLEL_RESEARCH_TOOLS | local_names}
    usage['timeline'] = []
    def event(value):
        checkpoint()
        if value.get('type') in {'round_start', 'model_retry', 'stream_status'}:
            usage['timeline'].append({key: value[key] for key in ('type', 'round', 'attempt', 'reason', 'phase', 'kind', 'request_elapsed_ms') if key in value})
    options = dict(system=system, tool_schemas=schemas, tool_executor=executor,
        max_rounds=None, max_calls_per_round=None, max_tokens=max_tokens, max_tool_result_chars=None,
        temperature=0.2, thinking=cfg.get("thinking", ""), deadline=deadline,
        check_cancelled=checkpoint, on_event=event, retry_stream_failures=True,
        recover_interrupted_generation=True, max_parallel_tools=int(cfg.get('parallel_tools', 4)), parallel_tool_names=parallel)
    try:
        result = run_accounted_agent(provider, store, usage, user_prompt=prompt, **options)
        for attempt in range(3):
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
                raw = load_json_response(result.text)
                # Memory is independently validated/repaired after preserving the completed analysis.
                body = {**raw, 'experience': None} if stage == 'retrospective' else raw
                analysis = normalize_plan_timing(output_model.model_validate(body).model_dump())
                if stage == 'retrospective':
                    analysis['experience'] = raw.get('experience')
                if len({u["code"] for u in analysis.get("watchlist_updates", [])}) != len(analysis.get("watchlist_updates", [])):
                    raise ValueError("同一股票只能有一个观察名单决定")
                validate_plan_quantities(analysis, facts)
                if stage == 'planning':
                    validate_contract_plan_claims(analysis, facts)
                elif stage == 'retrospective':
                    narrative = {**analysis, 'experience': None}
                    validate_historical_board_claims(narrative, facts)
                    validate_prior_auction_handoff_claims(narrative, facts)
                    validate_cross_day_verified_claims(narrative, facts, source_evidence)
                with evidence_lock:
                    valid_ids = set(facts.get("evidence_ids", [])) | {e["id"] for e in source_evidence if not e.get("is_error")}
                    if stage != 'planning':
                        validate_lessons(analysis, valid_ids)
                        if stage != 'retrospective':
                            validate_experience_update(analysis, facts, valid_ids, source_evidence +
                                list((facts.get('current_review') or {}).get('tool_evidence') or []))
                    saved_sources = deepcopy(source_evidence)
                if stage == 'retrospective':
                    for field in ('plans', 'next_steps', 'watchlist_updates'):
                        if analysis.get(field):
                            raise ValueError('本阶段只评价已发生的决策；未来计划由独立的规划阶段生成')
                usage['stage'] = stage
                usage["presentation"] = (validate_brief(analysis, period) if stage not in ('planning', 'experience')
                                         else {'plan_count': len(analysis.get('plans', []))})
                return analysis, usage, saved_sources
            except ValueError as exc:
                detail = (json.dumps(exc.errors(include_input=False, include_url=False), ensure_ascii=False)
                          if isinstance(exc, ValidationError) else str(exc))[:1500]
                diagnostic["error"] = detail
                failed_response(diagnostic, result.text)
                if attempt >= 2 or result.stopped_reason != "completed" or result.finish_reason not in {"", "stop", "end_turn", "length", "max_tokens"}:
                    raise ValueError(f"报告生成失败（尝试{attempt + 1}次，结束原因{result.finish_reason or result.stopped_reason}）：{detail}") from exc
                messages = messages_from_json(getattr(result, "messages", [])) or [ChatMessage(role="user", content=prompt)]
                if not messages or messages[-1].role != "assistant" or messages[-1].content != result.text:
                    messages.append(ChatMessage(role="assistant", content=result.text))
                messages.append(ChatMessage(role="user", content=f"上次报告未通过完整性或数据契约校验：{detail}。修正后输出完整JSON，不续接残片。保留有效研究与条件；需要时仍可调用本轮只读工具核实或回读证据，不必重复全部研究。"))
                result = run_accounted_agent(provider, store, usage, messages=messages, **options)
    except BaseException as exc:
        with evidence_lock:
            usage["tool_evidence"] = deepcopy(source_evidence)
        exc.usage = usage
        raise
    raise AssertionError("报告校验循环未返回结果")
