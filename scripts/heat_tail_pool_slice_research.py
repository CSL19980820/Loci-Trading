"""热度尾盘：宽池子切片探索（先找胜率长在哪，再定策略）。

与 ``heat_tail_attention_proxy_research.py`` 的关系：那份是**确认式**的，把 ADR-011
的闸门链整套预设进去跑对照臂——结果市值闸被自己的对照臂打了脸，说明预设策略再
验证的顺序是错的。本脚本是**探索式**的：只保留三条无争议的硬条件

    注意力代理前 50  ∩  主板 / 创业板  ∩  非涨停（含非一字、非停牌、成交额底线）

池内**全部等权**跑，不预设市值闸、不预设涨幅带、不选 top3。然后按各维度切片，
看胜率究竟长在哪一格。策略应当从切片结果里长出来，而不是反过来。

热度用本地注意力代理而非同花顺 ``rate``：``smart_hotlist`` 无日期入参，
``intel_snapshots`` 目前只攒了 2 天真热度（2026-08-11 / 08-12），回测不了。
代理定义与局限见 ``2026-08-heat-tail-attention-proxy-backtest.md``。
"""
from __future__ import annotations

import argparse
from dataclasses import asdict
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
from src.formula import MA, REF, limit_up_flags  # noqa: E402
from scripts.heat_tail_attention_proxy_research import (  # noqa: E402
    PRICE_FIELDS,
    WIDE_LIMIT_PREFIXES,
    Gates,
    _load_panels,
    _load_universe,
    _safe_rank,
)
from scripts.sanyuan_tail_resonance_research import _load_days, _read_only_connection  # noqa: E402

#: 科创板前缀。前 50 的注意力排名在**全市场**算，但只有主板/创业板可入池。
STAR_PREFIXES = ("688", "689")


