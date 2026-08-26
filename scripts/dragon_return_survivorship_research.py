"""龙回头·存活偏差与 ST 名称前视的量化。

## 本地库能做什么、不能做什么

探测结论（`market.db`，2026-08-12）：

| 事实 | 数值 | 含义 |
|---|---|---|
| `instruments.delist_date` 非空 | **0 / 5540** | 字段未维护 |
| `instruments.status='delisted'` | **1 / 5540** | 字段未维护 |
| `quotes_daily` 中不在 `instruments` 的代码 | **0** | **已退市股票的行情根本不在库里** |
| 各年度末在交易股票数 | 5279 → 5535 单调上升 | 库内无任何退市记录 |

所以**真正的退市存活偏差在本地无法测量**——不是没做，是数据层缺这批标的。这条要
单独记入文档，而不是用「假设影响不大」糊过去。

## 能测的那一半：ST 名称前视

`is_st_name(name)` 用的是 **instruments 里的当前名称**。当前名称含 ST 的有 **206 只**，
2024 年后全部有行情。此前所有回测都把这 206 只**整段**排除，包括它们当时还不是 ST
的那段历史——这是用未来信息做的筛选，性质与存活偏差相同，方向也相同（偏乐观）。

没有历史名称表，无法还原「某日是否 ST」。因此这里跑两个极端把真值夹住：

- **票池 A（现状）**：排除当前 ST → **偏乐观**，剔掉了后来变坏的票
- **票池 B（含 ST）**：完全不排除 → **偏保守**，纳入了当时可能已 ST（涨跌幅 5%、
  流动性差）的票

两者之差即该前视的影响幅度上界。同时单独统计「当前 ST 的那 206 只」贡献的信号与
收益——如果它们是亏的，就直接证明排除它们制造了乐观偏差。
"""
from __future__ import annotations

import argparse
from dataclasses import asdict
import gc
import json
import os
from pathlib import Path
import sqlite3
from typing import Any

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
from src.market.domain.universe import classify_board, is_st_name  # noqa: E402
from src.market.infrastructure.store_schema import DEFAULT_DB  # noqa: E402
from scripts.dragon_return_pool_trigger_research import (  # noqa: E402
    PoolRule,
    build_pool_and_triggers,
)
from scripts.heat_tail_attention_proxy_research import PRICE_FIELDS, _load_panels  # noqa: E402
from scripts.sanyuan_tail_resonance_research import _load_days, _read_only_connection  # noqa: E402

WARMUP_BARS = 170

#: 最优配置（见 incumbent-benchmark 第 6 节）：MA10 触发 + 强市 + 新高附近，持 3 日、2 槽位。
BEST_MA = 10
BEST_HOLD = 3
BEST_SLOTS = 2
INITIAL_CAPITAL = 200_000.0


def load_universe_pair(
    conn: sqlite3.Connection, *, as_of: str, boards: set[str]
) -> tuple[list[str], set[str]]:
    """返回 (含 ST 的全票池, 其中当前名称含 ST 的子集)。

    不按名称排除，交给调用方决定；同时把 ST 子集单独交出来做归因。
    """
    rows = conn.execute(
        "SELECT code,name,list_date,status FROM instruments WHERE instrument_type='STOCK'"
    ).fetchall()
    as_of_date = pd.Timestamp(as_of)
    codes: list[str] = []
    st_codes: set[str] = set()
    for code_raw, name_raw, listed_raw, status_raw in rows:
        code = str(code_raw).zfill(6)
        name = str(name_raw or "")
        if classify_board(code) not in boards:
            continue
        if str(status_raw or "normal") in {"suspended", "delisted"}:
            continue
        listed = str(listed_raw or "")[:10]
        if listed:
            try:
                if (as_of_date - pd.Timestamp(listed)).days < 60:
                    continue
            except (TypeError, ValueError):
                pass
        codes.append(code)
        if is_st_name(name):
            st_codes.add(code)
    return sorted(set(codes)), st_codes


