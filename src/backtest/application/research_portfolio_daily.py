"""Cash-constrained daily economic marks, with terminal positions left open."""

from __future__ import annotations

from collections import Counter, defaultdict
from dataclasses import asdict, dataclass
from math import floor, isclose, isfinite
from typing import Any, Iterable, Sequence

import pandas as pd

from src.backtest.domain.models import Trade

from .research_portfolio import (
    PortfolioAllocation,
    PortfolioDay,
    PortfolioResearchConfig,
    PortfolioResearchError,
    PortfolioResearchResult,
    PortfolioSegment,
    _build_segments,
    _round,
)
from .research_portfolio_marks import (
    PortfolioInvariantError,
    assert_cash_conservation,
    drawdown_pct,
)
from .research_portfolio_prices import DailyPrices, EconomicMark, _day


@dataclass(frozen=True, slots=True)
class _ClosedAllocation(PortfolioAllocation):
    entry_cost: float = 0.0
    exit_cost: float = 0.0

    def to_dict(self) -> dict[str, Any]:
        result = PortfolioAllocation.to_dict(self)
        for name in ("entry_cost", "exit_cost"):
            result[name] = _round(result[name])
        return result


@dataclass(frozen=True, slots=True)
class _DailySegment(PortfolioSegment):
    avg_idle_cash_pct: float = 0.0

    def to_dict(self) -> dict[str, Any]:
        result = PortfolioSegment.to_dict(self)
        result["avg_idle_cash_pct"] = _round(self.avg_idle_cash_pct)
        return result


@dataclass(slots=True)
class _Position:
    trade: Trade
    slot: int
    quantity: int
    capital: float
    entry_cost: float
    cost_rate: float
    entry_factor: float
    mark: EconomicMark

    @property
    def market_value(self) -> float:
        return self.quantity * self.mark.price / self.entry_factor

    @property
    def unrealized_pnl(self) -> float:
        return self.market_value - self.capital - self.entry_cost

    def open_dict(self, as_of: str) -> dict[str, Any]:
        return {
            "code": str(self.trade.code),
            "signal_date": _day(self.trade.signal_date),
            "entry_date": _day(self.trade.entry_date),
            "slot": self.slot,
            "quantity": self.quantity,
            "status": "open",
            "as_of": as_of,
            "entry_price": float(self.trade.entry_price),
            "entry_factor": self.entry_factor,
            "entry_notional": self.capital,
            "entry_cost": self.entry_cost,
            "mark_date": self.mark.date,
            "raw_close": self.mark.raw_close,
            "adjustment_factor": self.mark.factor,
            "market_value": self.market_value,
            "unrealized_pnl": self.unrealized_pnl,
            "unrealized_return_pct": self.unrealized_pnl / self.capital * 100.0,
        }


def _positive(value: Any, name: str) -> float:
    try:
        number = float(value)
    except (TypeError, ValueError) as exc:
        raise PortfolioResearchError(f"{name} 必须是有限正数") from exc
    if not isfinite(number) or number <= 0:
        raise PortfolioResearchError(f"{name} 必须是有限正数")
    return number


def _entry_terms(trade: Trade, prices: DailyPrices) -> tuple[float, float, float]:
    price = _positive(trade.entry_price, "entry_price")
    entry_factor = _positive(getattr(trade, "entry_factor", 1.0), "entry_factor")
    exit_factor = _positive(getattr(trade, "exit_factor", 1.0), "exit_factor")
    if prices.factors is None and (entry_factor != 1.0 or exit_factor != 1.0):
        raise PortfolioResearchError("非单位Trade复权因子需要adjustment_factors面板")
    try:
        cost = (float(trade.gross_return_pct) - float(trade.net_return_pct)) / 100.0
    except (TypeError, ValueError) as exc:
        raise PortfolioResearchError("gross/net收益必须能推导有限成本率") from exc
    if not isfinite(cost) or cost < -1e-12:
        raise PortfolioResearchError("gross/net收益推导的成本率无效")
    return price, entry_factor, max(0.0, cost)