def build_slices(
    qfq: dict[str, pd.DataFrame],
    raw: dict[str, pd.DataFrame],
    gates: Gates,
) -> tuple[pd.DataFrame, dict[str, pd.DataFrame]]:
    """返回 (入池掩码, 各切片维度面板)。维度值为字符串标签，便于直接分组。"""
    close = qfq["close"]
    raw_close, raw_high, raw_low = raw["close"], raw["high"], raw["low"]
    volume, amount, turnover = raw["volume"], raw["amount"], raw["turnover"]
    shares = raw["outstanding_share"]

    pct_chg = (close / REF(close, 1) - 1.0) * 100.0
    vol_ratio = volume / MA(volume, 20)
    turnover_pct = turnover * 100.0
    spread = (qfq["high"] - qfq["low"]).replace(0.0, np.nan)
    clv = ((close - qfq["low"]) / spread).clip(0.0, 1.0)

    ratios = pd.DataFrame(
        np.repeat(
            [[0.20 if c.startswith(WIDE_LIMIT_PREFIXES) else 0.10 for c in close.columns]],
            len(close),
            axis=0,
        ),
        index=close.index,
        columns=close.columns,
    )
    sealed = limit_up_flags(raw_close, raw_high, ratios, tolerance=0.995)
    one_word = pd.DataFrame(
        np.isclose(raw_high, raw_low, equal_nan=False), index=close.index, columns=close.columns
    )

    tradable = (
        (volume > 0)
        & amount.ge(gates.amount_min)
        & turnover.notna()
        & close.notna()
        & ~sealed
        & ~one_word
    )
    attention = (
        _safe_rank(turnover.where(tradable)) * 0.30
        + _safe_rank(vol_ratio.clip(upper=8.0).where(tradable)) * 0.30
        + _safe_rank(amount.where(tradable)) * 0.25
        + _safe_rank(pct_chg.abs().where(tradable)) * 0.15
    ).where(tradable)
    hot_rank = attention.rank(axis=1, ascending=False, method="first")
    hot_pool = hot_rank.le(gates.hot_top_n).fillna(False)
    # shift 会把 bool 面板降成 object，而 object 上的 ~True 是 -2、~False 是 -1，
    # 两个都为真——不 astype(bool) 的话 ~prev_hot 恒真，"新进榜"会吞掉全部样本。
    prev_hot = hot_pool.shift(1, fill_value=False).astype(bool)
    rank_delta = (REF(hot_rank, 1) - hot_rank)

    is_star = pd.Series(
        [c.startswith(STAR_PREFIXES) for c in close.columns], index=close.columns
    )
    board_ok = pd.DataFrame(
        np.repeat((~is_star).to_numpy()[None, :], len(close), axis=0),
        index=close.index,
        columns=close.columns,
    )

    # 入池 = 三条无争议硬条件。市值、涨幅、只数一律不设——它们是待切片的维度。
    pool = (hot_pool & tradable & board_ok).fillna(False)

    def cut(panel: pd.DataFrame, edges: list[float], labels: list[str]) -> pd.DataFrame:
        flat = pd.cut(
            pd.Series(panel.to_numpy().ravel()), bins=edges, labels=labels, right=False
        )
        return pd.DataFrame(
            np.asarray(flat).reshape(panel.shape), index=panel.index, columns=panel.columns
        )

    heat_bucket = cut(
        hot_rank, [1, 11, 21, 31, 41, 51], ["01-10", "11-20", "21-30", "31-40", "41-50"]
    )
    delta_bucket = pd.DataFrame(
        "持平±10", index=close.index, columns=close.columns, dtype=object
    )
    delta_bucket = delta_bucket.where(~rank_delta.gt(10), "升10~50")
    delta_bucket = delta_bucket.where(~rank_delta.gt(50), "升>50")
    delta_bucket = delta_bucket.where(~rank_delta.lt(-10), "降>10")
    # 新进榜优先级最高：昨日不在前 50，今日在。
    delta_bucket = delta_bucket.where(~(hot_pool & ~prev_hot), "新进榜")

    slices = {
        "热度排名": heat_bucket,
        "热度增量": delta_bucket,
        "流通市值(亿)": cut(
            raw_close * shares / 1e8,
            [0, 50, 100, 200, 400, 1000, float("inf")],
            ["<50", "50-100", "100-200", "200-400", "400-1000", "≥1000"],
        ),
        "当日涨幅%": cut(
            pct_chg,
            [-float("inf"), -5, -2, 0, 2, 5, 7, float("inf")],
            ["<-5", "-5~-2", "-2~0", "0~2", "2~5", "5~7", "≥7"],
        ),
        "换手率%": cut(
            turnover_pct,
            [0, 3, 6, 10, 20, float("inf")],
            ["<3", "3-6", "6-10", "10-20", "≥20"],
        ),
        "量比": cut(
            vol_ratio, [0, 1, 2, 4, float("inf")], ["<1", "1-2", "2-4", "≥4"]
        ),
        "板块": pd.DataFrame(
            np.repeat(
                np.where(
                    [c.startswith(("300", "301")) for c in close.columns], "创业板", "主板"
                )[None, :],
                len(close),
                axis=0,
            ),
            index=close.index,
            columns=close.columns,
        ),
        "收盘位置CLV": cut(
            clv, [0, 0.3, 0.6, 0.85, 1.01], ["0-0.3", "0.3-0.6", "0.6-0.85", "0.85-1"]
        ),
        "昨日是否涨停": pd.DataFrame(
            np.where(sealed.shift(1).fillna(False).to_numpy(), "昨涨停", "昨未涨停"),
            index=close.index,
            columns=close.columns,
        ),
    }
    return pool, slices


