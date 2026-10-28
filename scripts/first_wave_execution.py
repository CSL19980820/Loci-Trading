"""Independent, causal first-wave execution research; no I/O or portfolio limits.

Daily orders use the next market open. Minute decisions use the 14:50 snapshot
(14:49 is the oldest accepted observation), then the next minute's open. Minute
timestamps denote the observation minute in Shanghai time. A pullback requires
two non-overlapping, complete five-minute windows, starting on the first return
to the MA5 band; both window endpoints must remain in that band.

The horizon is entry's market-calendar index + hold_days: its open in daily mode,
and its first minute open in minute mode. Suspended calendar rows count. MA5 uses
the last four observed adjusted closes and the current observed price. Allocation
is raw-price notional, before costs; fractional shares and factor-adjusted share
counts remove lot-size and corporate-action price distortions. Unused cash earns
zero. Any open leg makes both aggregate returns null; realized P&L is separate.
"""

from __future__ import annotations

from datetime import date
from decimal import ROUND_HALF_UP, Decimal
from math import isfinite
import re

import pandas as pd


_OHLCV = ["open", "high", "low", "close", "volume"]
_COMMISSION = 0.0003
_SLIPPAGE = 0.0005
_EPS = 1e-10
_STAMP = (
    ("2023-08-28", 0.0, 0.0005),
    ("2008-09-19", 0.0, 0.001),
    ("2008-04-24", 0.001, 0.001),
    ("2007-05-30", 0.003, 0.003),
    ("2005-01-24", 0.001, 0.001),
    ("2001-11-16", 0.002, 0.002),
    ("1998-06-12", 0.004, 0.004),
    ("1997-05-12", 0.005, 0.005),
    ("1992-06-12", 0.003, 0.003),
)


def _positive(value: float) -> bool:
    return isfinite(value) and value > 0


def _active(row: pd.Series) -> bool:
    return all(_positive(row[name]) for name in _OHLCV)


def _limit_rate(code: str, day: str) -> float | None:
    if day < "1996-12-16":
        return None
    digits = re.search(r"\d{6}", code)
    symbol = digits.group() if digits else code
    if code.upper().endswith(".BJ") or symbol.startswith(("4", "8", "92")):
        return 0.30
    if symbol.startswith(("688", "689")):
        return 0.20
    if symbol.startswith(("300", "301")) and day >= "2020-08-24":
        return 0.20
    return 0.10


def _small_k(opening: float, price: float, reference: float, ma5: float) -> bool:
    return (
        abs(price / opening - 1) <= 0.02 + _EPS
        and abs(price / reference - 1) <= 0.03 + _EPS
        and price >= ma5 - _EPS
    )


def _minute_frame(raw: pd.DataFrame, day: str) -> pd.DataFrame:
    if not isinstance(raw.index, pd.DatetimeIndex):
        raise ValueError("minute_index_must_be_datetime")
    frame = raw.loc[:, _OHLCV].astype(float).copy()
    if frame.index.tz is not None:
        frame.index = frame.index.tz_convert("Asia/Shanghai").tz_localize(None)
    if not frame.index.is_unique or not frame.index.is_monotonic_increasing:
        raise ValueError("minute_index_must_be_unique_and_sorted")
    if any(
        t.date().isoformat() != day or t.second or t.microsecond for t in frame.index
    ):
        raise ValueError("minute_index_must_match_session")
    clock = frame.index.strftime("%H:%M")
    return frame.loc[
        ((clock >= "09:30") & (clock <= "11:30"))
        | ((clock >= "13:00") & (clock <= "15:00"))
    ]


