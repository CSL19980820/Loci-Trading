"""Isolated, preregistered ChiNext candidate-filter study; never edits live strategies.

Train first, freeze at most three variants per strategy, then evaluate only that
frozen shortlist and predefined controls. The shared exit-study helper enforces
the same 20-session maturity/purge and strict raw execution contracts.
"""
from __future__ import annotations

import argparse
import json
import math
import sys
from datetime import datetime
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from tools.research_chinext_payoff_exits import (  # noqa: E402
    BASELINE,
    CutoffMarketStore,
    common_maturity_mask,
    context_evidence,
    execute_split_context,
    prepare,
    serializable_run,
    sha256,
    source_hashes,
)
from tools.strategy_chinext_review import clean_json, write_json  # noqa: E402

OUTPUT_ROOT = ROOT / "docs/research/2026-10-04-chinext-payoff-study/filters"
STRATEGIES = ("contraction-rebreakout-v1", "impulse-inside-breakout-v1")
SPLITS = {
    "train": ("2024-01-01", "2025-06-30"),
    "validation_2025h2": ("2025-07-01", "2025-12-31"),
    "observed_2026": ("2026-01-01", "2026-09-30"),
}
FILTERS = {
    "baseline": "原完整形态候选、原评分，创业板每日前2",
    "index_ma20": "沪深300信号日收盘严格高于当日20日均线；缺失不填充",
    "breadth_50": "所有当日有效创业板股票的上涨比例>=50%；平盘计入分母",
    "stock_ma20_rising": "个股C>MA(C,20)且MA(C,20)>REF(MA(C,20),5)",
    "momentum_0_30": "个股10交易日收盘动量严格>0且严格<30%",
    "breakout_volume_le3": "原策略定义的突破量比<=3，保留原放量下限",
    "relative_volume_le2_5": "V/MA(V,5)<=2.5，5日均量包含信号日",
    "clv_ge0_75": "收盘位置(C-L)/(H-L)>=0.75",
    "prior_extreme_lt15": "T-10至T-1最大单日复权收盘涨幅严格<15%；不含T",
}
EQUAL_CONTROL = "historical_equal_four"
SELECTION = {
    "max_per_strategy": 3,
    "eligibility": "closed>=80 AND payoff_ratio>1 AND profit_factor>1 AND mean_net>0; both wins and losses required",
    "ranking": "training unrounded payoff descending, PF descending, mean descending, scenario id ascending",
    "baseline_is_control_not_shortlist": True,
    "no_validation_based_retuning": True,
}


def plan() -> dict[str, Any]:
    return {
        "study": "candidate filters, fixed existing shape/ranking and fixed 4-session/-6% exit",
        "splits": SPLITS, "filters": FILTERS,
        "historical_score_control": {"id": EQUAL_CONTROL, "strategy": STRATEGIES[0],
            "definition": "原四项等权25/25/25/25，保留当前收盘涨停过滤，仅重排完整原形态候选",
            "already_seen": True},
        "selection": SELECTION, "max_hold_including_entry_for_every_cohort": 20,
        "fixed_exit": BASELINE.to_dict(), "round_trip_cost_pct": .21,
        "stress_round_trip_cost_pct": .42,
        "breadth_definition": "current catalog six-digit 300/301 STOCK; same-day and prior market-day finite positive qfq closes plus same-day volume>0; no ST/status narrowing, no forward-fill, no future quote membership",
        "filter_before_top2": True,
        "limitations": [
            "当前证券目录、名称/状态存在幸存者及历史成员偏差，非严格PIT证券池。",
            "2026-09-29案例与2026年结果已经观察且参与当前五项评分校准，2026仅后验检验。",
            "2025H2是本轮过滤选择未开启的留出期；基底策略本身并非2024年事前冻结设计。",
            "每笔独立事件交易，不模拟组合容量、资金占用或组合净值。",
        ],
    }


def study_sources() -> dict[str, str]:
    result = source_hashes()
    result["tools/research_chinext_payoff_filters.py"] = sha256(Path(__file__))
    return result


