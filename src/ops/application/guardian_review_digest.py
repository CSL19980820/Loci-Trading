"""通知是一张短笺，不是报告的第一段；研究原文和交易条件始终完整保存。"""
from copy import deepcopy

from src.ledger.domain.guardian_watchlist import update_watchlist
from src.ops.application.guardian_cycle_notice import observation_changes, observation_notice

DIGEST_MAX_BYTES = 1600  # Outbound only; allow several observation actions and the share link.


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


def _observation_lines(facts: dict, analysis: dict, observed_at: str) -> list[str]:
    updates = analysis.get('watchlist_updates') or []
    if not updates:
        return []
    if not observed_at:
        raise ValueError('观察动作缺少报告完成时间')
    before = {'watchlist': deepcopy(facts.get('watchlist') or [])}
    after = deepcopy(before)
    names = facts.get('stock_names') or {}
    for update in updates:
        update_watchlist(after, update, observed_at, name=names.get(update['code'], ''))
    # unwatch also dismisses a reference that was not yet in the explicit watchlist.
    references = [{'code': u['code'], 'name': names.get(u['code'], u['code'])}
                  for u in updates if u['action'] == 'unwatch']
    changes = observation_changes(before, after, observed_at, references=references)
    return observation_notice(changes).splitlines() if changes else []


def notification_digest(facts: dict, analysis: dict, *, share_url: str = '',
                        observed_at: str = '', revision: int = 1,
                        limit_bytes: int = DIGEST_MAX_BYTES) -> str:
    account = facts['account']
    equity = account['equity_cents']
    exposure = (equity - account['cash_cents']) / equity * 100 if equity else 0
    premarket = facts['period'] == 'premarket'
    pnl = account['total_pnl_cents'] if premarket else facts['period_pnl_cents']
    label = '累计盈亏' if premarket else '期间盈亏'
    lines = [f'{label} {pnl / 100:+,.2f}元', f'仓位 {exposure:.1f}% · 持仓 {len(account["positions"])}只']
    receipt = execution_brief(facts)
    observations = _observation_lines(facts, analysis, observed_at) if revision == 1 else []
    # Whole optional short summary only. Never reuse full summary/next_steps,
    # split clauses, count conditional branches as orders, or regenerate research.
    short = str(analysis.get('notification_summary') or '').strip()
    if observations or not short or len(short) > 64 or '\n' in short:
        short = receipt
    else:
        short = '观点：' + short
    destination = f'查看完整报告（免登录）\n{share_url}' if share_url else '完整报告：天才交易员 → 复盘与计划'
    def compose(message: str, header: list[str] | None = None) -> str:
        parts = [*(lines if header is None else header)]
        if message:
            parts.append(message)
        if observations:
            parts.extend(['', '观察调整', *observations])
        return '\n'.join([*parts, '', destination])

    body = compose(short)
    if len(body.encode('utf-8')) > limit_bytes:
        body = compose(receipt)
    if len(body.encode('utf-8')) > limit_bytes:
        body = compose('')
    if len(body.encode('utf-8')) > limit_bytes:
        body = compose('', lines[:1])
    if len(body.encode('utf-8')) > limit_bytes:
        raise ValueError('通知预算不足以容纳观察动作与报告链接')
    return body
