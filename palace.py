"""潜龙记忆宫殿 CLI：仓位、候选、预案、执行与复盘的单一入口。"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys
from typing import Sequence

from src.palace import PalaceError, PalaceStore


HERE = Path(__file__).resolve().parent
DEFAULT_DB = HERE / ".palace" / "qianlong.db"


def _write_or_print(content: str, output: str | None) -> None:
    if output:
        path = Path(output)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")
        print(f"已写入：{path.resolve()}")
    else:
        print(content, end="")


def _parse_evidence(items: list[str] | None) -> dict[str, str]:
    return {f"evidence_{index}": value for index, value in enumerate(items or [], start=1)}


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="潜龙记忆宫殿：可追溯、可复盘、可量化的本地研究账本（不含自动交易）。",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    parser.add_argument("--db", default=str(DEFAULT_DB), help="SQLite 账本路径")
    commands = parser.add_subparsers(dest="command", required=True)

    commands.add_parser("init", help="初始化账本")

    stock = commands.add_parser("stock", help="登记或更新股票主档")
    stock.add_argument("code")
    stock.add_argument("name")
    stock.add_argument("--tag", action="append", default=[], help="可重复使用，例如 --tag AI")
    stock.add_argument("--note", default="")

    for action, label in (("buy", "记录买入"), ("sell", "记录卖出")):
        trade = commands.add_parser(action, help=label)
        trade.add_argument("code")
        trade.add_argument("shares", type=int)
        trade.add_argument("price", type=float)
        trade.add_argument("--name", default="", help="买入时可补充名称")
        trade.add_argument("--date", default=None)
        trade.add_argument("--reason", default="")
        trade.add_argument("--source", default="manual")
        trade.add_argument("--correlation-id", default="", help="关联候选/计划/外部报告 ID")

    cashflow = commands.add_parser("cashflow", help="记录资金转入/取出；正数转入，负数取出")
    cashflow.add_argument("amount", type=float)
    cashflow.add_argument("--date", default=None)
    cashflow.add_argument("--note", default="")

    snapshot = commands.add_parser("snapshot", help="记录账户总资产快照")
    snapshot.add_argument("total_assets", type=float)
    snapshot.add_argument("--cash", type=float, default=None)
    snapshot.add_argument("--date", default=None)
    snapshot.add_argument("--note", default="")

    candidate = commands.add_parser("candidate", help="归档一个潜龙候选裁决")
    candidate.add_argument("code")
    candidate.add_argument("--name", default="")
    candidate.add_argument("--decision", required=True, help="高确定性/值得做/落选/空仓等")
    candidate.add_argument("--reason", required=True)
    candidate.add_argument("--score", type=float, default=None)
    candidate.add_argument("--timing", default="", help="W/D-low/D-flat/D-high")
    candidate.add_argument("--pool", default="", help="同一批候选共享 pool ID")
    candidate.add_argument("--date", default=None)
    candidate.add_argument("--rule-version", default="qianlong-v1")
    candidate.add_argument("--evidence", action="append", default=[], help="可重复的事实或证据链接")

    plan = commands.add_parser("plan", help="归档一条作战预案")
    plan.add_argument("code")
    plan.add_argument("--title", required=True)
    plan.add_argument("--scenario", required=True)
    plan.add_argument("--entry-zone", default="")
    plan.add_argument("--stop", type=float, default=None)
    plan.add_argument("--target", type=float, default=None)
    plan.add_argument("--layers", type=float, default=None)
    plan.add_argument("--invalidation", default="")
    plan.add_argument("--date", default=None)
    plan.add_argument("--rule-version", default="qianlong-v1")
    plan.add_argument("--note", default="")
    plan.add_argument("--supersedes", default=None)

    review = commands.add_parser("review", help="记录候选、预案或交易的结果复盘")
    review.add_argument("entity_type", choices=["plan", "candidate", "trade"])
    review.add_argument("entity_id")
    review.add_argument("--outcome", required=True)
    review.add_argument("--return-pct", type=float, default=None)
    review.add_argument("--mfe", type=float, default=None, help="最大有利波动百分比")
    review.add_argument("--mae", type=float, default=None, help="最大不利波动百分比")
    review.add_argument("--lesson", default="")
    review.add_argument("--next-rule", default="")
    review.add_argument("--strategy-tag", default="qianlong")
    review.add_argument("--date", default=None)

    dashboard = commands.add_parser("dashboard", help="生成日常经营看板")
    dashboard.add_argument("--date", default=None)
    dashboard.add_argument("--output", default=None)

    timeline = commands.add_parser("timeline", help="输出单只股票的完整追溯时间线")
    timeline.add_argument("code")
    timeline.add_argument("--output", default=None)

    scorecard = commands.add_parser("scorecard", help="输出已实现交易与复盘样本统计")
    scorecard.add_argument("--output", default=None)

    importer = commands.add_parser("import-skill-memory", help="从潜龙技能 state.json 导入起始快照（仅限空账本）")
    importer.add_argument("--state", required=True, help="qianlong-position-review/memory/state.json")
    importer.add_argument("--source", default="qianlong-skill-memory")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        with PalaceStore(args.db) as store:
            if args.command == "init":
                print(f"账本已就绪：{Path(args.db).resolve()}")
            elif args.command == "stock":
                store.register_stock(args.code, args.name, args.tag, args.note)
                print(f"已登记：{args.code} {args.name}")
            elif args.command in {"buy", "sell"}:
                event = store.record_trade(
                    action="BUY" if args.command == "buy" else "SELL",
                    code=args.code,
                    shares=args.shares,
                    price=args.price,
                    name=args.name,
                    occurred_on=args.date,
                    reason=args.reason,
                    source=args.source,
                    correlation_id=args.correlation_id,
                )
                print(
                    f"已记 {event['id']}：{event['action']} {event['code']} {event['shares_after']}股"
                    f"｜余票成本 {event['cost_after']:.3f}｜本笔已实现 {event['realized_pnl']:+.2f} 元"
                )
            elif args.command == "cashflow":
                event_id = store.record_account_event(kind="CASHFLOW", amount=args.amount, occurred_on=args.date, note=args.note)
                print(f"已记 {event_id}：资金进出 {args.amount:+.2f} 元（不计入已实现盈亏）")
            elif args.command == "snapshot":
                snapshot_id = store.record_snapshot(
                    total_assets=args.total_assets, cash=args.cash, occurred_on=args.date, note=args.note
                )
                print(f"已记 {snapshot_id}：总资产 {args.total_assets:,.2f} 元")
            elif args.command == "candidate":
                candidate_id = store.record_candidate(
                    code=args.code, name=args.name, decision=args.decision, reason=args.reason, score=args.score,
                    timing=args.timing, pool_id=args.pool, occurred_on=args.date, rule_version=args.rule_version,
                    evidence=_parse_evidence(args.evidence),
                )
                print(f"已记 {candidate_id}：候选 {args.code}｜{args.decision}")
            elif args.command == "plan":
                plan_id = store.record_plan(
                    code=args.code, title=args.title, scenario=args.scenario, entry_zone=args.entry_zone,
                    stop_price=args.stop, target_price=args.target, layers=args.layers, invalidation=args.invalidation,
                    occurred_on=args.date, rule_version=args.rule_version, note=args.note, supersedes_id=args.supersedes,
                )
                print(f"已记 {plan_id}：{args.code}｜{args.title}")
            elif args.command == "review":
                review_id = store.record_review(
                    entity_type=args.entity_type, entity_id=args.entity_id, outcome=args.outcome, return_pct=args.return_pct,
                    max_favorable_pct=args.mfe, max_adverse_pct=args.mae, lesson=args.lesson, next_rule=args.next_rule,
                    strategy_tag=args.strategy_tag, reviewed_on=args.date,
                )
                print(f"已记 {review_id}：{args.entity_type} {args.entity_id} 复盘完成")
            elif args.command == "dashboard":
                _write_or_print(store.dashboard_markdown(args.date), args.output)
            elif args.command == "timeline":
                _write_or_print(store.timeline_markdown(args.code), args.output)
            elif args.command == "scorecard":
                _write_or_print(json.dumps(store.scorecard(), ensure_ascii=False, indent=2) + "\n", args.output)
            elif args.command == "import-skill-memory":
                result = store.import_qianlong_state(args.state, args.source)
                print(json.dumps(result, ensure_ascii=False, indent=2))
            else:
                raise PalaceError(f"未知命令：{args.command}")
    except PalaceError as exc:
        print(f"[账本错误] {exc}", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
