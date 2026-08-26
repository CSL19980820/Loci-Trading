"""龙回头·监控池 + 探底回升收复均线触发器（含筹码分档）。

架构照用户澄清后的描述来，不是选股公式那套：

    入池：20 日涨幅进过全市场前 10（人气那一层回测期用不了，见下）
    窗口：入池后盯 20 个交易日
    触发：当日最低 <= MAn 且收盘 > MAn（探底回升收复均线），窗口内首次
    叠加：筹码——触发日的获利盘比例 WINNER 与 50% 筹码成本 COST(50)

三条均线（MA5 / MA10 / MA20）**分开跑**：它们的语义强度不同，混在一条公式里
会让信号密度差几倍，也就看不出哪条才是有效的那条。

## 两处口径声明

1. **人气那一层不进回测**。`smart_hotlist` 无日期入参，`intel_snapshots` 只攒了
   2 天真热度（2026-08-11 / 08-12）。本脚本只测「20 日涨幅入池 + 触发器 + 筹码」，
   人气门槛留给实盘的盘中提示。详见
   `docs/research/2026-08-heat-tail-attention-proxy-backtest.md`。

2. **触发条件用到当日 `LOW`**，本仓 `entry_timing="close"` 的前视审计只放
   `OPEN/CLOSE/VOL/AMOUNT/HSL`，当日 LOW 属越界。因此 `next_open` 是严格口径；
   `close` 一并给出但标注乐观（盘中 14:50 时当日 low 其实已经发生、并非前视，
   但日线回测无法区分「14:50 的 low」与「全天 low」，故只能标乐观）。

筹码用 qfq 复权价 + 原始换手率：`chips.py` 的价格档位按已见高低价动态扩展，
用不复权价会让除权日整个网格跳档。
"""
from __future__ import annotations

import argparse
from dataclasses import asdict, dataclass
import itertools
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
from src.formula import (  # noqa: E402
    COUNT,
    HHV,
    HHVBARS,
    MA,
    REF,
    chip_cost_series,
    chip_winner_series,
)
from src.market.infrastructure.store_schema import DEFAULT_DB  # noqa: E402
from scripts.heat_tail_attention_proxy_research import (  # noqa: E402
    PRICE_FIELDS,
    _load_panels,
    _load_universe,
)
from scripts.sanyuan_tail_resonance_research import _load_days, _read_only_connection  # noqa: E402

#: 筹码递推预热。换手 2%/日时衰减半衰期约 35 日，250 日足够收敛；
#: 短窗口求值会产生伪精确结果（见 src/formula/README.md）。
WARMUP_BARS = 260

#: MA60 / MA120 语义与短均线完全不同：刚翻倍的票价格远在 MA60 之上，
#: 「打到 MA60 又收复」意味着深度回撤后的收复，而不是浅回踩。
#: 预热 260 根同时覆盖 MA120(120) + 入池窗口(20) + 涨幅回看(20)。
MA_WINDOWS = (5, 10, 20, 60, 120)


@dataclass(frozen=True, slots=True)
class PoolRule:
    pct20_top_n: int = 10
    """入池：20 日涨幅全市场前 N。"""

    watch_days: int = 20
    """入池后监控多少个交易日。"""

    amount_min: float = 30_000_000.0
    """可交易底线（元），所有分支共用。"""


