"""账本回放：把不可变的事件流还原成任意一天的持仓。

这是复盘的地基。市值曲线、逐笔归因、候选池验证三件事都要先回答同一个
问题——**那天收盘时我到底持有什么**。此前 ``list_positions()`` 只能给出
"现在"的快照，任何历史视角都无从谈起。

## 为什么不重算成本

``position_events`` 每一行都存了 ``shares_after`` / ``cost_after``，
即写入当时就已经算好的仓位状态。回放只需要取"截至该日期的最后一条事件"，
不必重跑一遍加权成本逻辑。这很重要：账本用的是移动加权成本，且卖出时会
把已实现盈亏摊回余票成本（用户的长期规则）。重算等于把这套规则再实现
一遍，两份实现迟早分叉；直接读取则永远与账本一致。

## 持仓周期（round trip）

归因的单位是"持仓周期"——从空仓建仓到清仓算一段——而不是 FIFO 批次。
账本的加权成本口径下批次身份在成交那一刻就被抹平了，硬做 FIFO 要维护
第二套并行账本，心智负担不值。按周期算 MAE/MFE 与持有天数，语义直观，
也和此前手工回测的口径一致。
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from src.palace import PalaceStore, normalize_code


@dataclass
class HeldPosition:
    code: str
    name: str
    shares: int
    cost: float

    @property
    def cost_value(self) -> float:
        return round(self.shares * self.cost, 2)


@dataclass
class RoundTrip:
    """一个完整或仍在持有的持仓周期。"""

    code: str
    name: str
    opened_on: str
    closed_on: str | None
    peak_shares: int
    buy_amount: float
    sell_amount: float
    realized_pnl: float
    event_ids: list[str] = field(default_factory=list)
    #: 需要行情才能算的部分，由 attribution 模块回填。
    mae_pct: float | None = None
    mfe_pct: float | None = None
    hold_days: int | None = None

    @property
    def is_open(self) -> bool:
        return self.closed_on is None

    @property
    def avg_cost(self) -> float:
        return round(self.buy_amount / self.peak_shares, 4) if self.peak_shares else 0.0

    @property
    def return_pct(self) -> float | None:
        """已清仓周期的收益率。仍在持有的返回 None——浮盈不是收益。"""
        if self.is_open or self.buy_amount <= 0:
            return None
        return round(self.realized_pnl / self.buy_amount * 100, 4)

    def to_dict(self) -> dict[str, Any]:
        return {
            "code": self.code,
            "name": self.name,
            "opened_on": self.opened_on,
            "closed_on": self.closed_on,
            "is_open": self.is_open,
            "peak_shares": self.peak_shares,
            "avg_cost": self.avg_cost,
            "buy_amount": round(self.buy_amount, 2),
            "sell_amount": round(self.sell_amount, 2),
            "realized_pnl": round(self.realized_pnl, 2),
            "return_pct": self.return_pct,
            "hold_days": self.hold_days,
            "mae_pct": self.mae_pct,
            "mfe_pct": self.mfe_pct,
            "event_ids": self.event_ids,
        }


def _ordered_events(store: PalaceStore, *, until: str | None = None) -> list[dict[str, Any]]:
    """按发生顺序取事件。

    同日多笔必须严格按写入顺序回放，否则"那天收盘持有多少"会取到中间
    状态而不是当日最终状态。

    排序键用 **rowid** 而不是 created_at：created_at 只精确到秒，同一秒内
    录入的几笔时间戳完全相同，排序就会退化成按 id 排——而 id 是随机 UUID，
    等于任意顺序。实测同日三笔（买1000、买500、卖200）会被回放成 1000 股
    而不是正确的 1300 股。

    rowid 是 SQLite 的隐式插入序号，与 shares_before/shares_after 这条链
    被计算出来的顺序严格一致，是这里唯一可靠的排序依据。
    """
    sql = "SELECT rowid AS _seq, * FROM position_events"
    params: list[Any] = []
    if until:
        sql += " WHERE occurred_on <= ?"
        params.append(until)
    sql += " ORDER BY occurred_on ASC, _seq ASC"
    return [dict(row) for row in store.conn.execute(sql, params)]


def positions_as_of(store: PalaceStore, trade_date: str | None = None) -> list[HeldPosition]:
    """某个日期收盘时的持仓。trade_date 为空表示"当前"。

    直接取每只票截至该日的最后一条事件的 shares_after / cost_after，
    不重算成本——见模块文档。
    """
    latest: dict[str, dict[str, Any]] = {}
    for event in _ordered_events(store, until=trade_date):
        latest[str(event["code"])] = event

    held: list[HeldPosition] = []
    for code, event in sorted(latest.items()):
        shares = int(event["shares_after"] or 0)
        if shares <= 0:
            continue
        held.append(
            HeldPosition(
                code=code,
                name=str(event["name"] or ""),
                shares=shares,
                cost=float(event["cost_after"] or 0.0),
            )
        )
    return held


def holdings_timeline(store: PalaceStore) -> dict[str, dict[str, int]]:
    """每个有事件发生的日期 → {代码: 当日收盘持股数}。

    只在持仓**变化**的日子产生条目；两次变化之间持仓不变，由市值曲线
    模块自己前向填充。这样即便账本跨越十年，这里也只有几十条记录。
    """
    snapshots: dict[str, dict[str, int]] = {}
    running: dict[str, int] = {}
    for event in _ordered_events(store):
        code = str(event["code"])
        shares = int(event["shares_after"] or 0)
        if shares > 0:
            running[code] = shares
        else:
            running.pop(code, None)
        snapshots[str(event["occurred_on"])] = dict(running)
    return snapshots


def round_trips(store: PalaceStore, *, code: str | None = None) -> list[RoundTrip]:
    """把事件流切成持仓周期。

    一段周期从"持股数由 0 变正"开始，到"回到 0"结束。仍在持有的会作为
    未闭合周期返回——它们没有收益率（浮盈不是收益），但需要出现在
    归因里，否则"我现在扛着的这几只"就从复盘中消失了。
    """
    wanted = normalize_code(code) if code else None
    trips: list[RoundTrip] = []
    active: dict[str, RoundTrip] = {}

    for event in _ordered_events(store):
        current = str(event["code"])
        if wanted and current != wanted:
            continue

        before = int(event["shares_before"] or 0)
        after = int(event["shares_after"] or 0)
        shares = int(event["shares"] or 0)
        price = float(event["price"] or 0.0)
        action = str(event["action"])

        trip = active.get(current)
        if trip is None and before <= 0 < after:
            trip = RoundTrip(
                code=current,
                name=str(event["name"] or ""),
                opened_on=str(event["occurred_on"]),
                closed_on=None,
                peak_shares=0,
                buy_amount=0.0,
                sell_amount=0.0,
                realized_pnl=0.0,
            )
            active[current] = trip
        if trip is None:
            # 没有开仓记录却出现卖出：账本被手工改过或导入不完整。
            # 跳过而不是崩，但不静默——调用方能从 event_ids 的缺口看出来。
            continue

        trip.event_ids.append(str(event["id"]))
        if action in ("OPENING", "BUY"):
            trip.buy_amount += shares * price
        else:
            trip.sell_amount += shares * price
        trip.realized_pnl += float(event["realized_pnl"] or 0.0)
        trip.peak_shares = max(trip.peak_shares, after, before)

        if after <= 0:
            trip.closed_on = str(event["occurred_on"])
            trips.append(trip)
            active.pop(current, None)

    trips.extend(active.values())
    trips.sort(key=lambda item: (item.opened_on, item.code))
    return trips
