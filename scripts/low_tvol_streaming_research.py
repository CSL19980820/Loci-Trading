"""Read-only streaming sensitivity check for a low total-volatility candidate.

This is intentionally not an IVOL implementation.  It computes a trailing
standard deviation of adjusted close-to-close returns, then tests the declared
low-volatility direction with a fixed T+1-open execution proxy.  The market
database is opened read-only and no output is written unless --output is set.
"""
from __future__ import annotations

import argparse
from bisect import bisect_right
from collections import defaultdict
from dataclasses import dataclass
import json
from pathlib import Path
import sqlite3
from typing import Any, Callable, Iterable

import numpy as np
import pandas as pd

if __package__ in (None, ""):
    from streaming_execution_audit import execution_overlap_audit
else:
    from scripts.streaming_execution_audit import execution_overlap_audit


DEFAULT_START = "2018-01-02"
DEFAULT_END = "2026-07-07"
DEFAULT_WINDOW = 21
DEFAULT_HOLD_DAYS = 20
DEFAULT_REBALANCE_EVERY = 20
DEFAULT_CAPACITY = 20
DEFAULT_ROUND_TRIP_COST_PCT = 0.26
DEFAULT_EXIT_GRACE_DAYS = 20
DEFAULT_INITIAL_CAPITAL = 200_000.0


@dataclass(frozen=True)
class Candidate:
    signal_date: str
    code: str
    score: float
    net_return_pct: float | None
    signal_index: int | None = None
    entry_index: int | None = None
    exit_index: int | None = None


ScoreFunction = Callable[[np.ndarray, int], float | None]


def _read_only_connection(db_path: Path) -> sqlite3.Connection:
    resolved = db_path.resolve()
    if not resolved.is_file():
        raise FileNotFoundError(f"market database not found: {resolved}")
    connection = sqlite3.connect(f"{resolved.as_uri()}?mode=ro", uri=True)
    connection.execute("PRAGMA query_only = ON")
    return connection


def _calendar(connection: sqlite3.Connection) -> list[str]:
    return [
        str(row[0])
        for row in connection.execute(
            "SELECT trade_date FROM trading_calendar ORDER BY trade_date"
        )
    ]


def _signal_indexes(
    dates: list[str],
    *,
    start: str,
    end: str,
    hold_days: int,
    exit_grace_days: int,
    rebalance_every: int,
) -> tuple[list[int], int, int]:
    try:
        start_index = dates.index(start)
        end_index = dates.index(end)
    except ValueError as exc:
        raise ValueError("start and end must both be market trading days") from exc
    if end_index < start_index:
        raise ValueError("end must be on or after start")
    last_possible = len(dates) - hold_days - exit_grace_days - 1
    if last_possible < start_index:
        raise ValueError("calendar has no room for the requested holding period")
    bounded_end = min(end_index, last_possible)
    return list(range(start_index, bounded_end + 1, rebalance_every)), start_index, bounded_end


def _is_executable(
    open_price: np.ndarray,
    high_price: np.ndarray,
    low_price: np.ndarray,
    close_price: np.ndarray,
    volume: np.ndarray,
    index: int,
) -> bool:
    values = (
        open_price[index],
        high_price[index],
        low_price[index],
        close_price[index],
        volume[index],
    )
    return (
        all(np.isfinite(value) for value in values)
        and open_price[index] > 0
        and close_price[index] > 0
        and volume[index] > 0
        and high_price[index] > low_price[index]
    )


def _net_return_pct(
    open_price: np.ndarray,
    high_price: np.ndarray,
    low_price: np.ndarray,
    close_price: np.ndarray,
    volume: np.ndarray,
    *,
    signal_index: int,
    hold_days: int,
    exit_grace_days: int,
    round_trip_cost_pct: float,
) -> tuple[float, int, int] | None:
    entry_index = signal_index + 1
    if entry_index >= len(close_price) or not _is_executable(
        open_price, high_price, low_price, close_price, volume, entry_index
    ):
        return None
    target_exit = signal_index + hold_days
    last_exit = min(len(close_price), target_exit + exit_grace_days + 1)
    for exit_index in range(target_exit, last_exit):
        if _is_executable(open_price, high_price, low_price, close_price, volume, exit_index):
            gross = close_price[exit_index] / open_price[entry_index] - 1.0
            return (gross - round_trip_cost_pct / 100.0) * 100.0, entry_index, exit_index
    return None


