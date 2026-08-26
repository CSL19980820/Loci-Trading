"""A 股简化会话时钟（上海时区）。"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, time
from typing import Literal
from zoneinfo import ZoneInfo

_TZ = ZoneInfo("Asia/Shanghai")

SessionPhase = Literal["pre_auction", "auction", "open", "regular", "closed"]


@dataclass(frozen=True)
class SessionClock:
    phase: SessionPhase
    now: datetime
    in_auction: bool
    allow_open_fill: bool


def session_clock(now: datetime | None = None, *, auction_allow_open: bool = False) -> SessionClock:
    """A 股简化时钟（上海）。

    - ``auction``：09:15–09:25 集合竞价
    - ``open``：09:25–09:30 撮合后、连续竞价前（仍禁开仓，与扫描竞价窗对齐）
    - ``regular``：≥09:30 连续竞价时段才默认允许开仓成交
    """
    current = now.astimezone(_TZ) if now else datetime.now(_TZ)
    t = current.timetz().replace(tzinfo=None)
    if t < time(9, 15):
        phase: SessionPhase = "pre_auction"
    elif t < time(9, 25):
        phase = "auction"
    elif t < time(9, 30):
        phase = "open"
    elif time(9, 30) <= t < time(11, 30) or time(13, 0) <= t < time(15, 0):
        phase = "regular"
    else:
        phase = "closed"
    in_auction = phase == "auction"
    # 09:25–09:30（phase=open）与竞价窗同属禁开仓；仅 regular 或显式 auction_allow_open
    allow_open = phase == "regular" or (in_auction and auction_allow_open)
    return SessionClock(
        phase=phase,
        now=current,
        in_auction=in_auction,
        allow_open_fill=allow_open,
    )
