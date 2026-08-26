"""龙回头·组合条件的**月度**净收益分布。

回答的问题是「组合起来一个月能拿多少」。有两条纪律：

1. **不用单格最优的窄阈值拼装。** 十二维切片里挑出来的「n=61 均净 +2.572%」那类格子
   是数千个格里选最好的，直接 AND 起来是教科书式过拟合。这里只用**跨均线重复出现**
   的模式（市场宽度、距高点天数、筹码宽度、均线排列），阈值取宽档。

2. **月度收益按真实交易按月聚合，不由「每笔均净 × 每月笔数」外推。** 外推假设每月
   笔数恒定且相互独立，实际上信号在时间上高度成簇（强市扎堆、弱市空窗），
   外推会把月度波动算小一个量级。

仓位口径：单笔按 30%（用户的「打 3 层」，龙王舱 10 层 = 100%）与 100% 两档各报一次。
月收益 = 该月所有信号的净收益率之和 × 单笔仓位——**这不是复利，是同月多笔的算术叠加**，
成立前提是持有期只有 1 日、同月各笔基本不重叠。
"""
from __future__ import annotations

import argparse
from dataclasses import asdict
import json
import os
from pathlib import Path
from typing import Any, Callable

import numpy as np
import pandas as pd

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in os.sys.path:
    os.sys.path.insert(0, str(PROJECT_ROOT))

from src.backtest import (  # noqa: E402
    BacktestConfig,
    PortfolioResearchConfig,
    analyze_portfolio,
    run_backtest,
)
from src.market.infrastructure.store_schema import DEFAULT_DB  # noqa: E402
from scripts.dragon_return_pool_trigger_research import (  # noqa: E402
    PoolRule,
    build_pool_and_triggers,
)
from scripts.heat_tail_attention_proxy_research import (  # noqa: E402
    PRICE_FIELDS,
    _load_panels,
    _load_universe,
)
from scripts.sanyuan_tail_resonance_research import _load_days, _read_only_connection  # noqa: E402

WARMUP_BARS = 260

#: 单笔仓位档：3 层 = 30%（用户口径），100% 作为上界参考。
POSITION_SIZES = (0.30, 1.00)

Cond = Callable[[dict[str, pd.DataFrame]], pd.DataFrame]

#: 组合定义。只用跨均线重复出现的四个模式，阈值取宽档而非单格最优的窄档。
COMBOS: dict[str, list[tuple[str, Cond]]] = {
    "裸触发": [],
    "只加强市": [
        ("市场宽度≥55%", lambda d: d["市场宽度%"].ge(55.0)),
    ],
    "强市+新高附近": [
        ("市场宽度≥55%", lambda d: d["市场宽度%"].ge(55.0)),
        ("距高点≤3日", lambda d: d["距高点天数"].le(3)),
    ],
    "强市+新高+筹码密集": [
        ("市场宽度≥55%", lambda d: d["市场宽度%"].ge(55.0)),
        ("距高点≤3日", lambda d: d["距高点天数"].le(3)),
        ("筹码宽度<25%", lambda d: d["筹码宽度%"].lt(25.0)),
    ],
    "四条全上": [
        ("市场宽度≥55%", lambda d: d["市场宽度%"].ge(55.0)),
        ("距高点≤3日", lambda d: d["距高点天数"].le(3)),
        ("筹码宽度<25%", lambda d: d["筹码宽度%"].lt(25.0)),
        ("均线多头", lambda d: d["均线排列"].ge(2.0)),
    ],
}


def _monthly(trades: pd.DataFrame, months: list[str], size: float) -> dict[str, Any]:
    """按信号月聚合。空窗月记 0 收益，不能只统计有信号的月份。"""
    if trades.empty:
        return {"months": len(months), "active_months": 0}
    frame = trades.copy()
    frame["month"] = frame["signal_date"].str.slice(0, 7)
    grouped = frame.groupby("month")["net_return_pct"].agg(["sum", "count"])
    series = pd.Series(0.0, index=months, dtype=float)
    counts = pd.Series(0, index=months, dtype=int)
    for month, row in grouped.iterrows():
        if month in series.index:
            series[month] = float(row["sum"]) * size
            counts[month] = int(row["count"])
    equity = (1 + series / 100).cumprod()
    return {
        "months": len(months),
        "active_months": int((counts > 0).sum()),
        "signals_per_month": round(float(counts.mean()), 2),
        "monthly_mean_pct": round(float(series.mean()), 3),
        "monthly_median_pct": round(float(series.median()), 3),
        "monthly_win_rate_pct": round(float((series > 0).mean() * 100), 2),
        "best_month_pct": round(float(series.max()), 2),
        "worst_month_pct": round(float(series.min()), 2),
        "monthly_std_pct": round(float(series.std()), 3),
        "total_return_pct": round(float((equity.iloc[-1] - 1) * 100), 2),
        "max_drawdown_pct": round(float((equity / equity.cummax() - 1).min() * 100), 2),
        "months_ge_20pct": int((series >= 20).sum()),
        "months_le_neg10pct": int((series <= -10).sum()),
    }


