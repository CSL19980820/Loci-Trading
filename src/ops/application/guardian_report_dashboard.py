"""报告阅读入口与历史账务视图辅助函数；不生成交易判断。"""
from collections import Counter
from html import escape
import math
import re

from src.ops.application.guardian_report_document import _paragraph
from src.ops.application.guardian_review_data import PERIOD_LABELS
from src.ops.application.guardian_review_format import report_sections


def numeric(value):
    return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value)


def tone(value):
    return 'up' if numeric(value) and value > 0 else 'down' if numeric(value) and value < 0 else 'flat'


def money(value, *, signed=False):
    if not numeric(value):
        return '—'
    return f'{value / 100:+,.2f}' if signed and value else f'{value / 100:,.2f}'


def pct(value, *, signed=False):
    if not numeric(value):
        return '—'
    return (f'{value:+.2f}' if signed and value else f'{value:.1f}') + '%'


def icon(kind):
    paths = {
        'view': '<rect x="5" y="3" width="14" height="18" rx="2"/><path d="M9 7h6M9 11h6M9 15h4"/>',
        'holdings': '<path d="M5 20V10m5 10V4m5 16v-7m5 7V7"/>',
        'plans': '<rect x="3" y="5" width="18" height="16" rx="2"/><path d="M7 3v4m10-4v4M3 11h18m-13 5 3 3 5-5"/>',
        'research': '<path d="M12 5C8 2 4 3 2 4v15c4-2 7-1 10 1 3-2 6-3 10-1V4c-2-1-6-2-10 1Zm0 0v15"/>',
        'notice': '<rect x="3" y="3" width="18" height="15" rx="4"/><path d="m7 18-2 4 7-4m-4-8h8"/>',
    }
    return '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.7" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">'+paths[kind]+'</svg>'


def disclosure(label, body, *, css='more'):
    return f'<details class="{css}"><summary>{escape(label)}</summary><div class="more-content">{body}</div></details>'


def excerpt(text, fallback):
    """Only show a complete original sentence; long/non-prose content gets a label."""
    plain = str(text).strip()
    first = re.split(r'(?<=[。！？])|\n', plain, maxsplit=1)[0]
    if first and len(first) <= 75:
        return first
    topic = re.split('[：:]', first, maxsplit=1)
    return topic[0] if len(topic) > 1 and 0 < len(topic[0]) <= 24 else fallback


def reading_item(text, index, *, title='', state=''):
    heading = title or excerpt(text, f'判断 {index:02} · 阅读完整依据')
    tag = f'<span class="lesson-state">{escape(state)}</span>' if state else ''
    return (f'<details class="reading-item"><summary><span class="item-no">{index:02}</span>'
            f'<span class="item-title">{tag}{escape(heading)}</span><span class="chevron" aria-hidden="true">+</span></summary>'
            f'<div class="reading-body">{_paragraph(text)}</div></details>')


def reading_list(texts, *, label='其余完整分析', visible=3):
    rows = [reading_item(text, i + 1) for i, text in enumerate(texts)]
    return ''.join(rows[:visible]) + (disclosure(f'{label} · {len(rows) - visible}项', ''.join(rows[visible:])) if len(rows) > visible else '')


def panel(key, title, content, note=''):
    return f'<section class="panel" id="{key}" aria-labelledby="{key}-title"><div class="panel-head"><h2 id="{key}-title">{icon(key)}{escape(title)}</h2><span>{escape(note)}</span></div>{content}</section>'


def stat_block(label, value, meta='', css=''):
    return f'<div class="metric"><div class="metric-label">{escape(label)}</div><div class="metric-value {css}">{value}</div><div class="metric-meta">{meta}</div></div>'


