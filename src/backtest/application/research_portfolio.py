"""组合层研究分析。

``engine.run_backtest`` 仍然是一笔信号一笔交易的权威事件回测。本模块只
在其输出之上建立固定资金槽位的研究账本，因此不会改变已有成交口径或四
战法的默认参数。

组合层有意采用保守假设：同一槽位在 ``exit_date`` 当天收盘前不可再次使
用；没有完整退出的 ``data_end`` 交易默认跳过；没有逐日标记价时，持仓按
入场名义本金保留到退出日，未把 MAE/MFE 伪装成逐日净值。
"""
from __future__ import annotations

from collections import defaultdict
from dataclasses import asdict, dataclass, field
from datetime import date
from math import floor, isfinite
from typing import Any, Iterable, Sequence

from src.backtest.application.engine import Trade, compute_metrics
from src.shared.jsonify import jsonable as _jsonable


class PortfolioResearchError(ValueError):
    """组合研究输入不满足可审计契约。"""


def _iso(value: str | date) -> str:
    text = value.isoformat() if isinstance(value, date) else str(value).strip()
    try:
        date.fromisoformat(text)
    except ValueError as exc:
        raise PortfolioResearchError(f"日期格式无效：{text}") from exc
    return text


def _round(value: float | int | None, digits: int = 6) -> float | None:
    if value is None:
        return None
    number = float(value)
    return round(number, digits) if isfinite(number) else None


@dataclass(frozen=True, slots=True)
class PortfolioResearchConfig:
    """组合资金假设。

    ``max_positions`` 是固定资金槽位数，不是强制满仓数量；无法成交或槽位
    被占用时保持现金。A 股默认按 100 股整手计算；其他市场/合成数据必须
    显式传入适合的 ``lot_size``。
    """

    initial_capital: float = 200_000.0
    max_positions: int = 2
    lot_size: int = 100
    period: str = "month"
    include_data_end: bool = False
    allow_same_code_overlap: bool = False

    def __post_init__(self) -> None:
        if not isfinite(float(self.initial_capital)) or self.initial_capital <= 0:
            raise PortfolioResearchError("initial_capital 必须是正数")
        if int(self.max_positions) != self.max_positions or self.max_positions <= 0:
            raise PortfolioResearchError("max_positions 必须是正整数")
        if int(self.lot_size) != self.lot_size or self.lot_size <= 0:
            raise PortfolioResearchError("lot_size 必须是正整数")
        if self.period not in {"day", "month", "quarter", "year"}:
            raise PortfolioResearchError("period 仅支持 day/month/quarter/year")

    @property
    def slot_capital(self) -> float:
        return float(self.initial_capital) / int(self.max_positions)

    def to_dict(self) -> dict[str, Any]:
        body = asdict(self)
        body["slot_capital"] = _round(self.slot_capital, 4)
        return body


# Short name for callers that already use the generic backtest vocabulary.
PortfolioConfig = PortfolioResearchConfig


@dataclass(frozen=True, slots=True)
class PortfolioAllocation:
    """一笔被组合资金槽位接受的成交。"""

    code: str
    signal_date: str
    entry_date: str
    exit_date: str
    slot: int
    quantity: int
    entry_notional: float
    exit_notional: float
    pnl: float
    gross_return_pct: float
    net_return_pct: float
    turnover_notional: float

    def to_dict(self) -> dict[str, Any]:
        body = asdict(self)
        for key in (
            "entry_notional",
            "exit_notional",
            "pnl",
            "gross_return_pct",
            "net_return_pct",
            "turnover_notional",
        ):
            body[key] = _round(body[key])
        return body


@dataclass(frozen=True, slots=True)
class PortfolioDay:
    """观察日资金快照。

    ``capital_in_use`` 在退出成交前统计，因此退出日仍算占用；同日退出的
    现金只能到下一观察日再次使用，避免没有时分数据时制造同日回转。
    """

    date: str
    equity: float
    cash: float
    idle_cash: float
    capital_in_use: float
    open_positions: int
    realized_pnl: float
    turnover_notional: float
    entries: int
    exits: int

    def to_dict(self) -> dict[str, Any]:
        body = asdict(self)
        for key in (
            "equity",
            "cash",
            "idle_cash",
            "capital_in_use",
            "realized_pnl",
            "turnover_notional",
        ):
            body[key] = _round(body[key])
        return body


