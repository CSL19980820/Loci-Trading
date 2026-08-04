"""潜龙尾盘 V1：排分因子 × TopN 对照研究。

基线候选 = V3 条件 + 尾盘价≥10（尚未按 ROC5 截断）。
执行口径对齐战法：T 日收盘成交、持有 1 可卖日、止盈 +3%、止损 -6%；
成交价用未复权 OHLC；信号指标用 qfq。
成本对齐三元研究：佣金 0.03%×2、印花税 0.05%、滑点 0.10%×2。
产物：report.md / compare.csv / summary.json / baseline-trades.csv。
"""
from __future__ import annotations

import argparse
from dataclasses import asdict
import json
import os
from pathlib import Path
import sys
from typing import Any

import numpy as np
import pandas as pd

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from src.backtest.application.engine import BacktestConfig, run_backtest
from src.formula import REF
from src.market.infrastructure.store_schema import DEFAULT_DB
from src.strategy.application.price_constraints import attach_raw_limit_close
from src.strategy.application.qianlong import QianlongCloseePickerV3
from scripts.sanyuan_tail_resonance_research import (
    _json_safe,
    _load_days,
    _load_panels,
    _load_universe,
    _metrics,
    _read_only_connection,
)
from scripts.qianlong_structure_research import _PanelStore

# 至少 12 组：排分 × TopN
VARIANTS: list[tuple[str, str, int | None]] = [
    ("ROC5×Top1（现行基线）", "roc5", 1),
    ("ROC5×Top2", "roc5", 2),
    ("ROC5×Top3", "roc5", 3),
    ("ROC5×Top5", "roc5", 5),
    ("ROC1×Top1", "roc1", 1),
    ("ROC1×Top2", "roc1", 2),
    ("量比×Top1", "vol_ratio", 1),
    ("量比×Top2", "vol_ratio", 2),
    ("换手高×Top1", "turnover", 1),
    ("换手低×Top1", "turnover_asc", 1),
    ("CLV低×Top1", "clv_asc", 1),
    ("CLV高×Top1", "clv", 1),
    ("60日位置低×Top1", "pos60_asc", 1),
    ("ROC5×量比复合×Top1", "roc5_vol", 1),
    ("全部候选", "roc5", None),
]


def _date_window(
    days: list[str], start: str, end: str, *, hold: int, warmup: int
) -> tuple[str, str, str]:
    if start not in days or end not in days:
        raise ValueError(f"回测日期必须是行情交易日：{start} / {end}")
    start_pos, end_pos = days.index(start), days.index(end)
    if end_pos < start_pos:
        raise ValueError("end 不能早于 start")
    # close 入场当日可买；还需 hold 个可卖日完成退出。
    need = max(1, hold)
    if end_pos - start_pos < need:
        raise ValueError(f"窗口至少需要 {need} 个交易日完成退出")
    signal_end = days[end_pos - need]
    load_start = days[max(0, start_pos - warmup)]
    return load_start, end, signal_end


def _select_top(
    candidates: pd.DataFrame, score: pd.DataFrame, *, top_n: int | None, ascending: bool
) -> pd.DataFrame:
    """在候选掩码内按 score 取每日 top_n；top_n=None 保留全部候选。"""
    mask = candidates.fillna(False).astype(bool)
    if top_n is None:
        return mask
    ranked = score.where(mask)
    # ascending=True → 越小越好，用 rank ascending；否则越大越好。
    order = ranked.rank(axis=1, ascending=ascending, method="first")
    return (mask & order.le(int(top_n))).fillna(False)


