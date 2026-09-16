"""盘外更新公共日历，不推送机器人消息。"""
from src.market import refresh_exchange_calendar


def execute_exchange_calendar(config, context):
    return refresh_exchange_calendar(force=bool(config.get('force')))