def metrics(facts):
    account, period = facts['account'], facts['period']
    equity, cash = account['equity_cents'], account['cash_cents']
    exposure = (equity - cash) / equity * 100 if equity > 0 else None
    premarket, weekly = period == 'premarket', period == 'weekly'
    pnl = account['total_pnl_cents'] if premarket else facts['period_pnl_cents']
    ret = facts.get('period_return_pct') if not premarket else None
    count = len(account['positions'])
    trades = facts.get('trades', [])
    fills = [t for t in trades if t.get('origin') != 'legacy_conversion' and t.get('quote_source') != 'legacy_conversion']
    sides = Counter(t.get('side') for t in fills)
    label = '累计盈亏' if premarket else '本周净收益' if weekly else '今日盈亏'
    meta = f'<span class="{tone(ret)}">{pct(ret, signed=True)}</span> · 期间收益率' if numeric(ret) else '金额单位：元 · 已计交易费用'
    bar = f'<span class="exposure-track" aria-hidden="true"><i style="width:{max(0, min(100, exposure)):.2f}%"></i></span>' if numeric(exposure) else ''
    rows = [stat_block(label + '（元）', money(pnl, signed=True), meta, tone(pnl)),
            stat_block('期末仓位' if weekly else '当前仓位', pct(exposure) + bar, '可用现金 ' + money(cash) + '元'),
            stat_block('期末持仓' if weekly else '持仓数量', str(count) + '<small>只</small>', '账户权益 ' + money(equity) + '元')]
    if weekly:
        drawdown = facts.get('close_drawdown_pct')
        rows.append(stat_block('收盘净值最大回撤', pct(drawdown), '收盘采样 · 不代表盘中最大回撤', tone(drawdown)))
    else:
        note = '计划尚未执行' if premarket else f'买入 {sides["buy"]}笔 / 卖出 {sides["sell"]}笔'
        if len(fills) != len(trades):
            note += f' · 另含历史折算{len(trades)-len(fills)}笔'
        rows.append(stat_block('今日成交' if not premarket else '盘前阶段', '—' if premarket else str(len(fills)) + '<small>笔</small>', note))
    return '<div class="metrics" aria-label="账户表现">'+''.join(rows)+'</div>'


def equity_chart(facts):
    points = facts.get('equity_points', [])
    if len(points) < 2 or any(not numeric(p.get('equity_cents')) for p in points):
        return '<p class="empty">缺少完整收盘权益序列，本页不补画走势。</p>'
    dates = [str(p.get('date', '')) for p in points]
    if dates != sorted(set(dates)):
        return '<p class="empty">权益采样时点需核对，暂不绘制曲线。</p>'
    values = [p['equity_cents'] for p in points]
    low, high = min(values), max(values)
    spread = max(high - low, abs(high) * .003, 100)
    low, high = low - spread * .15, high + spread * .15
    left, right, top, bottom = 48, 556, 17, 153
    coords = [(left + i * (right-left)/(len(points)-1), bottom - (v-low)/(high-low)*(bottom-top)) for i, v in enumerate(values)]
    elements = []
    for k in range(3):
        y = top + (bottom-top)*k/2
        label = (high - (high-low)*k/2) / 1000000
        elements.append(f'<line class="chart-grid" x1="{left}" y1="{y}" x2="{right}" y2="{y}"/><text class="chart-label" x="0" y="{y+4}">{label:.2f}</text>')
    for i, ((x, y), p) in enumerate(zip(coords, points)):
        if i:
            px, py = coords[i-1]
            elements.append(f'<path class="chart-line {tone(values[i]-values[i-1])}" d="M{px:.2f},{py:.2f} L{x:.2f},{y:.2f}"/>')
        color = tone(values[i]-values[i-1]) if i else 'flat'
        elements.append(f'<circle class="chart-dot {color}" cx="{x:.2f}" cy="{y:.2f}" r="3"><title>{escape(dates[i])} · {money(values[i])}元</title></circle>')
        elements.append(f'<text class="chart-label" text-anchor="{"start" if i == 0 else "end" if i == len(points)-1 else "middle"}" x="{x:.2f}" y="181">{escape(dates[i][5:].replace("-", "/"))}</text>')
    table = '<table aria-label="每日收盘权益"><thead><tr><th>采样日</th><th>收盘权益（元）</th></tr></thead><tbody>'+''.join(f'<tr><td>{escape(d)}</td><td>{money(v)}</td></tr>' for d, v in zip(dates, values))+'</tbody></table>'
    return ('<figure class="chart"><figcaption class="chart-heading"><span>收盘权益 · 万元</span><span>期初基准 + 本周收盘</span></figcaption>'
            '<svg class="equity-svg" viewBox="0 0 570 193" role="img" aria-label="本周收盘权益变化，红升绿降"><title>本周收盘权益</title>'+''.join(elements)+'</svg>'
            f'<div class="chart-foot"><span>期初 {money(values[0])}元</span><span>期末 {money(values[-1])}元</span></div></figure>'+disclosure('查看收盘采样数值', table))


