"""三源尾盘共振半年分层研究。

研究口径固定为：T 日收盘后 15:30 选股，T+1 开盘成交，T+2 收盘退出。
脚本只读外部 market.db，信号由已注册的 SanyuanTailResonance 计算，
不在研究脚本中复制公式条件。
"""
from __future__ import annotations

import argparse
from dataclasses import asdict
import json
import os
from pathlib import Path
import sqlite3
from typing import Any, Iterable

import numpy as np
import pandas as pd

if __package__ in {None, ""}:
    import sys

    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.backtest.application.engine import BacktestConfig, run_backtest
from src.market.domain.universe import classify_board, is_delisting_name, is_st_name
from src.market.infrastructure.store_schema import DEFAULT_DB
from src.strategy.application.tail_resonance import SanyuanTailResonance


PRICE_FIELDS = ("open", "high", "low", "close")
RAW_FIELDS = ("volume", "turnover", "outstanding_share")
ALL_FIELDS = PRICE_FIELDS + RAW_FIELDS


def _read_only_connection(path: Path) -> sqlite3.Connection:
    uri = f"file:{path.resolve().as_posix()}?mode=ro"
    return sqlite3.connect(uri, uri=True)


def _load_days(conn: sqlite3.Connection) -> list[str]:
    try:
        rows = conn.execute("SELECT trade_date FROM trading_calendar ORDER BY trade_date").fetchall()
    except sqlite3.OperationalError:
        rows = []
    days = [str(row[0]) for row in rows]
    if days:
        return days
    rows = conn.execute(
        "SELECT DISTINCT trade_date FROM quotes_daily ORDER BY trade_date"
    ).fetchall()
    return [str(row[0]) for row in rows]


def _load_universe(
    conn: sqlite3.Connection, *, as_of: str, boards: set[str]
) -> tuple[list[str], dict[str, dict[str, str]]]:
    rows = conn.execute(
        """
        SELECT code, name, list_date, delist_date, status, instrument_type
        FROM instruments
        WHERE instrument_type = 'STOCK'
        """
    ).fetchall()
    as_of_date = pd.Timestamp(as_of)
    codes: list[str] = []
    meta: dict[str, dict[str, str]] = {}
    for row in rows:
        code = str(row[0]).zfill(6)
        name = str(row[1] or "")
        board = classify_board(code)
        if board not in boards or is_st_name(name):
            continue
        if str(row[4] or "normal") in {"suspended", "delisted"}:
            continue
        if is_delisting_name(name):
            continue
        list_date = str(row[2] or "")[:10]
        if list_date:
            try:
                if (as_of_date - pd.Timestamp(list_date)).days < 60:
                    continue
            except ValueError:
                pass
        codes.append(code)
        meta[code] = {"board": board, "name": name}
    return sorted(set(codes)), meta


def _date_window(days: list[str], start: str, end: str, warmup: int) -> tuple[str, str, str]:
    if start not in days or end not in days:
        raise ValueError(f"回测日期必须是行情交易日：{start} / {end}")
    start_pos = days.index(start)
    end_pos = days.index(end)
    if end_pos < start_pos:
        raise ValueError("end 不能早于 start")
    load_start = days[max(0, start_pos - warmup)]
    if end_pos - start_pos < 2:
        raise ValueError("窗口至少需要两个交易日用于 T+1 入场、T+2 退出")
    signal_end = days[end_pos - 2]
    return load_start, end, signal_end


def _panel_from_flat(
    flat: pd.DataFrame, *, dates: pd.Index, codes: list[str]
) -> dict[str, pd.DataFrame]:
    panels: dict[str, pd.DataFrame] = {}
    for field in ALL_FIELDS:
        panel = flat.pivot(index="trade_date", columns="code", values=field)
        panel.index = panel.index.astype(str)
        panel.columns = panel.columns.astype(str).str.zfill(6)
        panels[field] = panel.reindex(index=dates, columns=codes).sort_index()
    return panels


