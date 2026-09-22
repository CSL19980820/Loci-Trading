"""工作日记的只读正文投影；不改写意图、回执、工作记忆或账户。"""
from src.ops.application.guardian_decision import ACTION_LABELS
from src.ops.application.guardian_review_format import money


def section(heading, kind, paragraphs=None, plans=None):
    return dict(heading=heading, kind=kind, paragraphs=paragraphs or [], plans=plans or [],
                stats=[], plan_date='', detail=False)


def trading_run_sections(detail: dict, *, summary: str = '', status: str = '') -> list[dict]:
    """Only public human fields; never dump provider config, tool records or raw JSON."""
    # Model orders may omit names. Resolve only from this run's saved evidence,
    # including pre-trade holdings for stocks already sold; never rewrite history.
    context = detail.get('decision_context') or {}
    names = dict(detail.get('stock_names') or {})
    for rows in (context.get('candidates'), detail.get('candidates'), detail.get('fills'),
                 (detail.get('account') or {}).get('positions'),
                 (context.get('account_before') or {}).get('watchlist'),
                 (context.get('account_before') or {}).get('positions')):
        for row in rows or []:
            code, name = str(row.get('code') or '').strip(), str(row.get('name') or '').strip()
            if code and name and name != code:
                names[code] = name

    def stock_identity(row):
        code, name = str(row.get('code') or '').strip(), str(row.get('name') or '').strip()
        if not name or name == code:
            name = names.get(code, '')
        return f'{name}（{code}）' if name and code else name or code or '名称待核对'

    title = str(detail.get('summary') or detail.get('analysis') or summary or '').strip()
    if not title and status == 'running':
        title = '正在核验资料，判断尚未完成。'
    result = [section('本轮判断', 'overview', [title])] if title else []
    if detail.get('error'):
        result.append(section('注意', 'warning', [str(detail['error'])]))
    elif status in {'failed', 'expired', 'interrupted'}:
        result.append(section('注意', 'warning', ['本轮未正常完成；已有成交以实际回执为准。']))
    fills = detail.get('fills') or []
    if detail.get('analysis_only') and not fills:
        result.append(section('阶段', 'notes', ['本阶段只做研判，不执行模拟交易。']))
    for item in detail.get('decisions') or []:
        action = item.get('action', '')
        label = ACTION_LABELS.get(action, action)
        if action in {'buy', 'add', 'sell', 'reduce', 'take_profit', 'stop_loss'}:
            label = '拟'+label
        quantity = item.get('quantity')
        if quantity:
            label += f' · {quantity:,}股'
        identity = stock_identity(item)
        lines = [str(item['reason'])] if item.get('reason') else []
        conditions = []
        for key, name in (('holding_plan', '持有条件'), ('take_profit_plan', '止盈条件'),
                          ('stop_loss_plan', '止损条件'), ('exit_today_plan', '当日退出条件'),
                          ('entry_condition', '参与条件'), ('exit_condition', '撤销观察条件')):
            if item.get(key):
                conditions.append(name+'：'+str(item[key]))
        if conditions:
            lines.append('\n'.join(conditions))
        result.append(section(identity+' · '+label, 'decisions', lines or [label]))
    if fills:
        lines = []
        for fill in fills:
            name = stock_identity(fill)
            legacy = fill.get('origin') == 'legacy_conversion' or fill.get('quote_source') == 'legacy_conversion'
            action = '历史折算（非新成交）' if legacy else '已模拟'+ACTION_LABELS.get(fill.get('action') or fill.get('side'), '成交')
            at = fill.get('occurred_at') or fill.get('at')
            line = (str(at)+' · ' if at else '')+name+' · '+action
            if fill.get('quantity') is not None:
                line += f" {fill['quantity']:,}股 × {money(fill.get('price_cents'))}元"
                if fill.get('after_quantity') is not None:
                    line += f"；成交后剩余{fill['after_quantity']:,}股"
            else:
                line += f"；历史分层记录 {fill.get('before_layers', '—')} → {fill.get('after_layers', '—')}层"
            lines.append(line)
        result.append(section('实际模拟成交回执', 'actions', lines))
    for key, heading in (('rejects', '未成交与拒单原因'), ('deferred', '暂未执行')):
        lines = [f"{stock_identity(r)}：{r.get('reason') or '执行状态待核验'}" for r in detail.get(key) or []]
        if lines:
            result.append(section(heading, 'warning', lines))
    research = str(detail.get('research_plan') or '').strip()
    if research and research != title:
        result.append(section('后续计划与待核验', 'research', [research]))
    if not result and detail.get('outcome') == 'no_action':
        result.append(section('本轮结果', 'overview', ['本轮无交易。']))
    return result