def _trade_stats(frame: pd.DataFrame) -> dict[str, Any]:
    if frame.empty:
        return {"trades": 0}
    net = frame["net_return_pct"].astype(float)
    wins, losses = net[net > 0], net[net <= 0]
    avg_win = float(wins.mean()) if not wins.empty else None
    avg_loss = float(losses.mean()) if not losses.empty else None
    payoff = None if avg_win is None or not avg_loss else round(avg_win / abs(avg_loss), 3)
    return {
        "trades": int(len(frame)),
        "win_rate_pct": round(float((net > 0).mean() * 100), 2),
        "payoff_ratio": payoff,
        "avg_net_pct": round(float(net.mean()), 3),
        "median_net_pct": round(float(net.median()), 3),
        "profit_factor": (
            None
            if losses.empty or losses.sum() == 0
            else round(float(wins.sum() / abs(losses.sum())), 3)
        ),
    }


def run(args: argparse.Namespace) -> dict[str, Any]:
    db_path = Path(args.db).expanduser().resolve()
    rule = PoolRule(pct20_top_n=int(args.pct20_top_n))
    with _read_only_connection(db_path) as conn:
        days = _load_days(conn)
        codes_all, st_codes = load_universe_pair(
            conn, as_of=args.end, boards={"main", "chi_next", "star"}
        )
    load_start = days[max(0, days.index(args.start) - WARMUP_BARS)]
    with _read_only_connection(db_path) as conn:
        qfq, raw = _load_panels(
            conn, load_start=load_start, load_end=args.end, dates=days, codes=codes_all
        )
    ctx = build_pool_and_triggers(qfq, raw, rule)
    window = [day for day in qfq["close"].index if args.start <= day <= args.end]
    price_panels = {field: qfq[field] for field in PRICE_FIELDS}
    price_panels["volume"] = raw["volume"]
    trigger = ctx["triggers"][BEST_MA]
    breadth = ctx["dims"]["市场宽度%"]
    peak_days = ctx["dims"]["距高点天数"]
    ctx.clear()
    for field in list(raw):
        if field != "volume":
            del raw[field]
    for field in list(qfq):
        if field not in PRICE_FIELDS:
            del qfq[field]
    gc.collect()

    base = (trigger & breadth.ge(55.0) & peak_days.le(3)).fillna(False)
    non_st = [code for code in base.columns if code not in st_codes]

    universes = {
        "A_排除当前ST（此前口径·偏乐观）": non_st,
        "B_含ST（偏保守）": list(base.columns),
        "C_仅当前ST这206只": sorted(st_codes & set(base.columns)),
    }

    rows: list[dict[str, Any]] = []
    for label, cols in universes.items():
        if not cols:
            continue
        scoped = pd.DataFrame(False, index=base.index, columns=base.columns)
        scoped.loc[window, cols] = base.loc[window, cols]
        signals = int(scoped.loc[window].to_numpy().sum())
        if signals == 0:
            rows.append({"universe": label, "codes": len(cols), "signals": 0})
            continue
        config = BacktestConfig(
            hold_days=BEST_HOLD, stop_loss_pct=None, take_profit_pct=None, benchmark=None
        )
        result = run_backtest(
            scoped,
            price_panels,
            entry_timing="next_open",
            config=config,
            strategy_slug=f"survivorship:{label}",
        )
        valid = [t for t in result.trades if t.exit_reason != "data_end"]
        frame = result.to_frame()
        frame = frame[frame["exit_reason"] != "data_end"]
        portfolio: dict[str, Any] = {}
        if valid:
            try:
                payload = analyze_portfolio(
                    valid,
                    config=PortfolioResearchConfig(
                        initial_capital=INITIAL_CAPITAL,
                        max_positions=BEST_SLOTS,
                        period="month",
                    ),
                    trading_dates=window,
                    strategy_slug=label,
                ).to_dict()
                metrics = payload.get("metrics") or {}
                ret = metrics.get("return_pct")
                portfolio = {
                    "accepted_trades": metrics.get("accepted_trades"),
                    "return_pct": ret,
                    "monthly_geo_pct": (
                        round(((1 + float(ret) / 100) ** (1 / 31) - 1) * 100, 3)
                        if ret is not None
                        else None
                    ),
                    "avg_utilization_pct": metrics.get("avg_capital_utilization_pct"),
                    "max_drawdown_pct": metrics.get("max_drawdown_pct"),
                }
            except Exception as exc:  # noqa: BLE001
                portfolio = {"error": f"{type(exc).__name__}: {exc}"}
        rows.append(
            {
                "universe": label,
                "codes": len(cols),
                "signals": signals,
                "stats": _trade_stats(frame),
                "portfolio": portfolio,
            }
        )

    summary = {
        "purpose": "量化 ST 名称前视的影响，并记录退市存活偏差在本地不可测",
        "config": {
            "trigger": f"MA{BEST_MA} 探底回升收复 + 市场宽度≥55% + 距高点≤3日",
            "hold_days": BEST_HOLD,
            "slots": BEST_SLOTS,
            "entry": "next_open",
        },
        "local_data_gap": {
            "delist_date_非空": 0,
            "status_delisted": 1,
            "quotes_daily_中不在_instruments_的代码": 0,
            "各年度末在交易股票数": {
                "2024-06-28": 5279,
                "2024-12-31": 5328,
                "2025-06-30": 5383,
                "2025-12-31": 5448,
                "2026-07-31": 5535,
            },
            "结论": "已退市股票的行情不在库内，退市存活偏差无法测量；本轮只能量化 ST 名称前视",
        },
        "pool_rule": asdict(rule),
        "data": {
            "range": [args.start, args.end],
            "trading_days": len(window),
            "codes_total": len(codes_all),
            "st_codes": len(st_codes),
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
        f"全票池 {meta['codes_total']} 只，其中当前名称含 ST {meta['st_codes']} 只",
        f"配置：{summary['config']['trigger']}，持 {summary['config']['hold_days']} 日，"
        f"{summary['config']['slots']} 槽位，{summary['config']['entry']}",
        "",
        f"{'票池':<28}{'代码':>6}{'信号':>6}{'笔数':>6}{'胜率%':>7}{'盈亏比':>7}"
        f"{'每笔%':>8}{'中位%':>8}{'PF':>7}{'全期%':>9}{'月化%':>8}{'占用%':>7}{'回撤%':>8}",
    ]
    for row in summary["rows"]:
        s = row.get("stats") or {}
        p = row.get("portfolio") or {}
        if not s.get("trades"):
            lines.append(f"{row['universe']:<28}{row['codes']:>6}{row['signals']:>6}  无有效交易")
            continue
        lines.append(
            f"{row['universe']:<28}{row['codes']:>6}{row['signals']:>6}{s['trades']:>6}"
            f"{f(s['win_rate_pct']):>7}{f(s['payoff_ratio'], 3):>7}"
            f"{f(s['avg_net_pct'], 3):>8}{f(s['median_net_pct'], 3):>8}"
            f"{f(s['profit_factor'], 3):>7}{f(p.get('return_pct')):>9}"
            f"{f(p.get('monthly_geo_pct'), 3):>8}"
            f"{f(p.get('avg_utilization_pct')):>7}{f(p.get('max_drawdown_pct')):>8}"
        )
    gap = summary["local_data_gap"]
    lines += [
        "",
        "退市存活偏差：**本地不可测**。"
        f"delist_date 非空 {gap['delist_date_非空']} 条、"
        f"status=delisted {gap['status_delisted']} 条、"
        f"quotes_daily 中不在 instruments 的代码 {gap['quotes_daily_中不在_instruments_的代码']} 只；"
        "各年度末在交易股票数单调上升（5279→5535），库内无任何退市记录。",
    ]
    return "\n".join(lines)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--db", default=os.environ.get("PALACE_MARKET_DB") or str(DEFAULT_DB))
    parser.add_argument("--start", default="2024-01-02")
    parser.add_argument("--end", default="2026-07-31")
    parser.add_argument("--pct20-top-n", type=int, default=10)
    parser.add_argument("--output", default="output/dragon-survivorship")
    return parser


if __name__ == "__main__":
    run(build_parser().parse_args())
