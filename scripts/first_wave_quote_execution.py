"""Causal execution on sampled close/volume quotes, without I/O or fake OHLC.

These are sampled prices, not minute candles or a replay of complete ticks.
An order assumes unlimited capacity at the close of the next positive-volume
sample strictly after its decision. Zero-volume samples can inform decisions.
The 14:50 decision accepts an observation no older than 14:49. D3's known daily
open also counts as an observed price for the 5% surge definition.

After a surge, a touch in [dynamic MA5, MA5 * 1.01] starts two non-overlapping
five-sample windows. Each endpoint must remain in that band. All ten one-minute samples
must be observed in the same trading session; lunch/day gaps reset the windows.
Waiting for a new touch can continue on later market dates. Each leg observes
T+1. The horizon is the first actual entry's calendar index + hold_days, including
non-trading rows. Unused cash earns zero; an open leg prevents a realized total
return. No global mutable state is used.
"""

from __future__ import annotations

from datetime import date
from decimal import ROUND_HALF_UP, Decimal
from math import isfinite

import pandas as pd

from scripts.first_wave_execution import (
    _COMMISSION,
    _EPS,
    _SLIPPAGE,
    _STAMP,
    _limit_rate,
    _positive,
    _small_k,
)


def _quote_frame(raw: pd.DataFrame, day: str) -> pd.DataFrame:
    if not isinstance(raw.index, pd.DatetimeIndex):
        raise ValueError("quote_index_must_be_datetime")
    frame = raw.loc[:, ["close", "volume"]].apply(pd.to_numeric, errors="coerce")
    if frame.index.tz is not None:
        frame.index = frame.index.tz_convert("Asia/Shanghai").tz_localize(None)
    if (
        frame.index.hasnans
        or not frame.index.is_unique
        or not frame.index.is_monotonic_increasing
    ):
        raise ValueError("quote_index_must_be_unique_and_sorted")
    if any(
        t.date().isoformat() != day or t.second or t.microsecond or t.nanosecond
        for t in frame.index
    ):
        raise ValueError("quote_index_must_match_session")
    clock = frame.index.strftime("%H:%M")
    return frame.loc[
        ((clock >= "09:30") & (clock <= "11:30"))
        | ((clock >= "13:01") & (clock <= "15:00"))
    ]


