"""龙回头·十日翻倍回踩企稳：用户原稿公式的回测。

原稿是通达信方言。两处必须改写，改写理由与等价性说明如下：

1. **`换手:=VOL/CAPITAL*100` → `HSL`（本仓 `turnover*100`）**。本仓 `volume` 存在
   「手 vs 股」的历史单位分歧（东财历史为手、新浪 spot 为股），有整个
   ``turnover_repair`` 模块在修；自己拿 VOL/CAPITAL 算会把换手撑到上千百分数。
   `HSL` 是 Screen Formula 的既有映射，口径已修。

2. **动态周期 `COUNT(cond, 回调天数+1)` / `SUM(换手, 回调天数+1)`**。本仓公式编译器
   拒绝变量窗口（`E_WINDOW_DYNAMIC`）。但原稿的 `充分回调` 已把 `回调天数` 限定在
   [3, 10]，因此按 d = 3..10 枚举、每档用固定窗口 d+1 计算，再按 `回调天数 == d`
   合并——**与通达信动态周期语义完全等价**，不是近似。

执行时点：原稿信号用到当日 `H`/`L`（`HHVBARS(H,20)`、长下影、止跌），本仓
`entry_timing="close"` 的前视审计只放 `OPEN/CLOSE/VOL/AMOUNT/HSL`，当日 H/L 属越界。
因此 **`next_open` 是严格口径**，`close` 一并给出但标注为乐观口径（等价于假设
14:50 已知全天最高最低与收盘）。

只读行情库，不注册活动战法，不写任何业务表。
"""
from __future__ import annotations

import argparse
from dataclasses import asdict, dataclass
import json
import os
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in os.sys.path:
    os.sys.path.insert(0, str(PROJECT_ROOT))

from src.backtest import BacktestConfig, run_backtest  # noqa: E402
from src.formula import COUNT, HHV, HHVBARS, LLV, MA, MIN, REF, SUM  # noqa: E402
from src.market.infrastructure.store_schema import DEFAULT_DB  # noqa: E402
from scripts.heat_tail_attention_proxy_research import (  # noqa: E402
    PRICE_FIELDS,
    _load_panels,
    _load_universe,
)
from scripts.sanyuan_tail_resonance_research import _load_days, _read_only_connection  # noqa: E402

#: 原稿 `充分回调` 把 `回调天数` 限定在这个闭区间，枚举范围据此而来。
PULLBACK_DAYS = range(3, 11)

#: 预热根数：REF(C,10) + COUNT(...,20) 叠加约 30，再留一倍余量给 MA(C,20)。
WARMUP_BARS = 80


@dataclass(frozen=True, slots=True)
class Signals:
    """原稿各中间条件，便于逐条报命中率、定位是哪一关卡死。"""

    double_20: pd.DataFrame
    enough_pullback: pd.DataFrame
    pullback_active: pd.DataFrame
    first_yin: pd.DataFrame
    stabilized: pd.DataFrame
    final: pd.DataFrame
    pullback_days: pd.DataFrame