def _load_panels(
    conn: sqlite3.Connection,
    *,
    load_start: str,
    load_end: str,
    dates: list[str],
    codes: list[str],
) -> tuple[dict[str, pd.DataFrame], dict[str, pd.DataFrame]]:
    fields = ", ".join(["trade_date", "code", *ALL_FIELDS])
    flat = pd.read_sql_query(
        f"SELECT {fields} FROM quotes_daily WHERE trade_date >= ? AND trade_date <= ?",
        conn,
        params=[load_start, load_end],
    )
    flat["code"] = flat["code"].astype(str).str.zfill(6)
    flat = flat[flat["code"].isin(set(codes))]
    date_index = pd.Index([day for day in dates if load_start <= day <= load_end], name="trade_date")
    raw = _panel_from_flat(flat, dates=date_index, codes=codes)

    factor_flat = pd.read_sql_query(
        "SELECT code, trade_date, hfq_factor FROM adjust_factors WHERE trade_date <= ?",
        conn,
        params=[load_end],
    )
    factor_flat["code"] = factor_flat["code"].astype(str).str.zfill(6)
    factor_flat = factor_flat[factor_flat["code"].isin(set(codes))]
    if factor_flat.empty:
        ratio = pd.DataFrame(1.0, index=date_index, columns=codes)
    else:
        sparse = factor_flat.pivot(index="trade_date", columns="code", values="hfq_factor")
        sparse.index = sparse.index.astype(str)
        sparse.columns = sparse.columns.astype(str).str.zfill(6)
        aligned = (
            sparse.reindex(sparse.index.union(date_index))
            .sort_index()
            .ffill()
            .bfill()
            .reindex(date_index)
            .reindex(columns=codes)
            .astype(float)
            .fillna(1.0)
        )
        latest = aligned.iloc[-1].replace(0.0, 1.0)
        ratio = aligned.div(latest, axis=1)
    adjusted = {field: raw[field].copy() for field in ALL_FIELDS}
    for field in PRICE_FIELDS:
        adjusted[field] = raw[field] * ratio
    return adjusted, raw


def _bool_panel(panel: pd.DataFrame) -> pd.DataFrame:
    return panel.fillna(False).astype(bool)


def _band(value: Any, bands: Iterable[tuple[float, str]], missing: str = "缺失") -> str:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return missing
    if not np.isfinite(number):
        return missing
    for upper, label in bands:
        if number < upper:
            return label
    return list(bands)[-1][1]


def _gap_band(value: Any) -> str:
    return _band(
        value,
        [
            (-0.03, "低开>3%"),
            (-0.01, "低开1%-3%"),
            (0.01, "平开±1%"),
            (0.03, "高开1%-3%"),
            (float("inf"), "高开>3%"),
        ],
    )


def _scalar(panel: pd.DataFrame, date: str, code: str) -> float:
    try:
        value = panel.at[date, code]
    except (KeyError, TypeError):
        return float("nan")
    try:
        return float(value)
    except (TypeError, ValueError):
        return float("nan")


def _metrics(frame: pd.DataFrame, *, label: str) -> dict[str, Any]:
    if frame.empty:
        return {"group": label, "trades": 0, "sample_warning": "无完成交易"}
    evaluable = frame[frame["exit_reason"] != "data_end"].copy()
    net = pd.to_numeric(evaluable["net_return_pct"], errors="coerce").dropna()
    if net.empty:
        return {
            "group": label,
            "trades": 0,
            "data_end_trades": int(len(frame)),
            "sample_warning": "没有完成交易",
        }
    wins = net[net > 0]
    losses = net[net <= 0]
    avg_win = float(wins.mean()) if not wins.empty else None
    avg_loss = float(losses.mean()) if not losses.empty else None
    payoff = avg_win / abs(avg_loss) if avg_win is not None and avg_loss else None
    pf = wins.sum() / abs(losses.sum()) if not losses.empty and losses.sum() else None
    return {
        "group": label,
        "trades": int(len(net)),
        "wins": int(len(wins)),
        "losses": int(len(losses)),
        "win_rate_pct": round(float((net > 0).mean() * 100), 2),
        "avg_net_return_pct": round(float(net.mean()), 4),
        "median_net_return_pct": round(float(net.median()), 4),
        "avg_win_pct": None if avg_win is None else round(avg_win, 4),
        "avg_loss_pct": None if avg_loss is None else round(avg_loss, 4),
        "payoff_ratio": None if payoff is None else round(payoff, 4),
        "profit_factor": None if pf is None else round(float(pf), 4),
        "best_pct": round(float(net.max()), 4),
        "worst_pct": round(float(net.min()), 4),
        "data_end_trades": int(len(frame) - len(net)),
        "sample_warning": "样本<30，仅作观察" if len(net) < 30 else "",
    }


