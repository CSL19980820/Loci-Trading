"""三源 vs 潜龙：2026 YTD 逐笔口径下 T+2 / T+3 卖出对照。

口径：
- 每个信号独立成交（``run_backtest`` 默认），不做组合槽位与资金约束。
- 两个策略 ``entry_timing`` 均为 next_open：T 日盘后选股，T+1 开盘买入。
- ``hold_days`` 自买入日起算，到期收盘了结：hold=1 → T+2 收盘卖，hold=2 → T+3 收盘卖。
- 不设止损止盈，隔离出「只换卖出日」这一个变量。
- 信号截止到 T+3 仍有行情的最后一天，避免 hold=2 因数据到头少算样本。
"""
from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.backtest import BacktestConfig  # noqa: E402
from src.backtest.application.runner import (  # noqa: E402
    execute_backtest_context,
    prepare_backtest_context,
)
from src.market import MarketStore  # noqa: E402

STRATEGIES = {
    "sanyuan-tail-v1": "三源尾盘共振",
    "qianlong-close-v3": "潜龙出海 V3.2",
}
HOLDS = {1: "T+2 收盘卖", 2: "T+3 收盘卖"}
START = "2026-01-01"


def _tail_capped_end(store: MarketStore, max_hold: int) -> str:
    """最后一个「T+1 买入 + max_hold 持有」仍有完整行情的信号日。"""
    days = store.trading_days()
    return days[-(1 + max_hold + 1)]


def _entry_day_dip(ctx: dict[str, Any], trades: list[Any]) -> dict[str, float]:
    """买入日（T+1）盘中相对开盘的最大折让，衡量「低吸」还有多少空间。"""
    panels = ctx.get("execution_panels", ctx["panels"])
    open_, low = panels["open"], panels["low"]
    dips: list[float] = []
    for trade in trades:
        try:
            o = float(open_.at[trade.entry_date, trade.code])
            lo = float(low.at[trade.entry_date, trade.code])
        except KeyError:
            continue
        if np.isfinite(o) and np.isfinite(lo) and o > 0:
            dips.append((lo / o - 1) * 100)
    if not dips:
        return {}
    arr = np.asarray(dips)
    return {
        "avg_entry_day_dip_pct": round(float(arr.mean()), 3),
        "median_entry_day_dip_pct": round(float(np.median(arr)), 3),
        "dip_ge_1pct_rate": round(float((arr <= -1.0).mean() * 100), 2),
    }


def _excursion_profile(trades: list[Any]) -> dict[str, float]:
    """持有期内的浮盈幅度分布，衡量「高抛」有多少可抓的窗口。"""
    live = [t for t in trades if t.exit_reason != "data_end"]
    if not live:
        return {}
    mfe = np.asarray([t.mfe_pct for t in live])
    net = np.asarray([t.net_return_pct for t in live])
    return {
        "mfe_ge_3pct_rate": round(float((mfe >= 3.0).mean() * 100), 2),
        "mfe_ge_5pct_rate": round(float((mfe >= 5.0).mean() * 100), 2),
        "median_mfe_pct": round(float(np.median(mfe)), 3),
        "give_back_pct": round(float(mfe.mean() - net.mean()), 3),
    }


def main() -> int:
    store = MarketStore()
    end = _tail_capped_end(store, max(HOLDS))
    print(f"信号区间 {START} ~ {end}（逐笔口径，无止损止盈，T+1 开盘买入）\n")

    report: dict[str, Any] = {"start": START, "signal_end": end, "results": {}}
    paired: dict[str, dict[int, dict[tuple[str, str], float]]] = {}

    for slug, label in STRATEGIES.items():
        ctx = prepare_backtest_context(
            store, slug, start=START, end=end,
            config=BacktestConfig(hold_days=max(HOLDS), stop_loss_pct=None),
        )
        paired[slug] = {}
        for hold, hold_label in HOLDS.items():
            run_ctx = dict(ctx)
            run_ctx["config"] = BacktestConfig(
                hold_days=hold,
                stop_loss_pct=None,
                take_profit_pct=None,
                benchmark="000300",
            )
            result = execute_backtest_context(store, run_ctx)
            m = dict(result.metrics)
            m.pop("return_distribution", None)
            m.pop("percentiles", None)
            m.update(_excursion_profile(result.trades))
            m.update(_entry_day_dip(run_ctx, result.trades))
            m["by_month"] = result.metrics.get("by_month")
            report["results"][f"{slug}/hold{hold}"] = m
            paired[slug][hold] = {
                (t.code, t.signal_date): t.net_return_pct
                for t in result.trades
                if t.exit_reason != "data_end"
            }
            print(
                f"{label:<14} {hold_label}  "
                f"{m['trades']:>4} 笔  胜率 {m['win_rate']:>5.1f}%  "
                f"净收益均值 {m['avg_net_return']:>+6.2f}%  "
                f"中位 {m['median_net_return']:>+6.2f}%  "
                f"累计 {m['total_net_return']:>+8.1f}%"
            )
            print(
                f"{'':<14} {'':<10}  盈亏比 {m['profit_factor']}  "
                f"均盈亏比 {m['payoff_ratio']}  "
                f"均盈 {m['avg_win']:+.2f}% / 均亏 {m['avg_loss']:+.2f}%  "
                f"超额 {m.get('avg_alpha', float('nan')):+.2f}%"
            )
            print(
                f"{'':<14} {'':<10}  MFE均值 {m['avg_mfe']:+.2f}%  "
                f"MAE均值 {m['avg_mae']:+.2f}%  回吐 {m['give_back_pct']:.2f}pt  "
                f"浮盈≥3% 占比 {m['mfe_ge_3pct_rate']:.1f}%  ≥5% {m['mfe_ge_5pct_rate']:.1f}%"
            )
            print(
                f"{'':<14} {'':<10}  买入日盘中折让 均值 "
                f"{m.get('avg_entry_day_dip_pct', float('nan')):.2f}%  "
                f"跌破开盘1% 占比 {m.get('dip_ge_1pct_rate', float('nan')):.1f}%"
            )
            print()

    print("—— 同一批信号配对：T+3 相对 T+2 的净收益增量 ——")
    for slug, label in STRATEGIES.items():
        keys = set(paired[slug][1]) & set(paired[slug][2])
        if not keys:
            continue
        delta = np.asarray([paired[slug][2][k] - paired[slug][1][k] for k in sorted(keys)])
        report["results"][f"{slug}/paired_delta"] = {
            "n": int(delta.size),
            "avg": round(float(delta.mean()), 4),
            "median": round(float(np.median(delta)), 4),
            "improve_rate": round(float((delta > 0).mean() * 100), 2),
        }
        print(
            f"{label:<14} 配对 {delta.size:>4} 笔  "
            f"多持一天平均 {delta.mean():+.3f}pt  "
            f"中位 {np.median(delta):+.3f}pt  "
            f"变好占比 {(delta > 0).mean() * 100:.1f}%"
        )

    out = Path(__file__).resolve().parents[1] / "docs" / "research" / "_scratch_sanyuan_qianlong_exit_compare.json"
    out.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"\n明细已写入 {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