def build_pool_and_triggers(
    qfq: dict[str, pd.DataFrame], raw: dict[str, pd.DataFrame], rule: PoolRule
) -> dict[str, Any]:
    close, low = qfq["close"], qfq["low"]
    volume, amount, turnover = raw["volume"], raw["amount"], raw["turnover"]

    tradable = (
        (volume > 0) & amount.ge(rule.amount_min) & close.notna() & turnover.notna()
    )
    pct20 = close / REF(close, 20) - 1.0
    # 入池：仅在可交易票内排名，避免停牌僵尸票占位。
    entered = (
        pct20.where(tradable).rank(axis=1, ascending=False, method="first")
        .le(rule.pct20_top_n)
        .fillna(False)
    )
    in_window = (COUNT(entered, rule.watch_days) >= 1).fillna(False)

    triggers: dict[int, pd.DataFrame] = {}
    for window in MA_WINDOWS:
        ma = MA(close, window)
        # 探底回升收复均线：盘中打到过均线（当日最低跌破/触及），收盘又站回上方。
        touch_reclaim = low.le(ma) & close.gt(ma)
        raw_hit = (in_window & tradable & touch_reclaim).fillna(False)
        # 窗口内首次：过去 watch_days-1 日内没有同样的命中。
        prior = COUNT(raw_hit, rule.watch_days) - raw_hit.astype(float)
        triggers[window] = (raw_hit & prior.le(0)).fillna(False)

    # 筹码：一次递推同时出 COST(15/50/85)，别为每个分位跑一遍。
    costs = chip_cost_series(
        qfq["high"], qfq["low"], close, turnover, (15.0, 50.0, 85.0)
    )
    winner = chip_winner_series(qfq["high"], qfq["low"], close, turnover)
    cost50 = costs[50.0]

    high, ma5, ma10, ma20 = qfq["high"], MA(close, 5), MA(close, 10), MA(close, 20)
    peak = HHV(high, rule.watch_days)
    breadth = (close > REF(close, 1)).mean(axis=1) * 100.0
    return {
        "entered": entered,
        "in_window": in_window,
        "triggers": triggers,
        # 12 个候选维度，全部是数值面板；分档在取出信号行之后做，
        # 提前做成标签面板会产出 12 张 (884×4992) 的 object 表，约 2.6 GB。
        "dims": {
            "获利盘%": winner,
            "现价/50%成本偏离%": (close / cost50 - 1.0) * 100.0,
            # 筹码宽度：COST(85)-COST(15) 占现价的比例，越小越接近「单峰密集」。
            # 这两个分位本来就跟 COST(50) 一起算出来了，之前只用了中位那个。
            "筹码宽度%": (costs[85.0] - costs[15.0]) / close * 100.0,
            "触发日20日涨幅%": pct20 * 100.0,
            # 真正的「回踩深度」：距窗口内最高点的回撤，而非相对 20 日前的涨幅。
            "距高点回撤%": (peak - low) / peak * 100.0,
            "距高点天数": HHVBARS(high, rule.watch_days),
            "量比": volume / MA(volume, 20),
            "换手率%": turnover * 100.0,
            "流通市值亿": raw["close"] * raw["outstanding_share"] / 1e8,
            "收盘位置CLV": ((close - low) / (high - low).replace(0.0, np.nan)).clip(0, 1),
            # 市场宽度：全市场当日上涨家数占比，逐日标量广播成面板。
            "市场宽度%": pd.DataFrame(
                np.repeat(breadth.to_numpy()[:, None], len(close.columns), axis=1),
                index=close.index,
                columns=close.columns,
            ),
            # 均线排列：2=多头(MA5>MA10>MA20)、1=纠缠、0=空头(MA5<MA10<MA20)
            "均线排列": (
                ((ma5 > ma10) & (ma10 > ma20)).astype(float) * 2.0
                + ((ma5 < ma10) & (ma10 < ma20)).astype(float) * 0.0
                + (~((ma5 > ma10) & (ma10 > ma20)) & ~((ma5 < ma10) & (ma10 < ma20)))
                .astype(float)
                * 1.0
            ),
        },
    }


