#!/usr/bin/env python
"""行情仓与选股的命令行入口。

    python market.py instruments                    刷新证券列表
    python market.py sync --limit 500               同步日线（断点续跑）
    python market.py sync --codes 600519,000001     只同步指定标的
    python market.py coverage                       看仓库现状
    python market.py strategies                     列出已注册战法
    python market.py screen qianlong-close          跑一次全市场选股
    python market.py rescore --since 2026-09-01     按当前评分口径重算已入库三源/杨氏候选（默认预览）
    python market.py bench                          面板加载与选股性能实测

设计上刻意让每个子命令都能单独重跑：同步有 watermark 断点，选股是纯函数，
中途失败重来一次就好，不需要先清理什么状态。
"""
from __future__ import annotations

import argparse
import json
import logging
from pathlib import Path
import sys
import time

from src.market import (
    DEFAULT_DB,
    MarketStore,
    MarketWriteBusy,
    market_write_lock,
    reclaim_market_db,
    sync_instruments,
    sync_quotes,
)
from src.market.application.storage_governance import (
    StoragePolicy,
    report_text,
    run_storage_maintenance,
    storage_check,
    storage_report,
)
from cli.market_intraday import (
    cmd_intraday_capture,
    cmd_intraday_prune,
 cmd_intraday_status,
)
from src.shared.paths import palace_db
from src.strategy import describe_all, get, screen

DISCLAIMER = "本工具仅用于信息整理与方法论辅助，输出不构成任何投资建议。股市有风险，入市需谨慎。"


def _store(args: argparse.Namespace) -> MarketStore:
    return MarketStore(args.db)


def cmd_instruments(args: argparse.Namespace) -> int:
    with _store(args) as store:
        count = sync_instruments(store)
        stocks = len(store.list_instruments(instrument_type="STOCK"))
        index = len(store.list_instruments(instrument_type="INDEX"))
    print(f"证券列表已更新：{count} 条（个股 {stocks}，指数 {index}）")
    return 0


def cmd_sync(args: argparse.Namespace) -> int:
    with _store(args) as store:
        db_path = store.db_path
        if args.codes:
            codes = [code.strip() for code in args.codes.split(",") if code.strip()]
            types: dict[str, str] = {}
        else:
            instruments = store.list_instruments()
            if not instruments:
                print("证券列表为空，请先执行：python market.py instruments", file=sys.stderr)
                return 2
            codes = [item["code"] for item in instruments]
            types = {item["code"]: item["instrument_type"] for item in instruments}
        if args.limit:
            codes = codes[: args.limit]

    total = len(codes)
    last_report = [0.0]

    def progress(done: int, count: int, code: str) -> None:
        now = time.monotonic()
        if now - last_report[0] >= 2.0 or done == count:
            last_report[0] = now
            print(f"\r  进度 {done}/{count}", end="", flush=True)

    print(f"开始同步 {total} 只证券（并发 {args.workers}，最小间隔 {args.interval}s）")
    # README 宣称「四入口共用同一把闸门」，可这里原先直调 sync_quotes，等于第四个
    # 入口根本不在闸门里：CLI 是独立进程，线程闸门 ops.market_gate 够不着它，能拦住
    # 的只有跨进程的 market_write_lock。于是「桌面端正在同步」时跑一次本命令就是双写
    # market.db，SQLite 直接顶成 locked。label 与 ops 侧同形（sync:<mode>），
    # 报错文案和运维诊断里能一眼认出占锁的是谁。
    lock_label = "sync:codes" if args.codes else "sync:full"
    try:
        with market_write_lock(db_path, label=lock_label):
            report = sync_quotes(
                lambda: MarketStore(args.db),
                codes,
                instrument_types=types if not args.codes else None,
                workers=args.workers,
                min_interval=args.interval,
                force=args.force,
                with_factors=not args.no_factors,
                progress=progress,
            )
    except MarketWriteBusy as exc:
        print(file=sys.stderr)
        print(f"本次同步没有开始：{exc}", file=sys.stderr)
        print(
            "行情库同一时刻只允许一个写入者，桌面端 Loci、定时调度和这条命令共用同一把锁。"
            "等对方跑完再执行本命令即可；若确认它已经卡死，"
            "到桌面端「运维 → 执行历史」把那条同步停掉。",
            file=sys.stderr,
        )
        return 3
    print()
    print(report.summary())
    if report.failures:
        print(f"失败 {len(report.failures)} 只，前 5 个：")
        for code, message in report.failures[:5]:
            print(f"  {code}: {message[:110]}")
        print("重试方式：python market.py sync --codes " + ",".join(c for c, _ in report.failures[:20]))
    return 0 if not report.failures else 1


