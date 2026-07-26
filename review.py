#!/usr/bin/env python
"""复盘命令行入口——基于真实账本与真实行情，不依赖任何 LLM。

    python review.py equity                  真实资金曲线与绩效指标
    python review.py trips                   持仓周期归因（MAE/MFE/持有天数）
    python review.py candidates              候选池 T+N 验证（含"当初否决的票涨了多少"）
    python review.py plans                   预案兑现率
    python review.py positions --date 2026-06-30   回放某天的持仓

这里回答的问题和 `market.py backtest` 不同：那个问"这套战法本身有没有
alpha"，这里问"我自己做得怎么样"。
"""
from __future__ import annotations

import argparse
import json
import sys

from pathlib import Path

from src.market.store import DEFAULT_DB as MARKET_DB, MarketStore
from src.palace import PalaceStore
from src.review import (
    HORIZONS,
    attribute_round_trips,
    build_equity_curve,
    evaluate_candidates,
    evaluate_plans,
    positions_as_of,
    round_trips,
    summarize_candidates,
    summarize_round_trips,
)

DISCLAIMER = "本工具仅用于信息整理与方法论辅助，输出不构成任何投资建议。"

#: 账本默认路径。PalaceStore 不像 MarketStore 那样接受 None，要显式给。
PALACE_DB = Path(__file__).resolve().parent / ".palace" / "qianlong.db"


def _stores(args: argparse.Namespace) -> tuple[PalaceStore, MarketStore]:
    return PalaceStore(args.palace_db), MarketStore(args.market_db)


def _palace(args: argparse.Namespace) -> PalaceStore:
    return PalaceStore(args.palace_db)


def _money(value: float | None) -> str:
    if value is None:
        return "—"
    return f"{value:,.2f}"


def _pct(value: float | None, *, signed: bool = True) -> str:
    if value is None:
        return "—"
    prefix = "+" if signed and value >= 0 else ""
    return f"{prefix}{value:.2f}%"


def cmd_equity(args: argparse.Namespace) -> int:
    palace, market = _stores(args)
    try:
        curve = build_equity_curve(
            palace, market, start=args.start, end=args.end,
            benchmarks=tuple(c.strip() for c in args.benchmarks.split(",") if c.strip()),
        )
    finally:
        palace.close()
        market.close()

    if not curve.points:
        print(curve.note or "没有可用数据", file=sys.stderr)
        return 1

    metrics = curve.metrics
    print(f"区间       {metrics.get('start_date')} ~ {metrics.get('end_date')}"
          f"（{metrics.get('days')} 个交易日）")
    print(f"期初/期末  {_money(metrics.get('start_equity'))} → {_money(metrics.get('end_equity'))}")
    print(f"总收益     {_pct(metrics.get('total_return_pct'))}")
    if metrics.get("annualized_pct") is not None:
        print(f"年化       {_pct(metrics['annualized_pct'])}")
    print(f"最大回撤   {_pct(metrics.get('max_drawdown_pct'))}")
    for key, label in (("sharpe", "夏普"), ("calmar", "卡玛")):
        if metrics.get(key) is not None:
            print(f"{label}       {metrics[key]}")
    print(f"已实现     {_money(metrics.get('realized_pnl'))}")
    print(f"浮动盈亏   {_money(metrics.get('floating_pnl'))}")
    for key, value in metrics.items():
        if key.startswith("alpha_vs_"):
            print(f"超额({key[9:-4]})  {_pct(value)}")
    print(f"\n口径       {curve.confidence}")
    if curve.note:
        print(f"           {curve.note}")
    if metrics.get("caution"):
        print(f"⚠ {metrics['caution']}")

    if args.json:
        print(json.dumps(curve.to_dict(), ensure_ascii=False, indent=2))
    elif args.points:
        print("\n日期         持仓市值        总资产      浮动盈亏     回撤")
        for point in curve.points[-args.points :]:
            print(f"{point.trade_date}  {_money(point.holding_value):>12}"
                  f"  {_money(point.total_equity):>12}  {_money(point.floating_pnl):>10}"
                  f"  {point.drawdown_pct:>7.2f}%")
    print()
    print(DISCLAIMER)
    return 0