#: 每个维度的分档边界与标签。右开区间。
BINS: dict[str, tuple[list[float], list[str]]] = {
    "获利盘%": ([0, 10, 25, 50, 75, 100.01], ["0-10", "10-25", "25-50", "50-75", "75-100"]),
    "现价/50%成本偏离%": (
        [-float("inf"), -20, -10, 0, 10, 20, float("inf")],
        ["<-20", "-20~-10", "-10~0", "0~10", "10~20", "≥20"],
    ),
    "筹码宽度%": (
        [0, 15, 25, 40, 60, float("inf")],
        ["<15密集", "15-25", "25-40", "40-60", "≥60发散"],
    ),
    "触发日20日涨幅%": (
        [-float("inf"), -20, 0, 20, 50, 100, float("inf")],
        ["<-20", "-20~0", "0~20", "20~50", "50~100", "≥100"],
    ),
    "距高点回撤%": (
        [0, 5, 10, 20, 30, float("inf")],
        ["<5", "5-10", "10-20", "20-30", "≥30"],
    ),
    "距高点天数": ([0, 2, 4, 7, 11, 21], ["0-1", "2-3", "4-6", "7-10", "11-20"]),
    "量比": ([0, 0.7, 1.0, 1.5, 2.5, float("inf")], ["<0.7缩量", "0.7-1", "1-1.5", "1.5-2.5", "≥2.5放量"]),
    "换手率%": ([0, 3, 6, 10, 20, float("inf")], ["<3", "3-6", "6-10", "10-20", "≥20"]),
    "流通市值亿": (
        [0, 50, 100, 200, 400, float("inf")],
        ["<50", "50-100", "100-200", "200-400", "≥400"],
    ),
    "收盘位置CLV": ([0, 0.3, 0.6, 0.85, 1.01], ["0-0.3", "0.3-0.6", "0.6-0.85", "0.85-1"]),
    "市场宽度%": ([0, 30, 45, 55, 70, 100.01], ["<30极弱", "30-45", "45-55", "55-70", "≥70极强"]),
    "均线排列": ([0, 1, 2, 3], ["空头", "纠缠", "多头"]),
}


def _long_frame(
    mask: pd.DataFrame, dims: dict[str, pd.DataFrame], window: list[str]
) -> pd.DataFrame:
    """摊成长表：一行一个 (signal_date, code)，各维度先取数值再分档。

    先取信号行（约 1000 行）再 `pd.cut`，而不是把每个维度做成全市场标签面板——
    后者是 12 张 (交易日 × 股票) 的 object 表，约 2.6 GB。
    """
    scoped = mask.loc[window]
    rows, cols = np.where(scoped.to_numpy())
    frame = pd.DataFrame(
        {
            "signal_date": scoped.index.to_numpy()[rows],
            "code": scoped.columns.to_numpy()[cols],
        }
    )
    for name, panel in dims.items():
        values = panel.loc[window].to_numpy()[rows, cols]
        frame[f"{name}_值"] = values
        edges, labels = BINS[name]
        frame[name] = pd.cut(
            pd.Series(values), bins=edges, labels=labels, right=False
        ).astype(object)
    return frame


def _combo_search(
    merged: pd.DataFrame,
    dims: list[str],
    *,
    min_n: int,
    split_date: str,
    top_k: int = 15,
) -> list[dict[str, Any]]:
    """2 维交叉搜索，只留前后两段都为正的组合。

    12 个维度两两组合是 66 对，每对再乘各自档位——**这是重度多重比较**。
    因此只输出「两段皆正」的，且前后段各自要够样本；即便如此也只能当线索，
    不能当结论。
    """
    out: list[dict[str, Any]] = []
    for left, right in itertools.combinations(dims, 2):
        for value, grp in merged.groupby([left, right], observed=True, dropna=True):
            if len(grp) < min_n:
                continue
            early = grp[grp["signal_date"] < split_date]
            late = grp[grp["signal_date"] >= split_date]
            if len(early) < min_n // 3 or len(late) < min_n // 3:
                continue
            stat_e, stat_l = _stats(early), _stats(late)
            if (stat_e.get("avg_net_pct") or -1) <= 0 or (
                stat_l.get("avg_net_pct") or -1
            ) <= 0:
                continue
            out.append(
                {
                    "combo": f"{left}={value[0]} ∩ {right}={value[1]}",
                    "all": _stats(grp),
                    "early": stat_e,
                    "late": stat_l,
                }
            )
    out.sort(key=lambda row: -row["all"]["avg_net_pct"])
    return out[:top_k]