def cmd_coverage(args: argparse.Namespace) -> int:
    with _store(args) as store:
        data = store.coverage()
    print(f"库文件      {data['db_path']}  {data['db_bytes'] / 1e6:.1f} MB")
    print(f"证券数      {data['codes']}")
    print(f"行数        {data['rows']:,}")
    print(f"日期区间    {data['first_date']} ~ {data['last_date']}")
    print(f"同步失败    {data['failed_codes']} 只")
    return 0


def cmd_strategies(args: argparse.Namespace) -> int:
    for item in describe_all():
        print(f"{item['slug']:<20} {item['name']}")
        print(f"  {item['description']}")
        print(f"  入场={item['entry_timing']}  需要字段={','.join(item['required_fields'])}"
              f"  最少K线={item['min_bars']}")
    return 0


def cmd_screen(args: argparse.Namespace) -> int:
    params = json.loads(args.params) if args.params else None
    with _store(args) as store:
        result = screen(
            store,
            args.strategy,
            trade_date=args.date,
            params=params,
            codes=[c.strip() for c in args.codes.split(",")] if args.codes else None,
        )
    print(result.summary())
    if args.json:
        print(json.dumps(result.__dict__, ensure_ascii=False, indent=2, default=str))
        return 0
    for pick in result.picks:
        factors = result_factor_line(pick["factors"])
        print(f"  {pick['code']}  开={pick['open']}  收={pick['close']}   {factors}")
    if not result.picks:
        print("  （当日无标的满足条件）")
    print()
    print(DISCLAIMER)
    return 0


def cmd_rescore(args: argparse.Namespace) -> int:
    """按战法当前评分口径重算已入库候选（默认只预览；--apply 前先备份账本）。"""
    import sqlite3
    from datetime import datetime

    from src.ledger import PalaceStore
    from src.strategy.application.rescore import apply_rescore, plan_rescore

    palace_path = Path(args.palace_db)
    if not palace_path.exists():
        print(f"账本不存在：{palace_path}", file=sys.stderr)
        return 2
    slugs = [slug.strip() for slug in args.strategy.split(",") if slug.strip()]
    with _store(args) as store, PalaceStore(palace_path) as palace:
        plan = [{**row, "strategy": slug} for slug in slugs
                for row in plan_rescore(palace, store, slug, since=args.since, until=args.until)]
        if not plan:
            print(f"{'、'.join(slugs)} 在所选日期范围内没有已入库候选")
            return 0
        print(f"{'战法':<18}{'日期':<12}{'代码':<8}{'名称':<10}{'裁决':<6}{'旧分':>8}{'新分':>8}  状态")
        for row in plan:
            old = "—" if row["old_score"] is None else f"{row['old_score']:.1f}"
            new = "—" if row["new_score"] is None else f"{row['new_score']:.1f}"
            note = f"  {row['note']}" if row["note"] else ""
            print(f"{row['strategy']:<18}{row['occurred_on']:<12}{row['code']:<8}{str(row['name'])[:8]:<10}"
                  f"{row['decision']:<6}{old:>8}{new:>8}  {row['status']}{note}")
        counts = {status: sum(r["status"] == status for r in plan) for status in {r["status"] for r in plan}}
        print("汇总：" + "，".join(f"{key} {value}" for key, value in sorted(counts.items())))
        if not args.apply:
            print("预览模式，未写入。确认后加 --apply；写入前会先备份账本。")
            return 0
        if not counts.get("updated"):
            print("没有需要更新的行")
            return 0
        backup = palace_path.with_name(f"{palace_path.name}.bak-rescore-{datetime.now():%Y%m%d%H%M%S}")
        target = sqlite3.connect(backup)
        try:
            palace.conn.backup(target)
        finally:
            target.close()
        changed = apply_rescore(palace, plan)
        print(f"已更新 {changed} 行；备份：{backup}（回退：停服后用备份替换账本）")
    return 0


