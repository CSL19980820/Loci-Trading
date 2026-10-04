"""Isolated, train-first exit research; never changes a strategy or market store.

Run ``train`` first. ``evaluate`` requires its immutable freeze receipt and only
evaluates the frozen shortlist plus the current 4-session/-6% control. Helpers
``common_maturity_mask`` and ``execute_split_context`` also accept a caller's
already prepared/filtered context, without changing its strategy or ranking.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
import sys
from dataclasses import dataclass, replace
from datetime import datetime
from itertools import product
from pathlib import Path
from typing import Any, Mapping
from zoneinfo import ZoneInfo

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from src.backtest.application.engine import run_backtest  # noqa: E402
from src.backtest.application.metrics import compute_metrics  # noqa: E402
from src.backtest.application.runner import prepare_backtest_context  # noqa: E402
from src.backtest.domain.models import BacktestConfig, Trade  # noqa: E402
from src.strategy.application.catalog import get  # noqa: E402
from tools.strategy_chinext_review import (  # noqa: E402
    STRATEGIES,
    UNIVERSE,
    ReadOnlyMarketStore,
    coverage,
    input_digest,
    wilson_interval,
    write_json,
)

OUTPUT = ROOT / "docs/research/2026-10-04-chinext-payoff-study/exits"
SPLITS = {
    "train": ("2024-01-01", "2025-06-30"),
    "validation": ("2025-07-01", "2025-12-31"),
    "observed_2026": ("2026-01-01", "2026-09-30"),
}
HOLDS = (4, 5, 7, 10, 20)
STOPS = (None, -4.0, -6.0, -8.0)
TAKES = (None, 12.0, 20.0)
MAX_HOLD = 20
COSTS = (0.21, 0.31, 0.41)
SELECTION_POLICY = {
    "primary_target": "payoff_ratio",
    "eligibility": "closed>=80, finite payoff, profit_factor>1, avg_net_return>0",
    "shortlist_holds": [4, 5, 7, 10],
    "pareto_axes": ["payoff_ratio", "profit_factor", "avg_net_return"],
    "representatives": ["maximum_payoff", "maximum_net_mean", "stress_drop_winner_pf"],
    "robustness": "0.41% total cost and remove largest winner; diagnostic, no validation tuning",
    "tie_break": "primary descending, payoff/PF/mean descending, shorter hold, lexical key",
    "maximum_per_strategy": 3,
    "baseline": "H04-S06-Tnone reported regardless of eligibility",
    "twenty_sessions": "training sensitivity only, excluded from short-hold shortlist",
}


@dataclass(frozen=True)
class Scenario:
    sessions: int
    stop: float | None
    take: float | None

    @property
    def key(self) -> str:
        stop = "none" if self.stop is None else f"{abs(self.stop):02.0f}"
        take = "none" if self.take is None else f"{self.take:02.0f}"
        return f"H{self.sessions:02d}-S{stop}-T{take}"

    def to_dict(self) -> dict[str, Any]:
        return {"key": self.key, "sessions_including_entry": self.sessions,
                "hold_days": self.sessions - 1, "stop_loss_pct": self.stop,
                "take_profit_pct": self.take}

    def config(self, end: str) -> BacktestConfig:
        return BacktestConfig(
            hold_days=self.sessions - 1, stop_loss_pct=self.stop,
            take_profit_pct=self.take, commission_bps=3, slippage_bps=5,
            stamp_duty_bps=5, strict_limit_prices=True, economic_returns=True,
            valuation_end=end, benchmark=None,
        )


GRID = tuple(Scenario(*values) for values in product(HOLDS, STOPS, TAKES))
BASELINE = Scenario(4, -6.0, None)


class CutoffMarketStore(ReadOnlyMarketStore):
    """Bound price/calendar reads to this phase's cutoff; source remains mode=ro."""

    def __init__(self, db_path: Path, cutoff: str) -> None:
        super().__init__(db_path)
        self.cutoff = cutoff

    def trading_days(self, start: str | None = None, end: str | None = None) -> list[str]:
        return super().trading_days(start=start, end=min(end or self.cutoff, self.cutoff))

    def history(self, code: str, *, start: str | None = None, end: str | None = None,
                adjust: str = "qfq", limit: int | None = None) -> pd.DataFrame:
        return super().history(code, start=start, end=min(end or self.cutoff, self.cutoff),
                               adjust=adjust, limit=limit)

    def load_panel(self, **kwargs: Any) -> dict[str, pd.DataFrame]:
        kwargs["end"] = min(kwargs.get("end") or self.cutoff, self.cutoff)
        return super().load_panel(**kwargs)

    def _quotes_daily_snapshot_fast(self) -> dict[str, object]:
        return dict(self.conn.execute(
            "SELECT COUNT(*) AS rows,MAX(trade_date) AS last_date,MAX(fetched_at) AS fetched_at "
            "FROM quotes_daily WHERE trade_date<=?", (self.cutoff,),
        ).fetchone())


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def source_hashes() -> dict[str, str]:
    paths = (
        "tools/research_chinext_payoff_exits.py", "tools/strategy_chinext_review.py",
        "src/backtest/application/runner.py", "src/backtest/application/engine.py",
        "src/backtest/application/metrics.py", "src/backtest/application/execution_contract.py",
        "src/backtest/domain/models.py", "src/market/infrastructure/store_panel.py",
        "src/strategy/application/contraction_rebreakout.py",
        "src/strategy/application/impulse_inside_breakout.py",
    )
    return {name: sha256(ROOT / name) for name in paths}