def independent_metrics(trades: list[Any], cost: float = .21) -> dict[str, Any]:
    """Aggregate economic gross returns independently of system compute_metrics."""
    values = np.asarray([trade.gross_return_pct - cost for trade in trades], dtype=float)
    if not np.isfinite(values).all():
        raise AssertionError("Non-finite closed return")
    wins, losses = values[values > 0], values[values <= 0]
    payoff = float(wins.mean() / abs(losses.mean())) if len(wins) and len(losses) and losses.mean() < 0 else None
    pf = float(wins.sum() / abs(losses.sum())) if len(wins) and len(losses) and losses.sum() < 0 else None
    return {"trades": len(values), "win_rate": float(len(wins) / len(values) * 100) if len(values) else None,
        "avg_net_return": float(values.mean()) if len(values) else None,
        "payoff_ratio": payoff, "profit_factor": pf,
        "wins": len(wins), "losses": len(losses),
        "avg_win": float(wins.mean()) if len(wins) else None,
        "avg_loss": float(losses.mean()) if len(losses) else None}


def verify_metrics(run: dict[str, Any]) -> dict[str, Any]:
    trades = run["closed_trades"]
    independent = independent_metrics(trades)
    system = run["metrics"]
    for key, digits in (("trades", 0), ("win_rate", 2), ("avg_net_return", 4), ("payoff_ratio", 3), ("profit_factor", 3)):
        if independent[key] is not None:
            if system[key] != round(independent[key], digits):
                raise AssertionError((key, system[key], independent[key]))
    for trade in trades:
        if not math.isclose(trade.gross_return_pct - trade.net_return_pct, .21, abs_tol=1e-8):
            raise AssertionError("Original fee is not .21 percent")
    winner = max(trades, key=lambda trade: trade.net_return_pct) if trades else None
    without = [trade for trade in trades if trade is not winner]
    return {"base_independent": independent, "double_cost_0_42": independent_metrics(trades, .42),
        "largest_winner_removed": independent_metrics(without),
        "double_cost_and_largest_winner_removed": independent_metrics(without, .42),
        "largest_winner": winner.to_dict(include_factors=True) if winner else None,
        "independent_metrics_verified": True}


def feature_masks(close: pd.DataFrame, high: pd.DataFrame, low: pd.DataFrame,
                  volume: pd.DataFrame, index_close: pd.Series,
                  breadth: pd.Series) -> dict[str, Any]:
    mean20, mean5v = close.rolling(20).mean(), volume.rolling(5).mean()
    with np.errstate(divide="ignore", invalid="ignore"):
        momentum_ratio = close / close.shift(10)
        relative_volume = volume / mean5v
        clv = (close - low) / (high - low).where((high - low).gt(0))
        daily_ratio = close / close.shift(1)
    prior_extreme = daily_ratio.shift(1).rolling(10).max()
    benchmark_gate = index_close.gt(index_close.rolling(20).mean()).reindex(close.index).fillna(False)
    return {
        "baseline": close.notna(), "index_ma20": benchmark_gate,
        "breadth_50": breadth.reindex(close.index).ge(.50).fillna(False),
        "stock_ma20_rising": close.gt(mean20) & mean20.gt(mean20.shift(5)),
        "momentum_0_30": momentum_ratio.gt(1) & momentum_ratio.lt(1.30)
            & ~np.isclose(momentum_ratio, 1.30, rtol=1e-12, atol=0),
        "relative_volume_le2_5": relative_volume.le(2.5) & np.isfinite(relative_volume),
        "clv_ge0_75": clv.ge(.75) & np.isfinite(clv),
        "prior_extreme_lt15": prior_extreme.lt(1.15) & np.isfinite(prior_extreme)
            & ~np.isclose(prior_extreme, 1.15, rtol=1e-12, atol=0),
    }


