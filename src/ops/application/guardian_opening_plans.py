"""09:25预案与开盘执行的逐笔接续；复用轮次事务保存，不把计划当挂单。"""
from copy import deepcopy
from datetime import datetime
from decimal import Decimal, ROUND_HALF_UP

from src.ops.application.guardian_decision import ACTION_LABELS, TRADE_ACTIONS

TERMINAL = {'executed', 'abandoned', 'expired'}


def build_opening_plans(decision, slot):
    plans = []
    for index, order in enumerate(decision.orders):
        if order.action not in TRADE_ACTIONS or order.quantity <= 0:
            continue
        terms = order.execution
        field = 'reference_price' if terms and terms.reference_price else ('max_price' if order.action in {'buy', 'add'} else 'min_price')
        price = getattr(terms, field, None) if terms else None
        amount = int((Decimal(str(price)) * order.quantity * 100).quantize(Decimal('1'), rounding=ROUND_HALF_UP)) if price else None
        plans.append({'id': f'{slot}:{index}', 'source_slot': slot, 'order': order.model_dump(mode='json'),
                      'status': 'pending', 'planned_amount_cents': amount, 'amount_basis': field if price else 'unknown',
                      'filled_quantity': 0, 'actual_gross_cents': 0, 'actual_fees_cents': 0,
                      'expires_at': slot[:10] + 'T15:00:00+08:00', 'history': []})
    return plans


def fold_opening_plans(cycles, as_of):
    plans = {}
    for cycle in cycles:
        result = cycle['result']
        for plan in result.get('opening_plans', []):
            plans.setdefault(plan['id'], deepcopy(plan))
        for update in result.get('opening_plan_updates', []):
            plan = plans.get(update['plan_id'])
            if not plan or plan['status'] in TERMINAL:
                continue
            plan['history'].append({'slot': cycle['slot'], **deepcopy(update)})
            plan.update(status=update['status'], last_reason=update['reason'], last_review_slot=cycle['slot'])
            for key in ('filled_quantity', 'actual_gross_cents', 'actual_fees_cents'):
                plan[key] += update.get(key, 0)
    for plan in plans.values():
        if plan['status'] not in TERMINAL and as_of >= datetime.fromisoformat(plan['expires_at']):
            plan.update(status='expired', last_reason='当日计划收盘到期未完成；不是模型主动放弃')
    return list(plans.values())


def pending_opening_plans(ledger, now):
    return [{key: value for key, value in p.items() if key != 'history'}
            for p in fold_opening_plans(ledger.opening_plan_cycles(now.date().isoformat()), now) if p['status'] not in TERMINAL]


def validate_opening_reviews(decision, plans, *, withdrawn_plan_ids=frozenset()):
    """``withdrawn_plan_ids``：预检修正撤回了关联订单的计划，保留原execute复核，
    由 ``opening_plan_updates`` 记为受阻（程序撤回），而不是让整轮失败。"""
    by_id = {p['id']: p for p in plans}
    reviews = {r.plan_id: r for r in decision.opening_plan_reviews}
    if len(reviews) != len(decision.opening_plan_reviews) or set(reviews) != set(by_id):
        raise ValueError('必须逐笔复核全部待处理竞价计划，不能漏项、重复或引用其他计划')
    linked = {}
    for order in decision.orders:
        if not order.opening_plan_id:
            continue
        plan = by_id.get(order.opening_plan_id)
        if not plan or order.opening_plan_id in linked or order.action not in TRADE_ACTIONS or order.quantity <= 0:
            raise ValueError('竞价计划必须绑定唯一有效的新交易订单')
        original = plan['order']
        if order.code != original['code'] or (order.action in {'buy', 'add'}) != (original['action'] in {'buy', 'add'}):
            raise ValueError('竞价计划关联的股票和买卖方向不匹配')
        linked[order.opening_plan_id] = order
    for plan_id, review in reviews.items():
        if plan_id in withdrawn_plan_ids and plan_id not in linked:
            continue
        if (review.decision == 'execute') != (plan_id in linked):
            raise ValueError('执行计划须绑定新订单；观察或放弃计划不得绑定交易订单')


def opening_plan_updates(plans, decision=None, fills=(), rejects=(), *, unavailable=''):
    reviews = {r.plan_id: r for r in decision.opening_plan_reviews} if decision and not unavailable else {}
    updates = []
    for plan in plans:
        review = reviews.get(plan['id'])
        matched = [f for f in fills if f.get('opening_plan_id') == plan['id']]
        if matched:
            status, reason = 'executed', review.reason if review else '实际成交回执'
        elif not review:
            status, reason = 'unreviewed', unavailable or '本轮未完成计划复核，继续等待后续轮次'
        elif review.decision == 'execute':
            errors = [r.get('reason', '') for r in rejects if r.get('opening_plan_id') == plan['id']]
            status, reason = 'blocked', '；'.join(errors) or '本轮执行未完成，继续复核'
        else:
            status, reason = ('waiting' if review.decision == 'wait' else 'abandoned'), review.reason
        updates.append({'plan_id': plan['id'], 'status': status, 'reason': reason,
                        'filled_quantity': sum(f['quantity'] for f in matched),
                        'actual_gross_cents': sum(f['gross_cents'] for f in matched),
                        'actual_fees_cents': sum(f['fees_cents'] for f in matched)})
    return updates


def opening_notice(decision, plans, now):
    amounts = {p['id'].rsplit(':', 1)[-1]: p for p in plans}
    lines = [f'{now:%Y-%m-%d %H:%M}竞价预案', decision.summary]
    for index, order in enumerate(decision.orders):
        text = f'{index + 1}. {order.name or order.code}（{order.code}）· {ACTION_LABELS[order.action]}'
        if order.quantity:
            text += f' {order.quantity}股'
        plan = amounts.get(str(index))
        if plan and plan['planned_amount_cents'] is not None:
            text += f" · 计划金额 {plan['planned_amount_cents'] / 100:,.2f}元（按{ {'reference_price':'参考价','max_price':'价格上限','min_price':'价格下限'}[plan['amount_basis']]}估算，不含费）"
        lines.append(text)
        if order.action not in {'watch', 'unwatch'}:
            lines.append(order.reason)
        if order.execution:
            terms = order.execution
            lines.append(f'计划价格条件：下限{terms.min_price if terms.min_price is not None else "未设"}，上限{terms.max_price if terms.max_price is not None else "未设"}；开盘后重新授权。')
    lines.append('本轮不挂单、不成交。09:30起按新行情逐笔判定执行、继续观察或放弃；运行失败继续待核验，当日收盘未完成则记为到期。')
    return '\n'.join(lines)