def _portfolio_metrics(frame: pd.DataFrame, *, top_n: int | None) -> dict[str, Any]:
    evaluable = frame[frame["exit_reason"] != "data_end"].copy()
    if evaluable.empty:
        return {
            "portfolio_groups": 0,
            "portfolio_return_pct": None,
            "portfolio_max_drawdown_pct": None,
        }
    # TopN：日仓位按当日完成笔数等权；等价于 sum/n。
    group = evaluable.groupby("signal_date", sort=True)["net_return_pct"].mean()
    equity = (1.0 + group / 100.0).cumprod()
    drawdown = equity / equity.cummax() - 1.0
    wins, losses = group[group > 0], group[group <= 0]
    avg_win = float(wins.mean()) if not wins.empty else None
    avg_loss = float(losses.mean()) if not losses.empty else None
    pf = wins.sum() / abs(losses.sum()) if not losses.empty and losses.sum() else None
    return {
        "portfolio_groups": int(len(group)),
        "portfolio_win_rate_pct": round(float((group > 0).mean() * 100), 2),
        "portfolio_payoff_ratio": (
            None if avg_win is None or not avg_loss else round(avg_win / abs(avg_loss), 4)
        ),
        "portfolio_profit_factor": None if pf is None else round(float(pf), 4),
        "portfolio_return_pct": round(float((equity.iloc[-1] - 1.0) * 100), 4),
        "portfolio_max_drawdown_pct": round(float(drawdown.min() * 100), 4),
        "avg_positions_per_group": round(float(evaluable.groupby("signal_date").size().mean()), 2),
        "top_n": top_n if top_n is not None else "all",
    }


def _score_panels(qfq: dict[str, pd.DataFrame]) -> dict[str, tuple[pd.DataFrame, bool]]:
    """name -> (score_panel, ascending)。ascending=True 表示越小越好。"""
    close, high, low, volume = qfq["close"], qfq["high"], qfq["low"], qfq["volume"]
    turnover = qfq["turnover"]
    spread = (high - low).replace(0, np.nan)
    clv = (2 * close - high - low) / spread
    roc5 = close / REF(close, 5)
    roc1 = close / REF(close, 1)
    vol_ratio = volume / volume.rolling(20, min_periods=5).mean()
    pos60 = close / close.rolling(60, min_periods=20).max()
    roc5_vol = roc5 * vol_ratio
    return {
        "roc5": (roc5, False),
        "roc1": (roc1, False),
        "vol_ratio": (vol_ratio, False),
        "turnover": (turnover, False),
        "turnover_asc": (turnover, True),
        "clv": (clv, False),
        "clv_asc": (clv, True),
        "pos60_asc": (pos60, True),
        "roc5_vol": (roc5_vol, False),
    }


