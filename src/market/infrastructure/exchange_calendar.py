"""交易所公告的全局磁盘快照；联网只发生在显式盘外刷新任务。"""
import json
import re
import time
import urllib.request
from datetime import date, datetime
from html import unescape
from pathlib import Path
from uuid import uuid4
from zoneinfo import ZoneInfo

from src.market.domain.exchange_schedule import HOLIDAYS, scheduled_trading_days as calculate_days
from src.shared.paths import market_db

SOURCE = 'https://www.sse.com.cn/disclosure/dealinstruc/closed/'
MAX_AGE = 72 * 3600


def calendar_path() -> Path:
    return market_db().parent / 'exchange_calendar.json'


def read_calendar() -> dict:
    try:
        return json.loads(calendar_path().read_text(encoding='utf-8'))
    except (OSError, ValueError):
        return {}


def parse_schedule(html: str) -> tuple[int, list[list[str]]]:
    match = re.search(r'(20\d{2})年休市安排\s*</strong>.*?<table[^>]*>(.*?)</table>', html, re.S)
    if not match:
        raise ValueError('交易所休市页面结构变化，保留旧日历')
    year, table = int(match[1]), match[2]
    spans = []
    for raw in re.findall(r'<tr\b[^>]*>(.*?)</tr>', table, re.S):
        row = re.sub(r'<[^>]+>|\s+', '', unescape(raw))
        span = re.search(r'(\d{1,2})月(\d{1,2})日(?:（[^）]+）)?(?:至(?:(\d{1,2})月)?(\d{1,2})日(?:（[^）]+）)?)?休市', row)
        if not span:
            raise ValueError('休市区间解析不完整，保留旧日历')
        m, d, m2, d2 = span.groups()
        start = date(year, int(m), int(d))
        end = date(year, int(m2 or m), int(d2 or d))
        if not 0 <= (end-start).days <= 15:
            raise ValueError('休市区间异常')
        spans.append([start.strftime('%m-%d'), end.strftime('%m-%d')])
    # 中秋与国庆同周时，交易所可能合并为一行，不能把固定七行当成完整性。
    holiday_names = ('元旦', '春节', '清明', '劳动', '端午', '中秋', '国庆')
    if not 6 <= len(spans) <= 7 or not all(name in table for name in holiday_names):
        raise ValueError('年度节假日清单不完整，拒绝覆盖')
    return year, spans


def refresh_exchange_calendar(*, force: bool = False) -> dict:
    now = datetime.now(ZoneInfo('Asia/Shanghai'))
    if 8 <= now.hour < 16:
        raise ValueError('交易日历仅在盘外更新，08:00至16:00不联网刷新')
    old = read_calendar()
    if not force and time.time()-old.get('checked_at', 0) < 6*3600:
        return {'status': 'fresh', 'checked_at': old['checked_at']}
    request = urllib.request.Request(SOURCE, headers={'User-Agent': 'Mozilla/5.0 Loci-calendar'})
    with urllib.request.urlopen(request, timeout=20) as response:
        html = response.read(2_000_001)
    if len(html) > 2_000_000:
        raise ValueError('休市页面响应超限')
    year, spans = parse_schedule(html.decode('utf-8'))
    if year not in (now.year, now.year+1):
        raise ValueError('交易所年度公告尚未更新，保留已验证日历')
    years = {str(y): list(v) for y, v in HOLIDAYS.items()}
    years.update(old.get('years', {}))
    years[str(year)] = spans
    value = {'source': SOURCE, 'checked_at': time.time(), 'source_year': year, 'years': years}
    target = calendar_path()
    target.parent.mkdir(parents=True, exist_ok=True)
    temporary = target.with_suffix(f'.{uuid4().hex}.tmp')
    try:
        temporary.write_text(json.dumps(value, ensure_ascii=False), encoding='utf-8')
        temporary.replace(target)
    finally:
        temporary.unlink(missing_ok=True)
    return {'status': 'updated', 'checked_at': value['checked_at'], 'year': year, 'source': SOURCE}


def scheduled_trading_days(start: str, end: str) -> list[str]:
    years = {**HOLIDAYS, **{int(k): v for k, v in read_calendar().get('years', {}).items()}}
    return calculate_days(start, end, holidays=years)


def calendar_trading_day(day: str) -> bool:
    if date.fromisoformat(day).weekday() >= 5:
        return False
    snapshot = read_calendar()
    if time.time()-snapshot.get('checked_at', 0) > MAX_AGE:
        raise ValueError('交易所日历未就绪或超过72小时未验证，本轮静默暂停，等待盘外更新')
    return bool(scheduled_trading_days(day, day))
