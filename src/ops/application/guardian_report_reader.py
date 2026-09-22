"""Guardian report reader: a factual cover, expandable holdings, and the full essay.

Only the presentation changes. Render explicit readable fields; never serialize the
account payload, tool receipts, configuration, or research history into the page.
"""
from __future__ import annotations

from datetime import date, datetime
from html import escape
import math
import re
from typing import Any

from src.ops.application.guardian_report_reader_style import STYLE
from src.ops.application.guardian_review_digest import execution_brief


def _text(value: Any) -> str:
    return escape(str(value))


def _paragraph(value: Any) -> str:
    safe = _text(value)
    safe = re.sub(r'\*\*([^*\n]+)\*\*', r'<strong>\1</strong>', safe)
    safe = re.sub(r'`([^`\n]+)`', r'<code>\1</code>', safe)
    return ''.join('<p>' + part.replace('\n', '<br>') + '</p>'
                   for part in safe.split('\n\n') if part.strip())


def _number(value: Any) -> float | None:
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
        return None
    return float(value)


def _money(cents: Any, *, signed: bool = False) -> str:
    value = _number(cents)
    return '—' if value is None else format(value / 100, '+,.2f' if signed else ',.2f')


def _tone(value: Any) -> str:
    number = _number(value)
    return '' if number is None or number == 0 else ('up' if number > 0 else 'down')


def _code(section: dict) -> str:
    match = re.search(r'[（(](\d{6})[）)]', str(section.get('heading', '')))
    return match.group(1) if match else ''


def _date(value: Any, *, full: bool = False) -> str:
    try:
        parsed = date.fromisoformat(str(value))
    except ValueError:
        return _text(value or '日期未记录')
    return f'{parsed.year}.{parsed.month:02}.{parsed.day:02}' if full else f'{parsed.month:02}.{parsed.day:02}'


def _stats(section: dict) -> str:
    rows = ''.join(f'<div><dt>{_text(row["label"])}</dt><dd>{_text(row["value"])}</dd></div>'
                   for row in section.get('stats', []))
    return '<dl class="detail-stats">' + rows + '</dl>' if rows else ''


def _plans(section: dict) -> str:
    plans = section.get('plans', [])
    if not plans:
        return ''
    content = ''.join('<div class="plan"><h5>' + _text(plan['label']) + '</h5>'
                      + _paragraph(plan['detail']) + '<div class="condition">'
                      + _paragraph(plan['meta']) + '</div></div>' for plan in plans)
    return ('<div class="plan-list"><h4>条件计划 · 尚未下单</h4><p class="plan-date">'
            + _text(section.get('plan_date') or '后续交易日') + '</p>' + content + '</div>')


def _section_body(section: dict) -> str:
    paragraphs = ''.join(_paragraph(p) for p in section.get('paragraphs', []))
    plans = _plans(section)
    content = '<div class="reading">' + paragraphs + '</div>'
    if plans:
        content = '<div class="detail-grid">' + content + plans + '</div>'
    return _stats(section) + content