def view_panel(facts, analysis):
    weekly = facts['period'] == 'weekly'
    title = '一周回顾' if weekly else '盘前判断' if facts['period'] == 'premarket' else '今日判断'
    content = equity_chart(facts) if weekly else ''
    highlights = analysis.get('highlights', [])
    if highlights:
        rows = [reading_item(row['detail'], i+1, title=row['title']) for i, row in enumerate(highlights)]
        content += ''.join(rows[:3]) + (disclosure('其余核心判断', ''.join(rows[3:])) if len(rows) > 3 else '')
    elif not weekly:
        content += reading_list(analysis.get('assessments', []), visible=3)
    # Preserve every paragraph, not an LLM-made rewrite of an old report.
    full = '<h3>整周综合结论</h3>' if weekly else '<h3>完整结论</h3>'
    full += _paragraph(analysis['summary'])
    if weekly or highlights:
        full += ''.join('<div class="detail-stock">'+_paragraph(p)+'</div>' for p in analysis.get('assessments', []))
    content += disclosure('展开整周总结与决策归因' if weekly else '展开完整结论', full)
    content += '<p class="reading-note">'+('按整周权益与决策复盘，不以最后一天代替一周。' if weekly else '以上为判断摘录，点击条目查看原文与限定条件。')+'</p>'
    return panel('view', title, content, '整周视角' if weekly else '判断与依据')


def stock_identity(name, code):
    return f'<div class="stock-id"><b>{escape(str(name))}</b><span>{escape(str(code))}</span></div>'


def detail_stat(stat):
    value = str(stat['value'])
    match = re.fullmatch(r'([+−-]?[\d,]+(?:\.\d+)?)(?:元|%)?', value)
    number = float(match[1].replace(',', '').replace('−', '-')) if match else None
    css = tone(number) if any(word in stat['label'] for word in ('盈亏', '回撤', '收益')) else ''
    return '<div><dt>'+escape(str(stat['label']))+f'</dt><dd class="{css}">'+escape(value)+'</dd></div>'


def detail_sections(sections):
    output = []
    for section in sections:
        stats = ''.join(detail_stat(s) for s in section.get('stats', []))
        body = ('<dl class="detail-stats">'+stats+'</dl>' if stats else '')
        body += '<div class="detail-copy">'+''.join(_paragraph(p) for p in section.get('paragraphs', []))+'</div>'
        output.append('<article class="detail-stock"><h3>'+escape(section['heading'])+'</h3>'+body+'</article>')
    return ''.join(output)


