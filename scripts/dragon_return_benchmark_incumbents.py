"""把现役战法（潜龙、三源）放到与新战法相同的区间自己跑一遍。

## 为什么必须自己跑

两个现役战法在 `backtest_metrics` 里声明的头条数字都锁在
**2026-02-02 ~ 2026-07-31 这半年**，而它们各自迭代过四到五个版本
（`qianlong-close` v1→v3.1、`sanyuan-tail` v1→v2.5）。也就是说那半年大概率是
**调优区间（in-sample）**，不是样本外。直接拿它跟新战法在 31 个月上的数字比，
比的是「别人的最优半年」对「自己的全样本」。

三源自己留了对照：全样本 31 个月 `portfolio_return_pct` 638% 但
`max_drawdown_pct` −64.19%，且注明 `archived_pre_v25_reference`（V2.5 未在全样本重跑）。
半年 −10.6% 回撤与全样本 −64% 回撤之间的落差，本身就是 in-sample 优化的指纹。

所以这里在**同一区间、同一组合口径**下重跑，两个区间都跑：
- 半年（它们声明的区间）——看能否复现声明值
- 31 个月（新战法的区间）——这才是可比的那个

只读行情库，不注册战法，不写任何业务表。
"""
from __future__ import annotations

import argparse
from dataclasses import asdict
import json
import os
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in os.sys.path:
    os.sys.path.insert(0, str(PROJECT_ROOT))

from src.backtest import (  # noqa: E402
    BacktestConfig,
    PortfolioResearchConfig,
    analyze_portfolio,
    backtest_strategy,
)
from src.market import MarketStore  # noqa: E402
from src.market.infrastructure.store_schema import DEFAULT_DB  # noqa: E402

INCUMBENTS = ("qianlong-close-v3", "sanyuan-tail-v1")

#: 两段区间：前者是现役战法声明值所在的半年，后者是新战法的全样本。
WINDOWS = (
    ("声明半年", "2026-02-02", "2026-07-31"),
    ("全样本31月", "2024-01-02", "2026-07-31"),
)


def _trade_stats(frame: Any) -> dict[str, Any]:
    if frame is None or frame.empty:
        return {"trades": 0}
    valid = frame[frame["exit_reason"] != "data_end"]
    if valid.empty:
        return {"trades": 0}
    net = valid["net_return_pct"].astype(float)
    wins, losses = net[net > 0], net[net <= 0]
    avg_win = float(wins.mean()) if not wins.empty else None
    avg_loss = float(losses.mean()) if not losses.empty else None
    payoff = None if avg_win is None or not avg_loss else round(avg_win / abs(avg_loss), 3)
    return {
        "trades": int(len(valid)),
        "win_rate_pct": round(float((net > 0).mean() * 100), 2),
        "payoff_ratio": payoff,
        "avg_win_pct": None if avg_win is None else round(avg_win, 3),
        "avg_loss_pct": None if avg_loss is None else round(avg_loss, 3),
        "avg_net_pct": round(float(net.mean()), 3),
        "median_net_pct": round(float(net.median()), 3),
        "profit_factor": (
            None
            if losses.empty or losses.sum() == 0
            else round(float(wins.sum() / abs(losses.sum())), 3)
        ),
    }


