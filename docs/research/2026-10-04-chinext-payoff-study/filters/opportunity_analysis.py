"""Post-freeze diagnostics only; no model selection, no DB access or strategy edits."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parent


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def signals(path: Path) -> pd.DataFrame:
    frame = pd.read_csv(path, dtype={"code": str})
    if frame.duplicated(["signal_date", "code"]).any() or frame.groupby("signal_date").size().max() > 2:
        raise AssertionError("Invalid unique Top2 signal CSV")
    return frame


def trades(path: Path) -> dict[tuple[str, str], dict]:
    frame = pd.read_csv(path, dtype={"code": str})
    if frame.duplicated(["signal_date", "code"]).any():
        raise AssertionError("Duplicate independent event trade")
    return {(str(row["signal_date"]), str(row["code"])): row for row in frame.to_dict("records")}


def realization(key: tuple[str, str], selected: set, filled: dict,
                start: str, end: str) -> tuple[str, float]:
    if key not in selected:
        return "not_selected_known_zero", 0.
    if key not in filled:
        return "entry_skipped_known_zero", 0.
    trade = filled[key]
    if trade["exit_reason"] == "data_end":
        return "data_end_unknown", np.nan
    if not start <= trade["entry_date"] <= end or not start <= trade["exit_date"] <= end:
        return "boundary_unknown", np.nan
    if not trade["signal_date"] < trade["entry_date"] < trade["exit_date"]:
        raise AssertionError("Entry timing/T+1 violated")
    if not np.isclose(trade["gross_return_pct"] - trade["net_return_pct"], .21, atol=1e-8):
        raise AssertionError("Fee mismatch")
    return "closed", float(trade["net_return_pct"])


def analyze(segment: str, slug: str, record: dict, split: tuple[str, str],
            sources: dict) -> list[dict]:
    start, end = split
    base = next(row for row in record["runs"] if row["id"] == "baseline")
    base_signal_path = ROOT / f"{slug}-{segment}-baseline-signals.csv"
    base_trade_path = ROOT / f"{slug}-{segment}-baseline-trades.csv"
    base_signals, base_trades = signals(base_signal_path), trades(base_trade_path)
    base_keys = {(str(row["signal_date"]), str(row["code"])) for row in base_signals.to_dict("records")}
    assert len(base_keys) == base["accounting"]["eligible_signals"]
    result = []
    for run in record["runs"]:
        variant = run["id"]
        signal_path = ROOT / f"{slug}-{segment}-{variant}-signals.csv"
        trade_path = ROOT / f"{slug}-{segment}-{variant}-trades.csv"
        chosen_frame, filled = signals(signal_path), trades(trade_path)
        chosen = {(str(row["signal_date"]), str(row["code"])) for row in chosen_frame.to_dict("records")}
        assert len(chosen) == run["accounting"]["eligible_signals"]
        assert len(chosen) <= len(base_keys) and set(filled).issubset(chosen)
        assert len(chosen) == len(filled) + sum(run["accounting"]["skipped"].values())
        event_rows = []
        for key in sorted(base_keys):
            base_status, base_net = realization(key, base_keys, base_trades, start, end)
            status, net = realization(key, chosen, filled, start, end)
            if base_status == status == "closed" and not np.isclose(base_net, net, atol=1e-8):
                raise AssertionError("Filtering changed overlapping event execution")
            event_rows.append({"segment": segment, "strategy": slug, "variant": variant,
                "signal_date": key[0], "code": key[1], "baseline_status": base_status,
                "baseline_net_return_pct": base_net, "variant_selected": key in chosen,
                "variant_status": status, "variant_realized_net_return_pct": net,
                "both_realizations_known": np.isfinite(base_net) and np.isfinite(net)})
        events = pd.DataFrame(event_rows)
        events.to_csv(ROOT / f"opportunity-{slug}-{segment}-{variant}.csv", index=False, na_rep="NA")
        refill_rows = []
        for key in sorted(chosen - base_keys):
            status, net = realization(key, chosen, filled, start, end)
            refill_rows.append({"segment": segment, "strategy": slug, "variant": variant,
                "signal_date": key[0], "code": key[1], "status": status,
                "realized_net_return_pct": net})
        pd.DataFrame(refill_rows, columns=["segment", "strategy", "variant", "signal_date", "code", "status", "realized_net_return_pct"]).to_csv(
            ROOT / f"refill-{slug}-{segment}-{variant}.csv", index=False, na_rep="NA")
        assert len(refill_rows) == run["scope"]["refill_from_original_rank3_or_lower"]
        closed = [trade for key, trade in filled.items() if realization(key, chosen, filled, start, end)[0] == "closed"]
        closed_returns = np.array([row["net_return_pct"] for row in closed], dtype=float)
        assert len(closed) == run["accounting"]["closed"]
        if len(closed):
            assert round(float(closed_returns.mean()), 4) == run["metrics"]["avg_net_return"]
        baseline_unknown = int(events["baseline_net_return_pct"].isna().sum())
        matching_unknown = int(events["variant_realized_net_return_pct"].isna().sum())
        unknown_total = run["accounting"]["data_end"] + run["accounting"]["boundary_excluded"]
        refill_closed_net = sum(row["realized_net_return_pct"] for row in refill_rows if row["status"] == "closed")
        matching_net = float(events["variant_realized_net_return_pct"].sum())
        assert np.isclose(matching_net + refill_closed_net, closed_returns.sum(), atol=1e-8)
        known = events["both_realizations_known"]
        strict_known = baseline_unknown == 0 and matching_unknown == 0 and unknown_total == 0
        row = {"segment": segment, "strategy": slug, "variant": variant,
            "baseline_mature_opportunities": len(base_keys),
            "baseline_unmature_unknown_purged": base["accounting"]["common_maturity_purged"],
            "baseline_accounting": base["accounting"], "variant_accounting": run["accounting"],
            "selected_mature_signals": len(chosen), "closed": len(closed),
            "entry_skipped": sum(run["accounting"]["skipped"].values()),
            "data_end_unknown": run["accounting"]["data_end"], "boundary_unknown": run["accounting"]["boundary_excluded"],
            "unselected_original_opportunities": int((~events["variant_selected"]).sum()),
            "same_original_code_opportunity_known_n": int(known.sum()),
            "same_original_code_opportunity_mean_observed": float(events.loc[known, "variant_realized_net_return_pct"].mean()) if known.any() else None,
            "same_original_code_opportunity_mean_complete": matching_net / len(base_keys) if strict_known and base_keys else None,
            "all_variant_net_sum_per_original_opportunity_complete": float(closed_returns.sum()) / len(base_keys) if strict_known and base_keys else None,
            "selected_closed_trade_mean_net": float(closed_returns.mean()) if len(closed) else None,
            "baseline_same_pool_mean_net": float(events["baseline_net_return_pct"].mean()) if not baseline_unknown else None,
            "matching_original_net_sum": matching_net, "refill_original_rank3plus_signals": len(refill_rows),
            "refill_closed_net_sum": refill_closed_net, "all_variant_closed_net_sum": float(closed_returns.sum()),
            "unknowns_never_imputed_zero": True}
        result.append(row)
        sources[str(signal_path.name)] = sha(signal_path)
        sources[str(trade_path.name)] = sha(trade_path)
    return result


def main() -> None:
    training = json.loads((ROOT / "training-summary.json").read_text(encoding="utf-8"))
    validation = json.loads((ROOT / "validation-summary.json").read_text(encoding="utf-8"))
    before = sha(ROOT / "training-freeze.json")
    assert before == (ROOT / "training-freeze.sha256").read_text().strip()
    splits = {"train": ("2024-01-01", "2025-06-30"), "validation_2025h2": ("2025-07-01", "2025-12-31"), "observed_2026": ("2026-01-01", "2026-09-30")}
    segments = {"train": training["strategies"], **validation["segments"]}
    rows, sources = [], {}
    for segment, records in segments.items():
        for slug, record in records.items():
            rows += analyze(segment, slug, record, splits[segment], sources)
    assert sha(ROOT / "training-freeze.json") == before
    evidence = {"post_freeze_diagnostic_only": True, "training_freeze_sha256": before,
        "analysis_source_sha256": sha(Path(__file__)), "input_csv_sha256": sources,
        "definition": "Each original matured baseline (signal_date,code) is one equal-notional event opportunity. Unselected or unfilled entries are known realized zero; data_end/boundary are NA. Unmatured purge is excluded, never zero. Refilled rank3+ stocks are separate and only included in total variant net / original-opportunity ratio. This is not a portfolio return.",
        "rows": rows}
    (ROOT / "opportunity-summary.json").write_text(json.dumps(evidence,ensure_ascii=False,indent=2,allow_nan=False)+"\n",encoding="utf-8")
    scalar_rows = [{key:value for key,value in row.items() if not isinstance(value,dict)} for row in rows]
    pd.DataFrame(scalar_rows).to_csv(ROOT / "opportunity-metrics.csv",index=False,na_rep="NA")
    lines = ["# 固定原基准机会的净收益诊断", "", "本诊断在名单冻结后追加，不改变训练名单或择参。每个原始成熟baseline的日期+代码为一笔等名义金额机会。未参加/明确未成交计已实现0；data_end、跨界等未知标NA；段末未成熟机会被剔除，绝不填0。个股过滤替补原第3+代码的收益另列，不能误归原股票。", "", "同原代码机会均值包含不参与的0，解释对原股票机会的筛选；全部方案净收益/原基准机会数同时计入替补贡献，解释相同机会预算下的变化。只要涉及未知持仓，完整均值为NA，另列已知子集及计数。这些百分比按独立事件相加，不能解释为账户或组合收益。", "", "|段|策略|方案|原成熟机会|成交|跳过|data_end|边界|每成交净期望%|同原代码机会均值%|含补位/原机会%|补位数|补位净和%|", "|---|---|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|"]
    for row in rows:
        def fmt(value: float | None) -> str:
            return "NA" if value is None else f"{value:.4f}"
        lines.append(f"|{row['segment']}|{row['strategy']}|{row['variant']}|{row['baseline_mature_opportunities']}|{row['closed']}|{row['entry_skipped']}|{row['data_end_unknown']}|{row['boundary_unknown']}|{fmt(row['selected_closed_trade_mean_net'])}|{fmt(row['same_original_code_opportunity_mean_complete'])}|{fmt(row['all_variant_net_sum_per_original_opportunity_complete'])}|{row['refill_original_rank3plus_signals']}|{fmt(row['refill_closed_net_sum'])}|")
    lines += ["", "所有模型均使用相同原基准成熟机会集合；原基准未成熟剔除数量及完整closed/skip/data_end/boundary守恒记录在JSON中，逐机会与补位CSV可核查。", ""]
    (ROOT / "opportunity-report.md").write_text("\n".join(lines),encoding="utf-8")
    print(json.dumps({"cases":len(rows),"freeze_unchanged":before,"rows":[{key:row[key] for key in ["segment","strategy","variant","baseline_mature_opportunities","closed","entry_skipped","data_end_unknown","boundary_unknown","selected_closed_trade_mean_net","same_original_code_opportunity_mean_complete","all_variant_net_sum_per_original_opportunity_complete","refill_original_rank3plus_signals"]} for row in rows if row["segment"]!="train"]},ensure_ascii=False,indent=2))


if __name__ == "__main__":
    main()