@dataclass(frozen=True, slots=True)
class PortfolioSegment:
    """按月/季/年汇总的资金和交易片段。"""

    key: str
    start: str
    end: str
    sample_size: int
    entries: int
    exits: int
    net_pnl: float
    avg_net_return_pct: float | None
    win_rate: float | None
    turnover_notional: float
    capital_days: float
    avg_capital_utilization_pct: float
    max_capital_utilization_pct: float
    idle_cash_days: int
    idle_cash_pct: float
    max_drawdown_pct: float

    def to_dict(self) -> dict[str, Any]:
        body = asdict(self)
        for key in (
            "net_pnl",
            "avg_net_return_pct",
            "win_rate",
            "turnover_notional",
            "capital_days",
            "avg_capital_utilization_pct",
            "max_capital_utilization_pct",
            "idle_cash_pct",
            "max_drawdown_pct",
        ):
            body[key] = _round(body[key])
        return body


@dataclass
class PortfolioResearchResult:
    """组合研究结果，可直接写入 run card 的 JSON 字段。"""

    config: dict[str, Any]
    sample_size: int
    accepted_trades: int
    time_range: dict[str, str | None]
    metrics: dict[str, Any]
    allocations: list[PortfolioAllocation] = field(default_factory=list)
    daily: list[PortfolioDay] = field(default_factory=list)
    segments: list[PortfolioSegment] = field(default_factory=list)
    skipped: dict[str, int] = field(default_factory=dict)
    failures: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        """返回只含基础类型的稳定结构；``inf`` 等不可 JSON 值转为 null。"""
        return {
            "contract_version": "backtest-portfolio-research-v1",
            "config": dict(self.config),
            "sample_size": int(self.sample_size),
            "accepted_trades": int(self.accepted_trades),
            "time_range": dict(self.time_range),
            "metrics": _jsonable(self.metrics),
            "allocations": [item.to_dict() for item in self.allocations],
            "daily": [item.to_dict() for item in self.daily],
            "segments": [item.to_dict() for item in self.segments],
            "skipped": dict(self.skipped),
            "failures": list(self.failures),
        }




def _period_key(value: str, period: str) -> str:
    parsed = date.fromisoformat(value)
    if period == "day":
        return value
    if period == "month":
        return f"{parsed.year:04d}-{parsed.month:02d}"
    if period == "quarter":
        return f"{parsed.year:04d}-Q{(parsed.month - 1) // 3 + 1}"
    return f"{parsed.year:04d}"


def _coerce_trade_list(trades: Iterable[Trade]) -> list[Trade]:
    return list(trades)


def _candidate_sort_key(item: tuple[int, Trade]) -> tuple[str, str, str, int]:
    index, trade = item
    return (str(trade.entry_date), str(trade.signal_date), str(trade.code), index)


