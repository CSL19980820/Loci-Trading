#!/usr/bin/env python
"""复盘命令行入口——基于候选池与真实行情，不依赖任何 LLM。

    python review.py candidates   候选池 T+N 验证（含"当初否决的票涨了多少"）
    python review.py plans          预案兑现率

这里回答的问题和 `market.py backtest` 不同：那个问"这套战法本身有没有
alpha"，这里问"我挑出来的票后来走成什么样"。
"""
from __future__ import annotations

import argparse
import json
import sys

from src.market import DEFAULT_DB, MarketStore
from src.ledger import PalaceStore
from src.shared.paths import ensure_data_dir, palace_db
from src.review import (
    HORIZONS,
    evaluate_candidates,
    evaluate_plans,
    summarize_candidates,
)

DISCLAIMER = "本工具仅用于信息整理与方法论辅助，输出不构成任何投资建议。"

#: 账本默认路径：与 App / API 一致，走 data/palace.db
PALACE_DB = palace_db()


def _stores(args: argparse.Namespace) -> tuple[PalaceStore, MarketStore]:
    return PalaceStore(args.palace_db), MarketStore(args.market_db)


def _pct(value: float | None, *, signed: bool = True) -> str:
    if value is None:
        return "—"
    prefix = "+" if signed and value >= 0 else ""
    return f"{prefix}{value:.2f}%"


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


def build_parser() -> argparse.ArgumentParser:
    ensure_data_dir()
    parser = argparse.ArgumentParser(
        description="潜龙复盘：候选池 + 真实行情，不依赖 AI",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    parser.add_argument("--palace-db", default=str(palace_db()), help="账本路径（默认 data/palace.db）")
    parser.add_argument("--market-db", default=str(DEFAULT_DB), help="行情库路径")
    sub = parser.add_subparsers(dest="command", required=True)

    cands = sub.add_parser("candidates", help="候选池 T+N 验证")
    cands.add_argument("--limit", type=int, default=500, help="评估最近 N 条候选")
    cands.add_argument("--rows", type=int, default=30, help="明细打印行数")
    cands.add_argument("--json", action="store_true")
    cands.set_defaults(func=cmd_candidates)

    plans = sub.add_parser("plans", help="预案兑现率")
    plans.add_argument("--json", action="store_true")
    plans.set_defaults(func=cmd_plans)

    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    return int(args.func(args))


if __name__ == "__main__":
    raise SystemExit(main())