def _long_frame(
    pool: pd.DataFrame, slices: dict[str, pd.DataFrame], window: list[str]
) -> pd.DataFrame:
    """把入池信号摊成长表：一行一个 (signal_date, code) + 各维度标签。"""
    scoped = pool.loc[window]
    rows, cols = np.where(scoped.to_numpy())
    frame = pd.DataFrame(
        {
            "signal_date": scoped.index.to_numpy()[rows],
            "code": scoped.columns.to_numpy()[cols],
        }
    )
    for name, panel in slices.items():
        frame[name] = panel.loc[window].to_numpy()[rows, cols]
    return frame


def _bucket_stats(group: pd.DataFrame) -> dict[str, Any]:
    net = group["net_return_pct"].astype(float)
    gross = group["gross_return_pct"].astype(float)
    wins, losses = net[net > 0], net[net <= 0]
    avg_win = float(wins.mean()) if not wins.empty else None
    avg_loss = float(losses.mean()) if not losses.empty else None
    payoff = (
        None if avg_win is None or not avg_loss else round(avg_win / abs(avg_loss), 3)
    )
    win_rate = float((net > 0).mean())
    return {
        "n": int(len(group)),
        "win_rate_pct": round(win_rate * 100, 2),
        "avg_win_pct": None if avg_win is None else round(avg_win, 3),
        "avg_loss_pct": None if avg_loss is None else round(avg_loss, 3),
        "payoff_ratio": payoff,
        # 保本胜率 = 1/(1+盈亏比)。对称 ±3% 障碍下盈亏比天然接近 1，
        # 所以这一列基本都在 50% 上下——它是判断"胜率够不够"的唯一标尺。
        "breakeven_win_rate_pct": None if not payoff else round(100 / (1 + payoff), 2),
        "win_rate_gap_pp": (
            None if not payoff else round(win_rate * 100 - 100 / (1 + payoff), 2)
        ),
        "profit_factor": (
            None
            if losses.empty or losses.sum() == 0
            else round(float(wins.sum() / abs(losses.sum())), 3)
        ),
        "avg_net_pct": round(float(net.mean()), 3),
        "avg_gross_pct": round(float(gross.mean()), 3),
        "median_net_pct": round(float(net.median()), 3),
    }


def _combo_search(
    merged: pd.DataFrame,
    dims: list[str],
    *,
    min_n: int,
    split_date: str,
    top_k: int = 20,
) -> list[dict[str, Any]]:
    """2~3 维交叉搜索。

    这是**多重比较**：84 个组合里挑最好的，最好那个天生偏乐观。因此每个组合都
    必须同时报前后两段的数字，只有两段都为正才有讨论价值——单看全样本等于自欺。
    """
    out: list[dict[str, Any]] = []
    early = merged[merged["signal_date"] < split_date]
    late = merged[merged["signal_date"] >= split_date]
    for size in (2, 3):
        for combo in itertools.combinations(dims, size):
            keys = list(combo)
            for value, grp in merged.groupby(keys, observed=True, dropna=True):
                if len(grp) < min_n:
                    continue
                values = value if isinstance(value, tuple) else (value,)
                cond_early = early
                cond_late = late
                for key, val in zip(keys, values):
                    cond_early = cond_early[cond_early[key] == val]
                    cond_late = cond_late[cond_late[key] == val]
                if len(cond_early) < min_n // 4 or len(cond_late) < min_n // 4:
                    continue
                row = {
                    "combo": " ∩ ".join(f"{k}={v}" for k, v in zip(keys, values)),
                    "all": _bucket_stats(grp),
                    "early": _bucket_stats(cond_early),
                    "late": _bucket_stats(cond_late),
                }
                row["stable_positive"] = bool(
                    row["early"]["avg_net_pct"] > 0 and row["late"]["avg_net_pct"] > 0
                )
                out.append(row)
    out.sort(key=lambda r: -r["all"]["avg_net_pct"])
    return out[:top_k]