def _dates(
    trades: Sequence[Trade],
    prices: DailyPrices,
    trading_dates: Sequence[str] | None,
) -> list[str]:
    entries = [_day(trade.entry_date) for trade in trades]
    exits = [_day(trade.exit_date) for trade in trades]
    if trading_dates is not None:
        dates = sorted({_day(value) for value in trading_dates})
        if not dates:
            if trades:
                raise PortfolioResearchError("daily_close观察日历为空")
            return []
        start, end = dates[0], dates[-1]
    else:
        dates = list(prices.close.index)
        if not dates:
            if trades:
                raise PortfolioResearchError("daily_close缺少可观察的收盘价日期")
            return []
        end = min(max(exits, default=dates[-1]), dates[-1])
        past_entries = [value for value in entries if value <= end]
        start = min(past_entries) if past_entries else dates[0]
    # Respect the observation cutoff even if complete input Trade objects expose
    # later exits. Insert entry dates so missing opening-day quotes fail loudly.
    return sorted(
        {
            value
            for value in [*dates, *prices.close.index, *entries, *exits]
            if start <= value <= end
        }
    )


def _close(position: _Position, day: str, prices: DailyPrices) -> _ClosedAllocation:
    trade = position.trade
    price = _positive(trade.exit_price, "exit_price")
    factor = _positive(getattr(trade, "exit_factor", 1.0), "exit_factor")
    if not isclose(
        prices.factor(str(trade.code), day), factor, rel_tol=1e-9, abs_tol=1e-12
    ):
        raise PortfolioResearchError(f"{trade.code} exit_factor与退出日因子不一致")
    multiple = price * factor / (float(trade.entry_price) * position.entry_factor)
    gross_value = position.capital * multiple
    if not isfinite(gross_value) or gross_value <= 0:
        raise PortfolioResearchError("退出经济金额无效")
    fee = position.capital * position.cost_rate / 2.0
    proceeds = gross_value - fee
    pnl = proceeds - position.capital - position.entry_cost
    return _ClosedAllocation(
        code=str(trade.code),
        signal_date=_day(trade.signal_date),
        entry_date=_day(trade.entry_date),
        exit_date=day,
        slot=position.slot,
        quantity=position.quantity,
        entry_notional=position.capital,
        exit_notional=proceeds,
        pnl=pnl,
        gross_return_pct=(multiple - 1.0) * 100.0,
        net_return_pct=(multiple - 1.0 - position.cost_rate) * 100.0,
        turnover_notional=position.capital + gross_value,
        mae_pct=float(trade.mae_pct or 0.0),
        entry_cost=position.entry_cost,
        exit_cost=fee,
    )


def _ratios(day: PortfolioDay) -> tuple[float, float]:
    if day.equity <= 0:
        return 0.0, 0.0
    return float(
        day.market_value or 0.0
    ) / day.equity * 100.0, day.cash / day.equity * 100.0


def _segments(
    closed: list[_ClosedAllocation],
    daily: list[PortfolioDay],
    cfg: PortfolioResearchConfig,
) -> list[PortfolioSegment]:
    result: list[PortfolioSegment] = []
    for segment in _build_segments(closed, daily, cfg, float(cfg.initial_capital)):
        days = [day for day in daily if segment.start <= day.date <= segment.end]
        ratios = [_ratios(day) for day in days]
        values = asdict(segment)
        values.update(
            avg_capital_utilization_pct=sum(value[0] for value in ratios) / len(days),
            max_capital_utilization_pct=max(value[0] for value in ratios),
            idle_cash_days=sum(day.cash > 1e-8 for day in days),
            idle_cash_pct=sum(day.cash > 1e-8 for day in days) / len(days) * 100.0,
        )
        result.append(
            _DailySegment(
                **values,
                avg_idle_cash_pct=sum(value[1] for value in ratios) / len(days),
            )
        )
    return result


