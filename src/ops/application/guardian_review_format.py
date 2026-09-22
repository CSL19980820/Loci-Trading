"""三类报告共用清晰分区；同一股票的事实与计划集中呈现。"""
from src.ops.application.guardian_decision import ACTION_LABELS
from src.ops.application.guardian_review_data import PERIOD_LABELS
from src.ops.application.guardian_review_references import reference_summary
import math


def money(value):
    if not isinstance(value, (int, float)) or isinstance(value, bool) or not math.isfinite(value):
        return '—'
    return f'{value / 100:,.2f}'


def _section(heading, kind, paragraphs=None, stats=None, plans=None, plan_date=''):
    return dict(heading=heading, kind=kind, paragraphs=paragraphs or [], stats=stats or [], plans=plans or [], plan_date=plan_date)


def _stats(pairs):
    return [dict(label=label, value=value) for label, value in pairs]


def _plan(p, position=None):
    quantity = p.get('quantity')
    size = f' · {quantity:,}股' if quantity else ''
    selling = p['action'] in {'sell', 'reduce', 'take_profit', 'stop_loss'}
    if position and quantity and selling:
        available = position['available_quantity']
        if quantity == available:
            size = f' · 清仓当时剩余可卖（报告时{available:,}股）'
        elif quantity < available:
            size = f' · 卖{quantity:,}股 → 余{position["quantity"] - quantity:,}股（本项单独触发）'
    return dict(label=ACTION_LABELS[p['action']]+size, detail=(p['rationale']+'\n' if p.get('rationale') else '')+p['trigger'], meta=f"失效条件：{p['invalidation']}\n执行时机：{p.get('execution_note') or p.get('timing') or '条件满足后的研判轮次'}")