def analyze_portfolio(
    trades: Iterable[Trade],
    *,
    config: PortfolioResearchConfig | None = None,
    trading_dates: Sequence[str] | None = None,
    strategy_slug: str = "",
) -> PortfolioResearchResult:
    """将单笔事件按固定槽位编排成组合研究账本。

    输入交易会先按入场日、信号日、代码稳定排序；因此同一输入在不同
    ``set``/字典顺序下也产生相同结果。资金不可用、重复信号和不完整尾部
    交易都进入 ``skipped``，不会静默递补弱候选。
    """
    cfg = config or PortfolioResearchConfig()
    candidates = _coerce_trade_list(trades)
    skipped: dict[str, int] = defaultdict(int)
    failures: list[str] = []
    valid_dates: set[str] = set()
    for item in candidates:
        try:
            valid_dates.add(_iso(item.entry_date))
            valid_dates.add(_iso(item.exit_date))
        except PortfolioResearchError:
            skipped["日期无效"] += 1
    if trading_dates is not None:
        calendar: set[str] = set()
        for value in trading_dates:
            try:
                calendar.add(_iso(value))
            except PortfolioResearchError:
                skipped["交易日历日期无效"] += 1
        valid_dates.update(calendar)
    dates = sorted(valid_dates)

    # ``(slot, trade, allocation)``；slot 只有在该交易完全退出后才释放。
    occupied: dict[int, PortfolioAllocation] = {}
    accepted: list[PortfolioAllocation] = []
    seen_keys: set[tuple[str, str]] = set()
    ordered = sorted(enumerate(candidates), key=_candidate_sort_key)
    exits_by_date: dict[str, list[PortfolioAllocation]] = defaultdict(list)
    entries_turnover_by_date: dict[str, float] = defaultdict(float)

    cash = float(cfg.initial_capital)
    daily: list[PortfolioDay] = []
    equity_curve: list[float] = [cash]
    for day in dates:
        # 退出日当天不能在开盘前释放槽位；只释放更早已经结算的持仓。
        for slot, allocation in list(occupied.items()):
            if allocation.exit_date < day:
                cash += allocation.exit_notional
                del occupied[slot]

        entries_today = [pair for pair in ordered if _safe_date(pair[1].entry_date) == day]
        accepted_today: list[PortfolioAllocation] = []
        for original_index, trade in entries_today:
            key = (str(trade.code), day)
            if key in seen_keys:
                skipped["重复代码同日信号"] += 1
                continue
            seen_keys.add(key)
            if trade.exit_reason == "data_end" and not cfg.include_data_end:
                skipped["data_end不纳入组合"] += 1
                continue
            if not _valid_trade_numbers(trade):
                skipped["交易字段无效"] += 1
                continue
            if not cfg.allow_same_code_overlap and any(
                current.code == trade.code for current in occupied.values()
            ):
                skipped["同代码持仓冲突"] += 1
                continue
            free_slots = [slot for slot in range(cfg.max_positions) if slot not in occupied]
            if not free_slots:
                skipped["资金槽位已占用"] += 1
                continue
            slot = free_slots[0]
            entry_price = float(trade.entry_price)
            # 以固定槽位容量购买整手；默认 100 股，其他市场需显式覆盖。
            quantity = floor(cfg.slot_capital / entry_price / cfg.lot_size) * cfg.lot_size
            if quantity <= 0:
                skipped["槽位不足一手"] += 1
                continue
            entry_notional = quantity * entry_price
            # 组合现金必须按已扣成本的净收益结算；使用 gross 会让最终
            # equity 与交易指标不一致，尤其在短持有期会系统性高估结果。
            net_factor = max(0.0, 1.0 + float(trade.net_return_pct) / 100.0)
            exit_notional = entry_notional * net_factor
            pnl = entry_notional * float(trade.net_return_pct) / 100.0
            allocation = PortfolioAllocation(
                code=str(trade.code),
                signal_date=str(trade.signal_date),
                entry_date=day,
                exit_date=_safe_date(trade.exit_date) or day,
                slot=slot,
                quantity=int(quantity),
                entry_notional=entry_notional,
                exit_notional=exit_notional,
                pnl=pnl,
                gross_return_pct=float(trade.gross_return_pct),
                net_return_pct=float(trade.net_return_pct),
                turnover_notional=entry_notional + exit_notional,
            )
            if allocation.exit_date < day:
                skipped["退出日在入场日前"] += 1
                continue
            if cash + 1e-8 < entry_notional:
                skipped["可用现金不足"] += 1
                continue
            cash -= entry_notional
            occupied[slot] = allocation
            accepted.append(allocation)
            accepted_today.append(allocation)
            entries_turnover_by_date[day] += entry_notional
            exits_by_date[allocation.exit_date].append(allocation)

        capital_in_use = sum(item.entry_notional for item in occupied.values())
        idle_cash = max(0.0, cash)
        # 退出处理在入场后执行，故同日退出不能再塞入新仓位。
        exits_today = exits_by_date.get(day, [])
        realized = 0.0
        turnover_today = entries_turnover_by_date.get(day, 0.0)
        for allocation in exits_today:
            if occupied.get(allocation.slot) != allocation:
                continue
            cash += allocation.exit_notional
            realized += allocation.pnl
            turnover_today += allocation.exit_notional
            del occupied[allocation.slot]
        equity = cash + sum(item.entry_notional for item in occupied.values())
        equity_curve.append(equity)
        daily.append(
            PortfolioDay(
                date=day,
                equity=equity,
                cash=cash,
                idle_cash=idle_cash,
                capital_in_use=capital_in_use,
                open_positions=len(occupied) + len(exits_today),
                realized_pnl=realized,
                turnover_notional=turnover_today,
                entries=len(accepted_today),
                exits=len(exits_today),
            )
        )

    # Any allocation whose exit is beyond the supplied calendar remains open;
    # the input itself is still complete, so settle it at the known exit date in
    # the summary rather than inventing an extra mark-to-market observation.
    for allocation in list(occupied.values()):
        cash += allocation.exit_notional
        occupied.pop(allocation.slot, None)

    final_equity = float(cash)
    initial = float(cfg.initial_capital)
    net_pnl = final_equity - initial
    turnover_total = sum(item.turnover_notional for item in accepted)
    util_values = [item.capital_in_use / initial * 100.0 for item in daily]
    idle_values = [item.idle_cash / initial * 100.0 for item in daily]
    peak = initial
    max_drawdown = 0.0
    for value in equity_curve:
        peak = max(peak, value)
        if peak > 0:
            max_drawdown = min(max_drawdown, (value / peak - 1.0) * 100.0)
    capital_days = sum(item.capital_in_use for item in daily)
    idle_days = sum(1 for item in daily if item.idle_cash > 1e-8)
    metrics = {
        "strategy_slug": strategy_slug,
        "initial_capital": _round(initial, 4),
        "final_equity": _round(final_equity, 4),
        "net_pnl": _round(net_pnl, 4),
        "return_pct": _round(net_pnl / initial * 100.0, 4),
        "sample_size": len(candidates),
        "accepted_trades": len(accepted),
        "turnover_notional": _round(turnover_total, 4),
        "turnover_ratio": _round(turnover_total / initial, 6),
        "turnover_pct": _round(turnover_total / initial * 100.0, 4),
        "capital_days": _round(capital_days, 4),
        "avg_capital_utilization_pct": _round(
            sum(util_values) / len(util_values) if util_values else 0.0, 4
        ),
        "max_capital_utilization_pct": _round(max(util_values) if util_values else 0.0, 4),
        "idle_cash_days": idle_days,
        "observed_days": len(daily),
        "idle_cash_pct": _round(idle_days / len(daily) * 100.0 if daily else 100.0, 4),
        "avg_idle_cash_pct": _round(sum(idle_values) / len(idle_values) if idle_values else 100.0, 4),
        "max_drawdown_pct": _round(max_drawdown, 4),
        "exit_reasons": _count_allocations_by_reason(accepted, candidates),
    }
    segments = _build_segments(accepted, daily, cfg, initial)
    if not candidates:
        failures.append("没有输入交易")
    elif not accepted:
        failures.append("没有交易被组合资金槽位接受")
    return PortfolioResearchResult(
        config={**cfg.to_dict(), "strategy_slug": strategy_slug},
        sample_size=len(candidates),
        accepted_trades=len(accepted),
        time_range={"start": dates[0] if dates else None, "end": dates[-1] if dates else None},
        metrics=metrics,
        allocations=accepted,
        daily=daily,
        segments=segments,
        skipped=dict(skipped),
        failures=failures,
    )


