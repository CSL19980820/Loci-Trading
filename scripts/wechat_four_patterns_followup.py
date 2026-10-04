"""Post-hoc diagnostic of the contraction subgroup; not independent validation.

Run only after the predeclared 19-scenario experiment. No rule thresholds are
optimized here. Keep all outcomes, including adverse holding/cost sensitivities.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
from pathlib import Path

import numpy as np

from scripts.wechat_four_patterns_research import (
    DEFAULT_OUT, END, PERIODS, START, load_snapshot, save_json, save_picks, scenario, sha,
)
from src.strategy.application.wechat_four_patterns import WechatFourPatternsStrategy


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", type=Path, default=DEFAULT_OUT)
    args = parser.parse_args()
    out = args.out.resolve()
    if not (out / "summaries.json").exists():
        raise RuntimeError("run the predeclared study first")
    protocol = out / "followup_protocol.json"
    if not protocol.exists():
        save_json(protocol, {
            "created_at": datetime.now(timezone.utc).isoformat(), "post_hoc": True,
            "reason": "Contraction subgroup positive in both observed periods; selected after reviewing the original results.",
            "not_independent_oos": True, "threshold_changes": False,
            "scenarios": ["contraction full 20 months", "each period contraction double cost", "each period contraction 2 sessions", "each period contraction only 1 pick per day"],
            "code_sha256": sha(Path(__file__)),
        })
    raw, adjusted, benchmark = load_snapshot(out)
    engine = WechatFourPatternsStrategy()
    result = engine.compute(adjusted, {"pattern": "contraction"})
    singles = engine.compute(adjusted, {"pattern": "contraction", "daily_limit": 1})
    import pandas as pd
    names = pd.read_csv(out / "universe.csv", dtype={"code": str}).set_index("code").name.to_dict()
    pick_mask = result.signals.copy()
    pick_mask.loc[pick_mask.index < START] = False
    save_picks(out / "contraction_picks.csv", result, pick_mask, names)
    values = []
    for year, (start, end) in PERIODS.items():
        values.append(scenario(out, year + "_contraction_double_cost", result.signals, raw, benchmark, start, end, cost_multiple=2))
        values.append(scenario(out, year + "_contraction_hold_2sessions", result.signals, raw, benchmark, start, end, hold_days=1))
        values.append(scenario(out, year + "_contraction_one_pick", singles.signals, raw, benchmark, start, end))
    values.append(scenario(out, "full_contraction", result.signals, raw, benchmark, START, END))
    save_json(out / "followup_summaries.json", values)
    # Inspect liquidity-field provenance instead of calling proxy amounts native.
    valid = raw["close"].gt(0) & raw["volume"].gt(0) & raw["amount"].notna()
    product = raw["close"] * raw["volume"]
    exact = np.isclose(raw["amount"], product, rtol=1e-10, atol=0.01) & valid
    save_json(out / "liquidity_field_audit.json", {
        "quoted_rows_with_volume_and_amount": int(valid.sum().sum()),
        "amount_equal_close_times_volume_rows": int(exact.sum().sum()),
        "fraction_equal": float(exact.sum().sum() / valid.sum().sum()),
        "interpretation": "For matching rows, stored amount behaves like a close*volume liquidity proxy, not native daily turnover; no VWAP/order-flow inference is justified.",
        "provider_code_evidence": "src/market/infrastructure/tencent.py::_parse_daily_rows currently leaves native unavailable amount as None; frozen DB contains older stored values.",
        "affects": "50 million threshold is a stored-amount/proxy liquidity filter in this study. No real-amount provenance claim.",
    })
    print("FOLLOWUP COMPLETE (post-hoc, not independent OOS)", flush=True)


if __name__ == "__main__":
    main()
