"""龙回头·资金利用率网格：槽位数 × 持有期。

## 为什么单独做这件事

同尺度对比（[incumbent-benchmark](../docs/research/2026-08-incumbent-strategy-full-sample-benchmark.md)）
显示新战法每笔 +1.014% 已优于潜龙/三源在全样本上的 +0.550% / +0.457%，
差距在**资金周转**而非选股：现役战法资金占用六到八成，新战法按「单笔 30% 仓」
折算只有两成出头。所以这一轮不动任何选股条件，只调资金结构。

## 三个杠杆与各自的代价

| 杠杆 | 提高占用的方式 | 代价 |
|---|---|---|
| 减少槽位数 | 每个槽位分到更多钱 | 集中度风险线性上升 |
| 延长持有期 | 每个信号占用更多天 | 每笔收益实测随持有期衰减 |
| 放宽入选条件 | 信号频次上升 | 每笔收益下降（已实测） |

平均并发持仓 ≈ 信号频次 × 持有期。新战法 hold=1 时约 0.75 只/日，**给两个以上
槽位必然闲置**——这与潜龙相反（它 78 个信号里只有 38 笔被槽位接受，槽位是瓶颈）。
所以本轮网格必须同时扫槽位与持有期，单看一个维度会得出相反结论。

## 口径

`analyze_portfolio` 传**完整交易日历**而非只传有信号的日子。只传信号日会把闲置日
排除在观察期外，占用率与收益率双双虚高——上一轮 incumbent-benchmark 的占用率
就是这么算的，本轮已修正。
"""
from __future__ import annotations

import argparse
from dataclasses import asdict
import gc
import json
import os
from pathlib import Path
from typing import Any, Callable

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

#: 本轮只用 MA5/MA10 触发 + 筹码宽度，不需要 260 根预热：筹码衰减半衰期约 35 个
#: 交易日（换手 2%/日），170 根是四个半衰期以上；MA120 也只需 120 根。
#: 降到 170 是为了压住内存——884×4992×16 个面板会把本机撑爆（实测 MemoryError）。
WARMUP_BARS = 170
HOLD_DAYS = (1, 2, 3, 5)

#: **不含 1 槽位**：`PortfolioResearchConfig.slot_capital = 初始资金 / 槽位数` 是
#: 固定名义额、不随权益复利，而分配器要求 `cash >= entry_notional`
#: （`research_portfolio.py:317` 与 `:344`）。槽位数=1 时 slot_capital 等于全部本金，
#: 第一笔亏损后 cash 永远小于它，后续每笔都被「可用现金不足」拒掉——**死锁**，
#: 实测 466 个信号只接受 3 笔。那不是策略结果，是工具的边界。
SLOTS = (2, 3, 4, 5)
INITIAL_CAPITAL = 200_000.0

Cond = Callable[[dict[str, pd.DataFrame]], pd.DataFrame]

#: 只取前一轮验证过两段皆正的四条，不再新增条件组合。
VARIANTS: tuple[tuple[str, int, list[tuple[str, Cond]]], ...] = (
    ("MA5·只加强市", 5, [("宽度≥55", lambda d: d["市场宽度%"].ge(55.0))]),
    (
        "MA5·强市+新高",
        5,
        [
            ("宽度≥55", lambda d: d["市场宽度%"].ge(55.0)),
            ("距高点≤3", lambda d: d["距高点天数"].le(3)),
        ],
    ),
    (
        "MA10·强市+新高",
        10,
        [
            ("宽度≥55", lambda d: d["市场宽度%"].ge(55.0)),
            ("距高点≤3", lambda d: d["距高点天数"].le(3)),
        ],
    ),
    (
        "MA5·强市+新高+密集",
        5,
        [
            ("宽度≥55", lambda d: d["市场宽度%"].ge(55.0)),
            ("距高点≤3", lambda d: d["距高点天数"].le(3)),
            ("筹码<25", lambda d: d["筹码宽度%"].lt(25.0)),
        ],
    ),
)