def portfolio_panel(facts, sections):
    account, weekly = facts['account'], facts['period'] == 'weekly'
    positions, equity = account['positions'], account['equity_cents']
    performance = facts.get('stock_performance', [])
    content = ''
    if weekly and performance:
        known = [p for p in performance if numeric(p.get('period_pnl_cents'))]
        scale = max((abs(p['period_pnl_cents']) for p in known), default=1) or 1
        largest = sorted(known, key=lambda p: abs(p['period_pnl_cents']), reverse=True)[:4]
        shown = sorted(largest, key=lambda p: p['period_pnl_cents'], reverse=True)
        remainder = [p for p in performance if p not in largest]
        if remainder:
            losses = sum(numeric(p.get('period_pnl_cents')) and p['period_pnl_cents'] < 0 for p in remainder)
            total = sum(p['period_pnl_cents'] for p in remainder) if all(numeric(p.get('period_pnl_cents')) for p in remainder) else None
            shown.append({'code': '', 'name': f'其余{len(remainder)}只' + (f'（含{losses}只亏损）' if losses else ''), 'period_pnl_cents': total})
        scale = max([scale, *(abs(p['period_pnl_cents']) for p in shown if numeric(p.get('period_pnl_cents')))])
        rows = []
        # Signed contribution, not winners/net-profit percentages.
        for p in shown:
            value = p.get('period_pnl_cents')
            width = abs(value) / scale * 100 if numeric(value) else 0
            negative, positive = (width, 0) if numeric(value) and value < 0 else (0, width)
            bars = f'<span class="attribution-bar" aria-hidden="true"><span class="attribution-half down"><i style="width:{negative:.2f}%"></i></span><span class="attribution-half up"><i style="width:{positive:.2f}%"></i></span></span>'
            rows.append(f'<tr><td>{stock_identity(p.get("name", p["code"]), p["code"])}</td><td>{bars}</td><td class="number {tone(value)}">{money(value, signed=True)}</td></tr>')
        content += '<div class="table-wrap"><table class="attribution" aria-label="本周个股收益贡献"><thead><tr><th>标的</th><th>亏损 / 盈利</th><th>净贡献（元）</th></tr></thead><tbody>'+''.join(rows)+'</tbody></table></div>'
        content += '<p class="reading-note">主要贡献与其余合计；含已退出标的、费用和期间市值变化。完整逐股数据见明细。</p>'
        content += '<div class="table-foot"><span>本周合计净贡献</span><b class="'+tone(facts.get('period_pnl_cents'))+'">'+money(facts.get('period_pnl_cents'), signed=True)+'元</b></div>'
    else:
        rows = []
        for p in positions:
            weight = p.get('market_value_cents', p['quantity'] * p['mark_price_cents']) / equity * 100 if equity > 0 else None
            value = p.get('unrealized_pnl_cents')
            bar = f'<span class="weight-bar" aria-hidden="true"><i style="width:{max(0, min(100, weight)):.2f}%"></i></span>' if numeric(weight) else ''
            rows.append(f'<tr><td>{stock_identity(p["name"], p["code"])}</td><td>{pct(weight)}{bar}</td><td class="number {tone(value)}">{money(value, signed=True)}</td></tr>')
        content += ('<div class="table-wrap"><table aria-label="当前持仓"><thead><tr><th>标的 / 代码</th><th>权益占比</th><th>浮动盈亏（元）</th></tr></thead><tbody>'+''.join(rows)+'</tbody></table></div>') if rows else '<p class="empty">当前空仓，现金及后续判断见本报告。</p>'
        content += '<div class="table-foot"><span>持仓浮盈亏</span><b class="'+tone(account.get('unrealized_pnl_cents'))+'">'+money(account.get('unrealized_pnl_cents'), signed=True)+'元</b></div>'
    full = [s for s in sections if s['kind'] in {'stock', 'opportunity'}]
    accounts = [s for s in sections if s['kind'] == 'account' and s.get('detail')]
    content += disclosure('持仓、机会与账户明细', detail_sections([*accounts, *full]))
    allocations = facts.get('allocation_points')
    if weekly and allocations:
        table = '<table aria-label="收盘仓位演变"><thead><tr><th>日期</th><th>仓位</th><th>持仓</th><th>现金（元）</th></tr></thead><tbody>'+''.join(f'<tr><td>{escape(p["date"])}</td><td>{pct(p.get("exposure_pct"))}</td><td>{p["position_count"]}只</td><td>{money(p["cash_cents"])}</td></tr>' for p in allocations)+'</tbody></table>'
        content += disclosure('整周资金配置演变（收盘采样）', '<div class="table-wrap">'+table+'</div>')
    return panel('holdings', '收益贡献与仓位' if weekly else '持仓与关注', content, '本周净贡献' if weekly else '期末快照')


