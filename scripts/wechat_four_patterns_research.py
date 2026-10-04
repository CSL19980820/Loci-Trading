"""Reproducible local-only research; never writes the market/ledger databases.

Usage: python -m scripts.wechat_four_patterns_research
       python -m scripts.wechat_four_patterns_research --replay
A snapshot is created once and reused. Delete neither the snapshot nor existing
results to change inputs: choose a new --out directory instead.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import sqlite3
import sys

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.backtest.application.engine import run_backtest
from src.backtest.application.research_portfolio import PortfolioResearchConfig, analyze_portfolio
from src.backtest.domain.models import BacktestConfig
from src.strategy.application.wechat_four_patterns import PATTERNS, WechatFourPatternsStrategy, select_top_two

FIELDS = ("open", "high", "low", "close", "volume", "amount")
START, END, WARMUP = "2025-01-01", "2026-08-31", "2024-07-01"
PERIODS = {"2025": (START, "2025-12-31"), "2026_8m": ("2026-01-01", END)}
DEFAULT_OUT = ROOT / "data/research_runs/wechat_four_patterns_20260928"


def sha(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def save_json(path: Path, data: object) -> None:
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2, allow_nan=False), encoding="utf-8")


def code_hashes() -> dict[str, str]:
    paths = [
        "src/strategy/application/wechat_four_patterns.py", "scripts/wechat_four_patterns_research.py",
        "src/backtest/application/engine.py", "src/backtest/application/execution_contract.py",
        "src/backtest/application/research_portfolio_daily.py", "src/backtest/application/research_portfolio_prices.py",
        "src/backtest/application/research_portfolio.py", "src/backtest/domain/models.py",
    ]
    return {p: sha(ROOT / p) for p in paths}


def prepare_snapshot(out: Path, database: Path) -> None:
    snapshot = out / "snapshot.npz"
    if snapshot.exists():
        meta = json.loads((out / "snapshot_manifest.json").read_text(encoding="utf-8"))
        if sha(snapshot) != meta["snapshot_sha256"]:
            raise RuntimeError("snapshot hash mismatch; refusing to overwrite/reuse")
        return
    print("Reading a single SQLite read-only transaction", flush=True)
    con = sqlite3.connect(database.resolve().as_uri() + "?mode=ro", uri=True, timeout=30)
    con.execute("PRAGMA query_only=ON")
    con.execute("BEGIN")
    try:
        universe = pd.read_sql_query("SELECT code,name,instrument_type,list_date,delist_date,status FROM instruments ORDER BY code", con)
        mainboard = universe.instrument_type.eq("STOCK") & universe.code.str.startswith(("00", "60"))
        excluded = universe.name.str.contains("ST|退", case=False, regex=True) | universe.status.ne("normal")
        stocks = universe.loc[mainboard & ~excluded].copy()
        marks = pd.read_sql_query(
            "SELECT trade_date,code,open,high,low,close,volume,amount,source,fetched_at FROM quotes_daily "
            "WHERE trade_date>=? AND trade_date<=? AND (code LIKE '00%' OR code LIKE '60%') ORDER BY trade_date,code",
            con, params=(WARMUP, END),
        )
        factors = pd.read_sql_query("SELECT code,trade_date,hfq_factor FROM adjust_factors WHERE trade_date<=? ORDER BY trade_date,code", con, params=(END,))
        calendar = pd.read_sql_query("SELECT trade_date FROM trading_calendar WHERE trade_date>=? AND trade_date<=? ORDER BY trade_date", con, params=(WARMUP, END))
    finally:
        con.rollback()
        con.close()
    benchmark = marks.loc[marks.code.eq("000300"), ["trade_date", "close"]].set_index("trade_date").close
    marks = marks.loc[marks.code.isin(stocks.code)].copy()
    dates = sorted(set(marks.trade_date) | set(calendar.trade_date))
    if not dates or dates[-1] != END:
        raise RuntimeError(f"missing requested end date {END}")
    codes = sorted(marks.code.unique())
    stocks = stocks.set_index("code").reindex(codes)
    panels = {key: marks.pivot(index="trade_date", columns="code", values=key).reindex(index=dates, columns=codes) for key in FIELDS}
    fac = factors.loc[factors.code.isin(codes)].pivot(index="trade_date", columns="code", values="hfq_factor")
    fac = fac.reindex(index=sorted(set(fac.index) | set(dates)), columns=codes).ffill().reindex(dates)
    fac_known = np.isfinite(fac) & fac.gt(0)
    eligible = fac_known.copy()
    for code in codes:
        listed = str(stocks.at[code, "list_date"] or "")
        delisted = str(stocks.at[code, "delist_date"] or "")
        if listed:
            eligible[code] &= pd.Series(dates, index=dates).ge(listed)
        if delisted:
            eligible[code] &= pd.Series(dates, index=dates).lt(delisted)
    # Unknown corporate-action coordinates are not substituted into a signal.
    # Empty pre-history is masked out and given an inert execution factor only.
    unknown_quote_count = int((panels["close"].notna() & ~fac_known).sum().sum())
    for key in FIELDS:
        panels[key] = panels[key].where(fac_known)
    fac = fac.where(fac_known, 1.0)
    c, o, h, lo, v = (panels[k] for k in ("close", "open", "high", "low", "volume"))
    valid = c.gt(0) & o.gt(0) & lo.gt(0) & h.ge(c) & h.ge(o) & lo.le(c) & lo.le(o) & v.gt(0)
    bad = c.notna() & v.gt(0) & ~valid
    for key in FIELDS:
        panels[key] = panels[key].mask(bad)
    eligible &= ~bad
    coverage = pd.DataFrame({"date": dates, "quoted": c.notna().sum(axis=1).values, "valid": valid.sum(axis=1).values, "eligible": eligible.sum(axis=1).values})
    obs = coverage.loc[coverage.date.ge(START)]
    if int(obs.valid.min()) < 1000:
        raise RuntimeError("incomplete market-session coverage (<1000 valid stocks); inspect input")
    payload = {k: p.to_numpy(dtype=float) for k, p in panels.items()}
    payload.update(factor=fac.to_numpy(dtype=float), eligible=eligible.to_numpy(dtype=bool), dates=np.array(dates), codes=np.array(codes), benchmark=benchmark.reindex(dates).to_numpy(dtype=float))
    np.savez_compressed(snapshot, **payload)
    stocks.reset_index().to_csv(out / "universe.csv", index=False, encoding="utf-8-sig")
    coverage.to_csv(out / "coverage.csv", index=False)
    latest_fetch = str(marks.fetched_at.max())
    volume_units = (marks.amount / (marks.volume.replace(0, np.nan) * marks.close)).replace([np.inf, -np.inf], np.nan)
    meta = {
        "created_at": datetime.now(timezone.utc).isoformat(), "database": str(database.resolve()),
        "snapshot_sha256": sha(snapshot), "raw_rows": len(marks), "codes": len(codes),
        "first_date": dates[0], "last_date": dates[-1], "sessions": len(dates),
        "periods": PERIODS, "universe_current_mainboard": int(mainboard.sum()),
        "current_st_or_non_normal_excluded": int((mainboard & excluded).sum()),
        "no_known_factor_quote_count": unknown_quote_count, "invalid_ohlc_count": int(bad.sum().sum()),
        "min_observation_daily_valid": int(obs.valid.min()), "source_counts": marks.source.value_counts().to_dict(),
        "latest_fetch_in_snapshot": latest_fetch, "amount_over_volume_close_median": float(volume_units.median()),
        "historical_status_complete": False, "strict_pit": False,
        "limitations": [
            "Universe/name/status use the current instruments snapshot; historical ST, delisting and renaming membership are not reconstructed (survivorship/lookback bias).",
            "OHLCV and adjustment factors are later-fetched historical records, not archived decision-time vintages; split is temporal validation, not untouched OOS.",
            "Factor forward-fill uses only event dates <= each bar; cash distributions are modeled by economic factor returns, not an ex-dividend cash ledger.",
            "Daily-bar price limits are conservative inferred limits, not an official historical daily limit-price dataset.",
        ],
    }
    save_json(out / "snapshot_manifest.json", meta)
    print(json.dumps(meta, ensure_ascii=False), flush=True)


def load_snapshot(out: Path) -> tuple[dict[str, pd.DataFrame], dict[str, pd.DataFrame], pd.Series]:
    meta = json.loads((out / "snapshot_manifest.json").read_text(encoding="utf-8"))
    if sha(out / "snapshot.npz") != meta["snapshot_sha256"]:
        raise RuntimeError("snapshot hash mismatch")
    with np.load(out / "snapshot.npz", allow_pickle=False) as data:
        dates, codes = data["dates"].tolist(), data["codes"].tolist()
        raw = {k: pd.DataFrame(data[k], index=dates, columns=codes) for k in FIELDS}
        factor = pd.DataFrame(data["factor"], index=dates, columns=codes)
        raw["__adjust_factor"] = factor
        adjusted = {k: raw[k] * factor if k in ("open", "high", "low", "close") else raw[k] for k in FIELDS}
        adjusted["__eligible"] = pd.DataFrame(data["eligible"], index=dates, columns=codes)
        benchmark = pd.Series(data["benchmark"], index=dates, name="000300")
    return raw, adjusted, benchmark


def audit_signals(engine: WechatFourPatternsStrategy, panels: dict[str, pd.DataFrame], result: object) -> dict[str, object]:
    counts = result.signals.sum(axis=1)
    assert int(counts.max()) <= 2
    # Include genuine selected dates: no all-False fixture can satisfy this audit.
    active = result.signals.index[counts.gt(0) & result.signals.index.to_series().ge(START)]
    if len(active) < 5:
        raise RuntimeError("too few active dates for a meaningful historical truncation audit")
    cutoffs = sorted(set(active[np.linspace(0, len(active) - 1, 8, dtype=int)]))
    for end in cutoffs:
        cut = engine.compute({k: p.loc[:end] for k, p in panels.items()})
        pd.testing.assert_frame_equal(cut.signals, result.signals.loc[:end])
        for key in ("score", "candidate", *["pattern_" + p for p in PATTERNS]):
            pd.testing.assert_frame_equal(cut.factors[key], result.factors[key].loc[:end])
    return {"max_daily_picks": int(counts.max()), "historical_prefix_checks": cutoffs, "prefix_checks_passed": True}


def save_picks(path: Path, result: object, signals: pd.DataFrame, names: dict[str, str]) -> None:
    rows = []
    for day in signals.index:
        codes = signals.columns[signals.loc[day]]
        for rank, code in enumerate(sorted(codes, key=lambda x: (-float(result.factors["score"].at[day, x]), x)), 1):
            rows.append({"signal_date": day, "rank": rank, "code": code, "name": names.get(code, ""),
                         **{key: float(panel.at[day, code]) for key, panel in result.factors.items()}})
    pd.DataFrame(rows).to_csv(path, index=False, encoding="utf-8-sig")


def scenario(out: Path, key: str, signals: pd.DataFrame, raw: dict[str, pd.DataFrame], benchmark: pd.Series,
             start: str, end: str, hold_days: int = 2, cost_multiple: int = 1) -> dict[str, object]:
    directory = out / "results" / key
    directory.mkdir(parents=True, exist_ok=True)
    signals = signals.copy()
    signals.loc[(signals.index < start) | (signals.index > end)] = False
    used = signals.columns[signals.any()]
    # Preserve a non-empty panel in a zero-signal scenario; never fabricate trades.
    if len(used) == 0:
        used = signals.columns[:1]
    signals = signals.loc[:, used]
    execution = {k: panel.loc[:, used] for k, panel in raw.items()}
    cfg = BacktestConfig(hold_days=hold_days, stop_loss_pct=-6.0, take_profit_pct=None,
                         commission_bps=3 * cost_multiple, stamp_duty_bps=10 * cost_multiple,
                         slippage_bps=5 * cost_multiple, strict_limit_prices=True,
                         economic_returns=True, valuation_end=end, benchmark="000300")
    events = run_backtest(signals, execution, entry_timing="next_open", config=cfg,
                          strategy_slug="wechat-four-patterns-research", benchmark_close=benchmark)
    dates = [d for d in signals.index if start <= d <= end]
    portfolio = analyze_portfolio(events.trades,
        config=PortfolioResearchConfig(initial_capital=200_000, max_positions=2, account_model="daily_close"),
        trading_dates=dates, strategy_slug=key,
        closing_prices=execution["close"].where(execution["volume"].gt(0)),
        adjustment_factors=execution["__adjust_factor"])
    assert not portfolio.failures, portfolio.failures
    daily = pd.DataFrame([x.to_dict() for x in portfolio.daily])
    trades = pd.DataFrame([x.to_dict() for x in portfolio.allocations])
    assert daily.open_positions.max() <= 2 and daily.entries.max() <= 2
    assert daily.cash.min() >= -1e-6
    if not trades.empty:
        assert (trades.entry_date > trades.signal_date).all()
        assert (trades.exit_date > trades.entry_date).all()
        assert (trades.quantity % 100 == 0).all()
        assert trades.groupby("entry_date").size().max() <= 2
    events.to_frame().to_csv(directory / "events.csv", index=False, encoding="utf-8-sig")
    trades.to_csv(directory / "trades.csv", index=False, encoding="utf-8-sig")
    daily.to_csv(directory / "daily_nav.csv", index=False, encoding="utf-8-sig")
    save_json(directory / "portfolio.json", portfolio.to_dict())
    pnl = trades.pnl if not trades.empty else pd.Series(dtype=float)
    returns = trades.net_return_pct if not trades.empty else pd.Series(dtype=float)
    gains, losses = pnl[pnl > 0], pnl[pnl < 0]
    b = benchmark.loc[dates].dropna()
    monthly = []
    prior = 200_000.0
    for month, group in daily.groupby(daily.date.str[:7], sort=True):
        value = float(group.equity.iloc[-1])
        monthly.append({"month": month, "return_pct": (value / prior - 1) * 100,
                        "end_equity": value, "entries": int(group.entries.sum()),
                        "average_close_exposure_pct": float((group.market_value / group.equity).mean() * 100)})
        prior = value
    pd.DataFrame(monthly).to_csv(directory / "monthly.csv", index=False)
    counts = signals.loc[dates].sum(axis=1)
    nav = np.r_[200_000.0, daily.equity.to_numpy()]
    drawdown = nav / np.maximum.accumulate(nav) - 1
    summary = {
        "scenario": key, "start": dates[0], "end": dates[-1], "sessions": len(dates),
        "signals": int(counts.sum()), "active_signal_days": int(counts.gt(0).sum()),
        "zero_signal_days": int(counts.eq(0).sum()), "max_daily_picks": int(counts.max()),
        "closed_trades": len(trades), "open_positions_end": len(portfolio.open_allocations),
        "event_skips": events.skipped, "portfolio_skips": portfolio.skipped,
        "account_return_pct": (float(daily.equity.iloc[-1]) / 200_000 - 1) * 100,
        "max_drawdown_pct": float(drawdown.min() * 100),
        "win_rate_pct": float((pnl > 0).mean() * 100) if len(pnl) else None,
        "mean_trade_net_pct": float(returns.mean()) if len(returns) else None,
        "profit_factor_cash": float(gains.sum() / -losses.sum()) if len(losses) else None,
        "payoff_ratio_pct": float(returns[returns > 0].mean() / -returns[returns < 0].mean()) if (returns > 0).any() and (returns < 0).any() else None,
        "avg_close_exposure_pct": float((daily.market_value / daily.equity).mean() * 100),
        "best_trade_pct": float(returns.max()) if len(returns) else None,
        "worst_trade_pct": float(returns.min()) if len(returns) else None,
        "benchmark_close_return_pct": float((b.iloc[-1] / b.iloc[0] - 1) * 100) if len(b) >= 2 else None,
        "benchmark_missing_sessions": int(benchmark.loc[dates].isna().sum()),
        "holding_sessions_planned": hold_days + 1, "round_trip_cost_pct": cfg.round_trip_cost_pct(),
        "cash_conservation_passed": True,
    }
    save_json(directory / "summary.json", summary)
    print(json.dumps(summary, ensure_ascii=False), flush=True)
    return summary


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", type=Path, default=DEFAULT_OUT)
    parser.add_argument("--database", type=Path, default=ROOT / "data/market.db")
    parser.add_argument("--prepare-only", action="store_true")
    parser.add_argument("--replay", action="store_true", help="Replay frozen inputs; compare numerical summaries to saved results")
    args = parser.parse_args()
    out = args.out.resolve()
    out.mkdir(parents=True, exist_ok=True)
    prepare_snapshot(out, args.database)
    if args.prepare_only:
        return
    previous = json.loads((out / "summaries.json").read_text(encoding="utf-8")) if args.replay else None
    engine = WechatFourPatternsStrategy()
    protocol = {
        "frozen_before_first_backtest_at": datetime.now(timezone.utc).isoformat(),
        "source_url": "https://mp.weixin.qq.com/s/nEaStkjoKRzxwD_xYfDVrg",
        "strategy_params": engine.default_params(), "periods": PERIODS,
        "primary_holding_sessions": 3, "primary_stop_loss_pct": -6,
        "account": {"initial_capital": 200000, "max_positions": 2, "lot_size": 100, "marks": "daily_close"},
        "execution": "close signal -> next market open; no replacement of unfilled candidates; T+1; strict inferred limit prices",
        "costs": "3bps commission + 5bps slippage per side; 10bps experimental sell levy; 26bps round trip (not a current statutory fee assertion)",
        "declared_sensitivities": ["each of four patterns alone", "2/5-session holding", "double costs", "breadth filter disabled"],
        "not_untouched_oos": True, "no_parameter_optimization": True, "code_hashes": code_hashes(),
    }
    if not (out / "protocol.json").exists():
        save_json(out / "protocol.json", protocol)
    save_json(out / "execution_manifest.json", {"executed_at": datetime.now(timezone.utc).isoformat(), "code_hashes": code_hashes(), "snapshot_sha256": sha(out / "snapshot.npz"), "python": sys.version})
    raw, adjusted, benchmark = load_snapshot(out)
    print("Computing frozen rule set", flush=True)
    result = engine.compute(adjusted)
    audit = audit_signals(engine, adjusted, result)
    save_json(out / "signal_audit.json", audit)
    names = pd.read_csv(out / "universe.csv", dtype={"code": str}).set_index("code").name.to_dict()
    in_period = result.signals.copy()
    in_period.loc[in_period.index < START] = False
    save_picks(out / "picks.csv", result, in_period, names)
    variants = {"primary": result.signals}
    for pattern in PATTERNS:
        candidates = result.factors["candidate"] & result.factors["pattern_" + pattern]
        variants[pattern] = select_top_two(candidates, result.factors["score"])
    variants["no_breadth_gate"] = engine.compute(adjusted, {"breadth_floor": 0.0}).signals
    summaries = []
    for year, (start, end) in PERIODS.items():
        for name, signals in variants.items():
            summaries.append(scenario(out, f"{year}_{name}", signals, raw, benchmark, start, end))
        for label, hold, multiple in (("hold_2sessions", 1, 1), ("hold_5sessions", 4, 1), ("double_cost", 2, 2)):
            summaries.append(scenario(out, f"{year}_{label}", result.signals, raw, benchmark, start, end, hold, multiple))
    summaries.append(scenario(out, "full_primary", result.signals, raw, benchmark, START, END))
    save_json(out / "summaries.json", summaries)
    pd.DataFrame(summaries).drop(columns=["event_skips", "portfolio_skips"]).to_csv(out / "summary.csv", index=False, encoding="utf-8-sig")
    if previous is not None:
        assert previous == summaries, "replay numerical summaries differ from the saved run"
        save_json(out / "replay_verification.json", {"passed": True, "scenarios_compared": len(summaries), "executed_at": datetime.now(timezone.utc).isoformat(), "code_hashes": code_hashes()})
        print("REPLAY PASSED: all numerical summaries match", flush=True)
    print("COMPLETE", out, flush=True)


if __name__ == "__main__":
    main()