def common_maturity_mask(index: pd.Index, start: str, end: str, *,
                         entry_timing: str = "next_open", max_hold: int = MAX_HOLD) -> pd.Series:
    """Common signal mask: entry + (max_hold-1) market sessions <= split end.

    The index MUST be the same complete market-session index used by the classic
    execution engine. Individual suspensions never compress this calendar.
    """
    dates = np.asarray([str(day)[:10] for day in index])
    if not index.is_unique or not index.is_monotonic_increasing or max_hold < 2:
        raise ValueError("Maturity mask requires an ordered unique market calendar and max_hold>=2")
    if entry_timing not in {"next_open", "next_dip", "open", "close"}:
        raise ValueError(f"Unknown entry timing: {entry_timing}")
    offset = 1 if entry_timing in {"next_open", "next_dip"} else 0
    rows = np.arange(len(index))
    last = int(np.searchsorted(dates, end, side="right")) - 1
    entry = rows + offset
    inside = (dates >= start) & (dates <= end)
    valid = inside & (entry < len(index)) & (entry + max_hold - 1 <= last)
    return pd.Series(valid, index=index, name="common_maturity_eligible")


def metric_summary(trades: list[Trade]) -> dict[str, Any]:
    metrics = compute_metrics(trades)
    metrics["win_rate_wilson_95_pct"] = wilson_interval(metrics)
    return metrics


def cost_diagnostics(trades: list[Trade]) -> dict[str, Any]:
    closed = [trade for trade in trades if trade.exit_reason != "data_end"]
    winner = max(closed, key=lambda trade: trade.net_return_pct) if closed else None
    rows = {}
    for cost in COSTS:
        repriced = [replace(trade, net_return_pct=trade.gross_return_pct - cost) for trade in closed]
        removed = [trade for trade, original in zip(repriced, closed) if original is not winner]
        rows[f"{cost:.2f}"] = {
            "metrics": metric_summary(repriced), "largest_winner_removed": metric_summary(removed),
        }
    return {"costs": rows, "largest_winner": winner.to_dict(include_factors=True) if winner else None}