def result_factor_line(factors: dict) -> str:
    """把因子字典压成一行可读文本，只展示数值型的关键项。"""
    keys = ["昨涨幅", "昨振幅", "昨实体", "昨量比", "昨换手"]
    parts = [
        f"{key}={factors[key]:.2f}"
        for key in keys
        if isinstance(factors.get(key), (int, float))
    ]
    return " ".join(parts)


def cmd_bench(args: argparse.Namespace) -> int:
    """实测面板加载与选股耗时，并按当前候选池规模外推到全市场。"""
    engine = get(args.strategy)
    with _store(args) as store:
        coverage = store.coverage()
        if coverage["codes"] == 0:
            print("行情仓为空，请先同步", file=sys.stderr)
            return 2

        started = time.monotonic()
        days = store.trading_days()
        bars = engine.min_bars() + 20
        start = days[max(0, len(days) - bars)]
        panels = store.load_panel(
            fields=engine.required_fields(), start=start, min_bars=engine.min_bars()
        )
        load_seconds = time.monotonic() - started

        shape = panels["close"].shape
        started = time.monotonic()
        result = engine.compute(panels)
        compute_seconds = time.monotonic() - started

    picked = int(result.signals.iloc[-1].sum())
    universe = shape[1]
    print(f"候选池        {universe} 只 × {shape[0]} 个交易日")
    print(f"面板加载      {load_seconds * 1000:.0f} ms")
    print(f"信号计算      {compute_seconds * 1000:.0f} ms   （全部 {shape[0]} 个交易日一次算完）")
    print(f"合计          {(load_seconds + compute_seconds) * 1000:.0f} ms，最后一日选出 {picked} 只")
    if universe:
        factor = 5400 / universe
        print(
            f"外推全市场    约 {(load_seconds + compute_seconds) * factor:.2f} s "
            f"（按 5400 只线性外推，仅供参考）"
        )
    return 0


def cmd_backtest(args: argparse.Namespace) -> int:
    from src.backtest import BacktestConfig, backtest_strategy

    config = BacktestConfig(
        hold_days=args.hold,
        stop_loss_pct=args.stop if args.stop else None,
        take_profit_pct=args.target if args.target else None,
        benchmark=args.benchmark or None,
    )
    params = json.loads(args.params) if args.params else None
    with _store(args) as store:
        result = backtest_strategy(
            store, args.strategy, start=args.start, end=args.end,
            params=params, config=config,
        )

    print(result.summary())
    if result.skipped:
        print("  跳过：" + "，".join(f"{k} {v} 次" for k, v in result.skipped.items()))
    metrics = result.metrics
    if metrics.get("trades"):
        print(f"  持有 {metrics['avg_hold_days']} 日  盈利 {metrics['wins']} / 亏损 {metrics['losses']}")
        print(f"  单笔最好 {metrics['best']:+.2f}%   最差 {metrics['worst']:+.2f}%")
        if "avg_alpha" in metrics:
            print(f"  相对基准超额均值 {metrics['avg_alpha']:+.2f}%   跑赢基准比例 {metrics['alpha_win_rate']:.1f}%")
        print(f"  退出原因 {metrics['exit_reasons']}")
        if metrics.get("data_end_trades"):
            print(f"  数据到头 {metrics['data_end_trades']} 笔未纳入绩效统计")
        print(f"  往返成本已扣 {result.config['commission_bps'] * 2 + result.config['stamp_duty_bps'] + result.config['slippage_bps'] * 2:.0f} bps")
        if metrics.get("caution"):
            print(f"  ⚠ {metrics['caution']}")
    if args.trades and result.trades:
        print("\n  信号日     入场日     代码    入场    出场    持有  净收益   MFE     MAE    退出")
        for trade in result.trades:
            print(
                f"  {trade.signal_date} {trade.entry_date} {trade.code}  "
                f"{trade.entry_price:7.2f} {trade.exit_price:7.2f} {trade.hold_days:3d}  "
                f"{trade.net_return_pct:+7.2f}% {trade.mfe_pct:+6.2f}% {trade.mae_pct:+6.2f}%  {trade.exit_reason}"
            )
    print()
    print(DISCLAIMER)
    return 0