def _detail_sections(facts, analysis):
    account, period = facts['account'], facts['period']
    positions = {p['code']: p for p in account['positions']}
    performance = {p['code']: p for p in facts['stock_performance']}
    names = dict(facts.get('stock_names', {}))
    for row in [*facts.get('strategy_reference_pool', []), *facts.get('watchlist', []), *performance.values(), *positions.values()]:
        if row.get('name'):
            names[row['code']] = row['name']
    planning = facts.get('planning_trade_date') or '后续交易日'
    planning_sellable = {row['code']: row['quantity'] for row in facts.get('planning_sellable', [])}
    risk_snapshot = facts.get('risk_contracts')
    risk_positions = {row['code']: row for row in (risk_snapshot or {}).get('positions', [])}
    global_notes, individual = [], {c: [] for c in positions | performance}
    operational = list(analysis.get('operational_notes', []))
    for text in analysis.get('assessments', []):
        if text.startswith(('时点核对', '流程事实', '工程', '失败轮次')):
            operational.append(text)
            continue
        code = next((c for c in individual if text.startswith((names.get(c, '\0'), c))), None)
        (individual[code] if code else global_notes).append(text)
    for row in analysis.get('stock_reviews', []):
        individual.setdefault(row['code'], []).append(row['assessment'])
    realized = facts['period_realized_pnl_cents'] if period != 'premarket' else account['realized_pnl_cents']
    sections = [_section('账户总览', 'account', [f"{'期间' if period != 'premarket' else '累计'}已实现 {money(realized)}元 · 浮动 {money(account['unrealized_pnl_cents'])}元 · 累计盈亏 {money(account['total_pnl_cents'])}元"], _stats([
        ('总资产', money(account['equity_cents'])+'元'), ('可用现金', money(account['cash_cents'])+'元'),
        ('期间盈亏' if period != 'premarket' else '累计盈亏', money(facts['period_pnl_cents'] if period != 'premarket' else account['total_pnl_cents'])+'元'), ('期间费用' if period != 'premarket' else '累计费用', money(facts['period_fees_cents'] if period != 'premarket' else account['fees_cents'])+'元')])),
        _section({'premarket':'盘前总计划','daily':'全天复盘','weekly':'本周复盘'}[period], 'overview', [analysis['summary'], *global_notes])]
    if period == 'weekly':
        sections[0]['stats'].extend(_stats([('期初资产', money(facts['baseline_equity_cents'])+'元'), ('收盘净值回撤', f"{facts['close_drawdown_pct']:.2f}%")]))
    plans_by_code = {}
    for plan in analysis.get('plans', []):
        plans_by_code.setdefault(plan['code'], []).append(plan)
    for code in dict.fromkeys([*positions, *performance]):
        p, perf = positions.get(code), performance.get(code, {})
        stats = _stats([('期间盈亏', money(perf.get('period_pnl_cents'))+'元')])
        if p:
            stats = _stats([('持仓 / 可卖' if period == 'premarket' else '报告日持仓 / 可卖', f"{p['quantity']:,} / {p['available_quantity']:,}股"), ('含费成本', f"{p['average_cost']:.4f}元/股"),
                ('成本总额', money(p['cost_cents'])+'元'), ('昨收' if period=='premarket' else '收盘价', money(p['mark_price_cents'])+'元'),
                ('期间盈亏' if period!='premarket' else '浮动盈亏', money(perf.get('period_pnl_cents',p['unrealized_pnl_cents']) if period!='premarket' else p['unrealized_pnl_cents'])+'元')])
            if facts.get('planning_trade_date') != facts['trade_date'] and code in planning_sellable:
                stats.extend(_stats([(f'{planning}预计可卖', f'{planning_sellable[code]:,}股')]))
            if risk_snapshot is not None:
                risk = risk_positions.get(code)
                known = risk_snapshot.get('available') and risk is not None and risk['quantity'] == p['quantity']
                count = sum(row.get('status') == 'active' for row in risk.get('risk_plans', [])) if known else None
                stats.extend(_stats([('有效风险合同（快照）', f'{count}条' if count is not None else '未知')]))
        paragraphs = list(individual.get(code, []))
        stock_plans = plans_by_code.pop(code, [])
        if len(stock_plans) > 1 and any(plan['action'] in {'sell', 'reduce', 'take_profit', 'stop_loss'} for plan in stock_plans):
            paragraphs.append('不同条件分支，不是累加委托；成交后按剩余持仓重新核验。')
        planned_position = {**p, 'available_quantity': planning_sellable[code]} if p and code in planning_sellable else p
        sections.append(_section(f"{names.get(code,'名称待核对')}（{code}）", 'stock', paragraphs, stats, [_plan(plan, planned_position) for plan in stock_plans], planning))
    for code, plans in plans_by_code.items():
        sections.append(_section(f"{names.get(code,'名称待核对')}（{code}）", 'opportunity', individual.get(code,[]), plans=[_plan(p) for p in plans], plan_date=planning))
    presented = set(positions) | set(performance) | set(plans_by_code)
    # A strategy's candidate pool remains available to research, not auto-published.
    # A researched stock need not have a holding, workshop signal or action plan.
    for code, paragraphs in individual.items():
        if code not in presented and paragraphs:
            sections.append(_section(f"{names.get(code,'名称待核对')}（{code}）", 'opportunity', paragraphs, plan_date=planning))
            presented.add(code)
    if analysis.get('research_notes'):
        sections.append(_section('研究与待核验问题', 'research', analysis['research_notes']))
    statuses = {'proposed': '待验证', 'supported': '有支持证据', 'refuted': '有反证',
                'inconclusive': '尚无定论', 'corrected': '已核实纠正'}
    lessons = [f"{statuses.get(r.get('status', 'proposed'), '待验证')}：{r['hypothesis']}\n验证方法：{r['validation_plan']}" for r in analysis.get('lessons',[])]
    if lessons:
        sections.append(_section('研究发现与验证','lessons',lessons))
    if analysis.get('experience') is not None:
        from src.ledger.domain.guardian_experience import experience_text
        items = analysis['experience']
        sections.append(_section('经验沉淀更新', 'lessons', [
            f"本次保留{len(items)}条经验，{len(experience_text(items))}/1600字符；完整当前版本见账户持仓 → 经验沉淀。",
            *[f"{statuses[item['status']]}：{item['hypothesis']}\n验证方法：{item['validation_plan']}" for item in items]]))
    if operational:
        sections.append(_section('注意', 'warning', operational))
    notes = []
    if period=='premarket':
        notes.append(f"估值基于 {facts['baseline_date']} 昨收，可卖股数按今日计算。")
    if period=='weekly':
        notes.append(f"按每日收盘净值采样的最大回撤 {facts['close_drawdown_pct']:.2f}%，不代表盘中最大回撤。")
    if facts.get('correction_reason'):
        notes.append('更正说明：'+facts['correction_reason'])
    if risk_snapshot is not None:
        notes.append(f"风险合同单独核验于 {risk_snapshot['as_of']}，不由收盘成交流水推算；条件计划不代表已登记合同。"
                     if risk_snapshot.get('available') else '缺少对应时点的风险合同快照，合同数量未知，不代表零条。')
    if notes:
        sections.append(_section('数据口径','notes',notes))
    return sections