def build_signals(qfq: dict[str, pd.DataFrame], raw: dict[str, pd.DataFrame]) -> Signals:
    close, open_, high, low = qfq["close"], qfq["open"], qfq["high"], qfq["low"]
    volume = raw["volume"]
    hsl = raw["turnover"] * 100.0  # 原稿的 换手:=VOL/CAPITAL*100

    # 十日翻倍 —— 拉升期换手要充分
    double_10 = (
        (close / REF(close, 10) >= 2.0)
        & (SUM(hsl, 10) >= 70.0)
        & (MA(hsl, 10) >= 6.0)
        & (COUNT(hsl > 5.0, 10) >= 5)
    )
    double_20 = COUNT(double_10, 20) >= 1

    # 以近 20 日最高点之后作为首阴/断板回调区
    peak_bars = HHVBARS(high, 20)
    peak_high = HHV(high, 20)
    pullback_pct = (peak_high - close) / peak_high * 100.0

    enough_pullback = (
        peak_bars.ge(3) & peak_bars.le(10) & pullback_pct.ge(12.0) & pullback_pct.le(32.0)
    )

    # 动态周期按 d 枚举后合并（见模块 docstring 第 2 条）
    first_yin = pd.DataFrame(False, index=close.index, columns=close.columns)
    pullback_active = pd.DataFrame(False, index=close.index, columns=close.columns)
    is_yin = close < open_
    hsl_gt2 = hsl > 2.0
    for days in PULLBACK_DAYS:
        window = days + 1
        at_days = peak_bars.eq(days)
        first_yin = first_yin | (at_days & (COUNT(is_yin, window) >= 1))
        avg_hsl = SUM(hsl, window) / window
        active = avg_hsl.ge(3.0) & (COUNT(hsl_gt2, window) >= days * 0.6)
        pullback_active = pullback_active | (at_days & active)

    # 企稳：靠近均线支撑 + 5 日线走平 + 止跌/小阳/下影/反包之一
    support = close.ge(MA(close, 10) * 0.97) | close.ge(MA(close, 20) * 0.97)
    ma5_flat = MA(close, 5) >= REF(MA(close, 5), 1) * 0.995
    stop_fall = low.ge(REF(LLV(low, 5), 1) * 0.995) & close.ge(REF(close, 1))
    body_pct = (close - open_) / REF(close, 1) * 100.0
    small_yang = (close > open_) & body_pct.ge(1.0) & body_pct.le(7.0)
    long_lower = (
        ((MIN(close, open_) - low) / (high - low + 0.01)).ge(0.35)
        & close.ge(REF(close, 1))
    )
    engulf = (
        (close > open_)
        & (close > REF(open_, 1))
        & (close > REF(close, 1))
        & volume.ge(MA(volume, 5) * 1.05)
    )
    stabilized = support & ma5_flat & (stop_fall | small_yang | long_lower | engulf)

    final = (
        double_20 & first_yin & enough_pullback & pullback_active & stabilized
    ).fillna(False)
    return Signals(
        double_20=double_20.fillna(False),
        enough_pullback=enough_pullback.fillna(False),
        pullback_active=pullback_active.fillna(False),
        first_yin=first_yin.fillna(False),
        stabilized=stabilized.fillna(False),
        final=final,
        pullback_days=peak_bars,
    )


def _stats(frame: pd.DataFrame) -> dict[str, Any]:
    if frame.empty:
        return {"trades": 0}
    valid = frame[frame["exit_reason"] != "data_end"]
    if valid.empty:
        return {"trades": 0, "data_end_trades": int(len(frame))}
    # 权益曲线必须按出场日排序：to_frame() 的行序是按代码来的，直接连乘等于把
    # 不同时间的交易乱序复利，算出来的回撤没有意义（会出现均净为正、回撤 -96% 的自相矛盾）。
    valid = valid.sort_values("exit_date", kind="stable")
    net = valid["net_return_pct"].astype(float)
    gross = valid["gross_return_pct"].astype(float)
    wins, losses = net[net > 0], net[net <= 0]
    avg_win = float(wins.mean()) if not wins.empty else None
    avg_loss = float(losses.mean()) if not losses.empty else None
    payoff = None if avg_win is None or not avg_loss else round(avg_win / abs(avg_loss), 3)
    win_rate = float((net > 0).mean())
    equity = (1 + net.div(100)).cumprod()
    return {
        "trades": int(len(valid)),
        "win_rate_pct": round(win_rate * 100, 2),
        "payoff_ratio": payoff,
        "breakeven_win_rate_pct": None if not payoff else round(100 / (1 + payoff), 2),
        "win_rate_gap_pp": (
            None if not payoff else round(win_rate * 100 - 100 / (1 + payoff), 2)
        ),
        "avg_win_pct": None if avg_win is None else round(avg_win, 3),
        "avg_loss_pct": None if avg_loss is None else round(avg_loss, 3),
        "avg_net_pct": round(float(net.mean()), 3),
        "avg_gross_pct": round(float(gross.mean()), 3),
        "median_net_pct": round(float(net.median()), 3),
        "profit_factor": (
            None
            if losses.empty or losses.sum() == 0
            else round(float(wins.sum() / abs(losses.sum())), 3)
        ),
        # 逐笔满仓串联的复利回撤（按出场日排序），**不是组合回撤**：
        # 日均只有 0.45 个信号，实盘不可能永远满仓单票。只用于看尾部风险量级。
        "serial_max_drawdown_pct": round(
            float((equity / equity.cummax() - 1).min() * 100), 3
        ),
        "exit_reasons": {
            str(k): int(v) for k, v in valid["exit_reason"].value_counts().items()
        },
    }