def _metrics(
    cfg: PortfolioResearchConfig,
    slug: str,
    sample_size: int,
    daily: list[PortfolioDay],
    closed: list[_ClosedAllocation],
    positions: dict[int, _Position],
    accepted: int,
    cash: float,
    entry_costs: float,
    exit_costs: float,
    exit_reasons: Counter[str],
) -> dict[str, Any]:
    initial = float(cfg.initial_capital)
    market_value = sum(position.market_value for position in positions.values())
    unrealized = sum(position.unrealized_pnl for position in positions.values())
    realized = sum(item.pnl for item in closed)
    equity = cash + market_value
    assert_cash_conservation(
        initial_capital=initial,
        final_equity=equity,
        realized_pnl_total=realized,
        unrealized_pnl_total=unrealized,
    )
    turnover = sum(item.turnover_notional for item in daily)
    utilization = [_ratios(item)[0] for item in daily]
    idle = [_ratios(item)[1] for item in daily]
    losses = -sum(min(item.pnl, 0.0) for item in closed)
    profits = sum(max(item.pnl, 0.0) for item in closed)
    return {
        "strategy_slug": slug,
        "initial_capital": initial,
        "final_equity": _round(equity, 4),
        "final_cash": _round(cash, 4),
        "net_pnl": _round(equity - initial, 4),
        "return_pct": _round((equity / initial - 1.0) * 100.0, 4),
        "sample_size": sample_size,
        "accepted_trades": accepted,
        "closed_trades": len(closed),
        "open_positions": len(positions),
        "open_market_value": _round(market_value, 4),
        "realized_pnl": _round(realized, 4),
        "unrealized_pnl": _round(unrealized, 4),
        "entry_cost_total": _round(entry_costs, 6),
        "exit_cost_total": _round(exit_costs, 6),
        "fees_paid": _round(entry_costs + exit_costs, 6),
        "profit_factor": _round(profits / losses) if losses else None,
        "win_rate": _round(sum(item.pnl > 0 for item in closed) / len(closed) * 100.0)
        if closed
        else None,
        "avg_net_return_pct": _round(
            sum(item.net_return_pct for item in closed) / len(closed)
        )
        if closed
        else None,
        "turnover_notional": _round(turnover, 4),
        "turnover_ratio": _round(turnover / initial),
        "turnover_pct": _round(turnover / initial * 100.0, 4),
        "capital_days": _round(sum(item.capital_in_use for item in daily), 4),
        "avg_capital_utilization_pct": _round(sum(utilization) / len(daily), 4)
        if daily
        else 0.0,
        "max_capital_utilization_pct": _round(max(utilization, default=0.0), 4),
        "idle_cash_days": sum(item.idle_cash > 1e-8 for item in daily),
        "observed_days": len(daily),
        "idle_cash_pct": _round(
            sum(item.idle_cash > 1e-8 for item in daily) / len(daily) * 100.0, 4
        )
        if daily
        else 100.0,
        "avg_idle_cash_pct": _round(sum(idle) / len(daily), 4) if daily else 100.0,
        "max_drawdown_pct": _round(
            drawdown_pct([item.equity for item in daily], peak_floor=initial), 4
        ),
        "mae_bound_max_drawdown_pct": None,
        "exit_reasons": dict(exit_reasons),
        "assumption": {
            "account_model": "daily_close",
            "equity_basis": "daily_close",
            "daily_close": True,
            "marks_to_market": True,
            "drawdown_basis": "daily_close",
            "position_sizing": "previous_observation_equity_divided_by_slots",
            "entry_priority": "entry_date_then_code",
            "same_day_exit_cash_reusable": False,
            "cost_model": "flat_gross_minus_net_split_half_at_entry_and_exit",
            "price_basis": "raw_close_times_factor_over_entry_factor",
            "missing_quote_policy": "carry_whole_last_observed_economic_mark; entry_day_requires_close",
            "data_end_policy": "open_mark_only_no_future_exit_cost",
            "allocations_closed_only": True,
            "closed_statistics_exclude_open_positions": True,
            "unrealized_pnl_includes_paid_opening_cost": True,
            "daily_open_positions": "after_close",
            "capital_in_use": "entry_notional_before_close_exits",
            "utilization_basis": "end_of_day_market_value_divided_by_equity",
            "idle_cash_amount_basis": "end_of_day_cash_divided_by_equity",
            "capital_days_basis": "sum_nominal_entry_capital_before_close_exits",
            "idle_cash_pct_basis": "fraction_of_observed_days_with_cash; not_cash_amount_ratio",
            "turnover_basis": "execution_notional_excluding_fees",
        },
    }