def execute_split_context(ctx: Mapping[str, Any], config: BacktestConfig,
                          start: str, end: str, *, max_hold: int = MAX_HOLD) -> dict[str, Any]:
    """Execute frozen signals on a common maturity set and strict split boundary.

    A custom filter may replace ctx['signals'] BEFORE calling this helper. The
    helper never recalculates ranking or fills omitted candidates from below Top2.
    Returns closed Trade objects under 'closed_trades' for caller diagnostics.
    """
    source_signals = ctx["signals"].fillna(False).astype(bool)
    maturity = common_maturity_mask(source_signals.index, start, end,
                                    entry_timing=ctx["engine"].entry_timing, max_hold=max_hold)
    window = (source_signals.index >= start) & (source_signals.index <= end)
    masked = source_signals.where(maturity, False, axis=0)
    execution = ctx.get("execution_panels", ctx["panels"])
    cfg = replace(config, valuation_end=end)
    if not cfg.strict_limit_prices or not cfg.economic_returns:
        raise ValueError("Research requires strict raw execution and economic returns")
    result = run_backtest(
        masked, execution, entry_timing=ctx["engine"].entry_timing,
        entry_price_panel=ctx.get("entry_price_panel"), config=cfg,
        strategy_slug=ctx["engine"].slug, benchmark_close=None,
    )
    closed = [trade for trade in result.trades if trade.exit_reason != "data_end"
              and start <= trade.entry_date <= end and start <= trade.exit_date <= end]
    data_end = [trade for trade in result.trades if trade.exit_reason == "data_end"]
    boundary = [trade for trade in result.trades if trade.exit_reason != "data_end" and trade not in closed]
    eligible = int(masked.to_numpy().sum())
    if eligible != len(result.trades) + sum(result.skipped.values()):
        raise AssertionError("Signal/entry skip/trade accounting mismatch")
    if len(result.trades) != len(closed) + len(data_end) + len(boundary):
        raise AssertionError("Closed/censored/boundary accounting mismatch")
    for trade in closed:
        if trade.entry_date >= trade.exit_date:
            raise AssertionError("T+1 violated")
        expected = (trade.exit_price * trade.exit_factor / (trade.entry_price * trade.entry_factor) - 1) * 100
        if not math.isclose(expected, trade.gross_return_pct, abs_tol=1e-8):
            raise AssertionError("Economic return does not match raw prices and adjustment factors")
        if not math.isclose(trade.gross_return_pct - cfg.round_trip_cost_pct(),
                            trade.net_return_pct, abs_tol=1e-8):
            raise AssertionError("Cost contract mismatch")
    metrics = metric_summary(closed)
    month_metrics = {
        str(month): metric_summary([trade for trade in closed if trade.signal_date.startswith(str(month))])
        for month in pd.period_range(start, end, freq="M")
    }
    eligible_days = maturity.index[maturity]
    both_touched = 0
    if cfg.stop_loss_pct is not None and cfg.take_profit_pct is not None:
        factors = execution["__adjust_factor"]
        for trade in closed:
            if trade.exit_reason not in {"stop_loss", "take_profit"}:
                continue
            basis = trade.entry_price * trade.entry_factor
            high = execution["high"].loc[trade.exit_date, trade.code] * factors.loc[trade.exit_date, trade.code]
            low = execution["low"].loc[trade.exit_date, trade.code] * factors.loc[trade.exit_date, trade.code]
            both_touched += int(high >= basis * (1 + cfg.take_profit_pct / 100)
                                and low <= basis * (1 + cfg.stop_loss_pct / 100))
    return {"config": cfg.to_dict(), "metrics": metrics,
            "by_signal_month": month_metrics, "diagnostics": cost_diagnostics(closed),
            "accounting": {
                "all_split_signals": int(source_signals.loc[window].to_numpy().sum()),
                "common_maturity_purged": int(source_signals.loc[window].to_numpy().sum()) - eligible,
                "eligible_signals": eligible, "closed": len(closed), "data_end": len(data_end),
                "boundary_excluded": len(boundary), "skipped": result.skipped,
                "last_allowed_signal_date": str(eligible_days[-1]) if len(eligible_days) else None,
                "max_hold_including_entry": max_hold,
                "both_exit_levels_touched_on_exit_day": both_touched,
            }, "closed_trades": closed, "all_trades": result.trades}


def serializable_run(run: dict[str, Any]) -> dict[str, Any]:
    return {name: value for name, value in run.items() if name not in {"closed_trades", "all_trades"}}


def numeric(value: Any, fallback: float = -math.inf) -> float:
    return float(value) if isinstance(value, (int, float)) and math.isfinite(value) else fallback


def eligible_candidate(row: dict[str, Any]) -> bool:
    metrics = row["metrics"]
    return (row["scenario"]["sessions_including_entry"] <= 10 and metrics.get("trades", 0) >= 80
            and numeric(metrics.get("payoff_ratio")) > -math.inf
            and numeric(metrics.get("profit_factor")) > 1
            and numeric(metrics.get("avg_net_return")) > 0)


def select_training_candidates(rows: list[dict[str, Any]]) -> dict[str, Any]:
    """Deterministic train-only Pareto shortlist, never consumes later split data."""
    eligible = [row for row in rows if eligible_candidate(row)]
    axes = SELECTION_POLICY["pareto_axes"]
    front = []
    for row in eligible:
        point = [numeric(row["metrics"].get(axis)) for axis in axes]
        dominated = any(
            all(a >= b for a, b in zip(other_point, point))
            and any(a > b for a, b in zip(other_point, point))
            for other in eligible if other is not row
            for other_point in [[numeric(other["metrics"].get(axis)) for axis in axes]]
        )
        if not dominated:
            front.append(row)
    selected = []
    for role in SELECTION_POLICY["representatives"]:
        def order(row: dict[str, Any]) -> tuple[Any, ...]:
            metrics = row["metrics"]
            primary = metrics.get("payoff_ratio") if role == "maximum_payoff" else metrics.get("avg_net_return")
            if role == "stress_drop_winner_pf":
                primary = row["diagnostics"]["costs"]["0.41"]["largest_winner_removed"].get("profit_factor")
            return (-numeric(primary), -numeric(metrics.get("payoff_ratio")),
                    -numeric(metrics.get("profit_factor")), -numeric(metrics.get("avg_net_return")),
                    row["scenario"]["sessions_including_entry"], row["scenario"]["key"])
        if not front:
            break
        winner = min(front, key=order)
        matching = next((record for record in selected if record["key"] == winner["scenario"]["key"]), None)
        if matching:
            matching["roles"].append(role)
        else:
            selected.append({**winner["scenario"], "roles": [role]})
    return {"eligible_count": len(eligible), "pareto_keys": sorted(row["scenario"]["key"] for row in front),
            "selected": selected, "no_eligible_candidate": not bool(eligible)}


