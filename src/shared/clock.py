"""统一的 UTC 时间戳。

这个格式是审计链上的字面量：run card、artifact、供应商记录、技能运行、行情
回执都按它写库并互相比对。此前 14 个模块各写一份 ``_now()``，任何一处改了
``timespec`` 都会让记录静默错位，所以收成一处。

**不要**把 ``ledger`` 的时间戳并进来：它刻意用本地时区 + 微秒，为的是让同一秒
内的快照与成交可排序（见 ``ledger/infrastructure/store_types.py``）。
"""
from __future__ import annotations

from datetime import datetime, timezone


def utc_now() -> str:
    """ISO-8601 UTC，秒级精度。"""
    return datetime.now(timezone.utc).isoformat(timespec="seconds")