def analyze_daily_close(
    trades: Iterable[Trade],
    cfg: PortfolioResearchConfig,
    trading_dates: Sequence[str] | None,
    strategy_slug: str,
    closing_prices: pd.DataFrame | None,
    adjustment_factors: pd.DataFrame | None,
) -> PortfolioResearchResult:
    candidates = list(trades)
    prices = DailyPrices(closing_prices, adjustment_factors)
    dates = _dates(candidates, prices, trading_dates)
    skipped: Counter[str] = Counter()
    orders: dict[str, list[Trade]] = defaultdict(list)
    for trade in sorted(
        candidates, key=lambda t: (_day(t.entry_date), str(t.code), _day(t.signal_date))
    ):
        entry, exit_ = _day(trade.entry_date), _day(trade.exit_date)
        if exit_ < entry:
            raise PortfolioResearchError("退出日在入场日前")
        if not dates or not dates[0] <= entry <= dates[-1]:
            skipped["入场日不在观察范围"] += 1
            continue
        orders[entry].append(trade)
    cash = equity = float(cfg.initial_capital)
    positions: dict[int, _Position] = {}
    closed: list[_ClosedAllocation] = []
    daily: list[PortfolioDay] = []
    seen: set[tuple[str, str]] = set()
    accepted = 0
    entry_costs = exit_costs = 0.0
    exit_reasons: Counter[str] = Counter()
    for day in dates:
        entries = 0
        turnover = 0.0
        for trade in orders.get(day, []):
            code = str(trade.code)
            key = (code, day)
            if key in seen:
                skipped["重复代码同日信号"] += 1
                continue
            seen.add(key)
            if not cfg.allow_same_code_overlap and any(
                str(p.trade.code) == code for p in positions.values()
            ):
                skipped["同代码持仓冲突"] += 1
                continue
            slots = [slot for slot in range(cfg.max_positions) if slot not in positions]
            if not slots:
                skipped["资金槽位已占用"] += 1
                continue
            price, entry_factor, cost = _entry_terms(trade, prices)
            budget = min(equity / cfg.max_positions, cash / (1.0 + cost / 2.0))
            quantity = floor(budget / price / cfg.lot_size) * cfg.lot_size
            if quantity <= 0:
                skipped["可用资金不足一手"] += 1
                continue
            mark = prices.mark(code, day, None)
            if not isclose(mark.factor, entry_factor, rel_tol=1e-9, abs_tol=1e-12):
                raise PortfolioResearchError(f"{code} entry_factor与开仓日因子不一致")
            capital = quantity * price
            entry_fee = capital * cost / 2.0
            cash -= capital + entry_fee
            positions[slots[0]] = _Position(
                trade, slots[0], quantity, capital, entry_fee, cost, entry_factor, mark
            )
            accepted += 1
            entries += 1
            entry_costs += entry_fee
            turnover += capital
        capital_in_use = sum(p.capital for p in positions.values())
        realized_today = 0.0
        exits = 0
        for slot, position in list(positions.items()):
            trade = position.trade
            if trade.exit_reason != "data_end" and _day(trade.exit_date) == day:
                allocation = _close(position, day, prices)
                cash += allocation.exit_notional
                realized_today += allocation.pnl
                exit_costs += allocation.exit_cost
                turnover += allocation.exit_notional + allocation.exit_cost
                exits += 1
                closed.append(allocation)
                exit_reasons[trade.exit_reason] += 1
                del positions[slot]
            else:
                position.mark = prices.mark(str(trade.code), day, position.mark)
        market_value = sum(p.market_value for p in positions.values())
        unrealized = sum(p.unrealized_pnl for p in positions.values())
        equity = cash + market_value
        if not isfinite(equity) or cash < -1e-8:
            raise PortfolioInvariantError("daily_close权益无效或可用现金透支")
        assert_cash_conservation(
            initial_capital=float(cfg.initial_capital),
            final_equity=equity,
            realized_pnl_total=sum(item.pnl for item in closed),
            unrealized_pnl_total=unrealized,
        )
        daily.append(
            PortfolioDay(
                date=day,
                equity=equity,
                cash=cash,
                idle_cash=cash,
                capital_in_use=capital_in_use,
                open_positions=len(positions),
                realized_pnl=realized_today,
                turnover_notional=turnover,
                entries=entries,
                exits=exits,
                market_value=market_value,
                unrealized_pnl=unrealized,
            )
        )
    metrics = _metrics(
        cfg,
        strategy_slug,
        len(candidates),
        daily,
        closed,
        positions,
        accepted,
        cash,
        entry_costs,
        exit_costs,
        exit_reasons,
    )
    failures = (
        []
        if accepted
        else ["没有输入交易" if not candidates else "没有交易被组合资金槽位接受"]
    )
    return PortfolioResearchResult(
        config={**cfg.to_dict(), "strategy_slug": strategy_slug},
        sample_size=len(candidates),
        accepted_trades=accepted,
        time_range={
            "start": dates[0] if dates else None,
            "end": dates[-1] if dates else None,
        },
        metrics=metrics,
        allocations=list(closed),
        daily=daily,
        segments=_segments(closed, daily, cfg),
        skipped=dict(skipped),
        failures=failures,
        open_allocations=[p.open_dict(dates[-1]) for p in positions.values()],
    )