def prepare(store: CutoffMarketStore, slug: str, start: str, end: str) -> dict[str, Any]:
    engine = get(slug)
    ctx = prepare_backtest_context(store, engine, start=start, end=end,
                                  universe=UNIVERSE, config=BASELINE.config(end),
                                  source_evidence_mode="compact")
    # The market-session calendar must not silently compress missing all-market days.
    market_days = store.trading_days(start=str(ctx["signals"].index[0]), end=end)
    if list(ctx["signals"].index) != market_days:
        raise AssertionError("Execution panel omits market sessions; maturity/holding would be distorted")
    if int(ctx["signals"].sum(axis=1).max()) > 2:
        raise AssertionError("Daily Top2 changed")
    if any(not str(code).startswith(("300", "301")) for code in ctx["signals"].columns):
        raise AssertionError("Non-ChiNext code present")
    return ctx


def selected_signal_digest(signals: pd.DataFrame) -> str:
    rows, cols = np.nonzero(signals.fillna(False).to_numpy(dtype=bool))
    keys = sorted(f"{signals.index[row]}:{signals.columns[col]}" for row, col in zip(rows, cols))
    return hashlib.sha256("\n".join(keys).encode()).hexdigest()


def context_evidence(ctx: Mapping[str, Any]) -> dict[str, Any]:
    return {"revision": ctx["engine"].strategy_revision, "name": ctx["engine"].name,
            "params": ctx["resolved_params"], "universe": ctx["resolved"].spec,
            "universe_funnel": ctx["resolved"].funnel.to_dict(),
            "panel_columns": len(ctx["signals"].columns), "load_start": ctx["load_start"],
            "load_end": ctx["load_end"], "execution_input_sha256": input_digest(dict(ctx)),
            "signals_sha256": hashlib.sha256(
                pd.util.hash_pandas_object(ctx["signals"], index=True).values.tobytes()).hexdigest(),
            "selected_signal_keys_sha256": selected_signal_digest(ctx["signals"]),
            "data_snapshot": ctx["data_snapshot"]}


def methodology() -> str:
    return """# 双策略退出方案研究：预先声明的方法

本研究仅新增离线工具和证据，不修改现有策略、评分、回测引擎、默认模板或生产运行。
当前缩量回调后二次突破 revision 2、大阳三日缩量突破 revision 3 固定使用完整创业板池内每日 Top2；不依退出结果改变选股。

训练段为 2024-01-01～2025-06-30，验证段为 2025-07-01～2025-12-31，已观察段为 2026-01-01～2026-09-30。
2026 年及 9 月 29 日目标样例此前已用于评分校准，因此不能把它叫纯样本外。固定当前规则回放更早历史也不能消除规则开发中的选择偏差。
train 命令把价格/成交面板与日历读取截止于训练末日；evaluate 命令只有在验证冻结 receipt 和源码/输入哈希后才能读取后续价格。
当前证券目录/名称、历史收据缺失、复权资料修订等仍需披露，不能据此宣称严格 point-in-time。

网格为含买入日持有 4/5/7/10/20 个市场交易日 × 止损无/-4%/-6%/-8% × 止盈无/+12%/+20%，每策略 60 档。
含买入日 N 对应引擎 hold_days=N-1；基准固定为第 4 日、-6%、无止盈。20 日仅是持有期敏感性，不作为超短建议。
所有方案与基准使用相同信号机会集：next_open 入场日为信号后第 1 个市场交易日，且 entry+19 不晚于本段末日。
这共同剔除每段末端无法覆盖最长持有期的信号，避免短持有或早止损额外纳入期末样本。
最后仍要求实际 entry_date 和 exit_date 均在本段，data_end 与停牌/跌停延期未闭仓单独计数。不会把边界持仓当闭仓盈利。
市场交易日按执行面板完整日历计数，个股停牌不压缩持有期。普通月度按 signal_date 归属，段内交易过滤后计算。

形态前复权、执行未复权、收益和触发线按显式经济权益因子换算。沿用经典引擎：T+1、涨停开盘拒买、停牌/收盘跌停不可卖、跳空穿止损按更差开盘价。
日 K 同日同时触及止损止盈采用现有止损优先规则，并披露同时触及笔数；日 K 无法确定盘中先后，不能当精确逐笔撮合。
成本一趟 0.21%：双边佣金各 3bps、双边滑点各 5bps、卖出印花税 5bps。训练始于 2024，不跨 2023 税率变更。
0.31%/0.41% 成本压力仅按同一成交重新扣费，不改变触发线或撮合；未含已知账户最小佣金、逐笔市场冲击和容量。

训练资格为已闭仓至少 80 笔、有限盈亏比、PF>1、平均净收益>0。只在 ≤10 日合格方案内按 payoff/PF/均值构造非支配前沿。
冻结最多三个代表：盈亏比最大、净均值最大、0.41% 成本且剔最大赢单后 PF 最大，重复方案合并角色。盈亏比为主要目标，PF/均值为约束，稳健性为诊断。
固定 tie-break 为主目标降序，再 payoff/PF/均值降序，再持有期较短、配置 key 字典序。没有合格方案就明确不选。
训练全网格表、选中 key、源码和数据输入哈希、选择规则、创建时间写入 freeze-receipt.json 及其独立 SHA256。
验证只跑冻结方案和基准；不从验证网格重新择优，不改参数。验证不通过或收益依赖大赢单时如实报告。

盈亏比=平均盈利/平均亏损绝对值，PF=盈利总和/亏损总和绝对值，期望=单笔平均净收益；高盈亏比可能伴随胜率降低。
交易独立评估、持有可能重叠，单笔收益总和不是账户回报。Wilson 胜率区间也不消除交易相关性和幸存者偏差。
会报告闭仓样本、跳过/边界排除、盈亏比、胜率、PF、均值、平均赢亏、月度、成本压力和剔最大赢单结果；不会只挑最高盈亏比而隐去亏损期望。
共同成熟缓冲后的 2026 基准与原九个月全期 185/118 笔口径不同，须明确区分，不把样本减少解释为策略计算改动。
"""