def _write_report(
    output_dir: Path,
    *,
    summary: dict[str, Any],
    rows: list[dict[str, Any]],
) -> None:
    output_dir.mkdir(parents=True, exist_ok=True)
    compare = pd.DataFrame(rows)
    compare.to_csv(output_dir / "compare.csv", index=False, encoding="utf-8-sig")
    (output_dir / "summary.json").write_text(
        json.dumps(_json_safe(summary), ensure_ascii=False, indent=2), encoding="utf-8"
    )
    # 主排序：平均净收益 → PF → 组合收益
    ranked = compare.sort_values(
        ["avg_net_return_pct", "profit_factor", "portfolio_return_pct"],
        ascending=[False, False, False],
        na_position="last",
    )
    lines = [
        "# 潜龙尾盘 V1 · 排分因子 × TopN 对照",
        "",
        "- 信号：潜龙 V3 条件 + 价≥10 + 换手 2%–8% + 非涨停；**先出全量候选，再按排分取 TopN**。",
        "- 成交：T 日收盘；退出：T+1（止盈 +3% / 止损 -6%，同日先止损）。",
        f"- 信号窗口：{summary['start']} 至 {summary['signal_end']}"
        f"（请求结束日 {summary['end']}）。",
        "- 股票池：主板+创业板，剔 ST/退市/停牌/上市不足 60 日。",
        f"- 成本：往返约 {summary['round_trip_cost_pct']:.2f}%"
        "（佣金 0.03%×2 + 印花税 0.05% + 滑点 0.10%×2）。",
        f"- 数据：`{summary['db_label']}`；行情末日 `{summary['data_last_date']}`；幸存者偏差。",
        "- 组合收益：信号日等权复利（TopN 当日多票均分）。",
        f"- 基线候选信号日：{summary['candidate_signal_days']}；"
        f"原始候选笔数：{summary['candidate_signals']}。",
        "",
        "## 对照总表（按平均净收益）",
        "",
        "| 方案 | 完成交易 | 胜率 | 平均净收益 | 平均盈亏比 | PF | 组合收益 | 组合回撤 | 有信号日 | 日均票 |",
        "|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|",
    ]
    for row in ranked.to_dict("records"):
        lines.append(
            "| {group} | {trades} | {win_rate_pct}% | {avg_net_return_pct}% | "
            "{payoff_ratio} | {profit_factor} | {portfolio_return_pct}% | "
            "{portfolio_max_drawdown_pct}% | {signal_days} | {avg_positions_per_group} |".format(
                group=row.get("group", ""),
                trades=row.get("trades", 0),
                win_rate_pct=row.get("win_rate_pct", "-"),
                avg_net_return_pct=row.get("avg_net_return_pct", "-"),
                payoff_ratio=row.get("payoff_ratio", "-"),
                profit_factor=row.get("profit_factor", "-"),
                portfolio_return_pct=row.get("portfolio_return_pct", "-"),
                portfolio_max_drawdown_pct=row.get("portfolio_max_drawdown_pct", "-"),
                signal_days=row.get("signal_days", "-"),
                avg_positions_per_group=row.get("avg_positions_per_group", "-"),
            )
        )

    baseline = next((r for r in rows if "现行基线" in str(r.get("group", ""))), None)
    best = ranked.iloc[0].to_dict() if not ranked.empty else {}
    lines.extend(["", "## 结论（收益率优先）", ""])
    if baseline:
        lines.append(
            f"- **现行基线** ROC5×Top1：净收益 {baseline.get('avg_net_return_pct')}%，"
            f"盈亏比 {baseline.get('payoff_ratio')}，PF {baseline.get('profit_factor')}，"
            f"组合 {baseline.get('portfolio_return_pct')}%"
            f"（n={baseline.get('trades')}，有信号日 {baseline.get('signal_days')}）。"
        )
    if best:
        better = (
            baseline is None
            or (best.get("avg_net_return_pct") or -999)
            > (baseline.get("avg_net_return_pct") or -999) + 1e-9
        )
        lines.append(
            f"- **对照最优**：{best.get('group')} → 净收益 {best.get('avg_net_return_pct')}%，"
            f"盈亏比 {best.get('payoff_ratio')}，PF {best.get('profit_factor')}，"
            f"组合 {best.get('portfolio_return_pct')}%"
            f"（n={best.get('trades')}）。"
            + ("相对基线有提升。" if better else "未超过基线净收益。")
        )
    # TopN 敏感性（仅 ROC5）
    roc5_rows = [r for r in rows if str(r.get("rank_key")) == "roc5"]
    if roc5_rows:
        lines.extend(["", "### ROC5 的 TopN 敏感性", ""])
        for r in sorted(roc5_rows, key=lambda x: (x.get("top_n") is None, x.get("top_n") or 0)):
            lines.append(
                f"- {r.get('group')}：净收益 {r.get('avg_net_return_pct')}% / "
                f"PF {r.get('profit_factor')} / 组合 {r.get('portfolio_return_pct')}% / "
                f"日均票 {r.get('avg_positions_per_group')}"
            )
    lines.extend(
        [
            "",
            "## 产物",
            "",
            "- `report.md` / `compare.csv` / `summary.json`",
            "- `baseline-trades.csv`：ROC5×Top1 逐笔",
            "- `best-trades.csv`：对照最优方案逐笔",
            "",
        ]
    )
    (output_dir / "report.md").write_text("\n".join(lines), encoding="utf-8")