def cmd_compare(args: argparse.Namespace) -> int:
    """横向对比全部战法，回答"我到底该用哪个"。

    单看一个战法的绝对收益意义有限——大盘涨的时候什么都赚。真正有用的是
    **同一区间、同一成本口径下的横向超额**，以及每个战法的 MFE 与净收益
    的差距（差距大 = 浮盈拿不住，问题在退出而不在选股）。
    """
    from src.backtest import BacktestConfig, backtest_strategy
    from src.strategy import all_strategies, get

    holds = [int(h) for h in args.holds.split(",") if h.strip()]
    engines = [get(s.strip()) for s in args.strategies.split(",")] if args.strategies         else all_strategies()

    rows = []
    with _store(args) as store:
        for engine in engines:
            for hold in holds:
                try:
                    result = backtest_strategy(
                        store, engine.slug, start=args.start, end=args.end,
                        config=BacktestConfig(
                            hold_days=hold, stop_loss_pct=args.stop or None,
                            benchmark=args.benchmark or None,
                        ),
                    )
                except Exception as exc:
                    print(f"  {engine.slug}/{hold}d 失败：{type(exc).__name__}: {exc}",
                          file=sys.stderr)
                    continue
                metrics = result.metrics
                if metrics.get("trades"):
                    rows.append((f"{engine.slug}/{hold}d", metrics))

    if not rows:
        print("没有任何战法产生可评估的交易。", file=sys.stderr)
        return 1

    # 按超额排序：绝对收益会被大盘涨跌掩盖真实水平。
    key = "avg_alpha" if any(m.get("avg_alpha") is not None for _, m in rows) else "avg_net_return"
    rows.sort(key=lambda item: item[1].get(key) or -999, reverse=True)

    print(f"{'战法':<24}{'笔数':>7}{'胜率':>8}{'净收益':>9}{'MFE':>8}{'MAE':>8}{'超额':>8}  回吐")
    print("-" * 88)
    for label, m in rows:
        alpha = m.get("avg_alpha")
        give_back = (m.get("avg_mfe") or 0) - (m.get("avg_net_return") or 0)
        flag = " ⚠" if give_back > 4 else ""
        print(f"{label:<24}{m['trades']:>7}{m['win_rate']:>7.1f}%"
              f"{m['avg_net_return']:>8.2f}%{m.get('avg_mfe', 0):>7.2f}%"
              f"{m.get('avg_mae', 0):>7.2f}%"
              f"{('%+.2f%%' % alpha) if alpha is not None else '—':>8}"
              f"  {give_back:>5.2f}%{flag}")
        if m.get("caution"):
            print(f"{'':24}  ⚠ {m['caution']}")

    worst = max(rows, key=lambda item: (item[1].get("avg_mfe") or 0) - (item[1].get("avg_net_return") or 0))
    gap = (worst[1].get("avg_mfe") or 0) - (worst[1].get("avg_net_return") or 0)
    print()
    print("「回吐」= MFE 均值 − 净收益均值：持有期内的浮盈最终没拿住多少。")
    print(f"全场最严重的是 {worst[0]}（{gap:.2f} 个百分点）。若多数战法回吐都大，")
    print("说明问题在退出纪律而不在选股——换战法解决不了，得先加止盈或缩短持有期。")
    print()
    print(DISCLAIMER)
    return 0