def save_trades(path: Path, run: dict[str, Any]) -> None:
    closed_ids = {id(trade) for trade in run["closed_trades"]}
    columns = list(Trade.__dataclass_fields__) + ["included_closed"]
    pd.DataFrame([{**trade.to_dict(include_factors=True), "included_closed": id(trade) in closed_ids}
                  for trade in run["all_trades"]], columns=columns).to_csv(path, index=False)


def grid_frame(rows: list[dict[str, Any]]) -> pd.DataFrame:
    return pd.DataFrame([{**row["scenario"], **{key: row["metrics"].get(key) for key in (
        "trades", "win_rate", "payoff_ratio", "profit_factor", "avg_net_return", "avg_win", "avg_loss")},
        "shortlist_eligible": eligible_candidate(row),
        "stress_041_pf": row["diagnostics"]["costs"]["0.41"]["metrics"].get("profit_factor"),
        "stress_041_drop_winner_pf": row["diagnostics"]["costs"]["0.41"]["largest_winner_removed"].get("profit_factor"),
        **row["accounting"]} for row in rows])


def run_train(db: Path, output: Path) -> None:
    receipt_path = output / "freeze-receipt.json"
    if receipt_path.exists():
        raise ValueError("Train receipt already exists: use a new output directory; never overwrite a freeze")
    output.mkdir(parents=True, exist_ok=True)
    (output / "methodology.md").write_text(methodology(), encoding="utf-8")
    start, end = SPLITS["train"]
    sources = source_hashes()
    summary = {"created_at": datetime.now(ZoneInfo("Asia/Shanghai")).isoformat(),
               "phase": "train", "database": str(db.resolve()), "database_sha256": sha256(db),
               "split": {"start": start, "end": end}, "selection_policy": SELECTION_POLICY,
               "grid_size_per_strategy": len(GRID), "source_sha256": sources, "strategies": {}}
    with CutoffMarketStore(db, end) as store:
        summary["coverage"] = coverage(store, start, end)
        pd.DataFrame(summary["coverage"]["daily"]).to_csv(output / "train-coverage.csv", index=False)
        for slug in STRATEGIES:
            print(f"TRAIN prepare {slug}; price cutoff={end}", flush=True)
            ctx = prepare(store, slug, start, end)
            rows = []
            for n, scenario in enumerate(GRID, 1):
                run = execute_split_context(ctx, scenario.config(end), start, end)
                rows.append({"scenario": scenario.to_dict(), **serializable_run(run)})
                save_trades(output / f"{slug}-train-{scenario.key}-trades.csv", run)
                if n % 10 == 0:
                    print(f"TRAIN {slug}: {n}/{len(GRID)} scenarios completed", flush=True)
            selection = select_training_candidates(rows)
            summary["strategies"][slug] = {**context_evidence(ctx), "runs": rows, "selection": selection}
            grid_frame(rows).to_csv(output / f"{slug}-train-grid.csv", index=False)
            print(f"TRAIN shortlist {slug}: {json.dumps(selection, ensure_ascii=False)}", flush=True)
            write_json(output / "training-summary.json", summary)
    if source_hashes() != sources:
        raise ValueError("Source changed during training; no freeze produced")
    receipt = {"created_at": datetime.now(ZoneInfo("Asia/Shanghai")).isoformat(),
               "phase": "training_complete_validation_unopened", "database_sha256": summary["database_sha256"],
               "training_summary_sha256": sha256(output / "training-summary.json"),
               "methodology_sha256": sha256(output / "methodology.md"),
               "source_sha256": sources, "splits": SPLITS, "max_hold_including_entry": MAX_HOLD,
               "selection_policy": SELECTION_POLICY,
               "strategies": {slug: {key: record[key] for key in (
                   "revision", "params", "execution_input_sha256", "signals_sha256",
                   "selected_signal_keys_sha256", "selection")}
                   for slug, record in summary["strategies"].items()}}
    write_json(receipt_path, receipt)
    (output / "freeze-receipt.sha256").write_text(sha256(receipt_path) + "\n", encoding="utf-8")
    print(f"FROZEN: {receipt_path}; SHA256={sha256(receipt_path)}; validation not executed", flush=True)