def _tvol_score(close_price: np.ndarray, signal_index: int, *, window: int) -> float | None:
    window_close = close_price[signal_index - window : signal_index + 1]
    if len(window_close) != window + 1 or not np.all(np.isfinite(window_close)):
        return None
    if np.any(window_close <= 0):
        return None
    daily_returns = window_close[1:] / window_close[:-1] - 1.0
    score = float(np.std(daily_returns, ddof=1))
    return score if np.isfinite(score) else None


def _append_code_candidates(
    rows: list[sqlite3.Row],
    *,
    factor_history: list[tuple[str, float]],
    all_dates: list[str],
    date_positions: dict[str, int],
    signal_indexes: Iterable[int],
    score_fn: ScoreFunction,
    hold_days: int,
    exit_grace_days: int,
    round_trip_cost_pct: float,
    candidates_by_date: dict[str, list[Candidate]],
) -> None:
    if not rows:
        return
    size = len(all_dates)
    open_price = np.full(size, np.nan)
    high_price = np.full(size, np.nan)
    low_price = np.full(size, np.nan)
    close_price = np.full(size, np.nan)
    volume = np.full(size, np.nan)
    code = str(rows[0][0])
    factor_dates = [date for date, _ in factor_history]
    factor_values = [value for _, value in factor_history]
    for row in rows:
        position = date_positions.get(str(row[1]))
        if position is None:
            continue
        # adjust_factors is sparse at corporate-action dates. Match the store's
        # panel behavior: use the earliest known factor before its first date,
        # then forward-fill each later factor change.
        factor = (
            factor_values[max(0, bisect_right(factor_dates, str(row[1])) - 1)]
            if factor_values
            else 1.0
        )
        raw_open = float(row[2]) if row[2] is not None else np.nan
        raw_high = float(row[3]) if row[3] is not None else np.nan
        raw_low = float(row[4]) if row[4] is not None else np.nan
        raw_close = float(row[5]) if row[5] is not None else np.nan
        open_price[position] = raw_open * factor
        high_price[position] = raw_high * factor
        low_price[position] = raw_low * factor
        close_price[position] = raw_close * factor
        volume[position] = float(row[6]) if row[6] is not None else np.nan

    for signal_index in signal_indexes:
        score = score_fn(close_price, signal_index)
        if score is None:
            continue
        outcome = _net_return_pct(
            open_price,
            high_price,
            low_price,
            close_price,
            volume,
            signal_index=signal_index,
            hold_days=hold_days,
            exit_grace_days=exit_grace_days,
            round_trip_cost_pct=round_trip_cost_pct,
        )
        candidates_by_date[all_dates[signal_index]].append(
            Candidate(
                signal_date=all_dates[signal_index],
                code=code,
                score=score,
                net_return_pct=outcome[0] if outcome is not None else None,
                signal_index=signal_index,
                entry_index=outcome[1] if outcome is not None else None,
                exit_index=outcome[2] if outcome is not None else None,
            )
        )


def _stream_candidates(
    connection: sqlite3.Connection,
    *,
    all_dates: list[str],
    signal_indexes: list[int],
    load_start: str,
    load_end: str,
    score_fn: ScoreFunction,
    hold_days: int,
    exit_grace_days: int,
    round_trip_cost_pct: float,
) -> dict[str, list[Candidate]]:
    date_positions = {date: index for index, date in enumerate(all_dates)}
    candidates_by_date: dict[str, list[Candidate]] = defaultdict(list)
    factor_history: dict[str, list[tuple[str, float]]] = defaultdict(list)
    for code, trade_date, factor in connection.execute(
        "SELECT code, trade_date, hfq_factor FROM adjust_factors ORDER BY code, trade_date"
    ):
        factor_history[str(code)].append((str(trade_date), float(factor)))
    query = """
        SELECT q.code, q.trade_date, q.open, q.high, q.low, q.close, q.volume
        FROM quotes_daily AS q
        JOIN instruments AS i ON i.code = q.code
        WHERE i.instrument_type = 'STOCK'
          AND i.status = 'normal'
          AND q.trade_date BETWEEN ? AND ?
        ORDER BY q.code, q.trade_date
    """
    cursor = connection.execute(query, (load_start, load_end))
    current_code: str | None = None
    rows: list[sqlite3.Row] = []
    for row in cursor:
        code = str(row[0])
        if current_code is not None and code != current_code:
            _append_code_candidates(
                rows,
                factor_history=factor_history.get(current_code, []),
                all_dates=all_dates,
                date_positions=date_positions,
                signal_indexes=signal_indexes,
                score_fn=score_fn,
                hold_days=hold_days,
                exit_grace_days=exit_grace_days,
                round_trip_cost_pct=round_trip_cost_pct,
                candidates_by_date=candidates_by_date,
            )
            rows = []
        current_code = code
        rows.append(row)
    _append_code_candidates(
        rows,
        factor_history=factor_history.get(current_code or "", []),
        all_dates=all_dates,
        date_positions=date_positions,
        signal_indexes=signal_indexes,
        score_fn=score_fn,
        hold_days=hold_days,
        exit_grace_days=exit_grace_days,
        round_trip_cost_pct=round_trip_cost_pct,
        candidates_by_date=candidates_by_date,
    )
    return candidates_by_date