def cmd_trips(args: argparse.Namespace) -> int:
    palace, market = _stores(args)
    try:
        trips = attribute_round_trips(round_trips(palace, code=args.code), market)
        summary = summarize_round_trips(trips)
    finally:
        palace.close()
        market.close()

    if not trips:
        print("账本里还没有持仓记录。")
        return 0

    print("代码    区间                      峰值股数    均价      收益      MAE      MFE   持有")
    for trip in trips:
        span = f"{trip.opened_on}~{trip.closed_on or '至今'}"
        print(f"{trip.code}  {span:<24} {trip.peak_shares:>8}  {trip.avg_cost:>8.3f}"
              f"  {_pct(trip.return_pct):>8}  {_pct(trip.mae_pct):>7}  {_pct(trip.mfe_pct):>7}"
              f"  {trip.hold_days if trip.hold_days is not None else '—':>4}")

    print(f"\n已了结 {summary['closed']} 段 / 持有中 {summary['open']} 段"
          f"   已实现 {_money(summary.get('realized_pnl'))}")
    for key, label in (
        ("win_rate", "胜率"), ("avg_return_pct", "平均收益"), ("profit_factor", "盈亏比"),
        ("avg_mae_pct", "平均MAE"), ("avg_mfe_pct", "平均MFE"), ("avg_hold_days", "平均持有"),
    ):
        if summary.get(key) is not None:
            print(f"  {label}: {summary[key]}")
    if summary.get("winner_avg_mae_pct") is not None:
        print(f"  赢家平均MAE {summary['winner_avg_mae_pct']}% vs 输家 {summary['loser_avg_mae_pct']}%")
    if summary.get("hint"):
        print(f"\n→ {summary['hint']}")
    if summary.get("caution"):
        print(f"⚠ {summary['caution']}")
    if args.json:
        print(json.dumps({"trips": [t.to_dict() for t in trips], "summary": summary},
                         ensure_ascii=False, indent=2))
    print()
    print(DISCLAIMER)
    return 0


def cmd_candidates(args: argparse.Namespace) -> int:
    palace, market = _stores(args)
    try:
        outcomes = evaluate_candidates(palace, market, limit=args.limit)
        summary = summarize_candidates(outcomes)
    finally:
        palace.close()
        market.close()

    if not outcomes:
        print("候选池还没有记录。")
        return 0

    header = "日期        代码    裁决        基准价" + "".join(f"    T+{h:<4}" for h in HORIZONS)
    print(header)
    for outcome in outcomes[: args.rows]:
        cells = "".join(f"  {_pct(outcome.returns.get(h)):>7}" for h in HORIZONS)
        base = f"{outcome.base_close:.2f}" if outcome.base_close else "—"
        print(f"{outcome.base_date}  {outcome.code}  {outcome.decision:<10} {base:>7}{cells}"
              f"  {outcome.note}")

    print(f"\n合计 {summary['total']} 条，可评估 {summary['evaluated']} 条")
    for name, stats in summary["by_decision"].items():
        line = f"  [{name}] {stats['count']} 条"
        for horizon in HORIZONS:
            item = stats.get(f"t{horizon}")
            if item:
                line += f"  T+{horizon} 均值{item['avg']:+.2f}% 胜率{item['win_rate']:.0f}%"
        print(line)

    if summary["missed_winners"]:
        print("\n当初否决、事后大涨的（改进规则最直接的线索）：")
        for item in summary["missed_winners"]:
            print(f"  {item['base_date']}  {item['code']} {item['name']}"
                  f"  [{item['decision']}]  T+20 {item['return_t20']:+.2f}%"
                  f"  区间最高 {item['max_favorable_pct']:+.2f}%")

    if summary.get("score_buckets"):
        print("\n评分分箱（不单调说明打分没有区分度）：")
        for bucket in summary["score_buckets"]:
            avg = f"{bucket['avg_t20']:+.2f}%" if bucket["avg_t20"] is not None else "—"
            print(f"  {bucket['range']:>8}  {bucket['count']:>3} 条  T+20 均值 {avg}")

    if args.json:
        print(json.dumps({"outcomes": [o.to_dict() for o in outcomes], "summary": summary},
                         ensure_ascii=False, indent=2))
    print()
    print(DISCLAIMER)
    return 0