def verify_freeze(db: Path, output: Path) -> tuple[dict[str, Any], dict[str, Any]]:
    receipt_path = output / "freeze-receipt.json"
    expected = (output / "freeze-receipt.sha256").read_text(encoding="utf-8").strip()
    if sha256(receipt_path) != expected:
        raise ValueError("Freeze receipt SHA mismatch")
    receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
    if receipt["source_sha256"] != source_hashes():
        raise ValueError("Frozen source changed; validation rejected")
    if receipt["database_sha256"] != sha256(db):
        raise ValueError("Frozen source database changed; validation rejected")
    if receipt["training_summary_sha256"] != sha256(output / "training-summary.json"):
        raise ValueError("Training summary changed")
    if receipt["methodology_sha256"] != sha256(output / "methodology.md"):
        raise ValueError("Methodology changed")
    training = json.loads((output / "training-summary.json").read_text(encoding="utf-8"))
    for slug in STRATEGIES:
        selected = select_training_candidates(training["strategies"][slug]["runs"])
        if selected != receipt["strategies"][slug]["selection"]:
            raise ValueError("Shortlist is not reproducible from training-only selection")
    return receipt, training


def fmt(value: Any, digits: int = 3) -> str:
    return "—" if value is None else f"{value:.{digits}f}" if isinstance(value, (int, float)) else str(value)