def _portfolio_metrics(frame: pd.DataFrame) -> dict[str, Any]:
    evaluable = frame[frame["exit_reason"] != "data_end"].copy()
    if evaluable.empty:
        return {"portfolio_groups": 0}
    # 严格两仓：每个信号日最多两只、每只占 50%；只有一只时剩余资金留现金。
    group = evaluable.groupby("signal_date", sort=True)["net_return_pct"].sum() / 2.0
    equity = (1.0 + group / 100.0).cumprod()
    drawdown = equity / equity.cummax() - 1.0
    wins = group[group > 0]
    losses = group[group <= 0]
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
    }


def _variant_signals(
    candidates: pd.DataFrame, rank: pd.DataFrame, *, top_n: int | None
) -> pd.DataFrame:
    if top_n is None:
        return candidates.copy()
    return (candidates & rank.le(top_n)).fillna(False)


def _enrich_trades(
    trades: pd.DataFrame,
    *,
    qfq: dict[str, pd.DataFrame],
    raw: dict[str, pd.DataFrame],
    factors: dict[str, pd.DataFrame],
    meta: dict[str, dict[str, str]],
    breadth: pd.Series,
) -> pd.DataFrame:
    if trades.empty:
        return trades
    close = qfq["close"]
    high = qfq["high"]
    low = qfq["low"]
    spread = high - low
    clv = ((2 * close - high - low) / spread).where(spread != 0)
    r1 = close / close.shift(1) - 1.0
    r5 = close / close.shift(5) - 1.0
    r20 = close / close.shift(20) - 1.0
    volume_ratio = raw["volume"] / raw["volume"].rolling(20).mean()
    position20 = close / close.rolling(20).max()
    position60 = close / close.rolling(60).max()
    branches = ["A_MA25突破", "B_双阴反包", "C_双子K"]
    rows: list[dict[str, Any]] = []
    for record in trades.to_dict("records"):
        date = str(record["signal_date"])
        code = str(record["code"]).zfill(6)
        branch_hits = [name for name in branches if bool(_scalar(factors[name], date, code))]
        branch_label = "+".join(branch_hits) if branch_hits else "未知"
        signal_close = _scalar(raw["close"], date, code)
        entry_open = _scalar(raw["open"], str(record["entry_date"]), code)
        gap = entry_open / signal_close - 1.0 if signal_close > 0 and np.isfinite(entry_open) else np.nan
        turn = _scalar(raw["turnover"], date, code)
        shares = _scalar(raw["outstanding_share"], date, code)
        market_cap = signal_close * shares if signal_close > 0 and shares > 0 else np.nan
        row = {
            **record,
            "rank": _scalar(factors["每日前二"], date, code),
            "score": _scalar(factors["横截面评分"], date, code),
            "signal_return_1": _scalar(r1, date, code),
            "signal_return_5": _scalar(r5, date, code),
            "signal_return_20": _scalar(r20, date, code),
            "clv": _scalar(clv, date, code),
            "volume_ratio": _scalar(volume_ratio, date, code),
            "position20": _scalar(position20, date, code),
            "position60": _scalar(position60, date, code),
            "turnover": turn,
            "market_cap_yuan": market_cap,
            "next_open_gap": gap,
            "branch": branch_label,
            "board": meta.get(code, {}).get("board", classify_board(code)),
            "breadth_up_pct": _scalar(breadth.to_frame("value"), date, "value"),
        }
        row["gap_band"] = _gap_band(gap)
        row["clv_band"] = _band(
            row["clv"], [(0.0, "低位收盘<0"), (0.5, "中位收盘0-0.5"), (float("inf"), "高位收盘≥0.5")]
        )
        row["position60_band"] = _band(
            row["position60"], [(0.7, "低位≤70%"), (0.9, "中位70%-90%"), (float("inf"), "高位>90%")]
        )
        row["turnover_band"] = _band(
            turn,
            [
                (0.02, "<2%"),
                (0.05, "2%-5%"),
                (0.08, "5%-8%"),
                (0.12, "8%-12%"),
                (0.20, "12%-20%"),
                (float("inf"), "≥20%"),
            ],
        )
        row["market_cap_band"] = _band(
            market_cap / 1e8 if np.isfinite(market_cap) else np.nan,
            [(50.0, "<50亿"), (100.0, "50-100亿"), (300.0, "100-300亿"), (1000.0, "300-1000亿"), (float("inf"), "≥1000亿")],
        )
        row["signal_return_band"] = _band(
            row["signal_return_1"], [(-0.03, "跌>3%"), (0.0, "跌0-3%"), (0.03, "涨0-3%"), (0.07, "涨3%-7%"), (float("inf"), "涨≥7%")]
        )
        row["breadth_band"] = _band(
            row["breadth_up_pct"], [(0.4, "上涨<40%"), (0.6, "上涨40%-60%"), (float("inf"), "上涨≥60%")]
        )
        row["rank_group"] = "第1名" if row["rank"] == 1 else ("第2名" if row["rank"] == 2 else "第2名以外")
        rows.append(row)
    return pd.DataFrame(rows)