def _split_stats(frame: pd.DataFrame, split_date: str) -> dict[str, Any]:
    """前后两段各算一次。单段为正、另一段为负说明是运气不是 edge。"""
    if frame.empty:
        return {"early": {"trades": 0}, "late": {"trades": 0}, "stable_positive": False}
    early = _stats(frame[frame["signal_date"] < split_date])
    late = _stats(frame[frame["signal_date"] >= split_date])
    return {
        "early": early,
        "late": late,
        "stable_positive": bool(
            early.get("trades", 0) >= 30
            and late.get("trades", 0) >= 30
            and (early.get("avg_net_pct") or -1) > 0
            and (late.get("avg_net_pct") or -1) > 0
        ),
    }


#: (标签, entry_timing, hold_days, stop_loss_pct, take_profit_pct)
#:
#: 原稿只给了入场条件、没给出场，所以先用「无障碍持有 N 日」看信号本身的方向性
#: （不含任何路径假设），再补两组常见障碍。
VARIANTS: tuple[tuple[str, str, int, float | None, float | None], ...] = (
    ("次开买·持1日", "next_open", 1, None, None),
    ("次开买·持3日", "next_open", 3, None, None),
    ("次开买·持5日", "next_open", 5, None, None),
    ("次开买·持10日", "next_open", 10, None, None),
    ("次开买·-5/+10·持5", "next_open", 5, -5.0, 10.0),
    ("次开买·-7/+15·持10", "next_open", 10, -7.0, 15.0),
    ("尾盘买·持1日[乐观]", "close", 1, None, None),
    ("尾盘买·持5日[乐观]", "close", 5, None, None),
    ("尾盘买·-5/+10·持5[乐观]", "close", 5, -5.0, 10.0),
)


