"""Read-only streaming check for a 12-1 cross-sectional momentum candidate."""
from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

import numpy as np

if __package__ in (None, ""):
    from streaming_execution_audit import execution_overlap_audit
    from low_tvol_streaming_research import (
        DEFAULT_CAPACITY,
        DEFAULT_END,
        DEFAULT_EXIT_GRACE_DAYS,
        DEFAULT_INITIAL_CAPITAL,
        DEFAULT_ROUND_TRIP_COST_PCT,
        _account_metrics,
        _audit_snapshot,
        _calendar,
        _flatten,
        _ic_metrics,
        _read_only_connection,
        _select_groups,
        _signal_indexes,
        _stream_candidates,
        _trade_metrics,
        _year_segments,
    )
else:
    from scripts.streaming_execution_audit import execution_overlap_audit
    from scripts.low_tvol_streaming_research import (
        DEFAULT_CAPACITY,
        DEFAULT_END,
        DEFAULT_EXIT_GRACE_DAYS,
        DEFAULT_INITIAL_CAPITAL,
        DEFAULT_ROUND_TRIP_COST_PCT,
        _account_metrics,
        _audit_snapshot,
        _calendar,
        _flatten,
        _ic_metrics,
        _read_only_connection,
        _select_groups,
        _signal_indexes,
        _stream_candidates,
        _trade_metrics,
        _year_segments,
    )


DEFAULT_START = "2018-01-02"
DEFAULT_FORMATION_DAYS = 252
DEFAULT_SKIP_DAYS = 21
DEFAULT_HOLD_DAYS = 21
DEFAULT_REBALANCE_EVERY = 21


def _momentum_12_1_score(
    close_price: np.ndarray,
    signal_index: int,
    *,
    formation_days: int,
    skip_days: int,
) -> float | None:
    start_index = signal_index - formation_days
    end_index = signal_index - skip_days
    if start_index < 0 or end_index <= start_index:
        return None
    history = close_price[start_index : end_index + 1]
    if len(history) != formation_days - skip_days + 1:
        return None
    if not np.all(np.isfinite(history)) or np.any(history <= 0):
        return None
    score = float(history[-1] / history[0] - 1.0)
    return score if np.isfinite(score) else None


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
        if start_index < args.formation_days:
            raise ValueError("not enough calendar history before start for the formation period")
        load_start = dates[start_index - args.formation_days]
        load_end = dates[
            min(len(dates) - 1, bounded_end_index + args.hold_days + args.exit_grace_days)
        ]
        candidates_by_date = _stream_candidates(
            connection,
            all_dates=dates,
            signal_indexes=signal_indexes,
            load_start=load_start,
            load_end=load_end,
            score_fn=lambda close_price, signal_index: _momentum_12_1_score(
                close_price,
                signal_index,
                formation_days=args.formation_days,
                skip_days=args.skip_days,
            ),
            hold_days=args.hold_days,
            exit_grace_days=args.exit_grace_days,
            round_trip_cost_pct=args.round_trip_cost_pct,
        )
        high_decile, low_decile, high_capacity = _select_groups(
            candidates_by_date, capacity=args.capacity, higher_is_better=True
        )
        account, group_returns = _account_metrics(
            high_capacity,
            capacity=args.capacity,
            initial_capital=args.initial_capital,
        )
        execution_audit = execution_overlap_audit(
            high_capacity, capacity=args.capacity, hold_days=args.hold_days
        )
        return {
            "candidate": f"momentum-{args.formation_days}-{args.skip_days}",
            "status": "exploratory_non_pit",
            "definition": {
                "score": (
                    f"adjusted_close[T-{args.skip_days}] / "
                    f"adjusted_close[T-{args.formation_days}] - 1"
                ),
                "orientation": "higher momentum is better",
                "note": "A daily approximation of monthly prior (2-12) return, not a published A-share replication",
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
                higher_is_better=True,
                direction_label="high_momentum_direction",
            ),
            "groups": {
                "high_decile": _trade_metrics(_flatten(high_decile)),
                "low_decile": _trade_metrics(_flatten(low_decile)),
                "highest_capacity": {
                    "trade_metrics": _trade_metrics(_flatten(high_capacity)),
                    "account_metrics": account,
                    "year_segments": _year_segments(group_returns),
                },
            },
            "data_audit": _audit_snapshot(connection),
            "limitations": [
                "Current instruments are used as a survivor-biased universe, not a historical membership snapshot.",
                "No source-route receipts or attempts imply this cannot meet strict PIT provenance.",
                "The score approximates monthly prior (2-12) return with trading days and does not reproduce size weighting.",
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
    parser.add_argument("--formation-days", type=int, default=DEFAULT_FORMATION_DAYS)
    parser.add_argument("--skip-days", type=int, default=DEFAULT_SKIP_DAYS)
    parser.add_argument("--hold-days", type=int, default=DEFAULT_HOLD_DAYS)
    parser.add_argument("--rebalance-every", type=int, default=DEFAULT_REBALANCE_EVERY)
    parser.add_argument("--capacity", type=int, default=DEFAULT_CAPACITY)
    parser.add_argument("--round-trip-cost-pct", type=float, default=DEFAULT_ROUND_TRIP_COST_PCT)
    parser.add_argument("--exit-grace-days", type=int, default=DEFAULT_EXIT_GRACE_DAYS)
    parser.add_argument("--initial-capital", type=float, default=DEFAULT_INITIAL_CAPITAL)
    parser.add_argument("--output", type=Path, help="Optional JSON output; omitted means stdout only")
    args = parser.parse_args()
    if min(args.formation_days, args.skip_days, args.hold_days, args.rebalance_every, args.capacity) <= 0:
        raise SystemExit("formation-days, skip-days, hold-days, rebalance-every, and capacity must be positive")
    if args.skip_days >= args.formation_days:
        raise SystemExit("skip-days must be smaller than formation-days")
    result = run(args)
    text = json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True)
    if args.output:
        args.output.write_text(text + "\n", encoding="utf-8")
    print(text)


if __name__ == "__main__":
    main()
