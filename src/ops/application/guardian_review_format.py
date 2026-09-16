"""三类报告共用清晰分区；同一股票的事实与计划集中呈现。"""
from src.ops.application.guardian_decision import ACTION_LABELS
from src.ops.application.guardian_review_data import PERIOD_LABELS
from src.ops.application.guardian_review_references import current_references, reference_summary


def money(value):
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
    return dict(label=ACTION_LABELS[p['action']]+size, detail=p['trigger'], meta=f"失效条件：{p['invalidation']}\n执行时机：{p.get('timing') or '条件满足后的研判轮次'}")


def report_sections(facts, analysis):
    account, period = facts['account'], facts['period']
    positions = {p['code']: p for p in account['positions']}
    performance = {p['code']: p for p in facts['stock_performance']}
    names = dict(facts.get('stock_names', {}))
    for row in [*facts.get('strategy_reference_pool', []), *facts.get('watchlist', []), *performance.values(), *positions.values()]:
        if row.get('name'):
            names[row['code']] = row['name']
    planning = facts.get('planning_trade_date') or '后续交易日'
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
    references = reference_summary(facts)
    if references:
        sections.append(_section('本期策略选股覆盖', 'references', references))
    plans_by_code = {}
    for plan in analysis.get('plans', []):
        plans_by_code.setdefault(plan['code'], []).append(plan)
    for code in dict.fromkeys([*positions, *performance]):
        p, perf = positions.get(code), performance.get(code, {})
        stats = _stats([('期间盈亏', money(perf.get('period_pnl_cents', 0))+'元')])
        if p:
            stats = _stats([('持仓 / 可卖', f"{p['quantity']:,} / {p['available_quantity']:,}股"), ('含费成本', f"{p['average_cost']:.4f}元/股"),
                ('成本总额', money(p['cost_cents'])+'元'), ('昨收' if period=='premarket' else '收盘价', money(p['mark_price_cents'])+'元'),
                ('期间盈亏' if period!='premarket' else '浮动盈亏', money(perf.get('period_pnl_cents',p['unrealized_pnl_cents']) if period!='premarket' else p['unrealized_pnl_cents'])+'元')])
        paragraphs = list(individual.get(code, []))
        if period != 'premarket':
            paragraphs.insert(0,f"本期买入 {perf.get('buy_quantity',0):,}股 · 卖出 {perf.get('sell_quantity',0):,}股")
        stock_plans = plans_by_code.pop(code, [])
        if p and any(plan['action'] in {'sell', 'reduce', 'take_profit', 'stop_loss'} for plan in stock_plans):
            paragraphs.append('以下是按同一持仓快照制定的备选条件，不是累计卖出委托。任一成交后，其余计划股数需按最新持仓重新研判。')
            partial = {plan['quantity'] for plan in stock_plans
                       if plan['action'] in {'sell', 'reduce', 'take_profit', 'stop_loss'}
                       and plan.get('quantity') and 0 < plan['quantity'] < p['available_quantity']}
            if len(partial) == 1:
                first = next(iter(partial))
                paragraphs.append(f'例如：首笔卖{first:,}股 → 剩{p["quantity"] - first:,}股；之后若清仓，卖当时剩余可卖股数。')
        sections.append(_section(f"{names.get(code,'名称待核对')}（{code}）", 'stock', paragraphs, stats, [_plan(plan, p) for plan in stock_plans], planning))
    for code, plans in plans_by_code.items():
        sections.append(_section(f"{names.get(code,'名称待核对')}（{code}）", 'opportunity', individual.get(code,[]), plans=[_plan(p) for p in plans], plan_date=planning))
    presented = set(positions) | set(performance) | set(plans_by_code)
    for row in current_references(facts):
        code = row['code']
        if code in presented:
            continue
        paragraphs = individual.get(code, []) or ['本轮模型未给出个股评价或行动计划；这不代表策略未选出，也不代表已决定放弃。']
        evidence = [f"{s['date']} 策略信号：{s.get('reason') or '已精选'}；计划口径：{s.get('timing') or '以策略规则为准'}。" for s in row['signals']]
        sections.append(_section(f"{row['name']}（{code}）", 'opportunity', [*evidence, *paragraphs], plan_date=planning))
        presented.add(code)
    lessons = [f"{r['hypothesis']}\n验证方法：{r['validation_plan']}" for r in analysis.get('lessons',[])]
    if lessons:
        sections.append(_section('待验证经验','lessons',lessons))
    notes = operational
    if period=='premarket':
        notes.append(f"估值基于 {facts['baseline_date']} 昨收，可卖股数按今日计算。")
    if period=='daily' and not facts.get('execution_facts',{}).get('has_premarket_report'):
        notes.append('今日没有本程序盘前计划，盘中判断不视为盘前规划。')
    if period=='weekly':
        notes.append(f"按每日收盘净值采样的最大回撤 {facts['close_drawdown_pct']:.2f}%，不代表盘中最大回撤。")
    if facts.get('correction_reason'):
        notes.append('更正说明：'+facts['correction_reason'])
    notes.append('盘中计划在后续研判轮次复核；收盘确认的条件最早下一交易日执行。计划尚未下单，新买入股数遵守T+1，经验尚待验证。')
    sections.append(_section('运行记录与口径','notes',notes))
    return sections


def report_body(facts, analysis, *, compact=False):
    sections = report_sections(facts,analysis)
    lines = [f"{facts['trade_date']} · {PERIOD_LABELS[facts['period']]}" ]
    if compact:
        lines.append('｜'.join(f"{s['label']} {s['value']}" for s in sections[0]['stats']))
        for s in sections:
            if s['kind']=='stock':
                values = '｜'.join(f"{v['label']} {v['value']}" for v in s['stats'] if v['label'] in ('持仓 / 可卖','含费成本','成本总额','期间盈亏','浮动盈亏'))
                lines.append(s['heading']+'\n'+values)
        lines.extend([analysis['summary'][:160],'完整报告：设置 → 自主交易员 → 复盘与计划'])
        return '\n\n'.join(lines)
    for s in sections:
        lines.append('【'+s['heading']+'】')
        if s['stats']:
            lines.append('｜'.join(f"{v['label']} {v['value']}" for v in s['stats']))
        lines.extend(s['paragraphs'])
        if s['plans']:
            lines.append(s['plan_date']+'行动计划')
        lines.extend(f"{p['label']}：{p['detail']}\n{p['meta']}" for p in s['plans'])
    return '\n\n'.join(lines)