def _contribution_figure(facts: dict) -> str:
    premarket = facts.get('period') == 'premarket'
    raw = ([{**row, 'period_pnl_cents': row.get('unrealized_pnl_cents')}
            for row in facts.get('account', {}).get('positions', [])] if premarket else facts.get('stock_performance', []))
    source = [row for row in raw
              if _number(row.get('period_pnl_cents')) is not None]
    if not source:
        return '<figure class="figure"><figcaption class="figure-head">盈亏分布</figcaption><p class="empty">暂无可核对的逐股盈亏。</p></figure>'
    ordered = sorted(source, key=lambda row: abs(row['period_pnl_cents']), reverse=True)
    shown = ordered[:5]
    if len(ordered) > 5:
        shown = [*shown, {'name': f'其余{len(ordered) - 5}只',
                         'period_pnl_cents': sum(row['period_pnl_cents'] for row in ordered[5:])}]
    magnitude = max(abs(row['period_pnl_cents']) for row in shown) or 1
    rows = []
    for row in shown:
        value = row['period_pnl_cents']
        width = abs(value) / magnitude * 100
        rows.append(f'<div class="contribution {"negative" if value < 0 else ""}">'
                    f'<span class="name">{_text(row.get("name") or row.get("code") or "其他")}</span>'
                    f'<span class="bar-lane" aria-hidden="true"><i style="width:{width:.3f}%"></i></span>'
                    f'<span class="value {_tone(value)}">{_money(value, signed=True)}</span></div>')
    heading = '当前持仓浮盈亏' if premarket else '盈亏来自哪里'
    subtitle = '昨收估值 / 元' if premarket else '本期贡献 / 元'
    note = '按昨收估值，非今日实时盈亏。' if premarket else '含已实现与持仓估值变化，按绝对金额排序。'
    return (f'<figure class="figure"><figcaption class="figure-head">{heading}<span>{subtitle}</span></figcaption>'
            + ''.join(rows) + f'<p class="fig-note">{note}</p></figure>')