def _layer_rows(trades: pd.DataFrame) -> list[dict[str, Any]]:
    dimensions = [
        ("次日开盘缺口", "gap_band"),
        ("信号日收盘位置", "clv_band"),
        ("60日位置", "position60_band"),
        ("换手率", "turnover_band"),
        ("市值", "market_cap_band"),
        ("信号日涨幅", "signal_return_band"),
        ("公式分支", "branch"),
        ("板块", "board"),
        ("市场宽度", "breadth_band"),
        ("top2排名", "rank_group"),
    ]
    rows: list[dict[str, Any]] = []
    for dimension, column in dimensions:
        if column not in trades:
            continue
        for value, group in trades.groupby(column, dropna=False, sort=True):
            label = "缺失" if pd.isna(value) else str(value)
            row = _metrics(group, label=label)
            row.update({"dimension": dimension, "value": label})
            rows.append(row)
    return rows


def _json_safe(value: Any) -> Any:
    if isinstance(value, dict):
        return {str(k): _json_safe(v) for k, v in value.items()}
    if isinstance(value, list):
        return [_json_safe(v) for v in value]
    if isinstance(value, (np.integer, np.floating)):
        value = value.item()
    if isinstance(value, float) and (np.isnan(value) or np.isinf(value)):
        return None
    return value