def render_report(summary: dict[str, Any]) -> str:
    lines = ["# 双策略退出参数研究", "", f"生成时间：{summary['created_at']}。",
             "本次为隔离研究，未替换现有策略或默认退出规则。训练冻结后才查看后续验证；2026 段已有开发者观察，不是纯样本外。",
             "详见 [预先声明的方法](methodology.md) 和 [训练冻结回执](freeze-receipt.json)。", "",
             "每档在同一段内共用最长20交易日成熟缓冲，实际买卖日期都在段内；以下只统计已平仓，data_end不计收益。",
             "固定当前Top2选股、经典T+1/涨跌停成交、经济权益收益和0.21%费用。",
             "", "|策略|段|配置（含入场日持有/止损/止盈）|角色|闭仓|胜率%|盈亏比|PF|净期望%|平均赢%|平均亏%|",
             "|---|---|---|---|---:|---:|---:|---:|---:|---:|---:|"]
    for slug in STRATEGIES:
        record = summary["strategies"][slug]
        for split in SPLITS:
            for row in record["runs"][split]:
                m = row["metrics"]
                lines.append("|" + "|".join(map(str, [record["name"], split, row["scenario"]["key"],
                    ",".join(row["roles"]), m.get("trades", 0), fmt(m.get("win_rate"), 2),
                    fmt(m.get("payoff_ratio")), fmt(m.get("profit_factor")), fmt(m.get("avg_net_return"), 4),
                    fmt(m.get("avg_win")), fmt(m.get("avg_loss"))])) + "|")
    for slug in STRATEGIES:
        record = summary["strategies"][slug]
        lines += ["", f"## {record['name']}", "", f"版本 `{record['revision']}`。训练合格 {record['selection']['eligible_count']} 档；冻结候选："
                  + ", ".join(row["key"] for row in record["selection"]["selected"]) + "。",
                  "", "|段/配置|成本%|净期望%|PF|剔最大赢单后净期望%|剔最大赢单后PF|", "|---|---:|---:|---:|---:|---:|"]
        for split, rows in record["runs"].items():
            for row in rows:
                for cost, diagnostic in row["diagnostics"]["costs"].items():
                    m, removed = diagnostic["metrics"], diagnostic["largest_winner_removed"]
                    lines.append(f"|{split}/{row['scenario']['key']}|{cost}|{fmt(m.get('avg_net_return'),4)}|"
                                 f"{fmt(m.get('profit_factor'))}|{fmt(removed.get('avg_net_return'),4)}|{fmt(removed.get('profit_factor'))}|")
        lines += ["", "月度按信号月份归属：", "", "|段/配置|月|闭仓|胜率%|盈亏比|PF|净期望%|", "|---|---|---:|---:|---:|---:|---:|"]
        for split, rows in record["runs"].items():
            for row in rows:
                for month, m in row["by_signal_month"].items():
                    lines.append(f"|{split}/{row['scenario']['key']}|{month}|{m.get('trades',0)}|{fmt(m.get('win_rate'),2)}|"
                                 f"{fmt(m.get('payoff_ratio'))}|{fmt(m.get('profit_factor'))}|{fmt(m.get('avg_net_return'),4)}|")
        lines += ["", "信号与边界核算：", "", "|段/配置|原信号|共同成熟缓冲剔除|执行信号|闭仓|data_end|跨界|买入跳过|同日双触线|",
                  "|---|---:|---:|---:|---:|---:|---:|---:|---:|"]
        for split, rows in record["runs"].items():
            for row in rows:
                a = row["accounting"]
                lines.append(f"|{split}/{row['scenario']['key']}|{a['all_split_signals']}|{a['common_maturity_purged']}|"
                             f"{a['eligible_signals']}|{a['closed']}|{a['data_end']}|{a['boundary_excluded']}|"
                             f"{sum(a['skipped'].values())}|{a['both_exit_levels_touched_on_exit_day']}|")
    lines += ["", "## 限制与复现", "", "高盈亏比伴随低胜率时仍可能亏损；应同时检查验证期PF、单笔期望、费用压力和最大赢单依赖。",
              "60档参数的训练选择具有多重比较偏差，验证只有一段，并不能证明未来稳定。日K同日触线止损优先，无法还原盘中路径；止损线不是损失上限。",
              "固定当前存量目录与当前名称有幸存者/历史ST偏差；来源收据缺口保留原状，非严格PIT。各段行情覆盖和来源缺口见summary.json。",
              "新的2026共同成熟机会集与原全期185/118笔不同，原报告是另一个边界口径，不能横向称为计算不一致。交易可能重叠，单笔收益之和不是账户收益。",
              "训练全60档和20日敏感性见各策略train-grid.csv；后续仅冻结短持有候选及基准。所有CSV含原始成交、因子、成本收益和是否纳入闭仓。",
              "", "```powershell", summary["commands"]["train"], summary["commands"]["evaluate"], "```", ""]
    return "\n".join(lines)


