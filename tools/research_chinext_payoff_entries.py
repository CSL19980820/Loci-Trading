"""Research two causal delayed-entry rules without changing deployed strategies."""
from __future__ import annotations

import argparse
import json
import math
import sys
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from tools.research_chinext_payoff_exits import (  # noqa: E402
    BASELINE,
    SPLITS,
    STRATEGIES,
    CutoffMarketStore,
    common_maturity_mask,
    context_evidence,
    execute_split_context,
    prepare,
    serializable_run,
    sha256,
    source_hashes,
    write_json,
)

VARIANTS = ("baseline", "next_day_strength", "next_day_platform_retest")
OUTPUT = ROOT / "docs/research/2026-10-04-chinext-payoff-study/entries"


def entry_signals(ctx: dict, variant: str, start: str, end: str) -> tuple[pd.DataFrame, dict]:
    # Common ORIGINAL signal cohort: an extra day is reserved for delayed entry.
    maturity = common_maturity_mask(ctx["signals"].index, start, end, max_hold=21)
    parent = ctx["signals"].where(maturity, False, axis=0).astype(bool)
    evidence = {"original_mature_opportunities": int(parent.to_numpy().sum()),
                "source_signal_days": int(parent.any(axis=1).sum()),
                "origin_maturity_sessions": 21,
                "last_original_signal": str(maturity.index[maturity][-1]) if maturity.any() else None}
    if variant == "baseline":
        result = parent
    else:
        panels = ctx["panels"]
        close, open_, high, low, volume = (panels[k] for k in ("close", "open", "high", "low", "volume"))
        valid = (np.isfinite(close) & np.isfinite(open_) & np.isfinite(high)
                 & np.isfinite(low) & np.isfinite(volume) & volume.gt(0)
                 & close.gt(0) & open_.gt(0) & low.gt(0)
                 & high.ge(close) & high.ge(open_) & low.le(close) & low.le(open_))
        previous_selected = parent.shift(1, fill_value=False)
        if variant == "next_day_strength":
            condition = close.gt(close.shift(1))
        elif variant == "next_day_platform_retest":
            computed = ctx["engine"].compute(panels, ctx["resolved_params"])
            field = ("前五日最高价" if ctx["engine"].slug == STRATEGIES[0] else "大阳线高点")
            level = computed.factors[field].shift(1)
            condition = low.le(level) & close.ge(level) & close.gt(open_)
        else:
            raise ValueError(variant)
        result = (previous_selected & valid & condition).fillna(False).astype(bool)
    if result.sum(axis=1).gt(2).any():
        raise AssertionError("A delayed rule expanded the original Top2 pool")
    evidence["confirmation_or_entry_signals"] = int(result.to_numpy().sum())
    evidence["not_confirmed_opportunities"] = evidence["original_mature_opportunities"] - evidence["confirmation_or_entry_signals"]
    return result, evidence


def run_variant(ctx: dict, variant: str, start: str, end: str) -> tuple[dict, list[dict]]:
    signals, evidence = entry_signals(ctx, variant, start, end)
    run = execute_split_context({**ctx, "signals": signals}, BASELINE.config(end), start, end)
    rows = []
    for trade in run["closed_trades"]:
        signal_pos = signals.index.get_loc(trade.signal_date)
        original_date = trade.signal_date if variant == "baseline" else str(signals.index[signal_pos - 1])
        row = {**trade.to_dict(include_factors=True), "origin_signal_date": original_date, "variant": variant}
        rows.append(row)
    count = evidence["original_mature_opportunities"]
    total = sum(trade.net_return_pct for trade in run["closed_trades"])
    body = {"variant": variant, **serializable_run(run), "opportunity_accounting": evidence,
            "net_mean_per_original_opportunity": round(total / count, 4) if count else None,
            "opportunity_convention": "Unconfirmed or skipped opportunities contribute zero; censored trades have unknown outcome and are separately disclosed. This is not account return."}
    return body, rows


def hashes() -> dict[str, str]:
    return {**source_hashes(), "tools/research_chinext_payoff_entries.py": sha256(Path(__file__))}


def eligible(row: dict) -> bool:
    m = row["metrics"]
    ratio = m.get("payoff_ratio")
    return (m.get("trades", 0) >= 80 and isinstance(ratio, (int, float)) and math.isfinite(ratio)
            and m.get("profit_factor", 0) > 1 and m.get("avg_net_return", 0) > 0)