def cmd_optimize(args: argparse.Namespace) -> int:
    """扫描退出规则，回答"这套战法该怎么卖"。

    横向对比已经指出：八个战法的 MFE 都远高于净收益，浮盈普遍拿不住。
    那问题就不在选股而在退出——换战法解决不了，得直接找出更好的卖法。

    这里固定选股信号不动，只扫持有期 × 止盈 × 止损三个维度，看哪一组
    组合的超额最高。
    """
    from src.backtest import BacktestConfig, backtest_strategy

    holds = [int(x) for x in args.holds.split(",") if x.strip()]
    targets: list[float | None] = [
        None if x.strip() in ("", "0") else float(x) for x in args.targets.split(",")
    ]
    stops: list[float | None] = [
        None if x.strip() in ("", "0") else float(x) for x in args.stops.split(",")
    ]

    total = len(holds) * len(targets) * len(stops)
    print(f"扫描 {total} 组退出规则（持有 {len(holds)} × 止盈 {len(targets)} × 止损 {len(stops)}）…")

    rows = []
    with _store(args) as store:
        for hold in holds:
            for target in targets:
                for stop in stops:
                    try:
                        result = backtest_strategy(
                            store, args.strategy, start=args.start, end=args.end,
                            config=BacktestConfig(
                                hold_days=hold, take_profit_pct=target,
                                stop_loss_pct=stop, benchmark=args.benchmark or None,
                            ),
                        )
                    except Exception as exc:
                        print(f"  跳过 {hold}d/{target}/{stop}：{exc}", file=sys.stderr)
                        continue
                    metrics = result.metrics
                    if metrics.get("trades"):
                        rows.append((hold, target, stop, metrics))

    if not rows:
        print("没有产生任何可评估的交易。", file=sys.stderr)
        return 1

    key = "avg_alpha" if any(m.get("avg_alpha") is not None for *_, m in rows) else "avg_net_return"
    rows.sort(key=lambda item: item[3].get(key) or -999, reverse=True)

    print()
    print(f"{'持有':>5}{'止盈':>8}{'止损':>8}{'笔数':>8}{'胜率':>8}{'净收益':>9}{'超额':>9}  退出分布")
    print("-" * 92)
    for hold, target, stop, m in rows[: args.top]:
        alpha = m.get("avg_alpha")
        reasons = m.get("exit_reasons") or {}
        labels = {"hold_expired": "到期", "stop_loss": "止损",
                  "take_profit": "止盈", "data_end": "无数据"}
        dist = " ".join(f"{labels.get(k, k)}{v}" for k, v in reasons.items())
        print(f"{hold:>4}d{(f'{target:+.0f}%' if target else '—'):>8}"
              f"{(f'{stop:+.0f}%' if stop else '—'):>8}{m['trades']:>8}"
              f"{m['win_rate']:>7.1f}%{m['avg_net_return']:>8.2f}%"
              f"{(f'{alpha:+.2f}%' if alpha is not None else '—'):>9}  {dist}")

    best = rows[0]
    baseline = next(
        (r for r in rows if r[1] is None and r[2] is None), None
    )
    print()
    print(f"最优组合：持有 {best[0]} 日"
          f"{f'，止盈 {best[1]:+.0f}%' if best[1] else '，不设止盈'}"
          f"{f'，止损 {best[2]:+.0f}%' if best[2] else '，不设止损'}")
    if baseline and baseline is not best:
        gain = (best[3].get(key) or 0) - (baseline[3].get(key) or 0)
        print(f"相比「只按持有期到期了结」，超额提升 {gain:+.2f} 个百分点。")
    if best[3].get("caution"):
        print(f"⚠ {best[3]['caution']}")
    print()
    print("注意：这是在同一段历史上反复试参数，天然存在过拟合风险。")
    print("换一段区间重跑一次，若最优组合完全不同，说明它只是拟合了噪声。")
    print()
    print(DISCLAIMER)
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Loci 行情仓与选股引擎", formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument("--db", default=str(DEFAULT_DB), help=f"行情库路径（默认 {DEFAULT_DB}）")
    parser.add_argument("--verbose", action="store_true", help="输出调试日志")
    sub = parser.add_subparsers(dest="command", required=True)

    sub.add_parser("instruments", help="刷新证券列表").set_defaults(func=cmd_instruments)

    sync = sub.add_parser("sync", help="同步日线行情")
    sync.add_argument("--codes", default="", help="逗号分隔的代码；不传则同步全部")
    sync.add_argument("--limit", type=int, default=0, help="只同步前 N 只，用于试跑")
    sync.add_argument("--workers", type=int, default=4, help="并发数（默认 4，过高易被限流）")
    sync.add_argument("--interval", type=float, default=0.15, help="全局最小请求间隔秒数")
    sync.add_argument("--force", action="store_true", help="忽略 watermark，强制重新同步")
    sync.add_argument("--no-factors", action="store_true", help="跳过复权因子，加快首次回填")
    sync.set_defaults(func=cmd_sync)

    sub.add_parser("coverage", help="查看行情仓现状").set_defaults(func=cmd_coverage)
    sub.add_parser("strategies", help="列出已注册战法").set_defaults(func=cmd_strategies)

    scr = sub.add_parser("screen", help="跑一次选股")
    scr.add_argument("strategy", help="策略 slug，见 strategies 子命令")
    scr.add_argument("--date", default=None, help="交易日，默认取仓库最新一日")
    scr.add_argument("--codes", default="", help="限定股票池，逗号分隔")
    scr.add_argument("--params", default="", help="覆盖参数的 JSON")
    scr.add_argument("--json", action="store_true", help="输出完整 JSON")
    scr.set_defaults(func=cmd_screen)

    rescore = sub.add_parser("rescore", help="按当前评分口径重算已入库候选的评分（默认预览）")
    rescore.add_argument("--strategy", default="sanyuan-tail-v1,yangshi-tail-v1",
                         help="逗号分隔的战法 slug（默认三源尾盘共振、杨氏尾盘选股）")
    rescore.add_argument("--palace-db", default=str(palace_db()), help="账本路径（默认当前数据目录的 palace.db）")
    rescore.add_argument("--since", default=None, help="起始候选日 YYYY-MM-DD")
    rescore.add_argument("--until", default=None, help="截止候选日 YYYY-MM-DD")
    rescore.add_argument("--apply", action="store_true", help="写入账本（先自动备份）；不加只预览")
    rescore.set_defaults(func=cmd_rescore)

    bench = sub.add_parser("bench", help="实测选股性能")
    bench.add_argument("--strategy", default="qianlong-close")
    bench.set_defaults(func=cmd_bench)

    opt = sub.add_parser("optimize", help="扫描退出规则，找最优卖法")
    opt.add_argument("strategy")
    opt.add_argument("--start", default=None)
    opt.add_argument("--end", default=None)
    opt.add_argument("--holds", default="1,2,3,5", help="持有天数候选")
    opt.add_argument("--targets", default="0,3,5,8", help="止盈候选，0 表示不设")
    opt.add_argument("--stops", default="0,-5,-8", help="止损候选，0 表示不设")
    opt.add_argument("--benchmark", default="000300")
    opt.add_argument("--top", type=int, default=12, help="展示前 N 组")
    opt.set_defaults(func=cmd_optimize)

    cmp = sub.add_parser("compare", help="横向对比全部战法的超额收益")
    cmp.add_argument("--start", default=None)
    cmp.add_argument("--end", default=None)
    cmp.add_argument("--holds", default="1,3", help="逗号分隔的持有天数")
    cmp.add_argument("--stop", type=float, default=-8.0, help="止损百分比，0 表示不设")
    cmp.add_argument("--benchmark", default="000300")
    cmp.add_argument("--strategies", default="", help="限定对比范围，逗号分隔 slug")
    cmp.set_defaults(func=cmd_compare)

    bt = sub.add_parser("backtest", help="对策略跑信号级回测")
    bt.add_argument("strategy", help="策略 slug")
    bt.add_argument("--start", default=None, help="起始交易日 YYYY-MM-DD")
    bt.add_argument("--end", default=None, help="结束交易日 YYYY-MM-DD")
    bt.add_argument("--hold", type=int, default=3, help="固定持有交易日数（默认 3）")
    bt.add_argument("--stop", type=float, default=-6.0, help="止损百分比，传 0 表示不设")
    bt.add_argument("--target", type=float, default=0.0, help="止盈百分比，0 表示不设")
    bt.add_argument("--benchmark", default="000300", help="基准指数，空字符串表示不比")
    bt.add_argument("--params", default="", help="覆盖策略参数的 JSON")
    bt.add_argument("--trades", action="store_true", help="逐笔打印交易明细")
    bt.set_defaults(func=cmd_backtest)
    rec = sub.add_parser("reclaim", help="删掉权威库无用索引并回收磁盘")
    rec.add_argument("--no-vacuum", action="store_true", help="只删索引，不 VACUUM")
    rec.add_argument("--force", action="store_true", help="跳过磁盘余量检查")
    rec.add_argument("--json", action="store_true", help="输出 JSON")
    rec.set_defaults(func=cmd_reclaim)

    report = sub.add_parser("storage-report", help="查看磁盘与 SQLite 存储分项")
    report.add_argument("--no-tables", action="store_true", help="不扫描 SQLite dbstat 分项")
    report.add_argument("--json", action="store_true", help="输出 JSON")
    report.set_defaults(func=cmd_storage_report)

    check = sub.add_parser("storage-check", help="执行轻量磁盘容量闸门")
    check.add_argument("--json", action="store_true", help="输出 JSON")
    check.set_defaults(func=cmd_storage_check)

    maintenance = sub.add_parser("storage-maintenance", help="执行行情存储保留期维护")
    maintenance.add_argument("--archive-root", default="", help="来源回执冷归档目录")
    maintenance.add_argument("--history-floor", default="2023-01-01")
    maintenance.add_argument("--selected-keep-days", type=int, default=14)
    maintenance.add_argument("--skipped-keep-days", type=int, default=7)
    maintenance.add_argument("--intel-keep-days", type=int, default=30)
    maintenance.add_argument("--archive-keep-days", type=int, default=90)
    maintenance.add_argument("--batch-size", type=int, default=20_000)
    maintenance.add_argument("--max-archive-batches", type=int, default=20)
    maintenance.add_argument("--no-vacuum", action="store_true", help="只清理，不尝试 VACUUM")
    maintenance.add_argument("--dry-run", action="store_true", help="只统计候选，不改数据库")
    maintenance.add_argument("--json", action="store_true", help="输出 JSON")
    maintenance.set_defaults(func=cmd_storage_maintenance)

    cap = sub.add_parser("intraday-capture", help="采集今日盘中快照（加密落盘）")
    cap.add_argument("--date", help="交易日 YYYY-MM-DD，默认今天")
    cap.add_argument("--only", help="只采这些数据集，逗号分隔")
    cap.add_argument("--json", action="store_true", help="输出 JSON")
    cap.set_defaults(func=cmd_intraday_capture)
    prn = sub.add_parser("intraday-prune", help="删掉过期的盘中留存目录")
    prn.add_argument("--keep-days", type=int, default=60, help="保留自然日数，默认 60")
    prn.add_argument("--max-delete", type=int, default=30, help="单次删除上限")
    prn.add_argument("--dry-run", action="store_true", help="只报要删什么，不动盘")
    prn.add_argument("--json", action="store_true", help="输出 JSON")
    prn.set_defaults(func=cmd_intraday_prune)
    sta = sub.add_parser("intraday-status", help="盘中留存带现状")
    sta.add_argument("--json", action="store_true", help="输出 JSON")
    sta.set_defaults(func=cmd_intraday_status)
    return parser