def cmd_plans(args: argparse.Namespace) -> int:
    palace, market = _stores(args)
    try:
        results = evaluate_plans(palace, market)
    finally:
        palace.close()
        market.close()

    if not results:
        print("还没有预案记录。")
        return 0
    labels = {
        "observing": "观察中", "stop_hit": "触发止损", "target_hit": "触发止盈",
        "stop_first": "先止损", "target_first": "先止盈", "no_data": "无行情",
    }
    print("日期        代码    状态      止损     止盈    标题")
    for item in results:
        print(f"{item['occurred_on']}  {item['code']}  {labels.get(item['status_final'], item['status_final']):<8}"
              f"  {item['stop_price'] or '—':>6}  {item['target_price'] or '—':>6}  {item['title']}")
    triggered = sum(1 for r in results if r["status_final"] not in ("observing", "no_data"))
    print(f"\n共 {len(results)} 条，已触发 {triggered} 条，兑现率 {triggered / len(results) * 100:.0f}%")
    if args.json:
        print(json.dumps(results, ensure_ascii=False, indent=2))
    print()
    print(DISCLAIMER)
    return 0


def cmd_positions(args: argparse.Namespace) -> int:
    palace = _palace(args)
    try:
        held = positions_as_of(palace, args.date)
    finally:
        palace.close()
    label = args.date or "当前"
    if not held:
        print(f"{label} 无持仓。")
        return 0
    print(f"{label} 持仓 {len(held)} 只：")
    print("代码    名称            股数        成本      市值成本")
    for item in held:
        print(f"{item.code}  {item.name:<12}  {item.shares:>8}  {item.cost:>8.3f}"
              f"  {_money(item.cost_value):>12}")
    print(f"\n合计成本 {_money(sum(i.cost_value for i in held))}")
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="潜龙复盘：真实账本 + 真实行情，不依赖 AI",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    parser.add_argument("--palace-db", default=str(PALACE_DB), help="账本路径")
    parser.add_argument("--market-db", default=str(MARKET_DB), help="行情库路径")
    sub = parser.add_subparsers(dest="command", required=True)

    equity = sub.add_parser("equity", help="真实资金曲线")
    equity.add_argument("--start", default=None)
    equity.add_argument("--end", default=None)
    equity.add_argument("--benchmarks", default="000300", help="逗号分隔的基准指数")
    equity.add_argument("--points", type=int, default=0, help="打印最近 N 个交易日明细")
    equity.add_argument("--json", action="store_true")
    equity.set_defaults(func=cmd_equity)

    trips = sub.add_parser("trips", help="持仓周期归因")
    trips.add_argument("--code", default=None)
    trips.add_argument("--json", action="store_true")
    trips.set_defaults(func=cmd_trips)

    cands = sub.add_parser("candidates", help="候选池 T+N 验证")
    cands.add_argument("--limit", type=int, default=500, help="评估最近 N 条候选")
    cands.add_argument("--rows", type=int, default=30, help="明细打印行数")
    cands.add_argument("--json", action="store_true")
    cands.set_defaults(func=cmd_candidates)

    plans = sub.add_parser("plans", help="预案兑现率")
    plans.add_argument("--json", action="store_true")
    plans.set_defaults(func=cmd_plans)

    pos = sub.add_parser("positions", help="回放某天的持仓")
    pos.add_argument("--date", default=None, help="YYYY-MM-DD，默认当前")
    pos.set_defaults(func=cmd_positions)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    return int(args.func(args))


if __name__ == "__main__":
    raise SystemExit(main())