def _trade_metrics(items: Iterable[Candidate]) -> dict[str, float | int | None]:
    returns = np.asarray(
        [item.net_return_pct for item in items if item.net_return_pct is not None], dtype=float
    )
    if returns.size == 0:
        return {
            "trades": 0,
            "win_rate_pct": None,
            "avg_net_return_pct": None,
            "median_net_return_pct": None,
            "payoff_ratio": None,
            "profit_factor": None,
        }
    wins = returns[returns > 0]
    losses = returns[returns <= 0]
    avg_win = float(wins.mean()) if wins.size else None
    avg_loss = float(losses.mean()) if losses.size else None
    return {
        "trades": int(returns.size),
        "win_rate_pct": round(float((returns > 0).mean() * 100.0), 4),
        "avg_net_return_pct": round(float(returns.mean()), 4),
        "median_net_return_pct": round(float(np.median(returns)), 4),
        "payoff_ratio": (
            None if avg_win is None or avg_loss in (None, 0.0) else round(avg_win / abs(avg_loss), 4)
        ),
        "profit_factor": (
            None
            if losses.size == 0 or float(losses.sum()) == 0.0
            else round(float(wins.sum() / abs(losses.sum())), 4)
        ),
    }


def _account_metrics(
    by_date: dict[str, list[Candidate]],
    *,
    capacity: int,
    initial_capital: float,
) -> tuple[dict[str, float | int | str | None], list[tuple[str, float]]]:
    if not by_date:
        return {
            "rebalance_groups": 0,
            "avg_positions_per_group": 0.0,
            "account_return_pct": None,
            "account_final_capital": None,
            "account_max_drawdown_pct": None,
            "drawdown_basis": "rebalance_boundary_realized_equity",
        }, []
    group_returns: list[tuple[str, float]] = []
    position_counts: list[int] = []
    for date, selected in sorted(by_date.items()):
        available = [item.net_return_pct for item in selected if item.net_return_pct is not None]
        position_counts.append(len(available))
        group_returns.append((date, float(sum(available) / capacity)))
    returns = np.asarray([value for _, value in group_returns], dtype=float) / 100.0
    equity = np.cumprod(1.0 + returns)
    drawdown = equity / np.maximum.accumulate(equity) - 1.0
    return {
        "rebalance_groups": len(group_returns),
        "avg_positions_per_group": round(float(np.mean(position_counts)), 4),
        "account_return_pct": round(float((equity[-1] - 1.0) * 100.0), 4),
        "account_final_capital": round(float(initial_capital * equity[-1]), 2),
        "account_max_drawdown_pct": round(float(drawdown.min() * 100.0), 4),
        "drawdown_basis": "rebalance_boundary_realized_equity",
    }, group_returns


def _year_segments(group_returns: Iterable[tuple[str, float]]) -> dict[str, dict[str, float | int | None]]:
    per_year: dict[str, list[float]] = defaultdict(list)
    for date, value in group_returns:
        per_year[date[:4]].append(value)
    result: dict[str, dict[str, float | int | None]] = {}
    for year, values in sorted(per_year.items()):
        returns = np.asarray(values, dtype=float)
        wins = returns[returns > 0]
        losses = returns[returns <= 0]
        result[year] = {
            "groups": int(returns.size),
            "avg_account_return_pct": round(float(returns.mean()), 4),
            "win_rate_pct": round(float((returns > 0).mean() * 100.0), 4),
            "profit_factor": (
                None
                if losses.size == 0 or float(losses.sum()) == 0.0
                else round(float(wins.sum() / abs(losses.sum())), 4)
            ),
        }
    return result