def _stats(group: pd.DataFrame) -> dict[str, Any]:
    if group.empty:
        return {"n": 0}
    net = group["net_return_pct"].astype(float)
    wins, losses = net[net > 0], net[net <= 0]
    avg_win = float(wins.mean()) if not wins.empty else None
    avg_loss = float(losses.mean()) if not losses.empty else None
    payoff = None if avg_win is None or not avg_loss else round(avg_win / abs(avg_loss), 3)
    win_rate = float((net > 0).mean())
    return {
        "n": int(len(group)),
        "win_rate_pct": round(win_rate * 100, 2),
        "payoff_ratio": payoff,
        "breakeven_win_rate_pct": None if not payoff else round(100 / (1 + payoff), 2),
        "win_rate_gap_pp": (
            None if not payoff else round(win_rate * 100 - 100 / (1 + payoff), 2)
        ),
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


#: (标签, entry_timing, hold_days)。原稿没给卖点，先用无障碍持有看信号方向性。
VARIANTS: tuple[tuple[str, str, int], ...] = (
    ("次开买·持1日", "next_open", 1),
    ("次开买·持3日", "next_open", 3),
    ("次开买·持5日", "next_open", 5),
    ("尾盘买·持3日[乐观]", "close", 3),
    ("尾盘买·持5日[乐观]", "close", 5),
)


def run(args: argparse.Namespace) -> dict[str, Any]:
    db_path = Path(args.db).expanduser().resolve()
    rule = PoolRule(pct20_top_n=int(args.pct20_top_n))
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
    ctx = build_pool_and_triggers(qfq, raw, rule)
    window = [day for day in qfq["close"].index if args.start <= day <= args.end]

    # 取值时点一律是**触发日**。入池时必然大涨，触发时往往已经回落，
    # 所以「触发日20日涨幅」看的是触发那天还剩多少涨幅，档位含负数。
    dims = ctx["dims"]
    price_panels = {field: qfq[field] for field in PRICE_FIELDS}
    price_panels["volume"] = raw["volume"]
    split_date = window[len(window) // 2]

    report: dict[str, Any] = {}
    for ma_window, trigger in ctx["triggers"].items():
        scoped = pd.DataFrame(False, index=trigger.index, columns=trigger.columns)
        scoped.loc[window] = trigger.loc[window]
        long = _long_frame(scoped, dims, window)
        block: dict[str, Any] = {
            "signals": int(scoped.loc[window].to_numpy().sum()),
            "signals_per_day": round(
                float(scoped.loc[window].sum(axis=1).mean()), 3
            ),
            "variants": {},
        }
        for label, timing, hold in VARIANTS:
            config = BacktestConfig(
                hold_days=hold, stop_loss_pct=None, take_profit_pct=None, benchmark=None
            )
            result = run_backtest(
                scoped,
                price_panels,
                entry_timing=timing,
                config=config,
                strategy_slug=f"dragon-pool-trigger:MA{ma_window}:{label}",
            )
            trades = result.to_frame()
            trades = trades[trades["exit_reason"] != "data_end"]
            merged = long.merge(trades, on=["signal_date", "code"], how="inner")
            entry: dict[str, Any] = {
                "overall": _stats(merged),
                "early": _stats(merged[merged["signal_date"] < split_date]),
                "late": _stats(merged[merged["signal_date"] >= split_date]),
            }
            entry["stable_positive"] = bool(
                entry["early"].get("n", 0) >= 50
                and entry["late"].get("n", 0) >= 50
                and (entry["early"].get("avg_net_pct") or -1) > 0
                and (entry["late"].get("avg_net_pct") or -1) > 0
            )
            # 筹码与涨幅分档只在主口径上切，避免表爆炸。
            # 每档必须同时报前后两段——只看全样本就会把前半段的运气当成 edge，
            # 而分档本身是多重比较（每维 5~6 档），偏乐观的倾向更强。
            if (timing, hold) in {("next_open", 1), ("next_open", 3)}:
                entry["combos"] = _combo_search(
                    merged,
                    list(dims),
                    min_n=args.min_combo_n,
                    split_date=split_date,
                )
                dimensions: dict[str, Any] = {}
                for name in dims:
                    buckets: dict[str, Any] = {}
                    for key, grp in merged.groupby(name, observed=True, dropna=True):
                        early_g = grp[grp["signal_date"] < split_date]
                        late_g = grp[grp["signal_date"] >= split_date]
                        stat = _stats(grp)
                        stat["early"] = _stats(early_g)
                        stat["late"] = _stats(late_g)
                        stat["stable_positive"] = bool(
                            len(early_g) >= 30
                            and len(late_g) >= 30
                            and (stat["early"].get("avg_net_pct") or -1) > 0
                            and (stat["late"].get("avg_net_pct") or -1) > 0
                        )
                        buckets[str(key)] = stat
                    dimensions[name] = dict(
                        sorted(
                            buckets.items(),
                            key=lambda kv: -(kv[1].get("avg_net_pct") or -999),
                        )
                    )
                entry["dimensions"] = dimensions
            block["variants"][label] = entry
        report[f"MA{ma_window}"] = block

    summary = {
        "strategy": "龙回头·监控池 + 探底回升收复均线（用户澄清版）",
        "pool_rule": asdict(rule),
        "trigger": "当日最低 <= MAn 且 收盘 > MAn，窗口内首次",
        "excluded": "人气门槛未进回测（热度无历史，仅 2 天真数据）",
        "chips": "COST(15/50/85) 与 WINNER 用 qfq 价 + 原始换手率，预热 260 根",
        "entry_note": (
            "触发用当日 LOW，close 档在前视审计下越界，故 next_open 为严格口径，"
            "close 标乐观"
        ),
        "data": {
            "db": str(db_path),
            "range": [args.start, args.end],
            "trading_days": len(window),
            "codes": len(codes),
            "split_date": split_date,
            "survivorship_note": "当前 instruments 快照，非严格历史成分",
        },
        "report": report,
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

    def f(value: Any, nd: int = 2) -> str:
        return "-" if value is None else f"{float(value):.{nd}f}"

    lines = [
        f"区间 {meta['range'][0]} .. {meta['range'][1]}  交易日={meta['trading_days']}  "
        f"票池={meta['codes']}  前后分割={meta['split_date']}",
        f"入池 {summary['pool_rule']['pct20_top_n']} 只/日，监控 "
        f"{summary['pool_rule']['watch_days']} 交易日；触发 = {summary['trigger']}",
    ]
    for name, block in summary["report"].items():
        lines += [
            "",
            "=" * 96,
            f"【{name}】触发 {block['signals']} 次，日均 {block['signals_per_day']}",
            "=" * 96,
            f"{'口径':<22}{'笔数':>7}{'胜率%':>8}{'盈亏比':>8}{'保本%':>8}{'缺口pp':>8}"
            f"{'均净%':>9}{'中位%':>9}{'盈利因子':>9}{'前段净%':>9}{'后段净%':>9}",
        ]
        for label, entry in block["variants"].items():
            ov, early, late = entry["overall"], entry["early"], entry["late"]
            if not ov.get("n"):
                lines.append(f"{label:<22}{'无有效交易':>10}")
                continue
            mark = "  [两段皆正]" if entry.get("stable_positive") else ""
            lines.append(
                f"{label:<22}{ov['n']:>7}{f(ov['win_rate_pct']):>8}"
                f"{f(ov['payoff_ratio'], 3):>8}{f(ov['breakeven_win_rate_pct']):>8}"
                f"{f(ov['win_rate_gap_pp']):>8}{f(ov['avg_net_pct'], 3):>9}"
                f"{f(ov['median_net_pct'], 3):>9}{f(ov['profit_factor'], 3):>9}"
                f"{f(early.get('avg_net_pct'), 3):>9}{f(late.get('avg_net_pct'), 3):>9}{mark}"
            )
        for label in ("次开买·持1日", "次开买·持3日"):
            combos = ((block["variants"].get(label) or {}).get("combos")) or []
            if not combos:
                continue
            lines.append(f"\n  {label} · 两段皆正的 2 维交叉组合 top{len(combos)}")
            lines.append(
                f"    {'样本':>6}{'胜率%':>8}{'盈亏比':>8}{'缺口pp':>8}{'均净%':>9}"
                f"{'中位%':>9}{'PF':>7}{'前段':>8}{'后段':>8}  组合"
            )
            for row in combos:
                a, e, l = row["all"], row["early"], row["late"]
                lines.append(
                    f"    {a['n']:>6}{f(a['win_rate_pct']):>8}{f(a['payoff_ratio'], 3):>8}"
                    f"{f(a['win_rate_gap_pp']):>8}{f(a['avg_net_pct'], 3):>9}"
                    f"{f(a['median_net_pct'], 3):>9}{f(a['profit_factor'], 3):>7}"
                    f"{f(e['avg_net_pct'], 2):>8}{f(l['avg_net_pct'], 2):>8}  {row['combo']}"
                )

        main = block["variants"].get("次开买·持1日") or {}
        for dim, buckets in (main.get("dimensions") or {}).items():
            lines.append(f"\n  按 {dim} 分档（次开买·持1日，按均净降序）")
            lines.append(
                f"    {'分档':<14}{'样本':>8}{'胜率%':>8}{'盈亏比':>8}{'缺口pp':>8}"
                f"{'均净%':>9}{'盈利因子':>9}{'前段n':>7}{'前段净%':>9}"
                f"{'后段n':>7}{'后段净%':>9}"
            )
            for key, stat in buckets.items():
                early, late = stat.get("early") or {}, stat.get("late") or {}
                flag = "  [两段皆正]" if stat.get("stable_positive") else ""
                lines.append(
                    f"    {key:<14}{stat['n']:>8}{f(stat.get('win_rate_pct')):>8}"
                    f"{f(stat.get('payoff_ratio'), 3):>8}"
                    f"{f(stat.get('win_rate_gap_pp')):>8}"
                    f"{f(stat.get('avg_net_pct'), 3):>9}"
                    f"{f(stat.get('profit_factor'), 3):>9}"
                    f"{early.get('n', 0):>7}{f(early.get('avg_net_pct'), 3):>9}"
                    f"{late.get('n', 0):>7}{f(late.get('avg_net_pct'), 3):>9}{flag}"
                )
    return "\n".join(lines)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--db", default=os.environ.get("PALACE_MARKET_DB") or str(DEFAULT_DB))
    parser.add_argument("--start", default="2024-01-02")
    parser.add_argument("--end", default="2026-07-31")
    parser.add_argument(
        "--output", default="output/dragon-pool-trigger-2024-01-02_2026-07-31"
    )
    parser.add_argument(
        "--pct20-top-n",
        type=int,
        default=10,
        help="入池：20 日涨幅全市场前 N。收紧到 5 会把样本砍掉约一半",
    )
    parser.add_argument(
        "--min-combo-n",
        type=int,
        default=60,
        help="2 维交叉组合的最小样本；调小会显著增加过拟合风险",
    )
    return parser


if __name__ == "__main__":
    run(build_parser().parse_args())