def cmd_reclaim(args: argparse.Namespace) -> int:
    """删掉权威库上无消费者的索引，并可选 VACUUM 真正缩小文件。"""
    import shutil

    db_path = Path(args.db) if args.db else Path(DEFAULT_DB)
    if not db_path.exists():
        print(f"行情库不存在：{db_path}")
        return 1
    free_bytes = None if args.force else shutil.disk_usage(db_path.parent).free
    print(f"行情库：{db_path}")
    print(f"当前大小：{db_path.stat().st_size / 1e6:,.1f} MB")
    if not args.no_vacuum:
        print("VACUUM 需要约等于库大小的额外磁盘，且全程持写锁，请勿同时同步行情。")
    report = reclaim_market_db(
        db_path,
        vacuum=not args.no_vacuum,
        free_bytes=free_bytes,
    )
    body = report.to_dict()
    if args.json:
        print(json.dumps(body, ensure_ascii=False, indent=2))
        return 0
    dropped = "、".join(body["dropped_indexes"]) or "（无可删索引）"
    print(f"已删索引：{dropped}")
    print(f"删除前空闲页：{body['freelist_pages_before']:,}")
    if body["skipped_reason"]:
        print(f"未 VACUUM：{body['skipped_reason']}")
    else:
        print(f"已 VACUUM：{body['vacuumed']}")
    print(f"回收后大小：{body['size_after_mb']:,.1f} MB（释放 {body['freed_mb']:,.1f} MB）")
    return 0


