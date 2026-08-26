"""潜龙记忆宫殿 CLI：候选、预案、复盘与追溯的单一入口（不含持仓与成交）。"""
from __future__ import annotations

import argparse
from pathlib import Path
import sys
from typing import Sequence

from src.ledger import PalaceError, PalaceStore
from src.shared.paths import ensure_data_dir, palace_db


HERE = Path(__file__).resolve().parent
DEFAULT_DB = palace_db()


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
    ensure_data_dir()
    parser = argparse.ArgumentParser(
        description="潜龙记忆宫殿：可追溯、可复盘、可量化的本地研究账本（不记录持仓与成交）。",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    parser.add_argument("--db", default=str(palace_db()), help="SQLite 账本路径（默认 data/palace.db）")
    commands = parser.add_subparsers(dest="command", required=True)

    commands.add_parser("init", help="初始化账本")

    stock = commands.add_parser("stock", help="登记或更新股票主档")
    stock.add_argument("code")
    stock.add_argument("name")
    stock.add_argument("--tag", action="append", default=[], help="可重复使用，例如 --tag AI")
    stock.add_argument("--note", default="")

    candidate = commands.add_parser("candidate", help="归档一个潜龙候选裁决")
    candidate.add_argument("code")
    candidate.add_argument("--name", default="")
    candidate.add_argument("--decision", required=True, help="精选/落选/观察")
    candidate.add_argument("--reason", required=True)
    candidate.add_argument("--score", type=float, default=None)
    candidate.add_argument("--timing", default="", help="尾盘/低吸/平开/高开回踩/观望/禁尾盘")
    candidate.add_argument("--pool", default="", help="同一批候选共享 pool ID")
    candidate.add_argument("--date", default=None)
    candidate.add_argument("--rule-version", default="潜龙")
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
    plan.add_argument("--rule-version", default="潜龙")
    plan.add_argument("--note", default="")
    plan.add_argument("--supersedes", default=None)

    review = commands.add_parser("review", help="记录候选或预案的结果复盘")
    review.add_argument("entity_type", choices=["plan", "candidate"])
    review.add_argument("entity_id")
    review.add_argument("--outcome", required=True)
    review.add_argument("--return-pct", type=float, default=None)
    review.add_argument("--mfe", type=float, default=None, help="最大有利波动百分比")
    review.add_argument("--mae", type=float, default=None, help="最大不利波动百分比")
    review.add_argument("--lesson", default="")
    review.add_argument("--next-rule", default="")
    review.add_argument("--strategy-tag", default="qianlong")
    review.add_argument("--date", default=None)

    timeline = commands.add_parser("timeline", help="输出单只股票的完整追溯时间线")
    timeline.add_argument("code")
    timeline.add_argument("--output", default=None)

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
            elif args.command == "timeline":
                _write_or_print(store.timeline_markdown(args.code), args.output)
            else:
                raise PalaceError(f"未知命令：{args.command}")
    except PalaceError as exc:
        print(f"[账本错误] {exc}", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