def breadth_fraction(close: pd.DataFrame, volume: pd.DataFrame) -> tuple[pd.Series, pd.Series]:
    previous = close.shift(1)
    valid = np.isfinite(close) & close.gt(0) & np.isfinite(previous) & previous.gt(0)
    valid &= np.isfinite(volume) & volume.gt(0)
    denominator = valid.sum(axis=1)
    fraction = (close.gt(previous) & valid).sum(axis=1) / denominator.where(denominator.gt(0))
    return fraction, denominator


def market_features(store: CutoffMarketStore, ctx: dict[str, Any], end: str) -> tuple[dict[str, Any], dict[str, Any]]:
    codes = [str(row[0]) for row in store.conn.execute(
        "SELECT code FROM instruments WHERE instrument_type='STOCK' AND length(code)=6 "
        "AND (code LIKE '300%' OR code LIKE '301%') ORDER BY code")]
    begin = str(ctx["panels"]["close"].index[0])
    broad = store.load_panel(fields=("close", "volume"), codes=codes, start=begin, end=end, adjust="qfq")
    breadth, denominator = breadth_fraction(broad["close"], broad["volume"])
    benchmark = store.load_panel(fields=("close",), codes=["000300"], start=begin, end=end, adjust="none")
    if "000300" not in benchmark["close"] or benchmark["close"]["000300"].notna().sum() < 20:
        raise ValueError("Required real 000300 benchmark missing; cannot simulate the index filter")
    p = ctx["panels"]
    masks = feature_masks(p["close"], p["high"], p["low"], p["volume"], benchmark["close"]["000300"], breadth)
    cutoff = p["close"].index[len(p["close"].index) * 2 // 3]
    prefix_breadth, _ = breadth_fraction(broad["close"].loc[:cutoff], broad["volume"].loc[:cutoff])
    pd.testing.assert_series_equal(prefix_breadth, breadth.loc[:cutoff])
    prefix_masks = feature_masks(*(p[field].loc[:cutoff] for field in ("close", "high", "low", "volume")),
        benchmark["close"]["000300"].loc[:cutoff], prefix_breadth)
    for key, mask in masks.items():
        if isinstance(mask, pd.DataFrame):
            pd.testing.assert_frame_equal(prefix_masks[key], mask.loc[:cutoff])
        else:
            pd.testing.assert_series_equal(prefix_masks[key], mask.loc[:cutoff])
    evidence = {"breadth_catalog_codes": len(codes), "breadth_valid_codes_min": int(denominator[denominator > 0].min()),
        "breadth_valid_codes_max": int(denominator.max()), "benchmark_real_code": "000300",
        "no_forward_fill": True, "maximum_price_read_date": str(broad["close"].index[-1]),
        "current_catalog_bias": True, "feature_mask_prefix_consistency_cutoff": str(cutoff)}
    return masks, evidence


def equal_four_score(computed: Any, panels: dict[str, Any]) -> pd.DataFrame:
    factors = computed.factors
    c, h, l = panels["close"], panels["high"], panels["low"]
    parts = [((1 - factors["回调均量比"]) / .5).clip(0, 1) * 25,
             (1 - factors["回调深度(%)"] / 10).clip(0, 1) * 25,
             ((factors["突破量比"] - 1) / 2).clip(0, 1) * 25,
             ((c - l) / (h - l).where((h - l).gt(0))).clip(0, 1) * 25]
    return sum(parts).where(computed.factors["条件候选"]).where(np.isfinite(sum(parts))).round(4)


def rank_filtered(candidates: pd.DataFrame, score: pd.DataFrame, mask: Any) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    eligible = candidates & np.isfinite(score)
    eligible = eligible & mask if isinstance(mask, pd.DataFrame) else eligible.mul(mask.fillna(False), axis=0).fillna(False).astype(bool)
    eligible = eligible.fillna(False).astype(bool)
    filtered_score = score.where(eligible).round(4)
    ranks = filtered_score.reindex(columns=sorted(filtered_score.columns)).rank(axis=1, ascending=False, method="first").reindex(columns=score.columns)
    selected = (eligible & ranks.le(2)).fillna(False).astype(bool)
    if int(selected.sum(axis=1).max()) > 2:
        raise AssertionError("More than two picks")
    return selected, filtered_score, ranks


def scope_counts(ctx: dict[str, Any], candidates: pd.DataFrame, selected: pd.DataFrame,
                 baseline: pd.DataFrame, score: pd.DataFrame, start: str, end: str) -> dict[str, int]:
    maturity = common_maturity_mask(selected.index, start, end)
    c, s, b = (frame.loc[maturity] for frame in (candidates, selected, baseline))
    usable = score.loc[maturity].notna()
    return {"original_shape_candidates": int(c.to_numpy().sum()),
        "filter_pass_candidates": int(usable.to_numpy().sum()),
        "top2_signals": int(s.to_numpy().sum()),
        "original_top2_removed": int((b & ~s).to_numpy().sum()),
        "refill_from_original_rank3_or_lower": int((s & ~b).to_numpy().sum()),
        "days_zero_picks": int(s.sum(axis=1).eq(0).sum()),
        "days_one_pick": int(s.sum(axis=1).eq(1).sum()), "days_two_picks": int(s.sum(axis=1).eq(2).sum())}


def save_trades(path: Path, run: dict[str, Any]) -> None:
    records = [trade.to_dict(include_factors=True) for trade in run["all_trades"]]
    pd.DataFrame(records).to_csv(path, index=False)


def save_signals(path: Path, selected: pd.DataFrame, score: pd.DataFrame, ranks: pd.DataFrame,
                 start: str, end: str) -> None:
    maturity = common_maturity_mask(selected.index, start, end)
    masked = selected.where(maturity, False, axis=0)
    records = [{"signal_date": str(selected.index[i]), "code": str(selected.columns[j]),
                "score": float(score.iloc[i, j]), "rank": int(ranks.iloc[i, j])}
               for i, j in zip(*np.nonzero(masked.to_numpy()))]
    pd.DataFrame(records, columns=["signal_date", "code", "score", "rank"]).to_csv(path, index=False)


def evaluate_variants(store: CutoffMarketStore, slug: str, start: str, end: str,
                      ids: list[str], output: Path, segment: str) -> dict[str, Any]:
    print(f"{segment} prepare {slug}; cutoff={end}", flush=True)
    ctx = prepare(store, slug, start, end)
    computed = ctx["engine"].compute(ctx["panels"], ctx["resolved_params"])
    candidates, original_score = computed.factors["条件候选"], computed.factors["score"]
    masks, market_evidence = market_features(store, ctx, end)
    masks["breakout_volume_le3"] = computed.factors["突破量比"].le(3)
    baseline, _, _ = rank_filtered(candidates, original_score, masks["baseline"])
    pd.testing.assert_frame_equal(baseline.loc[start:end], ctx["signals"].loc[start:end].fillna(False).astype(bool))
    cutoff = ctx["panels"]["close"].index[len(ctx["panels"]["close"].index) * 2 // 3]
    prefix = {key: value.loc[:cutoff] if isinstance(value, pd.DataFrame) else value for key, value in ctx["panels"].items()}
    prefix_computed = ctx["engine"].compute(prefix, ctx["resolved_params"])
    pd.testing.assert_frame_equal(prefix_computed.factors["score"], original_score.loc[:cutoff])
    pd.testing.assert_frame_equal(prefix_computed.factors["突破量比"], computed.factors["突破量比"].loc[:cutoff])
    rows = []
    for variant in ids:
        alternate = variant == EQUAL_CONTROL
        score = equal_four_score(computed, ctx["panels"]) if alternate else original_score
        mask = masks["baseline"] if alternate else masks[variant]
        selected, filtered_score, rank = rank_filtered(candidates, score, mask)
        run = execute_split_context({**ctx, "signals": selected}, BASELINE.config(end), start, end)
        diagnostics = verify_metrics(run)
        row = {"id": variant, "definition": FILTERS.get(variant, plan()["historical_score_control"]["definition"]),
               "scope": scope_counts(ctx, candidates, selected, baseline, filtered_score, start, end),
               **serializable_run(run), "independent_diagnostics": diagnostics}
        rows.append(row)
        save_trades(output / f"{slug}-{segment}-{variant}-trades.csv", run)
        save_signals(output / f"{slug}-{segment}-{variant}-signals.csv", selected, filtered_score, rank, start, end)
        m = diagnostics["base_independent"]
        print(f"{segment} {slug}/{variant}: closed={m['trades']} payoff={m['payoff_ratio']} PF={m['profit_factor']} mean={m['avg_net_return']}", flush=True)
    return {**context_evidence(ctx), "market_filter_evidence": market_evidence,
        "baseline_top2_reproduced": True, "canonical_score_prefix_consistency_cutoff": str(cutoff), "runs": rows}


def select_training(rows: list[dict[str, Any]]) -> dict[str, Any]:
    eligible, reasons = [], {}
    for row in rows:
        m = row["independent_diagnostics"]["base_independent"]
        failures = []
        if row["id"] == "baseline":
            failures.append("predefined control")
        if m["trades"] < 80:
            failures.append("closed<80")
        for key in ("payoff_ratio", "profit_factor"):
            if m[key] is None or not m[key] > 1:
                failures.append(key + "<=1 or undefined")
        if m["avg_net_return"] is None or not m["avg_net_return"] > 0:
            failures.append("mean<=0 or undefined")
        if failures:
            reasons[row["id"]] = failures
        else:
            eligible.append(row)
    def order(row: dict[str, Any]) -> tuple[Any, ...]:
        m = row["independent_diagnostics"]["base_independent"]
        return (-m["payoff_ratio"], -m["profit_factor"], -m["avg_net_return"], row["id"])
    eligible.sort(key=order)
    return {"selected": [row["id"] for row in eligible[:3]],
        "eligible": [row["id"] for row in eligible], "rejection_reasons": reasons,
        "no_eligible_candidate": not bool(eligible)}


def train(db: Path, output: Path) -> None:
    receipt = output / "training-freeze.json"
    if receipt.exists():
        raise ValueError("Training already frozen; never overwrite or retune a receipt")
    output.mkdir(parents=True, exist_ok=True)
    write_json(output / "PLAN.json", plan())
    sources = study_sources()
    start, end = SPLITS["train"]
    summary = {"phase": "training_complete_validation_unopened", "database_sha256": sha256(db),
        "source_sha256": sources, "split": SPLITS["train"], "strategies": {}}
    with CutoffMarketStore(db, end) as store:
        for slug in STRATEGIES:
            ids = list(FILTERS) + ([EQUAL_CONTROL] if slug == STRATEGIES[0] else [])
            record = evaluate_variants(store, slug, start, end, ids, output, "train")
            record["selection"] = select_training(record["runs"])
            summary["strategies"][slug] = record
            write_json(output / "training-summary.json", summary)
    if study_sources() != sources:
        raise ValueError("Source changed during training; no freeze created")
    frozen = {"created_at": datetime.now(ZoneInfo("Asia/Shanghai")).isoformat(),
        "phase": "training_complete_validation_unopened", "database_sha256": summary["database_sha256"],
        "source_sha256": sources, "training_summary_sha256": sha256(output / "training-summary.json"),
        "plan_sha256": sha256(output / "PLAN.json"), "selection_policy": SELECTION,
        "strategies": {slug: record["selection"] for slug, record in summary["strategies"].items()}}
    with receipt.open("x", encoding="utf-8") as file:
        json.dump(clean_json(frozen), file, ensure_ascii=False, indent=2, allow_nan=False)
        file.write("\n")
    (output / "training-freeze.sha256").write_text(sha256(receipt) + "\n", encoding="utf-8")
    print(f"FROZEN {receipt}; SHA={sha256(receipt)}; validation remains unopened", flush=True)


def validate(db: Path, output: Path) -> None:
    if sha256(output / "training-freeze.json") != (output / "training-freeze.sha256").read_text(encoding="utf-8").strip():
        raise ValueError("Training freeze receipt hash changed")
    receipt = json.loads((output / "training-freeze.json").read_text(encoding="utf-8"))
    if sha256(db) != receipt["database_sha256"] or study_sources() != receipt["source_sha256"]:
        raise ValueError("Frozen database or sources changed")
    if sha256(output / "training-summary.json") != receipt["training_summary_sha256"] or sha256(output / "PLAN.json") != receipt["plan_sha256"]:
        raise ValueError("Frozen training receipt inputs changed")
    training = json.loads((output / "training-summary.json").read_text(encoding="utf-8"))
    for slug in STRATEGIES:
        selection = select_training(training["strategies"][slug]["runs"])
        if selection != receipt["strategies"][slug] or selection != training["strategies"][slug]["selection"]:
            raise ValueError("Frozen shortlist does not reproduce training-only selection")
    result = {"freeze_receipt_sha256": sha256(output / "training-freeze.json"), "segments": {}}
    for segment in ("validation_2025h2", "observed_2026"):
        start, end = SPLITS[segment]
        result["segments"][segment] = {}
        with CutoffMarketStore(db, end) as store:
            for slug in STRATEGIES:
                ids = ["baseline", *receipt["strategies"][slug]["selected"]]
                if slug == STRATEGIES[0] and EQUAL_CONTROL not in ids:
                    ids.append(EQUAL_CONTROL)
                result["segments"][segment][slug] = evaluate_variants(store, slug, start, end, ids, output, segment)
        write_json(output / "validation-summary.json", result)
    write_report(output)


def write_report(output: Path) -> None:
    training = json.loads((output / "training-summary.json").read_text(encoding="utf-8"))
    validation = json.loads((output / "validation-summary.json").read_text(encoding="utf-8"))
    rows = []
    lines = ["# 创业板信号过滤隔离研究", "", "原系统策略、原评分与出口均未修改。固定出口为次日开盘入场、含买入日第4日/-6%止损，无止盈；经济复权、T+1和严格涨跌停约束，单笔费用0.21%，双倍费用0.42%。所有方案及对照统一20交易日成熟缓冲，实际入场/退出也在对应段内；data_end与跨界不计已平仓。", "", "过滤作用于完整形态候选后重新评分排序，最多每日2只。宽度仅固定50%，未搜索阈值；没有将只过滤原前2后的空缺伪装为完整候选排名。", "", "2024年1月至2025年6月只开启训练。每策略按预注册资格与payoff/PF/mean排序冻结最多3个方案，然后才开启2025下半年留出期和2026已观察后验检验；不按后两段结果重选或调参。新策略原四项等权是历史已看过的固定对照。", "", "2026年9月案例和该年回测已参与当前五权重评分设计，因此2026不能称完全未见样本外；2025下半年仅对本次过滤选择留出，基底策略本身并非2024年事前冻结。当前证券目录、名称/状态有历史成员与幸存者偏差。", "", "|段|策略|方案|平仓|胜率%|平均盈亏比|利润因子|平均净收益%|双费用PF|去最大赢单PF|候选通过/原候选|替补原第3+|", "|---|---|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|"]
    segments = {"train": training["strategies"], **validation["segments"]}
    for segment, records in segments.items():
        for slug, record in records.items():
            for run in record["runs"]:
                m, d, scope = run["metrics"], run["independent_diagnostics"], run["scope"]
                rows.append({"segment": segment, "strategy": slug, "variant": run["id"], **m,
                    "double_cost_pf": d["double_cost_0_42"]["profit_factor"], "winner_removed_pf": d["largest_winner_removed"]["profit_factor"], **scope})
                def fmt(value: Any, digits: int = 3) -> str:
                    return "—" if value is None else f"{value:.{digits}f}"
                lines.append(f"|{segment}|{slug}|{run['id']}|{m['trades']}|{fmt(m.get('win_rate'),2)}|{fmt(m.get('payoff_ratio'))}|{fmt(m.get('profit_factor'))}|{fmt(m.get('avg_net_return'),4)}|{fmt(d['double_cost_0_42']['profit_factor'])}|{fmt(d['largest_winner_removed']['profit_factor'])}|{scope['filter_pass_candidates']}/{scope['original_shape_candidates']}|{scope['refill_from_original_rank3_or_lower']}|")
    pd.DataFrame(rows).to_csv(output / "metrics.csv", index=False)
    lines += ["", "冻结方案：", ""]
    for slug, record in training["strategies"].items():
        lines.append(f"- {slug}：{', '.join(record['selection']['selected']) or '没有满足固定资格的方案；未放松门槛'}。")
    lines += ["", "胜率、平均盈亏比与利润因子分开记录；有限历史事件回测不等同于组合年化收益。双成本诊断只将相同成交的总费率翻倍，未模拟盘口冲击；最大赢家剔除是单笔依赖诊断，不用于验证后的模型选择。各信号/交易CSV、skip守恒、按信号月统计及冻结源SHA可复核。", ""]
    (output / "report.md").write_text("\n".join(lines), encoding="utf-8")


def self_check() -> None:
    days = pd.Index(pd.bdate_range("2024-01-01", periods=50).strftime("%Y-%m-%d"))
    candidates = pd.DataFrame(True, index=days, columns=["300001", "300002", "300003"])
    score = pd.DataFrame(np.tile([90., 80., 70.], (50, 1)), index=days, columns=candidates.columns)
    mask = candidates.copy(); mask["300001"] = False
    selected, _, _ = rank_filtered(candidates, score, mask)
    assert selected.iloc[0].to_dict() == {"300001": False, "300002": True, "300003": True}
    c = pd.DataFrame(100., index=days, columns=candidates.columns); v = c.copy()
    c.iloc[-1] = [101, 99, np.nan]
    fraction, n = breadth_fraction(c, v)
    assert fraction.iloc[-1] == .5 and n.iloc[-1] == 2
    extreme = pd.DataFrame(100., index=days, columns=["300001"])
    extreme.iloc[-1] = 120
    masks = feature_masks(extreme, extreme + 1, extreme - 1, extreme * 0 + 100,
                          extreme["300001"], pd.Series(.5, index=days))
    assert masks["prior_extreme_lt15"].iloc[-1, 0]
    extreme.iloc[-2] = 120
    masks = feature_masks(extreme, extreme + 1, extreme - 1, extreme * 0 + 100,
                          extreme["300001"], pd.Series(.5, index=days))
    assert not masks["prior_extreme_lt15"].iloc[-1, 0]
    extreme.iloc[-2:] = 115
    masks = feature_masks(extreme, extreme + 1, extreme - 1, extreme * 0 + 100,
                          extreme["300001"], pd.Series(.5, index=days))
    assert not masks["prior_extreme_lt15"].iloc[-1, 0]
    missing_gate = pd.Series(True, index=days, dtype="boolean"); missing_gate.iloc[-1] = pd.NA
    missing_selection, _, _ = rank_filtered(candidates, score, missing_gate)
    assert not missing_selection.iloc[-1].any()
    assert int(common_maturity_mask(days, days[0], days[-1]).sum()) == 30
    assert len(FILTERS) == 9
    print("Self-check passed: filter-before-Top2 refill, valid breadth/no-fill, strict prior10 boundary, common20", flush=True)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--db", type=Path)
    parser.add_argument("--output", type=Path, default=OUTPUT_ROOT)
    parser.add_argument("--phase", choices=("train", "validate", "self-check"), default="train")
    args = parser.parse_args()
    if args.phase == "self-check":
        self_check(); return
    output = args.output.resolve()
    if not output.is_relative_to(OUTPUT_ROOT.resolve()):
        raise ValueError("Outputs must stay in the authorized filters study directory")
    if args.db is None:
        parser.error("--db is required")
    db = args.db.resolve(strict=True)
    train(db, output) if args.phase == "train" else validate(db, output)


if __name__ == "__main__":
    main()
