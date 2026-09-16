"""A股已公告的休市日程；不同于仅覆盖已入库行情的 trading_calendar。"""
from datetime import date, timedelta

CALENDAR_SOURCE = "https://www.sse.com.cn/disclosure/announcement/general/c/c_20251222_10802507.shtml"
HOLIDAYS = {2026: (("01-01", "01-03"), ("02-15", "02-23"), ("04-04", "04-06"),
                   ("05-01", "05-05"), ("06-19", "06-21"), ("09-25", "09-27"), ("10-01", "10-07"))}


def scheduled_trading_days(start: str, end: str, *, holidays: dict | None = None) -> list[str]:
    calendar = HOLIDAYS if holidays is None else holidays
    first, last = date.fromisoformat(start), date.fromisoformat(end)
    if any(year not in calendar for year in range(first.year, last.year + 1)):
        raise ValueError("所需年度的交易所休市日程尚未配置，不能按普通工作日猜测")
    result = []
    day = first
    while day <= last:
        mmdd = day.strftime("%m-%d")
        if day.weekday() < 5 and not any(a <= mmdd <= b for a, b in calendar[day.year]):
            result.append(day.isoformat())
        day += timedelta(days=1)
    return result