def _safe_date(value: Any) -> str | None:
    try:
        return _iso(str(value))
    except PortfolioResearchError:
        return None


def _valid_trade_numbers(trade: Trade) -> bool:
    for value in (
        trade.entry_price,
        trade.exit_price,
        trade.gross_return_pct,
        trade.net_return_pct,
    ):
        if not isfinite(float(value)):
            return False
    return bool(_safe_date(trade.entry_date) and _safe_date(trade.exit_date))


def _count_allocations_by_reason(allocations: Sequence[PortfolioAllocation], candidates: Sequence[Trade]) -> dict[str, int]:
    by_code_date = {(item.code, item.entry_date) for item in allocations}
    out: dict[str, int] = defaultdict(int)
    for trade in candidates:
        key = (str(trade.code), _safe_date(trade.entry_date) or "")
        if key in by_code_date:
            out[trade.exit_reason] += 1
    return dict(out)


def _build_segments(
    allocations: Sequence[PortfolioAllocation],
    daily: Sequence[PortfolioDay],
    cfg: PortfolioResearchConfig,
    initial: float,
) -> list[PortfolioSegment]:
    by_key: dict[str, list[PortfolioDay]] = defaultdict(list)
    for item in daily:
        by_key[_period_key(item.date, cfg.period)].append(item)
    peak = initial
    drawdown_by_day: dict[str, float] = {}
    for item in daily:
        peak = max(peak, item.equity)
        drawdown_by_day[item.date] = (item.equity / peak - 1.0) * 100.0 if peak else 0.0
    result: list[PortfolioSegment] = []
    for key in sorted(by_key):
        days = by_key[key]
        items = [
            item
            for item in allocations
            if _period_key(item.exit_date, cfg.period) == key
        ]
        net_returns = [item.net_return_pct for item in items]
        util = [item.capital_in_use / initial * 100.0 for item in days]
        idle = [item.idle_cash > 1e-8 for item in days]
        result.append(
            PortfolioSegment(
                key=key,
                start=days[0].date,
                end=days[-1].date,
                sample_size=len(items),
                entries=sum(item.entries for item in days),
                exits=sum(item.exits for item in days),
                net_pnl=sum(item.pnl for item in items),
                avg_net_return_pct=(sum(net_returns) / len(net_returns) if net_returns else None),
                win_rate=(sum(value > 0 for value in net_returns) / len(net_returns) * 100.0 if net_returns else None),
                # 日快照同时记录入场和退出名义额；按观察日归属，避免把
                # 一整笔 round-trip 错记到退出月份。
                turnover_notional=sum(item.turnover_notional for item in days),
                capital_days=sum(item.capital_in_use for item in days),
                avg_capital_utilization_pct=sum(util) / len(util) if util else 0.0,
                max_capital_utilization_pct=max(util) if util else 0.0,
                idle_cash_days=sum(idle),
                idle_cash_pct=sum(idle) / len(idle) * 100.0 if idle else 100.0,
                max_drawdown_pct=min(drawdown_by_day.get(item.date, 0.0) for item in days),
            )
        )
    return result