def _storage_policy(args: argparse.Namespace) -> StoragePolicy:
    return StoragePolicy(
        history_floor=str(args.history_floor),
        selected_keep_days=max(0, int(args.selected_keep_days)),
        skipped_keep_days=max(0, int(args.skipped_keep_days)),
        intel_keep_days=max(0, int(args.intel_keep_days)),
        archive_keep_days=max(0, int(args.archive_keep_days)),
        batch_size=max(1, int(args.batch_size)),
        max_archive_batches=max(1, int(args.max_archive_batches)),
    )


def cmd_storage_report(args: argparse.Namespace) -> int:
    payload = storage_report(Path(args.db), include_tables=not args.no_tables)
    if args.json:
        print(json.dumps(payload, ensure_ascii=False, indent=2, default=str))
        return 0
    print(f"数据根目录：{payload['root']}")
    print(report_text(payload))
    for name, item in payload["databases"].items():
        print(f"{name:<16} {int(item.get('bytes', 0)) / 1e6:,.1f} MB")
    for name, size in payload["directories"].items():
        if size:
            print(f"{name + '/':<16} {int(size) / 1e6:,.1f} MB")
    if not args.no_tables:
        print("最大 SQLite 对象：")
        for item in payload["databases"]["market.db"].get("tables", [])[:8]:
            print(f"  {item['name']:<36} {int(item['bytes']) / 1e6:,.1f} MB")
    return 0