def run(args: argparse.Namespace) -> dict[str, Any]:
    db_path = Path(args.db).expanduser().resolve()
    with _read_only_connection(db_path) as conn:
        days = _load_days(conn)
    if args.start not in days:
        raise SystemExit(f"起始日 {args.start} 不是交易日；库内最近为 {days[-1]}")
    load_start = days[max(0, days.index(args.start) - WARMUP_BARS)]
    with _read_only_connection(db_path) as conn:
        codes, _ = _load_universe(
            conn, as_of=args.end, boards={"main", "chi_next", "star"}
        )
        qfq, raw = _load_panels(
            conn, load_start=load_start, load_end=args.end, dates=days, codes=codes
        )
    sig = build_signals(qfq, raw)
    window = [day for day in sig.final.index if args.start <= day <= args.end]
    scoped = pd.DataFrame(False, index=sig.final.index, columns=sig.final.columns)
    scoped.loc[window] = sig.final.loc[window]

    price_panels = {field: qfq[field] for field in PRICE_FIELDS}
    price_panels["volume"] = raw["volume"]

    total = int(scoped.loc[window].to_numpy().sum())
    stages = {
        "近20有翻倍": int(sig.double_20.loc[window].to_numpy().sum()),
        "充分回调": int(sig.enough_pullback.loc[window].to_numpy().sum()),
        "有首阴": int(sig.first_yin.loc[window].to_numpy().sum()),
        "回调活跃": int(sig.pullback_active.loc[window].to_numpy().sum()),
        "企稳": int(sig.stabilized.loc[window].to_numpy().sum()),
        "XG 全条件": total,
    }
    rows: list[dict[str, Any]] = []
    for label, timing, hold, stop, target in VARIANTS:
        config = BacktestConfig(
            hold_days=hold, stop_loss_pct=stop, take_profit_pct=target, benchmark=None
        )
        result = run_backtest(
            scoped,
            price_panels,
            entry_timing=timing,
            config=config,
            strategy_slug=f"dragon-return-double:{label}",
        )
        frame = result.to_frame()
        rows.append(
            {
                "variant": label,
                "config": asdict(config),
                "metrics": _stats(frame),
                "split": _split_stats(frame, window[len(window) // 2]),
            }
        )

    summary = {
        "strategy": "龙回头·十日翻倍回踩企稳（用户原稿）",
        "rewrites": [
            "换手 VOL/CAPITAL*100 → HSL（turnover*100），避开本仓 volume 的手/股单位坑",
            "动态周期 COUNT/SUM(…, 回调天数+1) → 按 d=3..10 枚举固定窗口后合并（等价改写）",
        ],
        "entry_note": (
            "原稿用当日 H/L，close 档在本仓前视审计下越界，故 next_open 为严格口径，"
            "close 档标注为乐观口径（假设 14:50 已知全天高低与收盘）"
        ),
        "data": {
            "db": str(db_path),
            "range": [args.start, args.end],
            "trading_days": len(window),
            "codes": len(codes),
            "boards": ["main", "chi_next", "star"],
            "signals_total": total,
            "signals_per_day": round(total / max(1, len(window)), 3),
            "survivorship_note": "当前 instruments 快照，非严格历史成分",
        },
        "stage_hits": stages,
        "variants": rows,
    }
    output = Path(args.output).expanduser().resolve()
    output.mkdir(parents=True, exist_ok=True)
    (output / "summary.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2, default=str), encoding="utf-8"
    )
    print(_render(summary))
    return summary


def _render(summary: dict[str, Any]) -> str:
    meta = summary["data"]
    lines = [
        f"区间 {meta['range'][0]} .. {meta['range'][1]}  交易日={meta['trading_days']}  "
        f"票池={meta['codes']}",
        f"XG 命中 {meta['signals_total']} 次，日均 {meta['signals_per_day']}",
        "",
        "各关卡单独命中次数（看是哪一关在卡）：",
    ]
    for name, hits in summary["stage_hits"].items():
        lines.append(f"  {name:<12}{hits:>10}")
    lines += [
        "",
        f"{'口径':<24}{'笔数':>7}{'胜率%':>8}{'盈亏比':>8}{'保本%':>8}{'缺口pp':>8}"
        f"{'均赢%':>8}{'均亏%':>8}{'均净%':>9}{'盈利因子':>9}",
    ]

    def f(value: Any, nd: int = 2) -> str:
        return "-" if value is None else f"{float(value):.{nd}f}"

    for row in summary["variants"]:
        met = row["metrics"]
        if not met.get("trades"):
            lines.append(f"{row['variant']:<24}{'无有效交易':>10}")
            continue
        flag = "  <= 正期望" if met["avg_net_pct"] > 0 else ""
        lines.append(
            f"{row['variant']:<24}{met['trades']:>7}{f(met['win_rate_pct']):>8}"
            f"{f(met['payoff_ratio'], 3):>8}{f(met['breakeven_win_rate_pct']):>8}"
            f"{f(met['win_rate_gap_pp']):>8}{f(met['avg_win_pct']):>8}"
            f"{f(met['avg_loss_pct']):>8}{f(met['avg_net_pct'], 3):>9}"
            f"{f(met['profit_factor'], 3):>9}{flag}"
        )
    lines += [
        "",
        "前后两段稳定性（只有两段都为正才算 edge，不是运气）：",
        f"{'口径':<24}{'前段n':>7}{'前段胜率%':>10}{'前段净%':>9}"
        f"{'后段n':>7}{'后段胜率%':>10}{'后段净%':>9}{'':>4}",
    ]
    for row in summary["variants"]:
        split = row.get("split") or {}
        early, late = split.get("early") or {}, split.get("late") or {}
        mark = "  [两段皆正]" if split.get("stable_positive") else ""
        lines.append(
            f"{row['variant']:<24}{early.get('trades', 0):>7}"
            f"{f(early.get('win_rate_pct')):>10}{f(early.get('avg_net_pct'), 3):>9}"
            f"{late.get('trades', 0):>7}"
            f"{f(late.get('win_rate_pct')):>10}{f(late.get('avg_net_pct'), 3):>9}{mark}"
        )
    lines += [
        "",
        "注：serial_max_drawdown_pct 在 summary.json 里，是逐笔满仓串联的复利回撤，"
        "不是组合回撤（日均仅 %.2f 个信号，实盘不会永远满仓单票）。"
        % summary["data"]["signals_per_day"],
    ]
    return "\n".join(lines)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--db", default=os.environ.get("PALACE_MARKET_DB") or str(DEFAULT_DB))
    parser.add_argument("--start", default="2024-01-02")
    parser.add_argument("--end", default="2026-07-31")
    parser.add_argument(
        "--output", default="output/dragon-return-double-2024-01-02_2026-07-31"
    )
    return parser


if __name__ == "__main__":
    run(build_parser().parse_args())