def simulate_quote_opportunity(
    bars: pd.DataFrame,
    signal_date: str,
    *,
    code: str,
    quotes: dict[str, pd.DataFrame] | None = None,
    hold_days: int = 10,
    notional: float = 100000,
) -> dict:
    """Simulate one independent D2 opportunity using raw sampled prices.

    Missing required quotes return ``unverifiable`` with ``missing_quote_date``
    and retain occurred legs. Only an empty frame explicitly carrying
    ``attrs['confirmed_no_trades'] is True`` proves a session had no trades.
    Values in future daily history/quotes are consumed only when needed.
    Commission, slipped turnover, historical stamp tax, fractional quantities
    and factor-based economic P&L follow ``first_wave_execution``.
    """
    if isinstance(hold_days, bool) or not isinstance(hold_days, int) or hold_days < 1:
        raise ValueError("hold_days must be a positive integer")
    if not _positive(notional):
        raise ValueError("notional must be finite and positive")

    flags = {
        "fractional_shares",
        "historical_st_status_unavailable",
        "historical_delisting_pool_unavailable",
        "listing_limit_exemptions_unavailable",
        "uniform_research_cost_parameters",
        "ma5_last_four_observed_adjusted_closes",
        "limit_quote_conservatively_unfilled",
        "sampled_quotes_not_strict_ohlc_replay",
        "intraminute_extrema_unavailable",
        "sampled_price_surge_definition",
        "next_positive_volume_quote_fill_assumption",
        "unlimited_quote_capacity",
    }
    result = {
        "code": code,
        "signal_date": signal_date,
        "mode": "sampled_quotes_1450",
        "hold_days": hold_days,
        "staged": True,
        "exit_rule": "ma5_or_horizon",
        "notional": float(notional),
        "legs": [],
        "evidence": [],
        "cost_assumption": [
            "Commission 3bps, minimum CNY5 per leg/side, and slippage 5bps per side "
            "are uniform research parameters, not historical broker fees.",
            "Allocations exclude costs; commission and stamp tax use slipped turnover.",
        ],
        "execution_assumption": [
            "Sampled close/volume prices contain no intraminute extrema; this is "
            "not strict minute-OHLC or complete-tick replay.",
            "Fill at the next positive-volume sampled close strictly after the "
            "decision, assuming unlimited capacity, subject to price limits and T+1.",
            "D3 surge means a known daily open or observed sampled close rose at "
            "least 5%; unobserved spikes between samples cannot be excluded.",
        ],
        "horizon_timing": "first_executable_quote",
    }
    legs = result["legs"]
    first_index = None
    buy_order = None
    pending_exit = None
    exit_decision = None
    waiting = False
    surge_time = None

    def finish(
        status: str, reason: str, *, missing_quote_date: str | None = None
    ) -> dict:
        invested = sum(leg["notional"] for leg in legs)
        closed = [leg for leg in legs if leg["exit_date"] is not None]
        gross = sum(leg["gross_pnl"] for leg in closed)
        net = sum(leg["net_pnl"] for leg in closed)
        complete = status == "closed"
        result.update(
            status=status,
            reason=reason,
            missing_quote_date=missing_quote_date,
            entry_date=legs[0]["entry_date"] if legs else None,
            exit_date=max(leg["exit_date"] for leg in closed) if complete else None,
            exit_reason=pending_exit,
            invested_notional=invested,
            uninvested_cash=notional - invested,
            realized_gross_pnl=gross,
            realized_net_pnl=net,
            gross_pnl=gross if complete else (0.0 if status == "skipped" else None),
            net_pnl=net if complete else (0.0 if status == "skipped" else None),
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
        daily = bars.loc[:, ["open", "high", "low", "close", "volume", "factor"]].apply(
            pd.to_numeric, errors="coerce"
        )
    except (KeyError, TypeError, ValueError) as exc:
        return finish("unverifiable", f"invalid_daily_data: {exc}")
    if signal_date not in dates:
        return finish("unverifiable", "signal_date_missing")
    signal_index = dates.index(signal_date)

    # Start with the baseline's daily observation convention. Explicit no-trade
    # evidence excludes stale daily values. A supplied quote session establishes
    # an observation even if its daily close is unknown: keep that NaN rather
    # than silently substitute an older fifth close. This only inspects frame
    # metadata; future price values are not validated here.
    factors = daily["factor"].where(
        daily["factor"].gt(0) & daily["factor"].lt(float("inf"))
    )
    closes = daily["close"].where(
        daily["close"].gt(0) & daily["close"].lt(float("inf"))
    )
    observed = daily[["open", "high", "low", "close"]].notna().any(axis=1)
    for quote_day, raw in (quotes or {}).items():
        if quote_day not in observed.index or not isinstance(raw, pd.DataFrame):
            continue
        if not raw.empty:
            observed.loc[quote_day] = True
        elif raw.attrs.get("confirmed_no_trades") is True:
            observed.loc[quote_day] = False
    adjusted = (closes * factors).loc[observed]
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

    def event(day: str, action: str, **evidence: object) -> None:
        result["evidence"].append({"date": day, "action": action, **evidence})

    def blocked(i: int, price: float, side: str) -> str | None:
        rate = _limit_rate(code, dates[i])
        if rate is None:
            flags.add("price_limit_regime_unverified_before_1996_12_16")
            return None
        if not _positive(references[i]):
            return "reference_price_missing"
        reference = (
            Decimal(str(previous_closes[i]))
            * Decimal(str(previous_factors[i]))
            / Decimal(str(daily.iloc[i]["factor"]))
        )
        multiplier = Decimal("1") + Decimal(str(rate)) * (1 if side == "buy" else -1)
        limit = float((reference * multiplier).quantize(Decimal("0.01"), ROUND_HALF_UP))
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
            assumption = (
                "Stamp tax before 1992-06-12 is unverified and assumed zero; "
                "net returns are estimates."
            )
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

    def buy(i: int, t: pd.Timestamp, price: float) -> str | None:
        nonlocal first_index
        factor = daily.iloc[i]["factor"]
        if not _positive(factor):
            return "invalid_adjustment_factor"
        failure = blocked(i, price, "buy")
        if failure:
            flags.add(f"buy_blocked_{failure}")
            event(dates[i], "buy_blocked", reason=failure, time=t.isoformat())
            return failure
        decision_time, why = buy_order
        amount = notional / 2
        legs.append(
            {
                "entry_date": dates[i],
                "entry_time": t.isoformat(),
                "entry_decision_time": decision_time.isoformat(),
                "entry_price": float(price),
                "factor": float(factor),
                "entry_factor": float(factor),
                "weight": 0.5,
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
        event(dates[i], "buy", reason=why, time=t.isoformat(), price=float(price))
        return None

    def sell(i: int, t: pd.Timestamp, price: float) -> str | None:
        factor = daily.iloc[i]["factor"]
        if not _positive(factor):
            return "invalid_adjustment_factor"
        failure = blocked(i, price, "sell")
        if failure:
            flags.add(f"sell_queued_{failure}")
            return failure
        for leg in legs:
            if leg["exit_date"] is not None or leg["entry_date"] >= dates[i]:
                continue
            proceeds = (
                leg["notional"]
                * price
                * factor
                / (leg["entry_price"] * leg["entry_factor"])
            )
            exit_costs = costs(dates[i], proceeds, "sell")
            gross = proceeds - leg["notional"]
            leg.update(
                exit_date=dates[i],
                exit_time=t.isoformat(),
                exit_decision_time=exit_decision.isoformat(),
                exit_price=float(price),
                exit_factor=float(factor),
                exit_reason=pending_exit,
                exit_costs=exit_costs,
                gross_pnl=gross,
                net_pnl=gross - leg["entry_costs"]["total"] - exit_costs["total"],
                exit_quantity=leg["quantity"] * factor / leg["entry_factor"],
            )
            event(
                dates[i],
                "sell",
                reason=pending_exit,
                time=t.isoformat(),
                price=float(price),
            )
        return None

    if _limit_rate(code, signal_date) is None:
        flags.add("price_limit_regime_unverified_before_1996_12_16")

    for i in range(signal_index, len(dates)):
        day, row = dates[i], daily.iloc[i]
        if (
            first_index is not None
            and i >= first_index + hold_days
            and not pending_exit
        ):
            pending_exit, exit_decision = "horizon", pd.Timestamp(day)
            buy_order = None
            event(
                day, "exit_queued", reason=pending_exit, time=exit_decision.isoformat()
            )
        raw = quotes.get(day) if quotes is not None else None
        if raw is None or raw.empty:
            if raw is not None and raw.attrs.get("confirmed_no_trades") is True:
                flags.add("confirmed_no_trade_session")
                event(day, "no_trades_confirmed")
                if i == signal_index:
                    return finish("skipped", "signal_no_trades")
                if pending_exit:
                    flags.add("sell_queued_suspended")
                continue
            return finish(
                "unverifiable", f"quote_data_missing: {day}", missing_quote_date=day
            )
        try:
            frame = _quote_frame(raw, day)
        except (KeyError, TypeError, ValueError) as exc:
            return finish(
                "unverifiable",
                f"invalid_quote_data: {day}: {exc}",
                missing_quote_date=day,
            )
        if frame.empty:
            return finish(
                "unverifiable", f"quote_session_empty: {day}", missing_quote_date=day
            )

        # The daily open is available at the opening, unlike this day's H/L/C.
        if (
            i == signal_index + 1
            and len(legs) < 2
            and not pending_exit
            and _positive(row["open"])
        ):
            if not _positive(references[i]):
                return finish("unverifiable", f"reference_price_missing: {day}")
            if row["open"] / references[i] - 1 >= 0.05 - _EPS:
                waiting, surge_time = True, pd.Timestamp(f"{day} 09:30")
                event(
                    day,
                    "pullback_wait",
                    time=surge_time.isoformat(),
                    price=float(row["open"]),
                    reference=float(references[i]),
                    observation="daily_open",
                )

        # A clock grid locates absent required samples; it supplies no prices.
        clock = pd.date_range(f"{day} 09:31", f"{day} 11:30", freq="min").union(
            pd.date_range(f"{day} 13:01", f"{day} 15:00", freq="min")
        )
        opening = pd.Timestamp(f"{day} 09:30")
        if opening in frame.index:
            clock = clock.insert(0, opening)
        decision = pd.Timestamp(f"{day} 14:50")
        snapshot = None
        window_size = held_windows = 0
        last_window_time = None

        for t in clock:
            sellable = any(
                leg["exit_date"] is None and leg["entry_date"] < day for leg in legs
            )
            if pending_exit and not sellable:
                # Only today's new leg remains. Later quotes cannot sell it.
                flags.add("sell_queued_t_plus_one")
                break
            sample = frame.loc[t] if t in frame.index else None
            price = sample["close"] if sample is not None else float("nan")
            executing = (pending_exit and t > exit_decision) or (
                buy_order is not None and t > buy_order[0]
            )
            if executing:
                if sample is None:
                    return finish(
                        "unverifiable",
                        f"next_execution_quote_missing: {t.isoformat()}",
                        missing_quote_date=day,
                    )
                volume = sample["volume"]
                if not isfinite(volume) or volume < 0:
                    return finish(
                        "unverifiable",
                        f"execution_quote_volume_unknown: {t.isoformat()}",
                        missing_quote_date=day,
                    )
                if volume > 0:
                    if not _positive(price):
                        return finish(
                            "unverifiable",
                            f"execution_quote_price_missing: {t.isoformat()}",
                            missing_quote_date=day,
                        )
                    adding = bool(legs)
                    failure = sell(i, t, price) if pending_exit else buy(i, t, price)
                    if failure in {
                        "invalid_adjustment_factor",
                        "reference_price_missing",
                    }:
                        return finish("unverifiable", f"{failure}: {day}")
                    if pending_exit:
                        if all(leg["exit_date"] is not None for leg in legs):
                            return finish("closed", "all_legs_closed")
                    else:
                        buy_order = None
                        if adding:
                            waiting = False
                        if failure and not legs:
                            return finish("skipped", f"first_buy_{failure}")
                else:
                    flags.add("execution_waited_for_positive_volume")
            if pending_exit:
                continue

            if _positive(price):
                snapshot = (t, price)
            if i > signal_index and len(legs) < 2:
                if not _positive(price):
                    flags.add("sampled_observations_incomplete")
                    window_size = held_windows = 0
                    last_window_time = None
                else:
                    if (
                        i == signal_index + 1
                        and not waiting
                        and (buy_order is None or not legs)
                    ):
                        if not _positive(references[i]):
                            return finish(
                                "unverifiable", f"reference_price_missing: {day}"
                            )
                        if price / references[i] - 1 >= 0.05 - _EPS:
                            waiting, surge_time = True, t
                            event(
                                day,
                                "pullback_wait",
                                time=t.isoformat(),
                                price=float(price),
                                reference=float(references[i]),
                                observation="sampled_close",
                            )
                    if (
                        waiting
                        and len(legs) == 1
                        and buy_order is None
                        and t > surge_time
                    ):
                        if not _positive(row["factor"]):
                            return finish(
                                "unverifiable", f"invalid_adjustment_factor: {day}"
                            )
                        if not _positive(prior_sums[i]):
                            return finish("unverifiable", "insufficient_ma5_history")
                        ma5 = (prior_sums[i] / row["factor"] + price) / 5
                        in_band = ma5 - _EPS <= price <= ma5 * 1.01 + _EPS
                        if (
                            last_window_time is not None
                            and t - last_window_time != pd.Timedelta(minutes=1)
                        ):
                            window_size = held_windows = 0
                        if window_size or held_windows or in_band:
                            window_size += 1
                            if window_size == 5:
                                held = bool(in_band)
                                held_windows = held_windows + 1 if held else 0
                                event(
                                    day,
                                    "pullback_window",
                                    time=t.isoformat(),
                                    held=held,
                                    price=float(price),
                                    ma5=float(ma5),
                                )
                                window_size = 0
                                if held_windows == 2:
                                    buy_order = (t, "ma5_pullback_two_windows")
                                    event(
                                        day,
                                        "add_queued",
                                        reason=buy_order[1],
                                        time=t.isoformat(),
                                    )
                        last_window_time = t

            if t != decision or not (i == signal_index or legs):
                continue
            if snapshot is None or decision - snapshot[0] > pd.Timedelta(minutes=1):
                return finish(
                    "unverifiable",
                    f"quote_1450_stale_or_missing: {day}",
                    missing_quote_date=day,
                )
            if not _positive(row["factor"]):
                return finish("unverifiable", f"invalid_adjustment_factor: {day}")
            if not _positive(prior_sums[i]):
                return finish("unverifiable", "insufficient_ma5_history")
            snapshot_time, price = snapshot
            ma5 = (prior_sums[i] / row["factor"] + price) / 5
            event(
                day,
                "snapshot_1450",
                time=snapshot_time.isoformat(),
                decision_time=decision.isoformat(),
                price=float(price),
                ma5=float(ma5),
            )
            if price < ma5 - _EPS:
                if not legs:
                    return finish("skipped", "d2_below_dynamic_ma5")
                pending_exit, exit_decision = "ma5_break", decision
                buy_order = None
                event(
                    day, "exit_queued", reason=pending_exit, time=decision.isoformat()
                )
                if any(leg["entry_date"] == day for leg in legs):
                    flags.add("sell_queued_t_plus_one")
            elif i == signal_index:
                buy_order = (decision, "d2_dynamic_ma5_confirmation")
                event(
                    day, "entry_queued", reason=buy_order[1], time=decision.isoformat()
                )
            elif (
                i == signal_index + 1
                and len(legs) == 1
                and not waiting
                and buy_order is None
            ):
                if not _positive(row["open"]):
                    return finish("unverifiable", f"d3_open_missing: {day}")
                if not _positive(references[i]):
                    return finish("unverifiable", f"reference_price_missing: {day}")
                if _small_k(row["open"], price, references[i], ma5):
                    buy_order = (decision, "d3_small_k")
                    event(
                        day,
                        "add_queued",
                        reason=buy_order[1],
                        time=decision.isoformat(),
                    )

    return finish(
        "data_end",
        "exit_pending_at_data_end" if pending_exit else "horizon_not_reached",
    )