def _ic_metrics(
    candidates_by_date: dict[str, list[Candidate]], *, higher_is_better: bool, direction_label: str
) -> dict[str, float | int | None]:
    pearson_values: list[float] = []
    rank_values: list[float] = []
    for rows in candidates_by_date.values():
        usable = [row for row in rows if row.net_return_pct is not None]
        if len(usable) < 3:
            continue
        oriented_score = pd.Series(
            [row.score if higher_is_better else -row.score for row in usable]
        )
        future_return = pd.Series([row.net_return_pct for row in usable])
        pearson = oriented_score.corr(future_return, method="pearson")
        rank_ic = oriented_score.corr(future_return, method="spearman")
        if pd.notna(pearson):
            pearson_values.append(float(pearson))
        if pd.notna(rank_ic):
            rank_values.append(float(rank_ic))
    return {
        "cross_sections": len(rank_values),
        f"mean_pearson_ic_{direction_label}": (
            None if not pearson_values else round(float(np.mean(pearson_values)), 6)
        ),
        f"mean_rank_ic_{direction_label}": (
            None if not rank_values else round(float(np.mean(rank_values)), 6)
        ),
    }


def _select_groups(
    candidates_by_date: dict[str, list[Candidate]], *, capacity: int, higher_is_better: bool
) -> tuple[dict[str, list[Candidate]], dict[str, list[Candidate]], dict[str, list[Candidate]]]:
    low_decile: dict[str, list[Candidate]] = {}
    high_decile: dict[str, list[Candidate]] = {}
    low_capacity: dict[str, list[Candidate]] = {}
    for date, rows in candidates_by_date.items():
        ordered = sorted(
            rows,
            key=lambda item: (-item.score, item.code) if higher_is_better else (item.score, item.code),
        )
        if not ordered:
            continue
        decile_size = max(1, len(ordered) // 10)
        low_decile[date] = ordered[:decile_size]
        high_decile[date] = ordered[-decile_size:]
        low_capacity[date] = ordered[:capacity]
    return low_decile, high_decile, low_capacity


def _flatten(groups: dict[str, list[Candidate]]) -> list[Candidate]:
    return [item for rows in groups.values() for item in rows]


def _audit_snapshot(connection: sqlite3.Connection) -> dict[str, int | str | None]:
    return {
        "eligible_current_stocks": int(
            connection.execute(
                "SELECT COUNT(*) FROM instruments WHERE instrument_type='STOCK' AND status='normal'"
            ).fetchone()[0]
        ),
        "quote_first_date": connection.execute("SELECT MIN(trade_date) FROM quotes_daily").fetchone()[0],
        "quote_last_date": connection.execute("SELECT MAX(trade_date) FROM quotes_daily").fetchone()[0],
        "source_route_receipts": int(
            connection.execute("SELECT COUNT(*) FROM source_route_receipts").fetchone()[0]
        ),
        "source_route_attempts": int(
            connection.execute("SELECT COUNT(*) FROM source_route_attempts").fetchone()[0]
        ),
        "adjust_factor_rows": int(
            connection.execute("SELECT COUNT(*) FROM adjust_factors").fetchone()[0]
        ),
    }


def run(args: argparse.Namespace) -> dict[str, Any]:
    connection = _read_only_connection(args.db)
    try:
        dates = _calendar(connection)
        signal_indexes, start_index, bounded_end_index = _signal_indexes(
            dates,
            start=args.start,
            end=args.end,
            hold_days=args.hold_days,
            exit_grace_days=args.exit_grace_days,
            rebalance_every=args.rebalance_every,
        )
        if start_index < args.window:
            raise ValueError("not enough calendar history before start for the requested window")
        load_start = dates[start_index - args.window]
        load_end = dates[
            min(len(dates) - 1, bounded_end_index + args.hold_days + args.exit_grace_days)
        ]
        candidates_by_date = _stream_candidates(
            connection,
            all_dates=dates,
            signal_indexes=signal_indexes,
            load_start=load_start,
            load_end=load_end,
            score_fn=lambda close_price, signal_index: _tvol_score(
                close_price, signal_index, window=args.window
            ),
            hold_days=args.hold_days,
            exit_grace_days=args.exit_grace_days,
            round_trip_cost_pct=args.round_trip_cost_pct,
        )
        low_decile, high_decile, low_capacity = _select_groups(
            candidates_by_date, capacity=args.capacity, higher_is_better=False
        )
        low_capacity_trades = _flatten(low_capacity)
        account, group_returns = _account_metrics(
            low_capacity,
            capacity=args.capacity,
            initial_capital=args.initial_capital,
        )
        execution_audit = execution_overlap_audit(
            low_capacity, capacity=args.capacity, hold_days=args.hold_days
        )
        return {
            "candidate": f"low-tvol-{args.window}d-sensitivity",
            "status": "exploratory_non_pit",
            "definition": {
                "score": (
                    f"std of {args.window} contiguous adjusted close-to-close daily returns"
                ),
                "orientation": "lower total volatility is better",
                "note": "TVOL is a sensitivity proxy, not idiosyncratic volatility",
            },
            "sample": {
                "requested_signal_start": args.start,
                "requested_signal_end": args.end,
                "actual_last_signal_date": dates[signal_indexes[-1]],
                "load_start": load_start,
                "load_end": load_end,
                "rebalance_dates": len(signal_indexes),
                "factor_observations": sum(len(rows) for rows in candidates_by_date.values()),
            },
            "execution_proxy": {
                "signal": "post-close",
                "entry": "next-session adjusted open; no suspension or one-price bar",
                "exit": (
                    f"adjusted close {args.hold_days} sessions after signal; "
                    "defer for suspension or one-price bar"
                ),
                "round_trip_cost_pct": args.round_trip_cost_pct,
                "selection_capacity": args.capacity,
                "empty_slots": "cash; no refill after an untradable ranked selection",
                "drawdown_basis": "rebalance-boundary realized equity, not daily mark-to-market",
            },
            "execution_audit": execution_audit,
            "factor_diagnostics": _ic_metrics(
                candidates_by_date,
                higher_is_better=False,
                direction_label="low_tvol_direction",
            ),
            "groups": {
                "low_decile": _trade_metrics(_flatten(low_decile)),
                "high_decile": _trade_metrics(_flatten(high_decile)),
                "lowest_capacity": {
                    "trade_metrics": _trade_metrics(low_capacity_trades),
                    "account_metrics": account,
                    "year_segments": _year_segments(group_returns),
                },
            },
            "data_audit": _audit_snapshot(connection),
            "limitations": [
                "Current instruments are used as a survivor-biased universe, not a historical membership snapshot.",
                "No source-route receipts or attempts imply this cannot meet strict PIT provenance.",
                "No A-share factor-return series is supplied, so this does not estimate IVOL.",
                "Rebalance-boundary account metrics are not executable evidence when the overlap audit reports slot conflicts.",
                "This reports an exploratory execution proxy, not a frozen research run or production strategy.",
            ],
        }
    finally:
        connection.close()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--db", type=Path, required=True, help="Path to market.db; opened mode=ro")
    parser.add_argument("--start", default=DEFAULT_START)
    parser.add_argument("--end", default=DEFAULT_END)
    parser.add_argument("--window", type=int, default=DEFAULT_WINDOW)
    parser.add_argument("--hold-days", type=int, default=DEFAULT_HOLD_DAYS)
    parser.add_argument("--rebalance-every", type=int, default=DEFAULT_REBALANCE_EVERY)
    parser.add_argument("--capacity", type=int, default=DEFAULT_CAPACITY)
    parser.add_argument("--round-trip-cost-pct", type=float, default=DEFAULT_ROUND_TRIP_COST_PCT)
    parser.add_argument("--exit-grace-days", type=int, default=DEFAULT_EXIT_GRACE_DAYS)
    parser.add_argument("--initial-capital", type=float, default=DEFAULT_INITIAL_CAPITAL)
    parser.add_argument("--output", type=Path, help="Optional JSON output; omitted means stdout only")
    args = parser.parse_args()
    if min(args.window, args.hold_days, args.rebalance_every, args.capacity) <= 0:
        raise SystemExit("window, hold-days, rebalance-every, and capacity must be positive")
    result = run(args)
    text = json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True)
    if args.output:
        args.output.write_text(text + "\n", encoding="utf-8")
    print(text)


if __name__ == "__main__":
    main()
