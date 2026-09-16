from datetime import datetime
from types import SimpleNamespace
from zoneinfo import ZoneInfo
from unittest.mock import Mock
import pytest
from src.ops.application import notify_calendar
from src.ops.application.notify_dispatch import dispatch_text
from src.ops.application.notify_registry import dispatch_report
from src.ops.application.notify import send_wecom_text
from src.ops.application.notify_bark import send_bark_text
from src.ops.domain.notify import NotifyMessage


@pytest.mark.parametrize('day',['2026-09-25','2026-10-01','2026-09-20'])
def test_holiday_mutes_all_business_channels_even_critical_bypass(day,monkeypatch):
    import time
    from src.market.infrastructure import exchange_calendar
    from src.market.domain.exchange_schedule import HOLIDAYS
    monkeypatch.setattr(exchange_calendar,'read_calendar',lambda:{'checked_at':time.time(),'years':{str(k):v for k,v in HOLIDAYS.items()}})
    now=datetime.fromisoformat(day+'T10:00:00').replace(tzinfo=ZoneInfo('Asia/Shanghai'))
    monkeypatch.setattr(notify_calendar,'datetime',SimpleNamespace(now=lambda tz:now))
    transport=Mock(side_effect=AssertionError('holiday sent'))
    monkeypatch.setattr('urllib.request.urlopen',transport)
    result=dispatch_text(Mock(),title='日常报告',body='test',level='critical',bypass_quiet=True,bypass_rate_limit=True)
    assert result['skipped']=='market_closed' and not result['sent']
    result=dispatch_report(Mock(),NotifyMessage(title='x',body='y'),channels=['wecom','feishu','dingtalk','email','inbox','webhook'],bypass_rate_limit=True)
    assert result['skipped']=='market_closed' and not result['sent']
    assert send_wecom_text('unused','test')['skipped']=='market_closed'
    assert send_bark_text(device_key='unused',title='x',body='y')['skipped']=='market_closed'
    transport.assert_not_called()