def _write_report(
    output_dir: Path,
    *,
    summary: dict[str, Any],
    topn: list[dict[str, Any]],
    layers: list[dict[str, Any]],
    trades: pd.DataFrame,
) -> None:
    output_dir.mkdir(parents=True, exist_ok=True)
    (output_dir / "summary.json").write_text(
        json.dumps(_json_safe(summary), ensure_ascii=False, indent=2), encoding="utf-8"
    )
    (output_dir / "topn.csv").write_text(pd.DataFrame(topn).to_csv(index=False), encoding="utf-8-sig")
    (output_dir / "layers.csv").write_text(pd.DataFrame(layers).to_csv(index=False), encoding="utf-8-sig")
    if not trades.empty:
        trades.to_csv(output_dir / "top2-trades.csv", index=False, encoding="utf-8-sig")
    lines = [
        "# 三源尾盘共振半年分层回测",
        "",
        f"- 信号时点：收盘后 15:30；成交：T+1 开盘；退出：T+2 收盘。",
        f"- 信号窗口：{summary['start']} 至 {summary['signal_end']}（原始请求窗口结束日为 {summary['end']}，最后两日不计入完成交易）。",
        f"- 股票池：主板+创业板，剔 ST/退市/停牌/上市不足 60 日；V2 先按评分取原始 top2，再应用后置闸门，不递补第三名。",
        f"- 成本：买卖佣金各 0.03%，卖出印花税 0.05%，买卖滑点各 0.10%。",
        f"- 数据：只读 `{summary['db_label']}`；行情最后日期 `{summary['data_last_date']}`；当前上市股票存在幸存者偏差。",
        "",
        "## TopN 对照",
        "",
        "| 方案 | 完成交易 | 胜率 | 平均净收益 | 平均盈亏比 | Profit Factor | 组合收益 | 组合回撤 |",
        "|---|---:|---:|---:|---:|---:|---:|---:|",
    ]
    for row in topn:
        lines.append(
            "| {group} | {trades} | {win_rate_pct}% | {avg_net_return_pct}% | {payoff_ratio} | {profit_factor} | {portfolio_return_pct}% | {portfolio_max_drawdown_pct}% |".format(
                group=row.get("group", ""),
                trades=row.get("trades", 0),
                win_rate_pct=row.get("win_rate_pct", "-"),
                avg_net_return_pct=row.get("avg_net_return_pct", "-"),
                payoff_ratio=row.get("payoff_ratio", "-"),
                profit_factor=row.get("profit_factor", "-"),
                portfolio_return_pct=row.get("portfolio_return_pct", "-"),
                portfolio_max_drawdown_pct=row.get("portfolio_max_drawdown_pct", "-"),
            )
        )
    lines.extend(["", "## 分层明细", "", "完整分层见 `layers.csv`；样本小于 30 的组只作观察。", ""])
    for dimension in sorted({str(row["dimension"]) for row in layers}):
        lines.extend([f"### {dimension}", "", "| 分组 | 样本 | 胜率 | 平均净收益 | 平均盈亏比 | PF |", "|---|---:|---:|---:|---:|---:|"])
        for row in [item for item in layers if item["dimension"] == dimension]:
            lines.append(
                f"| {row['value']} | {row.get('trades', 0)} | {row.get('win_rate_pct', '-')}% | {row.get('avg_net_return_pct', '-')}% | {row.get('payoff_ratio', '-')} | {row.get('profit_factor', '-')} |"
            )
        lines.append("")
    (output_dir / "report.md").write_text("\n".join(lines), encoding="utf-8")