def cmd_storage_check(args: argparse.Namespace) -> int:
    payload = storage_check(Path(args.db))
    if args.json:
        print(json.dumps(payload, ensure_ascii=False, indent=2, default=str))
    else:
        print(report_text(payload))
        for reason in payload.get("reasons", []):
            print(f"  ⚠ {reason}")
    return {"ok": 0, "warning": 1, "critical": 2}.get(str(payload["status"]), 2)


def cmd_storage_maintenance(args: argparse.Namespace) -> int:
    policy = _storage_policy(args)
    db_path = Path(args.db)
    try:
        # 与同步、spot、热库镜像使用同一把跨进程锁；禁止清理与行情写入交叉。
        with market_write_lock(db_path, label="storage:maintenance"):
            payload = run_storage_maintenance(
                db_path,
                archive_root=Path(args.archive_root) if args.archive_root else None,
                policy=policy,
                vacuum=not args.no_vacuum,
                dry_run=args.dry_run,
            )
    except MarketWriteBusy as exc:
        print(f"存储维护未开始：{exc}", file=sys.stderr)
        return 3
    if args.json:
        print(json.dumps(payload, ensure_ascii=False, indent=2, default=str))
    else:
        print(report_text(payload["after"]))
        print("删除：" + ", ".join(f"{k}={v}" for k, v in payload["deleted"].items()))
        print(f"完整性：{payload['integrity']}；VACUUM：{payload['vacuum']}")
        for error in payload.get("errors", []):
            print(f"  ⚠ {error}", file=sys.stderr)
    return 1 if payload.get("errors") or payload.get("integrity") not in {"ok", "not_run"} else 0


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.WARNING,
        format="%(levelname)s %(name)s: %(message)s",
    )
    return int(args.func(args))


if __name__ == "__main__":
    raise SystemExit(main())