def simulate_opportunity(
    bars: pd.DataFrame,
    signal_date: str,
    *,
    code: str,
    mode: str = "next_open",
    minutes: dict[str, pd.DataFrame] | None = None,
    hold_days: int = 10,
    staged: bool = True,
    exit_rule: str = "ma5_or_horizon",
    notional: float = 100000,
) -> dict:
    """Simulate one D2 signal. Bad/missing evidence returns ``unverifiable``.

    Unsupported strategy parameters raise ValueError. ``entry_price`` and
    ``exit_price`` are raw quotes; slippage is an explicit cash cost, commissions
    and stamp tax use slipped turnover, and minimum commission is per leg/side.
    ``invested_*_return_pct`` divides by allocated raw-price notional. ST history
    and listing-day price-limit exemptions are unavailable in this input schema.
    """
    if mode not in {"next_open", "intraday_1450"}:
        raise ValueError("unsupported mode")
    if exit_rule not in {"horizon", "ma5_or_horizon"}:
        raise ValueError("unsupported exit_rule")
    if isinstance(hold_days, bool) or not isinstance(hold_days, int) or hold_days < 1:
        raise ValueError("hold_days must be a positive integer")
    if not _positive(notional):
        raise ValueError("notional must be finite and positive")

    flags = {
        "fractional_shares",
        "historical_st_status_unavailable",
        "listing_limit_exemptions_unavailable",
        "uniform_research_cost_parameters",
        "ma5_last_four_observed_adjusted_closes",
        "limit_open_conservatively_unfilled",
        "daily_causal_control" if mode == "next_open" else "strict_minute_execution",
    }
    result = {
        "code": code,
        "signal_date": signal_date,
        "mode": mode,
        "hold_days": hold_days,
        "staged": staged,
        "exit_rule": exit_rule,
        "notional": float(notional),
        "legs": [],
        "evidence": [],
        "cost_assumption": [
            "Commission 3bps, minimum CNY5 per leg/side, and slippage 5bps per side "
            "are uniform research parameters, not historical broker fees.",
            "Allocations exclude costs; commission and stamp tax use slipped turnover.",
        ],
        "horizon_timing": "market_open" if mode == "next_open" else "first_minute_open",
    }
    legs = result["legs"]
    first_index = None
    pending_exit = None

    def finish(status: str, reason: str) -> dict:
        invested = sum(leg["notional"] for leg in legs)
        closed = [leg for leg in legs if leg["exit_date"] is not None]
        gross = sum(leg["gross_pnl"] for leg in closed)
        net = sum(leg["net_pnl"] for leg in closed)
        complete = status == "closed"
        result.update(
            status=status,
            reason=reason,
            entry_date=legs[0]["entry_date"] if legs else None,
            exit_date=max(leg["exit_date"] for leg in closed) if complete else None,
            exit_reason=pending_exit,
            invested_notional=invested,
            uninvested_cash=notional - invested,
            realized_gross_pnl=gross,
            realized_net_pnl=net,
            gross_return_pct=gross / notional * 100
            if complete
            else (0.0 if status == "skipped" else None),
            net_return_pct=net / notional * 100
            if complete
            else (0.0 if status == "skipped" else None),
            invested_gross_return_pct=gross / invested * 100 if complete else None,
            invested_net_return_pct=net / invested * 100 if complete else None,
            evidence_flags=sorted(flags),
        )
        return result

    try:
        if date.fromisoformat(signal_date).isoformat() != signal_date:
            return finish("unverifiable", "signal_date_must_be_iso")
        dates = list(bars.index)
        if (
            not bars.index.is_unique
            or not bars.index.is_monotonic_increasing
            or any(
                not isinstance(d, str) or date.fromisoformat(d).isoformat() != d
                for d in dates
            )
        ):
            return finish("unverifiable", "daily_index_must_be_unique_sorted_iso_dates")
        # Conversion does not reject unused future values. Evidence is rejected
        # only at the decision/execution boundary that actually consumes it.
        daily = bars.loc[:, [*_OHLCV, "factor"]].apply(pd.to_numeric, errors="coerce")
    except (KeyError, TypeError, ValueError) as exc:
        return finish("unverifiable", f"invalid_daily_data: {exc}")
    if signal_date not in dates:
        return finish("unverifiable", "signal_date_missing")
    if mode == "intraday_1450" and not minutes:
        return finish("unverifiable", "minute_data_missing")
    signal_index = dates.index(signal_date)
    factors = daily["factor"].where(
        daily["factor"].gt(0) & daily["factor"].lt(float("inf"))
    )
    closes = daily["close"].where(
        daily["close"].gt(0) & daily["close"].lt(float("inf"))
    )
    observed = daily[["open", "high", "low", "close"]].notna().any(axis=1)
    adjusted = (closes * factors).loc[observed]
    # reindex(method=...) only fills suspended calendar rows. It preserves NaN
    # on observed rows: a bad factor cannot substitute an older fifth close.
    prior_sums = (
        adjusted.rolling(4, min_periods=4)
        .sum()
        .reindex(daily.index, method="ffill")
        .shift(1)
        .to_numpy()
    )
    previous_closes = (
        closes.loc[observed].reindex(daily.index, method="ffill").shift(1).to_numpy()
    )
    previous_factors = (
        factors.loc[observed].reindex(daily.index, method="ffill").shift(1).to_numpy()
    )
    references = previous_closes * previous_factors / factors.to_numpy()
    daily_ma = (prior_sums + closes.to_numpy() * factors.to_numpy()) / (
        5 * factors.to_numpy()
    )

    def event(day: str, action: str, **evidence: object) -> None:
        result["evidence"].append({"date": day, "action": action, **evidence})

    def blocked(i: int, price: float, side: str) -> str | None:
        if not _positive(price):
            return "suspended"
        rate = _limit_rate(code, dates[i])
        if rate is None:
            flags.add("price_limit_regime_unverified_before_1996_12_16")
            return None
        reference = references[i]
        if not _positive(reference):
            return "reference_price_missing"
        multiplier = Decimal("1") + Decimal(str(rate)) * (1 if side == "buy" else -1)
        reference_decimal = (
            Decimal(str(previous_closes[i]))
            * Decimal(str(previous_factors[i]))
            / Decimal(str(daily.iloc[i]["factor"]))
        )
        limit = float(
            (reference_decimal * multiplier).quantize(
                Decimal("0.01"), rounding=ROUND_HALF_UP
            )
        )
        if side == "buy" and price >= limit - _EPS:
            return "upper_limit"
        if side == "sell" and price <= limit + _EPS:
            return "lower_limit"
        return None

    def costs(day: str, amount: float, side: str) -> dict:
        rate = next(
            (
                buy if side == "buy" else sell
                for start, buy, sell in _STAMP
                if day >= start
            ),
            None,
        )
        if rate is None:
            flags.add("stamp_tax_unverified_before_1992_06_12")
            assumption = "Stamp tax before 1992-06-12 is unverified and assumed zero; net returns are estimates."
            if assumption not in result["cost_assumption"]:
                result["cost_assumption"].append(assumption)
            rate = 0.0
        turnover = amount * (1 + _SLIPPAGE if side == "buy" else 1 - _SLIPPAGE)
        commission = max(5.0, turnover * _COMMISSION)
        stamp = turnover * rate
        slip = amount * _SLIPPAGE
        return {
            "commission": commission,
            "stamp_tax": stamp,
            "stamp_rate": rate,
            "slippage": slip,
            "total": commission + stamp + slip,
        }

    def buy(i: int, price: float, timestamp: str | None, why: str) -> str | None:
        nonlocal first_index
        factor = daily.iloc[i]["factor"]
        if _positive(price) and not _positive(factor):
            return "invalid_adjustment_factor"
        failure = blocked(i, price, "buy")
        if failure:
            flags.add(f"buy_blocked_{failure}")
            event(dates[i], "buy_blocked", reason=failure, time=timestamp)
            return failure
        amount = notional * (0.5 if staged else 1.0)
        legs.append(
            {
                "entry_date": dates[i],
                "entry_time": timestamp,
                "entry_price": float(price),
                "factor": float(factor),
                "entry_factor": float(factor),
                "weight": amount / notional,
                "notional": amount,
                "quantity": amount / price,
                "entry_costs": costs(dates[i], amount, "buy"),
                "entry_reason": why,
                "exit_date": None,
                "exit_time": None,
                "exit_price": None,
                "exit_factor": None,
                "exit_reason": None,
                "exit_costs": None,
                "gross_pnl": None,
                "net_pnl": None,
            }
        )
        if first_index is None:
            first_index = i
        event(dates[i], "buy", reason=why, time=timestamp, price=float(price))
        return None

    def sell(i: int, price: float, timestamp: str | None) -> str | None:
        for leg in legs:
            if leg["exit_date"] is not None:
                continue
            if leg["entry_date"] >= dates[i]:
                flags.add("sell_queued_t_plus_one")
                continue
            factor = daily.iloc[i]["factor"]
            if _positive(price) and not _positive(factor):
                return "invalid_adjustment_factor"
            failure = blocked(i, price, "sell")
            if failure == "reference_price_missing":
                return failure
            if failure:
                flags.add(f"sell_queued_{failure}")
                continue
            proceeds = (
                leg["notional"] * price * factor / (leg["entry_price"] * leg["factor"])
            )
            exit_costs = costs(dates[i], proceeds, "sell")
            gross = proceeds - leg["notional"]
            leg.update(
                exit_date=dates[i],
                exit_time=timestamp,
                exit_price=float(price),
                exit_factor=float(factor),
                exit_reason=pending_exit,
                exit_costs=exit_costs,
                gross_pnl=gross,
                net_pnl=gross - leg["entry_costs"]["total"] - exit_costs["total"],
                exit_quantity=leg["quantity"] * factor / leg["factor"],
            )
            event(
                dates[i],
                "sell",
                reason=pending_exit,
                time=timestamp,
                price=float(price),
            )
        return None

    if _limit_rate(code, signal_date) is None:
        flags.add("price_limit_regime_unverified_before_1996_12_16")

    if mode == "next_open":
        signal = daily.iloc[signal_index]
        if not _positive(signal["close"]):
            return finish("skipped", "signal_suspended")
        if not _positive(daily_ma[signal_index]):
            return finish("unverifiable", "insufficient_ma5_history")
        if signal["close"] < daily_ma[signal_index] - _EPS:
            return finish("skipped", "d2_below_ma5")
        event(
            signal_date,
            "d2_confirmed",
            price=signal["close"],
            ma5=daily_ma[signal_index],
        )
        if signal_index + 1 == len(dates):
            return finish("data_end", "next_entry_session_unavailable")
        entry_i = signal_index + 1
        row = daily.iloc[entry_i]
        failure = buy(entry_i, row["open"], None, "d2_close_confirmation")
        if failure:
            status = (
                "unverifiable"
                if failure in {"invalid_adjustment_factor", "reference_price_missing"}
                else "skipped"
            )
            return finish(status, f"first_buy_{failure}")
        add_at = None
        waiting = False
        for i in range(entry_i, len(dates)):
            row, day = daily.iloc[i], dates[i]
            if i >= first_index + hold_days and pending_exit is None:
                pending_exit = "horizon"
            if pending_exit:
                failure = sell(i, row["open"], None)
                if failure:
                    return finish("unverifiable", f"{failure}: {day}")
                if all(leg["exit_date"] for leg in legs):
                    return finish("closed", "all_legs_closed")
                continue
            if add_at == i:
                failure = buy(
                    i,
                    row["open"],
                    None,
                    "d3_small_k" if not waiting else "ma5_pullback",
                )
                if failure in {"invalid_adjustment_factor", "reference_price_missing"}:
                    return finish("unverifiable", f"{failure}: {day}")
                add_at = None
                waiting = False
            needs_ma5 = exit_rule == "ma5_or_horizon" or (
                staged and len(legs) == 1 and (i == entry_i or waiting)
            )
            if not needs_ma5:
                continue
            if not _positive(row["close"]):
                if row[["open", "high", "low", "close"]].isna().all():
                    continue
                return finish("unverifiable", f"close_confirmation_missing: {day}")
            ma5, reference = daily_ma[i], references[i]
            if not _positive(ma5):
                return finish("unverifiable", "insufficient_ma5_history")
            if exit_rule == "ma5_or_horizon" and row["close"] < ma5 - _EPS:
                pending_exit = "ma5_break"
                event(
                    day, "exit_queued", reason=pending_exit, price=row["close"], ma5=ma5
                )
                continue
            if not staged or len(legs) == 2:
                continue
            if i == entry_i:
                if not _positive(row["high"]):
                    return finish("unverifiable", f"d3_high_missing: {day}")
                if row["high"] / reference - 1 >= 0.05 - _EPS:
                    waiting = True
                    event(day, "pullback_wait", high=row["high"], reference=reference)
                elif _small_k(row["open"], row["close"], reference, ma5):
                    add_at = i + 1
                    event(day, "add_queued", reason="d3_small_k", ma5=ma5)
            elif waiting and ma5 - _EPS <= row["close"] <= ma5 * 1.01 + _EPS:
                add_at = i + 1
                event(
                    day,
                    "add_queued",
                    reason="ma5_pullback",
                    price=row["close"],
                    ma5=ma5,
                )
    else:
        buy_at = None
        buy_reason = None
        waiting = False
        surge_time = None
        for i in range(signal_index, len(dates)):
            day, row = dates[i], daily.iloc[i]
            if (
                first_index is not None
                and i >= first_index + hold_days
                and pending_exit is None
            ):
                pending_exit = "horizon"
                buy_at = None
            raw = minutes.get(day)
            if raw is None or raw.empty:
                if i > signal_index and row[_OHLCV[:4]].isna().all():
                    flags.add("suspended_market_session")
                    if pending_exit:
                        flags.add("sell_queued_suspended")
                    if buy_at is not None and buy_at[0] == i:
                        event(day, "buy_blocked", reason="suspended")
                        buy_at = None
                    continue
                return finish("unverifiable", f"minute_data_missing: {day}")
            try:
                frame = _minute_frame(raw, day)
            except (KeyError, TypeError, ValueError) as exc:
                return finish("unverifiable", f"invalid_minute_data: {day}: {exc}")
            if frame.empty:
                return finish("unverifiable", f"minute_session_empty: {day}")
            decision = pd.Timestamp(f"{day} 14:50")
            available = frame.loc[:decision]
            snapshot = available.iloc[-1] if not available.empty else None
            snapshot_time = available.index[-1] if not available.empty else None
            fresh = (
                snapshot_time is not None
                and decision - snapshot_time <= pd.Timedelta(minutes=1)
            )
            window = []
            held_windows = 0
            last_time = None
            exit_at = None
            if pending_exit and any(
                leg["exit_date"] is None and leg["entry_date"] < day for leg in legs
            ):
                if frame.index[0].strftime("%H:%M") not in {"09:30", "09:31"}:
                    return finish("unverifiable", f"minute_session_open_missing: {day}")
                exit_at = frame.index[0]

            def next_execution(t: pd.Timestamp) -> pd.Timestamp | None:
                if t.strftime("%H:%M") == "15:00":
                    return None
                if t.strftime("%H:%M") == "11:30":
                    afternoon = pd.Timestamp(f"{day} 13:00")
                    return (
                        afternoon
                        if afternoon in frame.index
                        else afternoon + pd.Timedelta(minutes=1)
                    )
                return t + pd.Timedelta(minutes=1)

            def schedule_buy(t: pd.Timestamp, why: str) -> None:
                nonlocal buy_at, buy_reason
                target = next_execution(t)
                buy_at = (i + 1, None) if target is None else (i, target)
                buy_reason = why
                event(
                    day,
                    "add_queued" if legs else "entry_queued",
                    reason=why,
                    time=t.isoformat(),
                )

            for t in frame.index.union(pd.DatetimeIndex([decision])).sort_values():
                candle = frame.loc[t] if t in frame.index else None
                active = candle is not None and _active(candle)
                if pending_exit and exit_at is not None and t >= exit_at:
                    if t != exit_at or candle is None:
                        return finish(
                            "unverifiable",
                            f"next_exit_minute_missing: {exit_at.isoformat()}",
                        )
                    failure = sell(i, candle["open"], t.isoformat())
                    if failure:
                        return finish("unverifiable", f"{failure}: {day}")
                    if all(leg["exit_date"] for leg in legs):
                        return finish("closed", "all_legs_closed")
                    exit_at = (
                        next_execution(t)
                        if any(
                            leg["exit_date"] is None and leg["entry_date"] < day
                            for leg in legs
                        )
                        else None
                    )
                if buy_at is not None and buy_at[0] == i:
                    target = buy_at[1]
                    if target is None or t >= target:
                        if target is None and frame.index[0].strftime("%H:%M") not in {
                            "09:30",
                            "09:31",
                        }:
                            return finish(
                                "unverifiable", f"minute_session_open_missing: {day}"
                            )
                        if target is not None and (t != target or candle is None):
                            return finish(
                                "unverifiable",
                                f"next_execution_minute_missing: {target.isoformat()}",
                            )
                        if not pending_exit:
                            failure = buy(
                                i,
                                candle["open"] if candle is not None else float("nan"),
                                t.isoformat(),
                                buy_reason,
                            )
                            if failure in {
                                "invalid_adjustment_factor",
                                "reference_price_missing",
                            }:
                                return finish("unverifiable", f"{failure}: {day}")
                            if failure and not legs:
                                return finish("skipped", f"first_buy_{failure}")
                        buy_at = None
                        waiting = False
                if pending_exit:
                    continue
                if active and staged and len(legs) == 1 and i > signal_index:
                    reference = references[i]
                    if not _positive(reference):
                        return finish("unverifiable", f"reference_price_missing: {day}")
                    if (
                        i == signal_index + 1
                        and not waiting
                        and buy_at is None
                        and candle["high"] / reference - 1 >= 0.05 - _EPS
                    ):
                        waiting, surge_time = True, t
                        event(
                            day,
                            "pullback_wait",
                            time=t.isoformat(),
                            high=candle["high"],
                            reference=reference,
                        )
                    if (
                        waiting
                        and buy_at is None
                        and (surge_time is None or t > surge_time)
                    ):
                        if not _positive(row["factor"]):
                            return finish(
                                "unverifiable", f"invalid_adjustment_factor: {day}"
                            )
                        if not _positive(prior_sums[i]):
                            return finish("unverifiable", "insufficient_ma5_history")
                        price = candle["close"]
                        ma5 = (prior_sums[i] / row["factor"] + price) / 5
                        in_band = ma5 - _EPS <= price <= ma5 * 1.01 + _EPS
                        if last_time is not None and t - last_time != pd.Timedelta(
                            minutes=1
                        ):
                            window, held_windows = [], 0
                        if window or held_windows or in_band:
                            window.append(t)
                            if len(window) == 5:
                                held_windows = held_windows + 1 if in_band else 0
                                event(
                                    day,
                                    "pullback_window",
                                    time=t.isoformat(),
                                    held=in_band,
                                    price=price,
                                    ma5=ma5,
                                )
                                window = []
                                if held_windows == 2:
                                    schedule_buy(t, "ma5_pullback_two_windows")
                        last_time = t
                if t != decision:
                    continue
                needs_snapshot = (
                    i == signal_index
                    or exit_rule == "ma5_or_horizon"
                    or (
                        staged
                        and len(legs) == 1
                        and i == signal_index + 1
                        and not waiting
                    )
                )
                if not needs_snapshot:
                    continue
                if not fresh or snapshot is None or not _active(snapshot):
                    return finish(
                        "unverifiable", f"minute_1450_stale_or_missing: {day}"
                    )
                if not _positive(prior_sums[i]):
                    return finish("unverifiable", "insufficient_ma5_history")
                if not _positive(row["factor"]):
                    return finish("unverifiable", f"invalid_adjustment_factor: {day}")
                price = snapshot["close"]
                ma5 = (prior_sums[i] / row["factor"] + price) / 5
                event(
                    day,
                    "snapshot_1450",
                    time=snapshot_time.isoformat(),
                    price=price,
                    ma5=ma5,
                )
                if price < ma5 - _EPS:
                    if not legs:
                        return finish("skipped", "d2_below_dynamic_ma5")
                    if exit_rule == "ma5_or_horizon":
                        pending_exit = "ma5_break"
                        buy_at = None
                        if any(
                            leg["exit_date"] is None and leg["entry_date"] < day
                            for leg in legs
                        ):
                            exit_at = next_execution(decision)
                        if any(
                            leg["exit_date"] is None and leg["entry_date"] == day
                            for leg in legs
                        ):
                            flags.add("sell_queued_t_plus_one")
                    continue
                if i == signal_index:
                    schedule_buy(decision, "d2_dynamic_ma5_confirmation")
                elif (
                    staged
                    and len(legs) == 1
                    and i == signal_index + 1
                    and not waiting
                    and buy_at is None
                ):
                    start = frame.index[0]
                    if start.strftime("%H:%M") not in {"09:30", "09:31"}:
                        return finish(
                            "unverifiable", f"minute_session_open_missing: {day}"
                        )
                    morning = pd.date_range(start, f"{day} 11:30", freq="min")
                    afternoon_start = (
                        f"{day} 13:00"
                        if pd.Timestamp(f"{day} 13:00") in frame.index
                        else f"{day} 13:01"
                    )
                    expected = morning.union(
                        pd.date_range(afternoon_start, snapshot_time, freq="min")
                    )
                    if not expected.isin(frame.index).all() or not all(
                        _active(c) for _, c in frame.loc[expected].iterrows()
                    ):
                        return finish(
                            "unverifiable", f"minute_d3_coverage_incomplete: {day}"
                        )
                    if _small_k(frame.iloc[0]["open"], price, references[i], ma5):
                        schedule_buy(decision, "d3_small_k")
            if buy_at is not None and buy_at[0] == i:
                return finish(
                    "unverifiable", f"next_execution_minute_missing: {buy_at[1]}"
                )
            if exit_at is not None:
                return finish(
                    "unverifiable", f"next_exit_minute_missing: {exit_at.isoformat()}"
                )
    return finish(
        "data_end",
        "exit_pending_at_data_end" if pending_exit else "horizon_not_reached",
    )