def run(args: argparse.Namespace) -> dict[str, Any]:
    db_path = Path(args.db).expanduser().resolve()
    engine = SanyuanTailResonance()
    config = BacktestConfig(
        hold_days=1,
        stop_loss_pct=None,
        take_profit_pct=None,
        commission_bps=3.0,
        stamp_duty_bps=5.0,
        slippage_bps=10.0,
        benchmark=None,
    )
    with _read_only_connection(db_path) as conn:
        days = _load_days(conn)
        load_start, load_end, signal_end = _date_window(days, args.start, args.end, engine.warmup_bars)
        codes, meta = _load_universe(conn, as_of=args.end, boards={"main", "chi_next"})
        qfq, raw = _load_panels(
            conn,
            load_start=load_start,
            load_end=load_end,
            dates=days,
            codes=codes,
        )
        data_last_date = str(qfq["close"].index[-1])

    result = engine.compute(qfq)
    factors = result.factors
    candidates = _bool_panel(factors["三源候选"])
    score = factors["横截面评分"]
    rank = score.where(candidates).rank(axis=1, ascending=False, method="first")
    signal_mask = (candidates.index >= args.start) & (candidates.index <= signal_end)
    panel_index = raw["close"].index
    breadth_values = (qfq["close"] > qfq["close"].shift(1)).sum(axis=1) / qfq["close"].notna().sum(axis=1)
    breadth_values = breadth_values.replace([np.inf, -np.inf], np.nan)

    topn_specs: list[tuple[str, int | None]] = [("V2后置Top2", None), ("原始Top1", 1), ("原始Top2", 2), ("原始Top3", 3), ("原始Top5", 5), ("原始Top10", 10), ("全部候选", None)]
    topn_rows: list[dict[str, Any]] = []
    default_trades = pd.DataFrame()
    for label, top_n in topn_specs:
        selected = factors["每日前二"].copy() if label == "V2后置Top2" else _variant_signals(candidates, rank, top_n=top_n)
        selected.loc[~signal_mask, :] = False
        backtest = run_backtest(
            selected.reindex(index=panel_index, columns=raw["close"].columns).fillna(False),
            raw,
            entry_timing=engine.entry_timing,
            config=config,
            strategy_slug=engine.slug,
        )
        trades = backtest.to_frame()
        row = _metrics(trades, label=label)
        row.update(_portfolio_metrics(trades))
        row.update(
            {
                "candidate_signals": int(selected.loc[signal_mask].to_numpy(dtype=bool).sum()),
                "signal_days": int(selected.loc[signal_mask].any(axis=1).sum()),
                "skipped": backtest.skipped,
            }
        )
        topn_rows.append(row)
        if label == "V2后置Top2":
            default_trades = _enrich_trades(
                trades,
                qfq=qfq,
                raw=raw,
                factors={
                    **factors,
                    "每日前二": rank,
                },
                meta=meta,
                breadth=breadth_values,
            )

    rank_rows: list[dict[str, Any]] = []
    for label, mask in (
        ("第1名", rank.eq(1)),
        ("第2名", rank.eq(2)),
        ("top2累计", rank.le(2)),
        ("top2以外", candidates & rank.gt(2)),
    ):
        selected = mask.fillna(False)
        selected.loc[~signal_mask, :] = False
        backtest = run_backtest(
            selected.reindex(index=panel_index, columns=raw["close"].columns).fillna(False),
            raw,
            entry_timing=engine.entry_timing,
            config=config,
            strategy_slug=engine.slug,
        )
        row = _metrics(backtest.to_frame(), label=label)
        row.update(_portfolio_metrics(backtest.to_frame()))
        rank_rows.append(row)

    layers = _layer_rows(default_trades)
    summary = {
        "strategy": engine.slug,
        "timing": "T日收盘后15:30选股 -> T+1开盘买入 -> T+2收盘卖出",
        "start": args.start,
        "end": args.end,
        "signal_end": signal_end,
        "load_start": load_start,
        "data_last_date": data_last_date,
        "universe_codes": len(codes),
        "config": asdict(config),
        "db_label": str(db_path),
        "topn": topn_rows,
        "rank_comparison": rank_rows,
        "top2_layers": layers,
        "notes": [
            "完成交易统计排除 data_end；窗口最后两个交易日不能完成 T+1 入场、T+2 退出。",
            "组合收益按每个信号日最多两仓各 50% 顺序复利；只有一只完成交易时另一半留现金。",
            "市值使用信号日未复权收盘价乘 outstanding_share；缺失股本的样本单列缺失。",
            "数据库是当前上市股票集合，存在幸存者偏差；日线收盘后 15:30 口径无法验证真实尾盘竞价成交。",
        ],
    }
    output_dir = Path(args.output).expanduser().resolve()
    _write_report(
        output_dir,
        summary=summary,
        topn=topn_rows + rank_rows,
        layers=layers,
        trades=default_trades,
    )
    print(json.dumps(_json_safe(summary), ensure_ascii=False, indent=2))
    print(f"REPORT_DIR={output_dir}")
    return summary


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--db", default=os.environ.get("PALACE_MARKET_DB") or str(DEFAULT_DB))
    parser.add_argument("--start", default="2026-02-02")
    parser.add_argument("--end", default="2026-07-31")
    parser.add_argument(
        "--output",
        default="output/sanyuan-tail-resonance-2026-02-02_2026-07-31",
    )
    return parser


if __name__ == "__main__":
    run(build_parser().parse_args())
