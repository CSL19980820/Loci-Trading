import json
import time
from datetime import datetime
from types import SimpleNamespace
from unittest.mock import Mock
import pytest
from src.market.infrastructure import exchange_calendar as calendar
from src.market.domain.exchange_schedule import HOLIDAYS


def document(year=2026):
    names = ('元旦','春节','清明','劳动','端午','中秋','国庆')
    rows = ''.join(f'<tr><td>{name}：{int(a[:2])}月{int(a[3:])}日（星期一）至{int(b[:2])}月{int(b[3:])}日（星期二）休市</td></tr>' for name,(a,b) in zip(names,HOLIDAYS[2026]))
    return f'<strong>{year}年休市安排</strong><table>{rows}</table>'


def test_parse_requires_complete_official_year_and_holidays():
    year, spans = calendar.parse_schedule(document(2027))
    assert year==2027 and spans[-1]==['10-01','10-07']
    import re
    combined = re.sub(r'<tr><td>中秋：.*?</tr>', '', document(2027)).replace('国庆：', '国庆、中秋：')
    assert len(calendar.parse_schedule(combined)[1]) == 6
    with pytest.raises(ValueError):
        calendar.parse_schedule('<strong>2027年休市安排</strong><table><tr><td>未知</td></tr></table>')


def test_refresh_rollover_atomic_failure_and_no_intraday_network(tmp_path,monkeypatch):
    path=tmp_path/'calendar.json'
    monkeypatch.setattr(calendar,'calendar_path',lambda:path)
    monkeypatch.setattr(calendar,'datetime',SimpleNamespace(now=lambda tz: datetime(2026,12,28,18,30,tzinfo=tz)))
    response=Mock(); response.__enter__=Mock(return_value=response); response.__exit__=Mock(return_value=None)
    response.read.return_value=document(2027).encode()
    fetch=Mock(return_value=response); monkeypatch.setattr(calendar.urllib.request,'urlopen',fetch)
    calendar.refresh_exchange_calendar(force=True)
    saved=json.loads(path.read_text())
    assert '2026' in saved['years'] and '2027' in saved['years']
    assert not calendar.calendar_trading_day('2026-09-25')
    assert calendar.calendar_trading_day('2026-09-24')
    before=path.read_bytes()
    response.read.return_value=b'broken'
    with pytest.raises(ValueError): calendar.refresh_exchange_calendar(force=True)
    assert path.read_bytes()==before and not list(tmp_path.glob('*.tmp'))
    fetch.reset_mock()
    monkeypatch.setattr(calendar,'datetime',SimpleNamespace(now=lambda tz: datetime(2026,9,14,10,tzinfo=tz)))
    with pytest.raises(ValueError,match='盘外'): calendar.refresh_exchange_calendar(force=True)
    fetch.assert_not_called()


def test_missing_stale_and_unknown_year_fail_closed(tmp_path,monkeypatch):
    path=tmp_path/'calendar.json'; monkeypatch.setattr(calendar,'calendar_path',lambda:path)
    with pytest.raises(ValueError): calendar.calendar_trading_day('2026-09-14')
    path.write_text(json.dumps({'checked_at':time.time()-73*3600,'years':{}}))
    with pytest.raises(ValueError): calendar.calendar_trading_day('2026-09-14')
    path.write_text(json.dumps({'checked_at':time.time(),'years':{}}))
    with pytest.raises(ValueError): calendar.calendar_trading_day('2027-01-04')
    assert not calendar.calendar_trading_day('2026-09-20')