def run(args: argparse.Namespace) -> dict[str, Any]:
    assert len(VARIANTS) >= 10, "对照组合不足 10 种"
    db_path = Path(args.db).expanduser().resolve()
    config = BacktestConfig(
        hold_days=1,
        stop_loss_pct=-6.0,
        take_profit_pct=3.0,
        commission_bps=3.0,
        stamp_duty_bps=5.0,
        slippage_bps=10.0,
        benchmark=None,
    )
    with _read_only_connection(db_path) as conn:
        days = _load_days(conn)
        load_start, load_end, signal_end = _date_window(
            days, args.start, args.end, hold=config.hold_days, warmup=80
        )
        codes, meta = _load_universe(conn, as_of=args.end, boards={"main", "chi_next"})
        qfq, raw = _load_panels(
            conn, load_start=load_start, load_end=load_end, dates=days, codes=codes
        )
        data_last_date = str(qfq["close"].index[-1])

    names = {code: meta[code]["name"] for code in codes if code in meta}
    signal_panels = dict(qfq)
    signal_panels["__instrument_names__"] = names  # type: ignore[assignment]
    attach_raw_limit_close(
        _PanelStore(raw["close"]),
        signal_panels,
        enabled=True,
        adjust="qfq",
        codes=codes,
        start=load_start,
        end=load_end,
        min_bars=46,
    )

    # 尾盘参数：V3 + price_min=10，先出全量候选。
    base_engine = QianlongCloseePickerV3()
    params = {**base_engine.default_params(), "price_min": 10.0}
    base = base_engine.compute(signal_panels, params)
    candidates = base.signals.fillna(False).astype(bool)
    signal_mask = (candidates.index >= args.start) & (candidates.index <= signal_end)
    candidates = candidates.copy()
    candidates.loc[~signal_mask, :] = False
    panel_index = raw["close"].index
    scores = _score_panels(qfq)

    candidate_signals = int(candidates.to_numpy(dtype=bool).sum())
    candidate_days = int(candidates.any(axis=1).sum())
    print(f"base candidates: signals={candidate_signals} days={candidate_days}")

    rows: list[dict[str, Any]] = []
    trades_cache: dict[str, pd.DataFrame] = {}
    for label, key, top_n in VARIANTS:
        score_panel, ascending = scores[key]
        selected = _select_top(candidates, score_panel, top_n=top_n, ascending=ascending)
        selected = selected.reindex(index=panel_index, columns=raw["close"].columns).fillna(False)
        backtest = run_backtest(
            selected,
            raw,  # 未复权成交
            entry_timing="close",
            config=config,
            strategy_slug=f"qianlong-tail-rank:{key}:top{top_n}",
        )
        trades = backtest.to_frame()
        metric = _metrics(trades, label=label)
        metric.update(_portfolio_metrics(trades, top_n=top_n))
        metric.update(
            {
                "rank_key": key,
                "top_n": top_n,
                "ascending": ascending,
                "candidate_signals": int(selected.to_numpy(dtype=bool).sum()),
                "signal_days": int(selected.any(axis=1).sum()),
                "skipped": backtest.skipped,
            }
        )
        rows.append(metric)
        trades_cache[label] = trades
        print(
            f"{label}: n={metric.get('trades')} avg={metric.get('avg_net_return_pct')} "
            f"pf={metric.get('profit_factor')} port={metric.get('portfolio_return_pct')}"
        )

    output_dir = Path(args.output).expanduser().resolve()
    output_dir.mkdir(parents=True, exist_ok=True)
    baseline_label = "ROC5×Top1（现行基线）"
    trades_cache[baseline_label].to_csv(
        output_dir / "baseline-trades.csv", index=False, encoding="utf-8-sig"
    )
    best_label = max(
        rows,
        key=lambda r: (
            r.get("avg_net_return_pct") is not None,
            r.get("avg_net_return_pct") or -999,
            r.get("profit_factor") or -999,
        ),
    )["group"]
    trades_cache[best_label].to_csv(
        output_dir / "best-trades.csv", index=False, encoding="utf-8-sig"
    )

    summary = {
        "strategy": "qianlong-tail-v1 rank×topN research",
        "timing": "T日收盘买入 -> T+1 止盈3%/止损6%/收盘退出",
        "start": args.start,
        "end": args.end,
        "signal_end": signal_end,
        "load_start": load_start,
        "data_last_date": data_last_date,
        "universe_codes": len(codes),
        "candidate_signals": candidate_signals,
        "candidate_signal_days": candidate_days,
        "round_trip_cost_pct": config.round_trip_cost_pct(),
        "config": asdict(config),
        "db_label": str(db_path),
        "variants": rows,
        "variant_count": len(rows),
        "notes": [
            "候选池为尾盘条件全量（未截断）；各方案仅改排分与 TopN。",
            "完成交易排除 data_end。",
            "组合收益按信号日等权复利。",
        ],
    }
    _write_report(output_dir, summary=summary, rows=rows)
    print(f"REPORT_DIR={output_dir}")
    return summary


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--db", default=os.environ.get("PALACE_MARKET_DB") or str(DEFAULT_DB))
    parser.add_argument("--start", default="2026-02-02")
    parser.add_argument("--end", default="2026-07-31")
    parser.add_argument(
        "--output",
        default="output/qianlong-tail-rank-2026-02-02_2026-07-31",
    )
    return parser


if __name__ == "__main__":
    run(build_parser().parse_args())