def report_sections(facts, analysis):
    """完整正文只有一份；附录只放账务与来源，不能藏关键条件。"""
    account, period = facts['account'], facts['period']
    equity = account['equity_cents']
    exposure = f"{(equity - account['cash_cents']) / equity * 100:.1f}%" if equity > 0 else '—'
    pnl = account['total_pnl_cents'] if period == 'premarket' else facts['period_pnl_cents']
    pairs = [('累计盈亏' if period == 'premarket' else '本周盈亏（含费）' if period == 'weekly' else '今日盈亏（含费）', money(pnl)+'元'),
             ('仓位', exposure), ('持仓', f"{len(account['positions'])}只")]
    if period == 'weekly':
        pairs[-1] = ('收盘净值最大回撤', f"{facts['close_drawdown_pct']:.2f}%")
    brief = [_section('账户简况', 'account', stats=_stats(pairs)),
        _section({'premarket':'盘前总计划','daily':'全天复盘','weekly':'本周复盘'}[period], 'overview', [analysis['summary']])]
    details = _detail_sections(facts, analysis)
    # _detail_sections already groups stock-specific assessments with that stock.
    # Only the remaining global assessments belong in the changes section.
    changes = [p for s in details if s['kind'] == 'overview' for p in s['paragraphs'][1:]]
    seen = {analysis['summary'], *changes}
    for row in analysis.get('highlights', []):
        if row['detail'] not in seen:
            changes.append((row['title']+'：' if row['title'] not in row['detail'] else '')+row['detail'])
            seen.add(row['detail'])
    changes = list(dict.fromkeys(p for p in changes if p and p != analysis['summary']))
    if changes:
        brief.append(_section('隔夜变化' if period == 'premarket' else '关键得失', 'decisions', changes))
    appendix, research = [], []
    for section in details:
        kind = section['kind']
        if kind == 'overview':
            continue
        section = {**section, 'paragraphs': list(dict.fromkeys(p for p in section['paragraphs'] if p))}
        if kind in {'account', 'notes'}:
            appendix.append({**section, 'detail': True})
        elif kind in {'stock', 'opportunity'}:
            if section['paragraphs'] or section['plans']:
                brief.append({**section, 'stats': [], 'detail': False})
                if section['stats']:
                    appendix.append({**section, 'kind': 'account', 'heading': section['heading']+' · 账务',
                                     'paragraphs': [], 'plans': [], 'detail': True})
            elif section['stats']:
                appendix.append({**section, 'detail': True})
        elif section['paragraphs'] or section['plans']:
            research.append({**section, 'detail': False})
    if analysis.get('next_steps'):
        heading = {'premarket':'今日行动', 'daily':'下一交易日变化', 'weekly':'下周重点'}[period]
        steps = list(dict.fromkeys(p for p in analysis['next_steps'] if p and p not in seen))
        if steps:
            brief.append(_section(heading, 'actions', steps))
    trades = []
    for trade in facts.get('trades', []):
        legacy = trade.get('origin') == 'legacy_conversion' or trade.get('quote_source') == 'legacy_conversion'
        action = '历史折算（非新成交）' if legacy else '模拟卖出' if trade['side'] == 'sell' else '模拟买入'
        trades.append(f"{trade['occurred_at']} · {trade.get('name') or trade['code']}（{trade['code']}） · {action} {trade['quantity']:,}股 × {money(trade['price_cents'])}元")
    if trades:
        appendix.append({**_section('成交回执', 'account', trades), 'detail': True})
    if 'strategy_reference_pool' in facts:
        research.append(_section('量化候选 · 近期参考', 'references', [
            '量化选股提供的参考名单，不是买入清单。列入输入不代表模型已逐股研究。',
            *reference_summary(facts),
        ]))
    updates = analysis.get('watchlist_updates', [])
    if updates:
        names = facts.get('stock_names', {})
        research.append(_section('自主观察调整', 'actions', [
            f"{names.get(u['code'], u['code'])}（{u['code']}）· {'纳入 / 继续观察' if u['action'] == 'watch' else '移除观察'}：{u['reason']}"
            + (f"\n关注条件：{u['entry_condition']}" if u.get('entry_condition') else '')
            + (f"\n退出条件：{u['exit_condition']}" if u.get('exit_condition') else '') for u in updates]))
    plans = facts.get('opening_plan_reconciliation', [])
    if plans:
        labels = {'pending': '待核验', 'unreviewed': '本轮未评估', 'waiting': '继续观察',
                  'blocked': '执行受阻', 'executed': '已执行', 'abandoned': '主动放弃', 'expired': '收盘到期未完成'}
        research.append(_section('竞价预案逐笔跟踪', 'decisions', [
            f"{p['order'].get('name') or p['order']['code']}（{p['order']['code']}）· {labels[p['status']]}\n"
            f"计划{p['order']['quantity']}股，计划金额{money(p['planned_amount_cents'])}元（价格授权估算，不含费）；"
            f"实际{p['filled_quantity']}股，成交金额{money(p['actual_gross_cents'])}元，费用{money(p['actual_fees_cents'])}元。\n"
            f"{p.get('last_reason', '等待开盘后使用新行情复核')}"
            for p in plans]))
    return brief + research + appendix


def report_body(facts, analysis, *, compact=False, detailed=False):
    if compact:
        from src.ops.application.guardian_review_digest import notification_digest
        return notification_digest(facts, analysis)
    sections = report_sections(facts, analysis)
    lines = [f"{facts['trade_date']} · {PERIOD_LABELS[facts['period']]}" ]
    for section in sections:
        if section.get('detail') and not detailed:
            continue
        lines.append('【'+section['heading']+'】')
        if section['stats']:
            lines.append('｜'.join(f"{v['label']} {v['value']}" for v in section['stats']))
        lines.extend(section['paragraphs'])
        if section['plans']:
            lines.append(f"{section['plan_date']}条件计划 · 尚未下单")
        lines.extend(f"{p['label']}：{p['detail']}\n{p['meta']}" for p in section['plans'])
    return '\n\n'.join(lines)