def _equity_figure(facts: dict) -> str:
    raw = facts.get('equity_points', [])
    points = [row for row in raw if _number(row.get('equity_cents')) is not None and row.get('date')]
    if len(points) < 3 or len(points) != len(raw):
        return _contribution_figure(facts)
    values = [row['equity_cents'] / 1_000_000 for row in points]  # cents -> ten-thousand yuan
    bottom, top = min(values), max(values)
    padding = max((top - bottom) * .18, .01)
    low, high = bottom - padding, top + padding
    left, right, upper, lower = 47, 429, 20, 158
    def x(index: int) -> float:
        return left + (right - left) * index / (len(values) - 1)
    def y(value: float) -> float:
        return lower - (value - low) / (high - low) * (lower - upper)
    coordinates = [(x(i), y(value)) for i, value in enumerate(values)]
    trace = 'M' + ' L'.join(f'{px:.2f},{py:.2f}' for px, py in coordinates)
    area = trace + f' L{right},{lower} L{left},{lower} Z'
    grid = ''
    for value in dict.fromkeys((top, (top + bottom) / 2, bottom)):
        py = y(value)
        grid += f'<line class="grid" x1="{left}" y1="{py:.2f}" x2="{right}" y2="{py:.2f}"/><text x="0" y="{py + 4:.2f}">{value:.2f}</text>'
    dots = ''.join(f'<circle class="dot" cx="{px:.2f}" cy="{py:.2f}" r="3.2"><title>'
                   + _text(f'{row["date"]} 收盘总资产 {_money(row["equity_cents"])}元')
                   + '</title></circle>' for (px, py), row in zip(coordinates, points))
    tick_indices = range(len(points)) if len(points) <= 7 else (0, len(points) // 2, len(points) - 1)
    ticks = ''.join(f'<text text-anchor="middle" x="{x(i):.2f}" y="188">{_date(points[i]["date"])}</text>' for i in tick_indices)
    accessible = '；'.join(f'{row["date"]}：{_money(row["equity_cents"])}元' for row in points)
    svg = (f'<svg class="equity-chart" viewBox="0 0 448 201" role="img" aria-labelledby="equity-title equity-description">'
           f'<title id="equity-title">本期收盘净值</title><desc id="equity-description">{_text(accessible)}</desc>'
           f'{grid}<path class="area" d="{area}"/><path class="trace" d="{trace}"/>{dots}{ticks}</svg>')
    return ('<figure class="figure"><figcaption class="figure-head">这一周的账户<span>收盘总资产 / 万元</span></figcaption>'
            + svg + '<p class="fig-note">含期初基准；仅连接收盘采样，不代表盘中走势。</p></figure>')


def _row(section: dict, *, position: dict | None, performance: dict | None,
         equity: float | None, period: str, identifier: str) -> str:
    code = _code(section)
    name = re.sub(r'\s*[（(]\d{6}[）)]\s*$', '', str(section.get('heading', '')))
    identity = f'<span class="stock-identity"><span class="stock-name">{_text(name)}</span><span class="stock-code">{_text(code)}</span></span>'
    value = (position or {}).get('unrealized_pnl_cents') if period == 'premarket' else (performance or {}).get('period_pnl_cents')
    is_position = position is not None
    if is_position or performance is not None:
        market_value = _number((position or {}).get('market_value_cents'))
        weight = f'{market_value / equity * 100:.1f}%' if market_value is not None and equity and equity > 0 else ('已退出' if not is_position else '—')
        if is_position:
            quantity = f'{position["quantity"]:,} / {position["available_quantity"]:,}'
            quantity_caption = '持仓/可卖'
        else:
            quantity = f'{(performance or {}).get("sell_quantity", 0):,}'
            quantity_caption = '本期卖出'
        summary = (identity + f'<span class="cell weight-cell"><span class="cell-caption">仓位</span>{weight}</span>'
                   f'<span class="cell pnl-cell {_tone(value)}"><span class="cell-caption">{"浮动盈亏" if period == "premarket" else "本期盈亏"}</span>{_money(value, signed=True)}</span>'
                   f'<span class="cell quantity-cell"><span class="cell-caption">{quantity_caption}</span>{quantity}<small> 股</small></span>')
        row_class = 'position-row'
    else:
        labels = list(dict.fromkeys(str(plan['label']).split(' · ')[0] for plan in section.get('plans', [])))
        intent = ' / '.join(labels) + '计划' if labels else '研究记录'
        summary = identity + f'<span class="intent">{_text(intent)}</span>'
        row_class = 'opportunity-row'
    return (f'<details class="{row_class}" id="{identifier}"><summary class="position-summary">'
            + summary + '<span class="row-plus" aria-hidden="true"></span></summary>'
            + '<div class="position-detail">' + _section_body(section) + '</div></details>')


def _fold(title: str, subtitle: str, body: str, *, identifier: str = '') -> str:
    anchor = f' id="{_text(identifier)}"' if identifier else ''
    return (f'<details class="fold"{anchor}>'
            '<summary><span>' + _text(title) + '<small>' + _text(subtitle)
            + '</small></span><span class="fold-icon" aria-hidden="true"></span></summary>'
            '<div class="opportunity-list">' + body + '</div></details>')


def render_guardian_reader(sections: list[dict], *, facts: dict, analysis: dict,
                           period: str, day: str, created_at: str, revision: int = 1) -> str:
    account = facts['account']
    positions = {row['code']: row for row in account.get('positions', [])}
    performance = {row['code']: row for row in facts.get('stock_performance', [])}
    equity, cash = _number(account.get('equity_cents')), _number(account.get('cash_cents'))
    exposure = (equity - cash) / equity * 100 if equity and equity > 0 and cash is not None else None
    percent = f'{exposure:.1f}%' if exposure is not None else '—'
    pnl = account.get('total_pnl_cents') if period == 'premarket' else facts.get('period_pnl_cents')
    profit = _money(pnl, signed=True)
    whole, dot, decimal = profit.partition('.')
    amount = _text(whole) + (f'<span class="decimal">.{decimal}</span>' if dot else '')
    names = {'daily': '日复盘', 'weekly': '周复盘', 'premarket': '盘前计划'}
    label = names.get(period, '交易报告')
    metric = {'daily': '今日盈亏', 'weekly': '本周盈亏', 'premarket': '累计盈亏'}.get(period, '期间盈亏')
    rate = _number(facts.get('period_return_pct')) if period != 'premarket' else None
    rate_html = (f'<strong class="{_tone(rate)}">{rate:+.2f}%</strong><span>相对期初资产</span>'
                 if rate is not None else '<span>按报告时点账户口径</span>')
    receipt = execution_brief(facts)
    short = str(analysis.get('notification_summary') or '').strip()
    short_html = '<p class="key-note">' + _text(short) + '</p>' if short and len(short) <= 100 else ''
    failures = (facts.get('execution_facts') or {}).get('failed_cycles')
    exception_note = f'<p class="key-note">本期有 {failures} 个异常轮次，影响与核验记录见完整复盘。</p>' if type(failures) is int and failures > 0 else ''
    span = f'{_date(facts.get("start_date", day))} — {_date(day)}' if period == 'weekly' else _date(day, full=True)
    update = f'更正 · 第 {int(revision)} 版' if int(revision) > 1 else '第 1 版'
    try:
        stamp = datetime.fromisoformat(str(created_at)).isoformat(sep=' ', timespec='seconds')
    except ValueError:
        stamp = str(created_at or '时间未记录')
    chart = _equity_figure(facts) if period == 'weekly' else _contribution_figure(facts)
    tracker = f'<span class="exposure-track" aria-hidden="true"><i style="width:{max(0, min(100, exposure)):.3f}%"></i></span>' if exposure is not None else ''
    cover = f'''<section class="cover" id="overview" aria-labelledby="report-title">
<div class="cover-title"><div><p class="eyebrow">自主交易员 · 模拟账户</p><h1 id="report-title">{label}</h1></div>
<div class="cover-date"><strong>{span}</strong><span>{_text(day[:4])} 年 / {"每周回顾" if period == "weekly" else "交易日记录"}</span><span class="revision">{update}</span></div></div>
<div class="hero"><div class="hero-lead"><div class="metric-label">{metric}</div><div class="pnl {_tone(pnl)}">{amount}<span class="unit">元</span></div>
<div class="rate">{rate_html}</div><p class="receipt">{_text(receipt)}</p>{short_html}{exception_note}
<a class="lead-link" href="#full-report-content">阅读判断与后续安排<span aria-hidden="true">↗</span></a></div>{chart}</div>
<dl class="account-strip"><div><dt>总资产</dt><dd>{_money(equity)}<small>元</small></dd></div><div><dt>可用现金</dt><dd>{_money(cash)}<small>元</small></dd></div><div><dt>已投入 / 仓位</dt><dd>{percent}<small>{len(positions)}只持仓</small></dd>{tracker}</div></dl></section>'''
    held, closed, opportunities, references, essays = [], [], [], [], []
    researched = {row.get('code') for row in analysis.get('stock_reviews', [])}
    lesson_text = '\n'.join(str(p) for s in sections if s.get('kind') == 'lessons' for p in s.get('paragraphs', []))
    for index, section in enumerate(sections):
        kind, code = section.get('kind', ''), _code(section)
        item = (index, section)
        if kind == 'stock' and code in positions:
            held.append(item)
        elif kind == 'stock' and code in performance:
            closed.append(item)
        elif kind == 'opportunity':
            (opportunities if section.get('plans') or code in researched else references).append(item)
        elif kind == 'references':
            references.append(item)
        elif kind == 'account' and not section.get('detail'):
            # All three brief metrics are on the cover; the full account is retained below.
            continue
        elif kind == 'insight' and section.get('paragraphs') and all(str(p) in lesson_text for p in section['paragraphs']):
            # The same hypotheses remain with their verification status, not as rules.
            continue
        else:
            essays.append(item)
    rows = ''.join(_row(section, position=positions.get(_code(section)), performance=performance.get(_code(section)),
                        equity=equity, period=period, identifier=f's{index}') for index, section in held)
    if not rows:
        empty = '持仓明细尚未提供。' if positions else '报告时点没有持仓。'
        rows = '<p class="empty">' + empty + '</p>'
    portfolio = ('<section class="major" id="portfolio" aria-labelledby="portfolio-heading"><div class="major-head">'
                 '<h2 id="portfolio-heading">持仓与计划</h2><p>先看结果，点击个股展开判断与完整条件</p></div>'
                 '<div class="position-header" aria-hidden="true"><span>报告日持仓</span><span>占总资产</span>'
                 f'<span>{"浮动盈亏" if period == "premarket" else "本期盈亏"} / 元</span><span>持仓 / 可卖</span><span></span></div>' + rows)
    if opportunities:
        other_rows = ''.join(_row(section, position=None, performance=None, equity=equity, period=period,
                                 identifier=f's{index}') for index, section in opportunities)
        portfolio += _fold('其他关注与后续计划', f'{len(opportunities)}个标的 · 研究与计划，非委托', other_rows, identifier='opportunities')
    if closed:
        other_rows = ''.join(_row(section, position=None, performance=performance.get(_code(section)), equity=equity,
                                 period=period, identifier=f's{index}') for index, section in closed)
        portfolio += _fold('本期已退出的持仓', f'{len(closed)}个标的 · 保留完整复盘', other_rows, identifier='closed-positions')
    portfolio += '<p class="planning-note">以上为报告当时的判断与条件计划，可修订；不代表当前委托或必须执行的策略。</p></section>'
    # Merge sections into three essays. Keep all text/conditions, including unknown
    # future section kinds, without exposing the raw data payload.
    groups = [('判断与后续安排', {'overview', 'highlights', 'decisions', 'actions'}),
              ('研究与验证', {'research', 'lessons', 'insight'}),
              ('账户与运行记录', {'account', 'notes'})]
    full = f'<div class="stamp">生成于 {_text(stamp)} · {update} · 本页为该版本的只读快照</div>'
    rendered: set[int] = set()
    for heading, kinds in groups:
        group = [(i, s) for i, s in essays if s.get('kind') in kinds]
        if not group:
            continue
        content = ''
        for i, s in group:
            subheading = '' if s.get('kind') == 'overview' else f'<h4>{_text(s["heading"])}</h4>'
            content += f'<div id="s{i}">{subheading}{_section_body(s)}</div>'
            rendered.add(i)
        full += '<section class="essay-group"><h3>' + heading + '</h3>' + content + '</section>'
    leftovers = [(i, s) for i, s in essays if i not in rendered]
    for i, s in leftovers:
        full += f'<section class="essay-group" id="s{i}"><h3>{_text(s["heading"])}</h3>{_section_body(s)}</section>'
    reference_html = ''
    if references:
        material = ''
        for i, section in references:
            heading = '' if section.get('kind') == 'references' else f'<h4>{_text(section["heading"])}</h4>'
            material += f'<div id="s{i}">{heading}{_section_body(section)}</div>'
        reference_html = '<section class="essay-group all-references" id="quant-references"><h2>量化候选参考</h2>' + material + '</section>'
    article = (f'<details class="paper-fold" id="full-report"><summary><span><span class="paper-title">完整{label}</span>'
               '<span class="paper-description">判断、下一步、研究与核验记录，按需阅读。</span></span>'
               '<span class="paper-cta"><span class="open-text">阅读全文</span><span class="close-text">收起全文</span>'
               '<span class="fold-icon" aria-hidden="true"></span></span></summary><div class="paper-body" id="full-report-content">' + full + '</div></details>')
    title = f'{day} · {label} · 自主交易员 · Loci'
    return f'''<!doctype html>
<html lang="zh-CN"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<meta name="robots" content="noindex,nofollow,noarchive"><meta name="referrer" content="no-referrer"><title>{_text(title)}</title><style>{STYLE}</style></head>
<body id="top"><a class="skip" href="#overview">跳到报告正文</a><header class="shell"><div class="brandbar"><div class="brand"><span class="logotype">loci<b>.</b></span><span class="byline">交易手记</span></div><span class="edition">自主交易员 / 只读报告</span></div></header>
<div class="nav-wrap"><nav class="reader-nav" aria-label="阅读目录"><a href="#overview">账户结果</a><a href="#portfolio">持仓与计划</a><a href="#full-report-content">完整复盘</a><span class="nav-date">{_date(day, full=True)}</span></nav></div>
<main class="shell">{cover}{portfolio}{reference_html}{article}<footer class="page-end"><p>模拟账户 · 计划不代表成交，成交以回执为准。<br>持有链接可阅读此报告，请谨慎转发。</p><a href="#top">回到顶部 ↑</a></footer></main></body></html>'''