def run_evaluate(db: Path, output: Path) -> None:
    receipt, training = verify_freeze(db, output)
    summary = {"created_at": datetime.now(ZoneInfo("Asia/Shanghai")).isoformat(),
               "phase": "frozen_evaluation", "database": str(db.resolve()),
               "database_sha256": receipt["database_sha256"], "freeze_sha256": sha256(output / "freeze-receipt.json"),
               "source_sha256": receipt["source_sha256"], "splits": SPLITS,
               "selection_policy": SELECTION_POLICY, "strategies": {}, "coverage": {},
               "commands": {phase: f'.\\.venv\\Scripts\\python.exe -X utf8 tools/research_chinext_payoff_exits.py {phase} '
                            f'--db "{db.resolve()}" --output "{output.resolve()}"' for phase in ("train", "evaluate")}}
    with CutoffMarketStore(db, SPLITS["observed_2026"][1]) as store:
        for split, (start, end) in SPLITS.items():
            summary["coverage"][split] = coverage(store, start, end)
        for slug in STRATEGIES:
            frozen = receipt["strategies"][slug]
            print(f"EVALUATE prepare {slug}; frozen shortlist verified", flush=True)
            ctx = prepare(store, slug, SPLITS["train"][0], SPLITS["observed_2026"][1])
            if ctx["engine"].strategy_revision != frozen["revision"] or ctx["resolved_params"] != frozen["params"]:
                raise ValueError("Strategy revision/parameters changed")
            prefix = ctx["signals"].loc[SPLITS["train"][0]:SPLITS["train"][1]]
            if selected_signal_digest(prefix) != frozen["selected_signal_keys_sha256"]:
                raise ValueError("Training Top2 prefix differs when later prices are loaded")
            selections = {row["key"]: row for row in frozen["selection"]["selected"]}
            keys = sorted({BASELINE.key, *selections})
            scenarios = {scenario.key: scenario for scenario in GRID}
            record = {**context_evidence(ctx), "selection": frozen["selection"],
                      "training_signal_prefix_verified": True, "runs": {"train": []}}
            for key in keys:
                row = next(row for row in training["strategies"][slug]["runs"] if row["scenario"]["key"] == key)
                roles = (["baseline"] if key == BASELINE.key else []) + selections.get(key, {}).get("roles", [])
                record["runs"]["train"].append({**row, "roles": roles})
            for split in ("validation", "observed_2026"):
                start, end = SPLITS[split]
                record["runs"][split] = []
                for key in keys:
                    scenario = scenarios[key]
                    run = execute_split_context(ctx, scenario.config(end), start, end)
                    roles = (["baseline"] if key == BASELINE.key else []) + selections.get(key, {}).get("roles", [])
                    record["runs"][split].append({"scenario": scenario.to_dict(), "roles": roles,
                                                 **serializable_run(run)})
                    save_trades(output / f"{slug}-{split}-{key}-trades.csv", run)
                    print(f"EVALUATE {slug}/{split}/{key}: " + json.dumps(
                        {name: run["metrics"].get(name) for name in ("trades", "payoff_ratio", "profit_factor", "avg_net_return")}), flush=True)
            summary["strategies"][slug] = record
            write_json(output / "summary.json", summary)
    if source_hashes() != receipt["source_sha256"]:
        raise ValueError("Source changed during evaluation")
    write_json(output / "summary.json", summary)
    (output / "report.md").write_text(render_report(summary), encoding="utf-8")
    print(f"SAVED {output / 'report.md'}", flush=True)


def self_check() -> None:
    from types import SimpleNamespace
    days = pd.bdate_range("2025-01-01", periods=50).strftime("%Y-%m-%d")
    index = pd.Index(days)
    mask = common_maturity_mask(index, days[0], days[-1])
    assert int(mask.sum()) == 30 and mask.iloc[29] and not mask.iloc[30]
    columns = ["300001"]
    base = pd.DataFrame(100.0, index=index, columns=columns)
    panels = {name: base.copy() for name in ("open", "high", "low", "close")}
    panels["high"] += 1
    panels["low"] -= 1
    panels["volume"] = base.copy()
    panels["__adjust_factor"] = base / 100
    signals = base.eq(-1)
    signals.iloc[[0, 29, 30], 0] = True
    ctx = {"engine": SimpleNamespace(entry_timing="next_open", slug="self-check"),
           "signals": signals, "panels": panels, "execution_panels": panels}
    run = execute_split_context(ctx, BASELINE.config(days[-1]), days[0], days[-1])
    assert run["accounting"]["common_maturity_purged"] == 1
    assert run["metrics"]["trades"] == 2
    assert all(math.isclose(trade.net_return_pct, -.21) for trade in run["closed_trades"])
    assert all(trade.hold_days == 3 for trade in run["closed_trades"])
    # Entry-day low cannot trigger an illegal T+0 exit; next-day dual touch is stop-first.
    panels["low"].iloc[1, 0] = 80
    panels["low"].iloc[2, 0] = 90
    panels["high"].iloc[2, 0] = 130
    run = execute_split_context(ctx, Scenario(4, -6, 12).config(days[-1]), days[0], days[-1])
    trade = run["closed_trades"][0]
    assert trade.exit_date == days[2] and trade.exit_reason == "stop_loss"
    assert math.isclose(trade.net_return_pct, -6.21)
    assert run["accounting"]["both_exit_levels_touched_on_exit_day"] == 1
    assert len(GRID) == 60 and len({scenario.key for scenario in GRID}) == 60
    print("Self-check passed: common maturity, holding count, costs, economic returns, T+1, stop-first", flush=True)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("phase", choices=("methodology", "self-check", "train", "evaluate"))
    parser.add_argument("--db", type=Path)
    parser.add_argument("--output", type=Path, default=OUTPUT)
    args = parser.parse_args()
    if args.phase == "self-check":
        self_check()
        return
    if args.phase == "methodology":
        args.output.mkdir(parents=True, exist_ok=True)
        (args.output / "methodology.md").write_text(methodology(), encoding="utf-8")
        print(args.output / "methodology.md")
        return
    if args.db is None:
        parser.error("--db is required for train/evaluate")
    (run_train if args.phase == "train" else run_evaluate)(args.db, args.output)


if __name__ == "__main__":
    main()