def _portfolio(trades: list[Any], window: list[str], slug: str) -> dict[str, Any]:
    """两仓等权的组合口径，与 `sanyuan-tail-v1` / `qianlong-close-v3` 声明值同源。"""
    try:
        payload = analyze_portfolio(
            trades,
            config=PortfolioResearchConfig(
                initial_capital=200_000.0, max_positions=2, period="month"
            ),
            trading_dates=window,
            strategy_slug=slug,
        ).to_dict()
    except Exception as exc:  # noqa: BLE001
        return {"error": f"{type(exc).__name__}: {exc}"}
    # to_dict() 的组合指标在 metrics 下，不在顶层（顶层是 contract_version /
    # config / allocations / daily / segments 这些）。
    metrics = payload.get("metrics") or {}
    out = {"accepted_trades": payload.get("accepted_trades")}
    out.update(metrics)
    return out


def run(args: argparse.Namespace) -> dict[str, Any]:
    db_path = Path(args.db).expanduser().resolve()
    rule = PoolRule(pct20_top_n=int(args.pct20_top_n))
    with _read_only_connection(db_path) as conn:
        days = _load_days(conn)
    load_start = days[max(0, days.index(args.start) - WARMUP_BARS)]
    with _read_only_connection(db_path) as conn:
        codes, _ = _load_universe(
            conn, as_of=args.end, boards={"main", "chi_next", "star"}
        )
        qfq, raw = _load_panels(
            conn, load_start=load_start, load_end=args.end, dates=days, codes=codes
        )
    ctx = build_pool_and_triggers(qfq, raw, rule)
    dims = ctx["dims"]
    window = [day for day in qfq["close"].index if args.start <= day <= args.end]
    months = sorted({day[:7] for day in window})
    split_date = window[len(window) // 2]
    price_panels = {field: qfq[field] for field in PRICE_FIELDS}
    price_panels["volume"] = raw["volume"]
    config = BacktestConfig(
        hold_days=1, stop_loss_pct=None, take_profit_pct=None, benchmark=None
    )

    rows: list[dict[str, Any]] = []
    for ma_window in (5, 10):
        trigger = ctx["triggers"][ma_window]
        for combo_name, conds in COMBOS.items():
            mask = trigger.copy()
            for _, fn in conds:
                mask = mask & fn(dims).fillna(False)
            scoped = pd.DataFrame(False, index=mask.index, columns=mask.columns)
            scoped.loc[window] = mask.loc[window].fillna(False)
            total = int(scoped.loc[window].to_numpy().sum())
            if total == 0:
                continue
            result = run_backtest(
                scoped,
                price_panels,
                entry_timing="next_open",
                config=config,
                strategy_slug=f"dragon-combo:MA{ma_window}:{combo_name}",
            )
            trades = result.to_frame()
            trades = trades[trades["exit_reason"] != "data_end"]
            net = trades["net_return_pct"].astype(float)
            wins, losses = net[net > 0], net[net <= 0]
            avg_win = float(wins.mean()) if not wins.empty else None
            avg_loss = float(losses.mean()) if not losses.empty else None
            payoff = (
                None if avg_win is None or not avg_loss else round(avg_win / abs(avg_loss), 3)
            )
            early = trades[trades["signal_date"] < split_date]["net_return_pct"]
            late = trades[trades["signal_date"] >= split_date]["net_return_pct"]
            rows.append(
                {
                    "ma": f"MA{ma_window}",
                    "combo": combo_name,
                    "conditions": [name for name, _ in conds],
                    "signals": total,
                    "trades": int(len(trades)),
                    "win_rate_pct": round(float((net > 0).mean() * 100), 2),
                    "payoff_ratio": payoff,
                    "avg_net_pct": round(float(net.mean()), 3),
                    "median_net_pct": round(float(net.median()), 3),
                    "early_n": int(len(early)),
                    "early_avg_pct": round(float(early.mean()), 3) if len(early) else None,
                    "late_n": int(len(late)),
                    "late_avg_pct": round(float(late.mean()), 3) if len(late) else None,
                    "stable_positive": bool(
                        len(early) >= 30
                        and len(late) >= 30
                        and float(early.mean()) > 0
                        and float(late.mean()) > 0
                    ),
                    "monthly": {
                        f"{int(size * 100)}%仓": _monthly(trades, months, size)
                        for size in POSITION_SIZES
                    },
                    # 与仓内现役战法可比的组合口径：两仓等权，同 analyze_portfolio。
                    # 三源/潜龙声明的 portfolio_return_pct 走的就是这条路径，
                    # 不这样算就是拿「单笔 30% 仓」跟「两仓各 50%」比，没有意义。
                    "portfolio_2slot": _portfolio(
                        result.trades, window, f"MA{ma_window}:{combo_name}"
                    ),
                }
            )

    summary = {
        "purpose": "组合条件的月度净收益分布（真实按月聚合，非由每笔均值外推）",
        "discipline": [
            "只用跨均线重复出现的模式，阈值取宽档，不用单格最优的窄阈值",
            "月度收益按信号月真实聚合；空窗月记 0，不只统计有信号的月份",
            "月收益 = 该月各笔净收益率之和 × 单笔仓位（算术叠加，非复利）",
        ],
        "pool_rule": asdict(rule),
        "exit": asdict(config),
        "entry": "next_open（严格口径；触发用当日 LOW，close 档过不了前视审计）",
        "data": {
            "range": [args.start, args.end],
            "trading_days": len(window),
            "months": len(months),
            "codes": len(codes),
            "split_date": split_date,
        },
        "rows": rows,
    }
    output = Path(args.output).expanduser().resolve()
    output.mkdir(parents=True, exist_ok=True)
    (output / "summary.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2, default=str), encoding="utf-8"
    )
    print(_render(summary))
    return summary


def _render(summary: dict[str, Any]) -> str:
    def f(v: Any, nd: int = 2) -> str:
        return "-" if v is None else f"{float(v):.{nd}f}"

    meta = summary["data"]
    lines = [
        f"区间 {meta['range'][0]}..{meta['range'][1]}  {meta['trading_days']} 交易日 / "
        f"{meta['months']} 个自然月  入池前 {summary['pool_rule']['pct20_top_n']} 只",
        "口径：次开买 · 持1日 · 无止损止盈",
        "",
        f"{'均线':<5}{'组合':<20}{'信号':>6}{'笔数':>6}{'胜率%':>7}{'盈亏比':>7}"
        f"{'均净%':>8}{'中位%':>8}{'前段':>7}{'后段':>7}",
    ]
    for row in summary["rows"]:
        mark = "  [两段皆正]" if row["stable_positive"] else ""
        lines.append(
            f"{row['ma']:<5}{row['combo']:<20}{row['signals']:>6}{row['trades']:>6}"
            f"{f(row['win_rate_pct']):>7}{f(row['payoff_ratio'], 3):>7}"
            f"{f(row['avg_net_pct'], 3):>8}{f(row['median_net_pct'], 3):>8}"
            f"{f(row['early_avg_pct'], 2):>7}{f(row['late_avg_pct'], 2):>7}{mark}"
        )

    for size_key in (f"{int(s * 100)}%仓" for s in POSITION_SIZES):
        lines += [
            "",
            f"===== 月度分布（单笔 {size_key}，共 {meta['months']} 个月，空窗月记 0）=====",
            f"{'均线':<5}{'组合':<20}{'有信号月':>9}{'月均信号':>9}{'月均%':>8}"
            f"{'月中位%':>9}{'月胜率%':>9}{'最好月%':>9}{'最差月%':>9}"
            f"{'月标准差':>9}{'全期%':>9}{'最大回撤%':>10}{'≥20%的月':>9}",
        ]
        for row in summary["rows"]:
            m = row["monthly"][size_key]
            if not m.get("active_months"):
                continue
            lines.append(
                f"{row['ma']:<5}{row['combo']:<20}{m['active_months']:>9}"
                f"{f(m['signals_per_month']):>9}{f(m['monthly_mean_pct'], 2):>8}"
                f"{f(m['monthly_median_pct'], 2):>9}{f(m['monthly_win_rate_pct']):>9}"
                f"{f(m['best_month_pct']):>9}{f(m['worst_month_pct']):>9}"
                f"{f(m['monthly_std_pct'], 2):>9}{f(m['total_return_pct']):>9}"
                f"{f(m['max_drawdown_pct']):>10}{m['months_ge_20pct']:>9}"
            )

    lines += [
        "",
        "===== 组合口径（两仓等权，与三源/潜龙声明值同源的 analyze_portfolio）=====",
        f"{'均线':<5}{'组合':<20}{'组合收益%':>10}{'最大回撤%':>10}{'占用率%':>9}"
        f"{'组合笔数':>9}{'组合胜率%':>10}",
    ]
    for row in summary["rows"]:
        p = row.get("portfolio_2slot") or {}
        if p.get("error"):
            lines.append(f"{row['ma']:<5}{row['combo']:<20}  {p['error']}")
            continue
        ret = p.get("portfolio_return_pct", p.get("total_return_pct"))
        lines.append(
            f"{row['ma']:<5}{row['combo']:<20}{f(ret):>10}"
            f"{f(p.get('max_drawdown_pct')):>10}{f(p.get('occupancy_pct')):>9}"
            f"{f(p.get('portfolio_trades'), 0):>9}{f(p.get('portfolio_win_rate')):>10}"
        )
    return "\n".join(lines)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--db", default=os.environ.get("PALACE_MARKET_DB") or str(DEFAULT_DB))
    parser.add_argument("--start", default="2024-01-02")
    parser.add_argument("--end", default="2026-07-31")
    parser.add_argument("--pct20-top-n", type=int, default=10)
    parser.add_argument(
        "--output", default="output/dragon-combo-monthly-2024-01-02_2026-07-31"
    )
    return parser


if __name__ == "__main__":
    run(build_parser().parse_args())