def train(db: Path, output: Path) -> None:
    output.mkdir(parents=True, exist_ok=True)
    receipt = output / "freeze-receipt.json"
    if receipt.exists():
        raise ValueError("Preserve the existing train freeze; choose a new output directory for a new study")
    write_json(output / "methodology.json", {
        "scope": "Only research artifacts; no deployed signal or entry change",
        "variants": {
            "baseline": "Original signal T; next market day T+1 open",
            "next_day_strength": "Original selected T; T+1 completed close > T close; enter T+2 open",
            "next_day_platform_retest": "Original selected T; T+1 low <= original breakout level, close >= level, close > open; enter T+2 open",
        },
        "exit": "Same 4 sessions including entry, -6% stop, no take profit, strict T+1/limit/economic execution; 0.21% cost",
        "pool": "Carry original actual Top2; no stock discovery or same-day confirmation-price fill",
        "cohort": "All rules share original T opportunities with next_open offset + 20 sessions + one confirmation-delay buffer. Actual entry and exit must fit the segment.",
        "selection": "Freeze every predeclared nonbaseline rule with >=80 training closed trades, finite payoff, PF>1, mean>0; at most 2 per strategy. No validation tuning.",
        "limitations": "Daily signals and next-open model, not tail fill. Current membership/factor revision and 2026-known base-score selection biases remain.",
        "splits": SPLITS,
    })
    start, end = SPLITS["train"]
    summaries, freeze_strategies = {}, {}
    with CutoffMarketStore(db, end) as store:
        for slug in STRATEGIES:
            ctx = prepare(store, slug, start, end)
            runs = {}
            for variant in VARIANTS:
                body, rows = run_variant(ctx, variant, start, end)
                runs[variant] = body
                pd.DataFrame(rows).to_csv(output / f"{slug}-train-{variant}-trades.csv", index=False)
                print(slug, "train", variant, json.dumps(body["metrics"], ensure_ascii=False), flush=True)
            # Prefix check concerns the ENTRY decision, not the future trade outcome.
            cutoff = "2024-10-31"
            prefix_panels = {k: v.loc[:cutoff] if isinstance(v, pd.DataFrame) else v for k, v in ctx["panels"].items()}
            base_prefix = ctx["engine"].compute(prefix_panels, ctx["resolved_params"])
            prefix_ctx = {**ctx, "panels": prefix_panels, "signals": base_prefix.signals}
            for variant in VARIANTS:
                # Use a common cohort mask decided by the segment, then test only interior rows.
                full, _ = entry_signals(ctx, variant, start, end)
                short, _ = entry_signals(prefix_ctx, variant, start, end)
                interior = str(short.index[-25])
                pd.testing.assert_frame_equal(full.loc[:interior], short.loc[:interior])
            chosen = [variant for variant in VARIANTS[1:] if eligible(runs[variant])]
            summaries[slug] = {"context": context_evidence(ctx), "runs": runs,
                               "entry_decision_prefix_cutoff": cutoff, "frozen": chosen}
            freeze_strategies[slug] = chosen
    write_json(output / "training-summary.json", summaries)
    write_json(receipt, {"phase": "training_complete_validation_unopened",
                        "created_at": datetime.now(ZoneInfo("Asia/Shanghai")).isoformat(),
                        "database_sha256": sha256(db), "source_sha256": hashes(),
                        "methodology_sha256": sha256(output / "methodology.json"),
                        "training_summary_sha256": sha256(output / "training-summary.json"),
                        "strategies": freeze_strategies})


def evaluate(db: Path, output: Path) -> None:
    receipt_path = output / "freeze-receipt.json"
    frozen = json.loads(receipt_path.read_text(encoding="utf-8"))
    assert sha256(db) == frozen["database_sha256"]
    assert hashes() == frozen["source_sha256"]
    assert sha256(output / "training-summary.json") == frozen["training_summary_sha256"]
    assert sha256(output / "methodology.json") == frozen["methodology_sha256"]
    summaries = {}
    for split in ("validation", "observed_2026"):
        start, end = SPLITS[split]
        summaries[split] = {}
        with CutoffMarketStore(db, end) as store:
            for slug in STRATEGIES:
                ctx = prepare(store, slug, start, end)
                runs = {}
                for variant in ("baseline", *frozen["strategies"][slug]):
                    body, rows = run_variant(ctx, variant, start, end)
                    runs[variant] = body
                    pd.DataFrame(rows).to_csv(output / f"{slug}-{split}-{variant}-trades.csv", index=False)
                    m = body["metrics"]
                    print(slug, split, variant, {k: m.get(k) for k in ("trades", "win_rate", "payoff_ratio", "profit_factor", "avg_net_return")}, flush=True)
                summaries[split][slug] = {"context": context_evidence(ctx), "runs": runs}
        write_json(output / "evaluation-summary.json", {"freeze_receipt_sha256": sha256(receipt_path), "splits": summaries})


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("phase", choices=("train", "evaluate"))
    parser.add_argument("--db", type=Path, required=True)
    parser.add_argument("--output", type=Path, default=OUTPUT)
    args = parser.parse_args()
    if args.phase == "train":
        train(args.db, args.output)
    else:
        evaluate(args.db, args.output)


if __name__ == "__main__":
    main()