def _monthly_from_daily(daily: list[dict[str, Any]]) -> dict[str, Any]:
    """从组合日权益曲线导出月度分布。比按信号月叠加收益率更准。"""
    if not daily:
        return {}
    frame = pd.DataFrame(daily)
    if "date" not in frame or "equity" not in frame:
        return {}
    frame["month"] = frame["date"].str.slice(0, 7)
    month_end = frame.groupby("month")["equity"].last()
    returns = month_end.pct_change().dropna() * 100
    first_month = frame.groupby("month")["equity"].first().iloc[0]
    head = (month_end.iloc[0] / first_month - 1) * 100
    series = pd.concat([pd.Series([head], index=[month_end.index[0]]), returns])
    if series.empty:
        return {}
    return {
        "months": int(len(series)),
        "monthly_mean_pct": round(float(series.mean()), 3),
        "monthly_median_pct": round(float(series.median()), 3),
        "monthly_win_rate_pct": round(float((series > 0).mean() * 100), 2),
        "best_month_pct": round(float(series.max()), 2),
        "worst_month_pct": round(float(series.min()), 2),
        "monthly_std_pct": round(float(series.std()), 3),
        "months_ge_20pct": int((series >= 20).sum()),
    }


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
    window = [day for day in qfq["close"].index if args.start <= day <= args.end]
    price_panels = {field: qfq[field] for field in PRICE_FIELDS}
    price_panels["volume"] = raw["volume"]
    # 只保留本轮真正要用的三个维度与两条触发线；其余面板立刻释放。
    # 不清的话 16 张 (日 × 票) 面板会一直挂在内存里，本机撑不住。
    dims = {
        key: ctx["dims"][key]
        for key in ("市场宽度%", "距高点天数", "筹码宽度%")
    }
    triggers = {key: ctx["triggers"][key] for key in (5, 10)}
    ctx.clear()
    for field in list(raw):
        if field != "volume":
            del raw[field]
    for field in list(qfq):
        if field not in PRICE_FIELDS:
            del qfq[field]
    gc.collect()

    rows: list[dict[str, Any]] = []
    for name, ma_window, conds in VARIANTS:
        mask = triggers[ma_window].copy()
        for _, fn in conds:
            mask = mask & fn(dims).fillna(False)
        scoped = pd.DataFrame(False, index=mask.index, columns=mask.columns)
        scoped.loc[window] = mask.loc[window].fillna(False)
        signals = int(scoped.loc[window].to_numpy().sum())
        if signals == 0:
            continue
        for hold in HOLD_DAYS:
            config = BacktestConfig(
                hold_days=hold, stop_loss_pct=None, take_profit_pct=None, benchmark=None
            )
            result = run_backtest(
                scoped,
                price_panels,
                entry_timing="next_open",
                config=config,
                strategy_slug=f"dragon-capital:{name}:h{hold}",
            )
            valid = [t for t in result.trades if t.exit_reason != "data_end"]
            frame = result.to_frame()
            frame = frame[frame["exit_reason"] != "data_end"]
            per_trade = (
                round(float(frame["net_return_pct"].astype(float).mean()), 3)
                if not frame.empty
                else None
            )
            for slots in SLOTS:
                try:
                    payload = analyze_portfolio(
                        valid,
                        config=PortfolioResearchConfig(
                            initial_capital=INITIAL_CAPITAL,
                            max_positions=slots,
                            period="month",
                        ),
                        # 完整交易日历：只传信号日会把闲置日排除，占用与收益虚高。
                        trading_dates=window,
                        strategy_slug=f"{name}:h{hold}:s{slots}",
                    ).to_dict()
                except Exception as exc:  # noqa: BLE001
                    rows.append(
                        {
                            "variant": name,
                            "hold": hold,
                            "slots": slots,
                            "error": f"{type(exc).__name__}: {exc}",
                        }
                    )
                    continue
                metrics = payload.get("metrics") or {}
                sample = int(metrics.get("sample_size") or 0)
                accepted = int(metrics.get("accepted_trades") or 0)
                ret = metrics.get("return_pct")
                dd = metrics.get("max_drawdown_pct")
                rows.append(
                    {
                        "variant": name,
                        "signals": signals,
                        "hold": hold,
                        "slots": slots,
                        "per_trade_net_pct": per_trade,
                        "sample_size": sample,
                        "accepted_trades": accepted,
                        "slot_reject_pct": (
                            round((1 - accepted / sample) * 100, 2) if sample else None
                        ),
                        "return_pct": ret,
                        "monthly_geo_pct": (
                            round(((1 + float(ret) / 100) ** (1 / 31) - 1) * 100, 3)
                            if ret is not None
                            else None
                        ),
                        "avg_utilization_pct": metrics.get("avg_capital_utilization_pct"),
                        "max_utilization_pct": metrics.get("max_capital_utilization_pct"),
                        "max_drawdown_pct": dd,
                        "return_over_dd": (
                            round(float(ret) / abs(float(dd)), 3)
                            if ret is not None and dd not in (None, 0)
                            else None
                        ),
                        "monthly": _monthly_from_daily(payload.get("daily") or []),
                    }
                )

    summary = {
        "purpose": "不动选股条件，只调资金结构（槽位数 × 持有期）看能把收益推到哪",
        "method": "analyze_portfolio 传完整交易日历；月度由组合日权益曲线导出（非按信号月叠加收益率）",
        "initial_capital": INITIAL_CAPITAL,
        "pool_rule": asdict(rule),
        "reference": {
            "潜龙V3.1_全样本每笔净%": 0.550,
            "三源V2.5_全样本每笔净%": 0.457,
            "潜龙半年槽位拒单率%": 51.3,
        },
        "data": {
            "range": [args.start, args.end],
            "trading_days": len(window),
            "codes": len(codes),
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
        f"区间 {meta['range'][0]}..{meta['range'][1]}  {meta['trading_days']} 交易日  "
        f"本金 {summary['initial_capital']:.0f}  入池前 {summary['pool_rule']['pct20_top_n']} 只",
        "口径：次开买 · 无止损止盈 · analyze_portfolio 传完整交易日历",
        "",
        f"{'组合':<22}{'持有':>5}{'槽位':>5}{'信号':>6}{'接受':>6}{'拒单%':>7}"
        f"{'每笔%':>7}{'全期%':>9}{'月化%':>8}{'占用%':>7}{'峰值%':>7}"
        f"{'回撤%':>8}{'收益/回撤':>9}{'月均%':>7}{'最差月%':>8}",
    ]
    for row in summary["rows"]:
        if row.get("error"):
            lines.append(
                f"{row['variant']:<22}{row['hold']:>5}{row['slots']:>5}  失败：{row['error']}"
            )
            continue
        m = row.get("monthly") or {}
        lines.append(
            f"{row['variant']:<22}{row['hold']:>5}{row['slots']:>5}"
            f"{row['signals']:>6}{row['accepted_trades']:>6}"
            f"{f(row['slot_reject_pct']):>7}{f(row['per_trade_net_pct'], 3):>7}"
            f"{f(row['return_pct']):>9}{f(row['monthly_geo_pct'], 3):>8}"
            f"{f(row['avg_utilization_pct']):>7}{f(row['max_utilization_pct']):>7}"
            f"{f(row['max_drawdown_pct']):>8}{f(row['return_over_dd'], 2):>9}"
            f"{f(m.get('monthly_mean_pct')):>7}{f(m.get('worst_month_pct')):>8}"
        )
    lines += [
        "",
        "对照（全样本 31 个月，逐笔口径）："
        f"潜龙 V3.1 每笔 +{summary['reference']['潜龙V3.1_全样本每笔净%']}%，"
        f"三源 V2.5 每笔 +{summary['reference']['三源V2.5_全样本每笔净%']}%",
    ]
    return "\n".join(lines)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--db", default=os.environ.get("PALACE_MARKET_DB") or str(DEFAULT_DB))
    parser.add_argument("--start", default="2024-01-02")
    parser.add_argument("--end", default="2026-07-31")
    parser.add_argument("--pct20-top-n", type=int, default=10)
    parser.add_argument("--output", default="output/dragon-capital-utilization")
    return parser


if __name__ == "__main__":
    run(build_parser().parse_args())
