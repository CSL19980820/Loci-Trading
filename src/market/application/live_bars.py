"""把 live 报价在内存聚成分钟 bar（环形缓冲，按交易日重置）。

**为什么不走 ``minute_bars`` lane**：那条 lane 是**逐票 HTTP**
（``application/minute.py`` → 通达信 / 东财 / 新浪）。大屏一轮几百只票就是几百次
外部请求，而 ``(spot_batch, 来源)`` 的在途名额只有 1，热循环里根本跑不动。
大屏要的只是「今日这一分钟的 OHLCV」，而 live 报价里已经带着最新价与**当日
累计**成交量/额，本地聚一下就够，一次外部请求都不用多加。

口径说明（都是会被问第二遍的地方）：

- 环形缓冲：每票最多 ``BARS_PER_DAY`` 根，超了自动丢最旧的，内存恒定；
- 按交易日重置：换日后第一笔进来就清空该票，不跨日拼接；
- ``volume``/``amount`` 是**当日累计值**，所以分钟量取相邻两次快照的差。
  当日第一笔没有前值可减，只能记 0——把开盘到此刻的累计量整个算进那一分钟
  会造出一根假巨量柱，比缺一根更糟；
- 差值为负（换源 / 上游回退）按 0 处理，**不编数**。

**铁律：绝不写库。** 这里的 bar 只活在进程内存里。
"""
from __future__ import annotations

from collections import deque
from dataclasses import dataclass, field
from datetime import datetime
import threading
from typing import Any, Deque

#: 一个交易日的分钟根数：09:30–11:30 + 13:00–15:00 共 240 分钟，含收盘那一根。
BARS_PER_DAY = 241


@dataclass
class MinuteBar:
    """一分钟聚合。``volume``/``amount`` 是该分钟的**增量**，不是累计。"""

    minute: str
    open: float
    high: float
    low: float
    close: float
    volume: float = 0.0
    amount: float = 0.0

    def as_dict(self) -> dict[str, Any]:
        return {
            "minute": self.minute, "open": self.open, "high": self.high,
            "low": self.low, "close": self.close, "volume": self.volume,
            "amount": self.amount,
        }


@dataclass
class _CodeState:
    day: str = ""
    bars: Deque[MinuteBar] = field(default_factory=lambda: deque(maxlen=BARS_PER_DAY))
    last_volume: float = 0.0
    last_amount: float = 0.0
    seeded: bool = False
    day_row: dict[str, Any] = field(default_factory=dict)


def _num(value: Any, default: float = 0.0) -> float:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return default
    return number if number == number and abs(number) != float("inf") else default


class LiveBarBook:
    """进程内分钟 bar 账本。线程安全：采集线程写、SSE 线程读。"""

    def __init__(self, *, capacity: int = BARS_PER_DAY) -> None:
        self._capacity = max(1, int(capacity))
        self._lock = threading.Lock()
        self._states: dict[str, _CodeState] = {}

    def ingest(self, rows: list[dict[str, Any]], *, now: datetime | None = None) -> int:
        """吃一批 live 报价，返回被更新的票数。"""
        moment = now or datetime.now()
        day, minute = moment.strftime("%Y-%m-%d"), moment.strftime("%H:%M")
        touched = 0
        with self._lock:
            for row in rows or []:
                code = str(row.get("code") or "").strip()
                price = _num(row.get("price"))
                if not code or price <= 0:
                    continue
                self._apply(code, row, price, day=day, minute=minute)
                touched += 1
        return touched

    def _apply(
        self, code: str, row: dict[str, Any], price: float, *, day: str, minute: str
    ) -> None:
        state = self._states.get(code)
        if state is None:
            state = _CodeState()
            state.bars = deque(maxlen=self._capacity)
            self._states[code] = state
        if state.day != day:
            # 换日：清空重来，不跨日拼接。
            state.day, state.seeded = day, False
            state.bars.clear()
            state.last_volume = state.last_amount = 0.0
        volume, amount = _num(row.get("volume")), _num(row.get("amount"))
        if state.seeded:
            delta_v = max(0.0, volume - state.last_volume)
            delta_a = max(0.0, amount - state.last_amount)
        else:
            # 当日第一笔：没有前值可减，记 0，见模块 docstring。
            delta_v = delta_a = 0.0
            state.seeded = True
        state.last_volume, state.last_amount = volume, amount
        state.day_row = {
            "trade_date": day,
            "open": _num(row.get("open"), price) or price,
            "high": _num(row.get("high"), price) or price,
            "low": _num(row.get("low"), price) or price,
            "close": price,
            "volume": volume,
            "amount": amount,
            "prev_close": _num(row.get("prev_close"), price) or price,
        }
        if state.bars and state.bars[-1].minute == minute:
            bar = state.bars[-1]
            bar.high, bar.low = max(bar.high, price), min(bar.low, price)
            bar.close = price
            bar.volume += delta_v
            bar.amount += delta_a
        else:
            state.bars.append(
                MinuteBar(minute, price, price, price, price, delta_v, delta_a)
            )

    def bars(self, code: str, *, limit: int = 0) -> list[dict[str, Any]]:
        """某票今日的分钟 bar（旧 → 新）。``limit>0`` 时只取末尾 N 根。"""
        with self._lock:
            state = self._states.get(str(code).strip())
            items = [bar.as_dict() for bar in state.bars] if state else []
        return items[-limit:] if limit > 0 else items

    def day_bar(self, code: str) -> dict[str, Any] | None:
        """今日**未完成** bar：直接取最近一笔报价的当日 OHLCV，口径最准。

        不要用分钟增量求和来凑当日量——第一笔的基线被记成 0，求和必然偏小。
        """
        with self._lock:
            state = self._states.get(str(code).strip())
            return dict(state.day_row) if state and state.day_row else None

    def codes(self) -> list[str]:
        with self._lock:
            return sorted(self._states)

    def reset(self) -> None:
        with self._lock:
            self._states.clear()

    def stats(self) -> dict[str, Any]:
        with self._lock:
            days = {state.day for state in self._states.values() if state.day}
            return {
                "codes": len(self._states),
                "bars": sum(len(state.bars) for state in self._states.values()),
                "capacity": self._capacity,
                "days": sorted(days),
            }


_BOOK_LOCK = threading.Lock()
_BOOK: LiveBarBook | None = None


def get_live_bars() -> LiveBarBook:
    """进程级单例账本。"""
    global _BOOK
    with _BOOK_LOCK:
        if _BOOK is None:
            _BOOK = LiveBarBook()
        return _BOOK


def reset_live_bars() -> None:
    global _BOOK
    with _BOOK_LOCK:
        _BOOK = None


__all__ = [
    "BARS_PER_DAY", "LiveBarBook", "MinuteBar", "get_live_bars", "reset_live_bars",
]