def plans_panel(facts, analysis, sections):
    weekly, premarket = facts['period'] == 'weekly', facts['period'] == 'premarket'
    title = '下周方向' if weekly else '今日准备' if premarket else '下一交易日计划'
    content = reading_list(analysis.get('next_steps', []), label='其余后续安排', visible=2 if weekly else 3)
    groups = []
    for section in sections:
        if not section.get('plans'):
            continue
        plans = section['plans']
        labels = list(dict.fromkeys(p['label'].split(' · ')[0] for p in plans))
        summary = ' / '.join(labels)
        body = ''.join('<div class="plan-condition"><b>'+escape(p['label'])+'</b>'+_paragraph(p['detail'])+'<div class="plan-meta">'+_paragraph(p['meta'])+'</div></div>' for p in plans)
        groups.append('<details class="plan-row"><summary><span>'+escape(section['heading'])+'</span><span class="intent">'+escape(summary)+'</span><span class="chevron" aria-hidden="true">+</span></summary><div class="plan-body">'+body+'</div></details>')
    if groups:
        content += '<p class="plan-disclaimer">条件预案 · 尚未下单。触发、失效与时机放在同一条目中，点击查看。</p>'
        content += ''.join(groups[:3]) + (disclosure(f'其余标的条件 · {len(groups)-3}只', ''.join(groups[3:])) if len(groups)>3 else '')
    if not groups and not analysis.get('next_steps'):
        content += '<p class="empty">本报告没有新增条件计划；不代表下一轮不能形成新判断。</p>'
    return panel('plans', title, content, str(facts.get('planning_trade_date') or '时间待确认'))


def research_panel(facts, analysis, sections):
    statuses = {'proposed': '待验证', 'supported': '有支持证据', 'refuted': '有反证', 'inconclusive': '尚无定论', 'corrected': '已核实纠正'}
    lessons = analysis.get('lessons', [])
    rows = [reading_item(r['hypothesis']+'\n\n验证方法：'+r['validation_plan'], i+1,
            title=excerpt(r['hypothesis'], '研究发现 · 阅读完整依据'), state=statuses.get(r.get('status', 'proposed'), '待验证')) for i,r in enumerate(lessons)]
    content = ''.join(rows[:2]) + (disclosure(f'其余研究发现 · {len(rows)-2}项', ''.join(rows[2:])) if len(rows)>2 else '')
    notes = analysis.get('research_notes', [])
    if notes:
        content += disclosure(f'完整研究与待验证问题 · {len(notes)}项', ''.join('<article class="detail-stock">'+_paragraph(n)+'</article>' for n in notes))
    if not rows and not notes:
        content += '<p class="empty">本期没有新增研究发现，不将单次盈亏升级为规律。</p>'
    appendix = [s for s in sections if s['kind'] in {'references', 'notes'}]
    content += disclosure('数据口径、运行记录与参考资料', detail_sections(appendix))
    content += '<div class="research-note">'+icon('notice')+'<span>企微只推送简短摘要。此页保留完整判断、条件与研究，按兴趣展开阅读。</span></div>'
    return panel('research', '研究进展' if facts['period'] == 'weekly' else '研究与待验证问题', content, '证据与反例')


def render_guardian_dashboard(period: str, day: str, result: dict) -> str:
    from src.ops.application.guardian_report_document import render_shared_document
    facts, analysis = result['facts'], result['analysis']
    if period != facts['period'] or day != facts['trade_date']:
        raise ValueError('报告类型或日期与快照不一致')
    date_label = f'{facts.get("start_date", day)} — {day}' if period == 'weekly' else day
    return render_shared_document(report_sections(facts, analysis),
        title=f'{date_label} · {PERIOD_LABELS[period]}', owner='自主交易员',
        created_at=result.get('created_at', ''), revision=int(result.get('revision', 1)))