def run(args: argparse.Namespace) -> dict[str, Any]:
    db_path = Path(args.db).expanduser().resolve()
    gates = Gates()
    with _read_only_connection(db_path) as conn:
        days = _load_days(conn)
    if args.start not in days:
        raise SystemExit(f"起始日 {args.start} 不是交易日；库内最近为 {days[-1]}")
    load_start = days[max(0, days.index(args.start) - 40)]
    with _read_only_connection(db_path) as conn:
        # 注意力排名要在全市场算，所以票池含科创板；板块过滤在入池时做。
        codes, _ = _load_universe(conn, as_of=args.end, boards={"main", "chi_next", "star"})
        qfq, raw = _load_panels(
            conn, load_start=load_start, load_end=args.end, dates=days, codes=codes
        )
    pool, slices = build_slices(qfq, raw, gates)
    window = [day for day in pool.index if args.start <= day <= args.end]
    scoped = pd.DataFrame(False, index=pool.index, columns=pool.columns)
    scoped.loc[window] = pool.loc[window]

    price_panels = {field: qfq[field] for field in PRICE_FIELDS}
    price_panels["volume"] = raw["volume"]
    long = _long_frame(pool, slices, window)

    report: dict[str, Any] = {}
    for timing in ("close", "next_open"):
        config = BacktestConfig(
            hold_days=1, stop_loss_pct=-3.0, take_profit_pct=3.0, benchmark=None
        )
        result = run_backtest(
            scoped,
            price_panels,
            entry_timing=timing,
            config=config,
            strategy_slug=f"heat-tail-slice:{timing}",
        )
        trades = result.to_frame()
        trades = trades[trades["exit_reason"] != "data_end"]
        merged = long.merge(trades, on=["signal_date", "code"], how="inner")
        overall = _bucket_stats(merged)
        per_dim: dict[str, Any] = {}
        for name in slices:
            buckets = {
                str(key): _bucket_stats(grp)
                for key, grp in merged.groupby(name, observed=True, dropna=True)
            }
            per_dim[name] = dict(
                sorted(buckets.items(), key=lambda kv: -kv[1]["win_rate_pct"])
            )
        report[timing] = {
            "overall": overall,
            "dimensions": per_dim,
            "combos": _combo_search(
                merged,
                list(slices),
                min_n=args.min_combo_n,
                split_date=window[len(window) // 2],
            ),
        }

    summary = {
        "purpose": "宽池子切片探索：先找胜率长在哪一格，再定策略（不预设市值闸/涨幅带/top3）",
        "pool_rule": "注意力代理前50 ∩ 主板或创业板 ∩ 非涨停非一字 ∩ 成交额≥3000万，池内全部等权",
        "heat_note": (
            "热度为本地注意力代理；smart_hotlist 无日期入参，"
            "intel_snapshots 目前仅 2 天真热度（2026-08-11/08-12），无法回测"
        ),
        "exit": asdict(
            BacktestConfig(hold_days=1, stop_loss_pct=-3.0, take_profit_pct=3.0, benchmark=None)
        ),
        "cost_note": "净收益已扣佣金 3bps 双边、印花税 10bps 卖出单边、滑点 5bps 单边（往返约 26bps）",
        "data": {
            "db": str(db_path),
            "range": [args.start, args.end],
            "trading_days": len(window),
            "codes": len(codes),
            "signals_per_day": round(float(scoped.loc[window].sum(axis=1).mean()), 2),
            "survivorship_note": "当前 instruments 快照，非严格历史成分",
        },
        "report": report,
    }
    output = Path(args.output).expanduser().resolve()
    output.mkdir(parents=True, exist_ok=True)
    (output / "summary.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2, default=str), encoding="utf-8"
    )
    long.to_csv(output / "signals.csv", index=False, encoding="utf-8-sig")
    print(_render(summary))
    return summary


def _render(summary: dict[str, Any]) -> str:
    meta = summary["data"]
    lines = [
        f"区间 {meta['range'][0]} .. {meta['range'][1]}  交易日={meta['trading_days']}  "
        f"日均入池={meta['signals_per_day']}",
        f"池规则 {summary['pool_rule']}",
    ]
    for timing, block in summary["report"].items():
        head = "尾盘买·T+1卖" if timing == "close" else "次开买·T+2卖"
        ov = block["overall"]
        lines += [
            "",
            "=" * 92,
            f"【{head}】全池 n={ov['n']}  胜率={ov['win_rate_pct']}%  "
            f"盈亏比={ov['payoff_ratio']}  保本胜率={ov['breakeven_win_rate_pct']}%  "
            f"缺口={ov['win_rate_gap_pp']}pp",
            f"        均赢={ov['avg_win_pct']}%  均亏={ov['avg_loss_pct']}%  "
            f"均净={ov['avg_net_pct']}%  盈利因子={ov['profit_factor']}",
            "=" * 92,
        ]
        for dim, buckets in block["dimensions"].items():
            covered = sum(stat["n"] for stat in buckets.values())
            gap = "" if covered == ov["n"] else f"  [!] 覆盖 {covered}/{ov['n']}（有样本未落档）"
            lines.append(f"\n  {dim}（按胜率降序）{gap}")
            lines.append(
                f"    {'分档':<12}{'样本':>8}{'胜率%':>8}{'盈亏比':>8}{'保本胜率%':>10}"
                f"{'缺口pp':>8}{'均赢%':>8}{'均亏%':>8}{'均净%':>9}"
            )
            for key, stat in buckets.items():
                flag = ""
                if stat["n"] >= 200 and stat["avg_net_pct"] > 0:
                    flag = "  ← 正期望"

                def num(value: Any, nd: int = 2) -> str:
                    return "-" if value is None else f"{float(value):.{nd}f}"

                lines.append(
                    f"    {key:<12}{stat['n']:>8}{stat['win_rate_pct']:>8.2f}"
                    f"{num(stat['payoff_ratio'], 3):>8}"
                    f"{num(stat['breakeven_win_rate_pct']):>10}"
                    f"{num(stat['win_rate_gap_pp']):>8}"
                    f"{num(stat['avg_win_pct']):>8}{num(stat['avg_loss_pct']):>8}"
                    f"{stat['avg_net_pct']:>9.3f}{flag}"
                )
        combos = block.get("combos") or []
        if combos:
            lines += [
                "",
                f"  交叉组合 top{len(combos)}（按全样本均净降序；多重比较，"
                "只有前后两段都为正才算数）",
                f"    {'全样本n':>8}{'均净%':>8}{'胜率%':>8}"
                f"{'前段n':>7}{'前段净%':>9}{'后段n':>7}{'后段净%':>9}  组合",
            ]
            for row in combos:
                a, e, l = row["all"], row["early"], row["late"]
                mark = "  [两段皆正] " if row["stable_positive"] else "  "
                lines.append(
                    f"    {a['n']:>8}{a['avg_net_pct']:>8.3f}{a['win_rate_pct']:>8.2f}"
                    f"{e['n']:>7}{e['avg_net_pct']:>9.3f}"
                    f"{l['n']:>7}{l['avg_net_pct']:>9.3f}{mark}{row['combo']}"
                )
    return "\n".join(lines)


def build_parser() -> argparse.ArgumentParser:
    from src.market.infrastructure.store_schema import DEFAULT_DB

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--db", default=os.environ.get("PALACE_MARKET_DB") or str(DEFAULT_DB))
    parser.add_argument("--start", default="2024-01-02")
    parser.add_argument("--end", default="2026-07-31")
    parser.add_argument(
        "--output", default="output/heat-tail-pool-slice-2024-01-02_2026-07-31"
    )
    parser.add_argument(
        "--min-combo-n",
        type=int,
        default=1000,
        help="交叉组合的最小全样本量；调小会显著增加过拟合风险",
    )
    return parser


if __name__ == "__main__":
    run(build_parser().parse_args())
