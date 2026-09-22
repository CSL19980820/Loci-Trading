"""无脚本的单列报告阅读页；与站内共用正文，不暴露配置或其他报告。"""
from datetime import datetime
from html import escape
import re

from src.ops.application.report_reading_style import REPORT_READING_CSS as STYLE


def _paragraph(text: str) -> str:
    safe = escape(str(text))
    safe = re.sub(r"\*\*([^*\n]+)\*\*", r"<strong>\1</strong>", safe)
    safe = re.sub(r"`([^`\n]+)`", r"<code>\1</code>", safe)
    return ''.join('<p>'+part.replace('\n', '<br>')+'</p>' for part in safe.split('\n\n') if part.strip())


def _tone(stat: dict) -> str:
    if not any(word in str(stat['label']) for word in ('盈亏', '回撤', '收益')):
        return ''
    raw = str(stat['value']).replace(',', '').replace('元', '').replace('%', '').replace('−', '-')
    try:
        value = float(raw)
    except ValueError:
        return ''
    return 'loss' if value < 0 else ('gain' if value > 0 else '')


def is_appendix(section: dict) -> bool:
    # Even an older report marked as detail may contain a critical condition.
    return bool(section.get('detail') and not section.get('plans') and (
        section.get('kind') in {'account', 'notes'} or
        section.get('kind') == 'stock' and not section.get('paragraphs')))


def _section_html(section: dict, index: int) -> str:
    kind = section.get('kind', 'document')
    allowed = {'overview', 'account', 'decisions', 'actions', 'stock', 'opportunity', 'research', 'lessons', 'notes', 'warning'}
    css = kind if kind in allowed else 'research'
    if kind == 'account' and not section.get('detail'):
        css += ' account-brief'
    stats = ''.join(f'<div><dt>{escape(str(s["label"]))}</dt><dd class="{_tone(s)}">{escape(str(s["value"]))}</dd></div>' for s in section.get('stats', []))
    paragraphs = ''.join(_paragraph(p) for p in section.get('paragraphs', []))
    plans = section.get('plans', [])
    rows = ''.join('<tr><td>'+escape(str(p['label']))+'</td><td>'+_paragraph(p['detail'])+
                   '<div class="condition">'+_paragraph(p.get('meta', ''))+'</div></td></tr>' for p in plans)
    table = '<table class="plan-table"><thead><tr><th scope="col">判断 / 计划</th><th scope="col">触发、失效与执行时机</th></tr></thead><tbody>'+rows+'</tbody></table>' if rows else ''
    stamp = '<span class="date">'+escape(str(section.get('plan_date') or '后续交易日'))+' · 条件计划，尚未下单</span>' if plans else ''
    return f'<section class="report-section {css}" id="s{index}" aria-labelledby="h{index}"><div class="section-heading"><h2 id="h{index}">{escape(str(section.get("heading", "")))}</h2>{stamp}</div>'+('<dl class="stats">'+stats+'</dl>' if stats else '')+paragraphs+table+'</section>'


def render_shared_document(sections: list[dict], *, title: str, owner: str, created_at: str, revision: int = 1) -> str:
    items = [dict(section) for section in sections if section.get('paragraphs') or section.get('stats') or section.get('plans')]
    lesson_text = '\n'.join(str(p) for s in items if s.get('kind') == 'lessons' for p in s.get('paragraphs', []))
    items = [s for s in items if not (s.get('kind') == 'insight' and s.get('paragraphs') and all(str(p) in lesson_text for p in s['paragraphs']))]
    visible = [s for s in items if not is_appendix(s)]
    # Conclusion first; preserve the remaining backend order and all essential content.
    visible.sort(key=lambda s: 0 if s.get('kind') == 'overview' else 1 if s.get('kind') == 'account' else 2)
    content = ''.join(_section_html(s, i) for i, s in enumerate(visible))
    appendix = ''.join(_section_html(s, i+len(visible)) for i, s in enumerate(s for s in items if is_appendix(s)))
    if appendix:
        content += '<details class="appendix"><summary>账务与成交依据</summary>'+appendix+'</details>'
    try:
        created = datetime.fromisoformat(str(created_at)).isoformat(sep=' ', timespec='seconds')
    except ValueError:
        created = str(created_at or '生成时间未记录')
    title, owner, created = escape(str(title)), escape(str(owner)), escape(created)
    version = f'更正 · 第 {int(revision)} 版' if int(revision) > 1 else '第 1 版'
    return f'''<!doctype html>
<html lang="zh-CN"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<meta name="robots" content="noindex,nofollow,noarchive"><meta name="referrer" content="no-referrer">
<title>{title} · {owner} · Loci</title><style>{STYLE}</style></head>
<body id="top"><a class="skip" href="#report-content">跳到报告正文</a>
<header class="topbar"><div><b class="brand">Loci</b><span class="readonly">模拟账户 · 只读分享</span></div></header>
<main class="sheet" id="report-content"><header class="heading"><div class="owner">{owner}</div><h1>{title}</h1><div class="metadata"><span>生成于 {created}</span><span>{version}</span></div></header>{content}</main>
<footer class="page-note">条件计划不等于成交；此页只读取对应报告。持有链接即可阅读，请谨慎转发。<a href="#top">返回顶部</a></footer></body></html>'''
