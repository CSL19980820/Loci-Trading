"""全系统业务通知休市静默；通道测试和严重级别也不绕过。"""
from datetime import datetime
from zoneinfo import ZoneInfo
from src.market import calendar_trading_day


def notification_silence_reason(now: datetime | None = None) -> str:
    current = now or datetime.now(ZoneInfo('Asia/Shanghai'))
    try:
        return '' if calendar_trading_day(current.astimezone(ZoneInfo('Asia/Shanghai')).date().isoformat()) else 'market_closed'
    except ValueError:
        return 'calendar_unavailable'
