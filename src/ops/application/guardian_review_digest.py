"""通知是一张短笺，不是报告的第一段；研究原文和交易条件始终完整保存。"""

DIGEST_MAX_BYTES = 560  # Only the outbound message; never an Agent output limit.


def execution_brief(facts: dict) -> str:
    """Use recorded fills, not plans or retrospective prose, for the short receipt."""
    if facts.get('period') == 'premarket':
        return '盘前计划已就绪，尚未执行交易。'
    trades = facts.get('trades')
    if not isinstance(trades, list):
        return '完整判断与后续安排见报告。'
    legacy = [t for t in trades if t.get('origin') == 'legacy_conversion' or t.get('quote_source') == 'legacy_conversion']
    fills = [t for t in trades if t not in legacy]
    if not trades:
        return '本期无成交，持仓判断见报告。'
    if len(fills) == 1 and not legacy:
        fill = fills[0]
        side = {'buy': '买入', 'sell': '卖出'}.get(fill.get('side'))
        name, quantity = str(fill.get('name') or fill.get('code') or ''), fill.get('quantity')
        if side and type(quantity) is int and len(name) <= 12:
            return f'本期成交：{side}{name}{quantity:,}股。'
    text = f'本期成交{len(fills)}笔' if fills else '本期无新增成交'
    return text + (f'，另含{len(legacy)}笔历史折算。' if legacy else '。')


def notification_digest(facts: dict, analysis: dict, *, share_url: str = '', limit_bytes: int = DIGEST_MAX_BYTES) -> str:
    account = facts['account']
    equity = account['equity_cents']
    exposure = (equity - account['cash_cents']) / equity * 100 if equity else 0
    premarket = facts['period'] == 'premarket'
    pnl = account['total_pnl_cents'] if premarket else facts['period_pnl_cents']
    label = '累计盈亏' if premarket else '期间盈亏'
    lines = [f'{label} {pnl / 100:+,.2f}元', f'仓位 {exposure:.1f}% · 持仓 {len(account["positions"])}只']
    receipt = execution_brief(facts)
    # Whole optional short summary only. Never reuse full summary/next_steps,
    # split clauses, count conditional branches as orders, or regenerate research.
    short = str(analysis.get('notification_summary') or '').strip()
    if not short or len(short) > 64 or '\n' in short:
        short = receipt
    else:
        short = '观点：' + short
    destination = f'查看完整报告（免登录）\n{share_url}' if share_url else '完整报告：自主交易员 → 复盘与计划'
    body = '\n'.join([*lines, short]) + '\n\n' + destination
    if len(body.encode('utf-8')) > limit_bytes:
        body = '\n'.join([*lines, receipt]) + '\n\n' + destination
    if len(body.encode('utf-8')) > limit_bytes:
        # Do not break a URL. An unusually long deployment URL gets an in-app route.
        body = '\n'.join([*lines, receipt]) + '\n\n完整报告：自主交易员 → 复盘与计划'
    if len(body.encode('utf-8')) > limit_bytes:
        raise ValueError('通知预算不足以容纳账户短讯与报告入口')
    return body