def run(args: argparse.Namespace) -> dict[str, Any]:
    from src.strategy import get as get_strategy

    store = MarketStore(args.db)
    rows: list[dict[str, Any]] = []
    try:
        for slug in INCUMBENTS:
            engine = get_strategy(slug)
            declared = dict(getattr(engine, "backtest_metrics", None) or {})
            top_n = int(getattr(engine, "screen_top_n", 2) or 2)
            for label, start, end in WINDOWS:
                config = BacktestConfig(
                    hold_days=int(getattr(engine, "screen_hold_days", 3) or 3),
                    stop_loss_pct=getattr(engine, "screen_stop_loss_pct", None),
                    take_profit_pct=None,
                    benchmark=None,
                )
                try:
                    result = backtest_strategy(
                        store, engine, start=start, end=end, config=config
                    )
                except Exception as exc:  # noqa: BLE001
                    rows.append(
                        {
                            "slug": slug,
                            "window": label,
                            "error": f"{type(exc).__name__}: {exc}",
                        }
                    )
                    continue
                frame = result.to_frame()
                dates = sorted({str(t.signal_date) for t in result.trades})
                portfolio: dict[str, Any] = {}
                if result.trades:
                    try:
                        payload = analyze_portfolio(
                            result.trades,
                            config=PortfolioResearchConfig(
                                initial_capital=200_000.0,
                                max_positions=top_n,
                                period="month",
                            ),
                            trading_dates=dates,
                            strategy_slug=slug,
                        ).to_dict()
                        portfolio = payload.get("metrics") or {}
                    except Exception as exc:  # noqa: BLE001
                        portfolio = {"error": f"{type(exc).__name__}: {exc}"}
                rows.append(
                    {
                        "slug": slug,
                        "name": getattr(engine, "name", slug),
                        "window": label,
                        "range": [start, end],
                        "entry_timing": getattr(engine, "entry_timing", ""),
                        "top_n": top_n,
                        "config": asdict(config),
                        "stats": _trade_stats(frame),
                        "portfolio": portfolio,
                        "declared": {
                            key: declared.get(key)
                            for key in (
                                "trades",
                                "win_rate",
                                "avg_net_return",
                                "payoff_ratio",
                                "profit_factor",
                                "portfolio_return_pct",
                                "max_drawdown_pct",
                                "occupancy_pct",
                            )
                        }
                        if label == "声明半年"
                        else None,
                    }
                )
    finally:
        store.conn.close()

    summary = {
        "purpose": "现役战法在声明半年与全样本 31 个月两段区间的自跑结果",
        "caveat": (
            "声明值锁在 2026-02-02~2026-07-31 且各自迭代过 4~5 个版本，"
            "该区间大概率是调优区间；全样本那段才与新战法可比"
        ),
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

    lines = [
        f"{'战法':<20}{'区间':<12}{'笔数':>7}{'胜率%':>8}{'盈亏比':>8}"
        f"{'均净%':>9}{'中位%':>9}{'盈利因子':>9}{'组合收益%':>10}{'回撤%':>9}{'占用%':>8}"
    ]
    for row in summary["rows"]:
        if row.get("error"):
            lines.append(f"{row['slug']:<20}{row['window']:<12}  失败：{row['error']}")
            continue
        s, p = row["stats"], row.get("portfolio") or {}
        if not s.get("trades"):
            lines.append(f"{row.get('name', row['slug']):<20}{row['window']:<12}  无有效交易")
            continue
        ret = p.get("total_return_pct", p.get("portfolio_return_pct"))
        lines.append(
            f"{row.get('name', row['slug']):<20}{row['window']:<12}{s['trades']:>7}"
            f"{f(s['win_rate_pct']):>8}{f(s['payoff_ratio'], 3):>8}"
            f"{f(s['avg_net_pct'], 3):>9}{f(s['median_net_pct'], 3):>9}"
            f"{f(s['profit_factor'], 3):>9}{f(ret):>10}"
            f"{f(p.get('max_drawdown_pct')):>9}"
            f"{f(p.get('avg_capital_utilization_pct', p.get('occupancy_pct'))):>8}"
        )
        if row.get("declared"):
            d = row["declared"]
            lines.append(
                f"{'  └ 仓内声明值':<20}{'':<12}{f(d.get('trades'), 0):>7}"
                f"{f(d.get('win_rate')):>8}{f(d.get('payoff_ratio'), 3):>8}"
                f"{f(d.get('avg_net_return'), 3):>9}{'-':>9}"
                f"{f(d.get('profit_factor'), 3):>9}"
                f"{f(d.get('portfolio_return_pct')):>10}"
                f"{f(d.get('max_drawdown_pct')):>9}{f(d.get('occupancy_pct')):>8}"
            )
    return "\n".join(lines)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--db", default=os.environ.get("PALACE_MARKET_DB") or str(DEFAULT_DB))
    parser.add_argument("--output", default="output/incumbent-benchmark")
    return parser


if __name__ == "__main__":
    run(build_parser().parse_args())
