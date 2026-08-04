"""潜龙出海 v1/v2/v3 结构研究（对齐三元尾盘共振报告标准）。

口径：T 日收盘出信号，T+1 开盘成交，持有 N 个可卖日后收盘退出。
成本与三元研究一致：佣金双边各 0.03%、卖出印花税 0.05%、滑点双边各 0.10%。
产物：report.md / layers.csv / summary.json / trades.csv。
"""
from __future__ import annotations

import argparse
from dataclasses import asdict
import importlib.util
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
from src.market.infrastructure.store_schema import DEFAULT_DB
from src.strategy.application.price_constraints import attach_raw_limit_close
from src.strategy.application.qianlong import QianlongCloseePickerV3, select_one_per_day
from src.strategy.domain import base as strategy_base
from src.formula import REF
from scripts.sanyuan_tail_resonance_research import (
    _band,
    _gap_band,
    _json_safe,
    _load_days,
    _load_panels,
    _load_universe,
    _metrics,
    _read_only_connection,
    _scalar,
)

HOLDS_PRIMARY = 3
VERSIONS = ("v1", "v2", "v3")


class _PanelStore:
    """给 attach_raw_limit_close 提供 load_panel 适配。"""

    def __init__(self, raw_close: pd.DataFrame) -> None:
        self._raw_close = raw_close

    def load_panel(self, **kwargs: Any) -> dict[str, pd.DataFrame]:
        return {"close": self._raw_close}


def _load_legacy() -> tuple[Any, Any]:
    path = PROJECT_ROOT / "src/strategy/application/backup/qianlong-legacy.py"
    spec = importlib.util.spec_from_file_location("_qianlong_legacy_src", path)
    if spec is None or spec.loader is None:
        raise ImportError(f"无法加载 {path}")
    module = importlib.util.module_from_spec(spec)
    original = strategy_base.register
    strategy_base.register = lambda engine: engine
    try:
        spec.loader.exec_module(module)
    finally:
        strategy_base.register = original
    return module.QianlongCloseePicker(), module.QianlongCloseePickerV2()


def _date_window(days: list[str], start: str, end: str, *, hold: int, warmup: int) -> tuple[str, str, str]:
    if start not in days or end not in days:
        raise ValueError(f"回测日期必须是行情交易日：{start} / {end}")
    start_pos, end_pos = days.index(start), days.index(end)
    if end_pos < start_pos:
        raise ValueError("end 不能早于 start")
    # next_open 入场 + hold 个可卖日，末尾需留 1+hold 个交易日。
    need = 1 + max(1, hold)
    if end_pos - start_pos < need:
        raise ValueError(f"窗口至少需要 {need} 个交易日完成入场与退出")
    signal_end = days[end_pos - need]
    load_start = days[max(0, start_pos - warmup)]
    return load_start, end, signal_end


def _portfolio_metrics(frame: pd.DataFrame) -> dict[str, Any]:
    """日等权复利：当日所有完成交易等权，再跨日连乘。"""
    evaluable = frame[frame["exit_reason"] != "data_end"].copy()
    if evaluable.empty:
        return {
            "portfolio_groups": 0,
            "portfolio_return_pct": None,
            "portfolio_max_drawdown_pct": None,
        }
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
    }


def _enrich_trades(
    trades: pd.DataFrame,
    *,
    qfq: dict[str, pd.DataFrame],
    raw: dict[str, pd.DataFrame],
    meta: dict[str, dict[str, str]],
    breadth: pd.Series,
    version: str,
) -> pd.DataFrame:
    if trades.empty:
        return trades
    close, high, low = qfq["close"], qfq["high"], qfq["low"]
    spread = high - low
    clv = ((2 * close - high - low) / spread).where(spread != 0)
    r1 = close / close.shift(1) - 1.0
    volume_ratio = raw["volume"] / raw["volume"].rolling(20).mean()
    position60 = close / close.rolling(60).max()
    rows: list[dict[str, Any]] = []
    for record in trades.to_dict("records"):
        date = str(record["signal_date"])
        code = str(record["code"]).zfill(6)
        signal_close = _scalar(raw["close"], date, code)
        entry_open = _scalar(raw["open"], str(record["entry_date"]), code)
        gap = (
            entry_open / signal_close - 1.0
            if signal_close > 0 and np.isfinite(entry_open)
            else np.nan
        )
        turn = _scalar(raw["turnover"], date, code)
        shares = _scalar(raw["outstanding_share"], date, code)
        market_cap = signal_close * shares if signal_close > 0 and shares > 0 else np.nan
        row = {
            **record,
            "version": version,
            "signal_return_1": _scalar(r1, date, code),
            "clv": _scalar(clv, date, code),
            "volume_ratio": _scalar(volume_ratio, date, code),
            "position60": _scalar(position60, date, code),
            "turnover": turn,
            "market_cap_yuan": market_cap,
            "next_open_gap": gap,
            "board": meta.get(code, {}).get("board", ""),
            "name": meta.get(code, {}).get("name", ""),
            "breadth_up_pct": float(breadth.get(date, np.nan))
            if date in breadth.index
            else np.nan,
        }
        row["gap_band"] = _gap_band(gap)
        row["clv_band"] = _band(
            row["clv"],
            [(0.0, "低位收盘<0"), (0.5, "中位收盘0-0.5"), (float("inf"), "高位收盘≥0.5")],
        )
        row["position60_band"] = _band(
            row["position60"],
            [(0.7, "低位≤70%"), (0.9, "中位70%-90%"), (float("inf"), "高位>90%")],
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
            [
                (50.0, "<50亿"),
                (100.0, "50-100亿"),
                (300.0, "100-300亿"),
                (1000.0, "300-1000亿"),
                (float("inf"), "≥1000亿"),
            ],
        )
        row["signal_return_band"] = _band(
            row["signal_return_1"],
            [
                (-0.03, "跌>3%"),
                (0.0, "跌0-3%"),
                (0.03, "涨0-3%"),
                (0.07, "涨3%-7%"),
                (float("inf"), "涨≥7%"),
            ],
        )
        row["breadth_band"] = _band(
            row["breadth_up_pct"],
            [(0.4, "上涨<40%"), (0.6, "上涨40%-60%"), (float("inf"), "上涨≥60%")],
        )
        row["volume_ratio_band"] = _band(
            row["volume_ratio"],
            [(1.0, "量比<1"), (1.5, "量比1-1.5"), (2.5, "量比1.5-2.5"), (float("inf"), "量比≥2.5")],
        )
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
        ("市场宽度", "breadth_band"),
        ("量比", "volume_ratio_band"),
        ("板块", "board"),
    ]
    rows: list[dict[str, Any]] = []
    for dimension, column in dimensions:
        if column not in trades.columns:
            continue
        for value, group in trades.groupby(column, dropna=False, sort=True):
            label = "缺失" if pd.isna(value) else str(value)
            row = _metrics(group, label=label)
            row.update({"dimension": dimension, "value": label})
            rows.append(row)
    return rows


def _metric_row(label: str, trades: pd.DataFrame) -> dict[str, Any]:
    row = _metrics(trades, label=label)
    row.update(_portfolio_metrics(trades))
    return row


def _write_report(
    output_dir: Path,
    *,
    summary: dict[str, Any],
    version_rows: list[dict[str, Any]],
    variant_rows: list[dict[str, Any]],
    layers_by_version: dict[str, list[dict[str, Any]]],
) -> None:
    output_dir.mkdir(parents=True, exist_ok=True)
    (output_dir / "summary.json").write_text(
        json.dumps(_json_safe(summary), ensure_ascii=False, indent=2), encoding="utf-8"
    )
    all_cmp = version_rows + variant_rows
    pd.DataFrame(all_cmp).to_csv(output_dir / "version-compare.csv", index=False, encoding="utf-8-sig")
    layer_frames = []
    for version, layers in layers_by_version.items():
        frame = pd.DataFrame(layers)
        if not frame.empty:
            frame.insert(0, "version", version)
            layer_frames.append(frame)
    if layer_frames:
        pd.concat(layer_frames, ignore_index=True).to_csv(
            output_dir / "layers.csv", index=False, encoding="utf-8-sig"
        )
    else:
        pd.DataFrame().to_csv(output_dir / "layers.csv", index=False, encoding="utf-8-sig")

    lines = [
        "# 潜龙出海 v1/v2/v3 结构分层回测",
        "",
        "- 信号时点：收盘后选股；成交：T+1 开盘；退出：买入后第 "
        f"{summary['hold_days']} 个可卖日收盘（可触发止损）。",
        f"- 信号窗口：{summary['start']} 至 {summary['signal_end']}"
        f"（原始请求结束日 {summary['end']}，末尾预留入场+持有期）。",
        "- 股票池：主板+创业板，剔 ST/退市/停牌/上市不足 60 日。",
        "- 成本：买卖佣金各 0.03%，卖出印花税 0.05%，买卖滑点各 0.10%"
        f"（往返约 {summary['round_trip_cost_pct']:.2f}%）。",
        f"- 止损：{summary['stop_loss_pct']}%；止盈：无。",
        f"- 数据：只读 `{summary['db_label']}`；行情最后日期 `{summary['data_last_date']}`；"
        "当前上市股票存在幸存者偏差。",
        "- 版本：v1=归档死叉20/价≥6；v2=归档死叉15/价≥8；v3=内置换手2%-8%+非涨停。",
        "- 组合收益：按信号日等权复利（当日多票均分）。",
        "",
        "## 版本对照",
        "",
        "| 方案 | 完成交易 | 胜率 | 平均净收益 | 平均盈亏比 | Profit Factor | 组合收益 | 组合回撤 |",
        "|---|---:|---:|---:|---:|---:|---:|---:|",
    ]

    def _fmt(row: dict[str, Any]) -> str:
        return (
            "| {group} | {trades} | {win_rate_pct}% | {avg_net_return_pct}% | "
            "{payoff_ratio} | {profit_factor} | {portfolio_return_pct}% | "
            "{portfolio_max_drawdown_pct}% |"
        ).format(
            group=row.get("group", ""),
            trades=row.get("trades", 0),
            win_rate_pct=row.get("win_rate_pct", "-"),
            avg_net_return_pct=row.get("avg_net_return_pct", "-"),
            payoff_ratio=row.get("payoff_ratio", "-"),
            profit_factor=row.get("profit_factor", "-"),
            portfolio_return_pct=row.get("portfolio_return_pct", "-"),
            portfolio_max_drawdown_pct=row.get("portfolio_max_drawdown_pct", "-"),
        )

    for row in version_rows:
        lines.append(_fmt(row))
    lines.extend(["", "## 执行变体（在对应版本信号上过滤）", ""])
    lines.append(
        "| 方案 | 完成交易 | 胜率 | 平均净收益 | 平均盈亏比 | Profit Factor | 组合收益 | 组合回撤 |"
    )
    lines.append("|---|---:|---:|---:|---:|---:|---:|---:|")
    for row in variant_rows:
        lines.append(_fmt(row))

    lines.extend(
        [
            "",
            "## 分层明细",
            "",
            "完整分层见 `layers.csv`；样本小于 30 的组只作观察。主表按 **平均净收益** 排序。",
            "",
        ]
    )
    for version in VERSIONS:
        layers = layers_by_version.get(version, [])
        if not layers:
            continue
        lines.extend([f"### {version}", ""])
        for dimension in sorted({str(r["dimension"]) for r in layers}):
            subset = [r for r in layers if r["dimension"] == dimension]
            subset = sorted(
                subset,
                key=lambda r: (
                    r.get("avg_net_return_pct") is None,
                    -(r.get("avg_net_return_pct") or -999),
                ),
            )
            lines.extend(
                [
                    f"#### {dimension}",
                    "",
                    "| 分组 | 样本 | 胜率 | 平均净收益 | 平均盈亏比 | PF |",
                    "|---|---:|---:|---:|---:|---:|",
                ]
            )
            for row in subset:
                lines.append(
                    f"| {row['value']} | {row.get('trades', 0)} | "
                    f"{row.get('win_rate_pct', '-')}% | {row.get('avg_net_return_pct', '-')}% | "
                    f"{row.get('payoff_ratio', '-')} | {row.get('profit_factor', '-')} |"
                )
            lines.append("")

    # Best structure conclusion from v3 layers + variants.
    v3_layers = layers_by_version.get("v3", [])
    best_bits: list[str] = []
    for dim in ("次日开盘缺口", "换手率", "市场宽度", "信号日涨幅"):
        rows = [r for r in v3_layers if r["dimension"] == dim and (r.get("trades") or 0) >= 30]
        if not rows:
            continue
        top = max(rows, key=lambda r: r.get("avg_net_return_pct") or -999)
        best_bits.append(
            f"- v3 {dim}最优：`{top['value']}` "
            f"（n={top.get('trades')}, 净收益={top.get('avg_net_return_pct')}%, "
            f"盈亏比={top.get('payoff_ratio')}, PF={top.get('profit_factor')}）"
        )
    best_variant = None
    if variant_rows:
        best_variant = max(
            variant_rows,
            key=lambda r: (
                r.get("avg_net_return_pct") is not None,
                r.get("avg_net_return_pct") or -999,
            ),
        )
    lines.extend(["## 结论（收益率优先）", ""])
    if version_rows:
        best_ver = max(
            version_rows,
            key=lambda r: (r.get("avg_net_return_pct") is not None, r.get("avg_net_return_pct") or -999),
        )
        lines.append(
            f"1. 版本层面最优：**{best_ver.get('group')}** "
            f"（平均净收益 {best_ver.get('avg_net_return_pct')}%，"
            f"盈亏比 {best_ver.get('payoff_ratio')}，PF {best_ver.get('profit_factor')}，"
            f"组合收益 {best_ver.get('portfolio_return_pct')}%）。"
        )
    lines.extend(best_bits)
    if best_variant:
        lines.append(
            f"- 执行变体最优：**{best_variant.get('group')}** "
            f"（净收益 {best_variant.get('avg_net_return_pct')}%，"
            f"PF {best_variant.get('profit_factor')}，"
            f"组合 {best_variant.get('portfolio_return_pct')}%）。"
        )
    lines.extend(["", "## 产物", "",
                  "- `report.md` / `version-compare.csv` / `layers.csv` / `summary.json` / `v*-trades.csv`", ""])
    (output_dir / "report.md").write_text("\n".join(lines), encoding="utf-8")


def run(args: argparse.Namespace) -> dict[str, Any]:
    db_path = Path(args.db).expanduser().resolve()
    config = BacktestConfig(
        hold_days=args.hold_days,
        stop_loss_pct=args.stop_loss,
        take_profit_pct=None,
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

    # V3 涨停过滤需要未复权收盘 + 名称。
    names = {code: meta[code]["name"] for code in codes if code in meta}
    qfq_for_signal = dict(qfq)
    qfq_for_signal["__instrument_names__"] = names  # type: ignore[assignment]
    attach_raw_limit_close(
        _PanelStore(raw["close"]),
        qfq_for_signal,
        enabled=True,
        adjust="qfq",
        codes=codes,
        start=load_start,
        end=load_end,
        min_bars=46,
    )

    v1, v2 = _load_legacy()
    engines = {"v1": v1, "v2": v2, "v3": QianlongCloseePickerV3()}
    breadth = (qfq["close"] > qfq["close"].shift(1)).sum(axis=1) / qfq["close"].notna().sum(axis=1)
    breadth = breadth.replace([np.inf, -np.inf], np.nan)
    signal_mask = (qfq["close"].index >= args.start) & (qfq["close"].index <= signal_end)
    panel_index = raw["close"].index

    version_rows: list[dict[str, Any]] = []
    trades_by_version: dict[str, pd.DataFrame] = {}
    signals_by_version: dict[str, pd.DataFrame] = {}
    layers_by_version: dict[str, list[dict[str, Any]]] = {}

    for version, engine in engines.items():
        result = engine.compute(qfq_for_signal if version == "v3" else qfq)
        selected = result.signals.fillna(False).astype(bool)
        selected.loc[~signal_mask, :] = False
        signals_by_version[version] = selected
        backtest = run_backtest(
            selected.reindex(index=panel_index, columns=raw["close"].columns).fillna(False),
            raw,
            entry_timing="next_open",
            config=config,
            strategy_slug=getattr(engine, "slug", version),
        )
        trades = _enrich_trades(
            backtest.to_frame(),
            qfq=qfq,
            raw=raw,
            meta=meta,
            breadth=breadth,
            version=version,
        )
        trades_by_version[version] = trades
        row = _metric_row(version, trades)
        row.update(
            {
                "candidate_signals": int(selected.to_numpy(dtype=bool).sum()),
                "signal_days": int(selected.any(axis=1).sum()),
                "skipped": backtest.skipped,
            }
        )
        version_rows.append(row)
        layers_by_version[version] = _layer_rows(trades)
        print(f"{version}: {row}")

    # 执行变体：在 v3（及对照）上按说明书/结构过滤。
    variant_rows: list[dict[str, Any]] = []
    v3_trades = trades_by_version["v3"]
    practical_gaps = {"低开1%-3%", "平开±1%", "高开1%-3%"}
    variants: list[tuple[str, pd.DataFrame]] = [
        ("v3·跳过≥3%跳空", v3_trades[v3_trades["gap_band"].isin(practical_gaps)]),
        ("v3·仅低开1%-3%", v3_trades[v3_trades["gap_band"] == "低开1%-3%"]),
        ("v3·平开±1%", v3_trades[v3_trades["gap_band"] == "平开±1%"]),
        (
            "v3·换手2%-5%×宽度≥60%",
            v3_trades[
                (v3_trades["turnover_band"] == "2%-5%")
                & (v3_trades["breadth_band"] == "上涨≥60%")
            ],
        ),
        (
            "v3·低开1%-3%×换手2%-5%×宽度≥60%",
            v3_trades[
                (v3_trades["gap_band"] == "低开1%-3%")
                & (v3_trades["turnover_band"] == "2%-5%")
                & (v3_trades["breadth_band"] == "上涨≥60%")
            ],
        ),
    ]
    # 每日只留 ROC5 最强一只（可执行密度）。
    strength = qfq["close"] / REF(qfq["close"], 5)
    one = select_one_per_day(signals_by_version["v3"], strength)
    one.loc[~signal_mask, :] = False
    one_bt = run_backtest(
        one.reindex(index=panel_index, columns=raw["close"].columns).fillna(False),
        raw,
        entry_timing="next_open",
        config=config,
        strategy_slug="qianlong-close-v3-one-per-day",
    )
    one_trades = _enrich_trades(
        one_bt.to_frame(), qfq=qfq, raw=raw, meta=meta, breadth=breadth, version="v3-one"
    )
    variants.append(("v3·每日ROC5首选1只", one_trades))

    for label, frame in variants:
        row = _metric_row(label, frame)
        variant_rows.append(row)
        print(f"variant {label}: trades={row.get('trades')} avg={row.get('avg_net_return_pct')}")

    output_dir = Path(args.output).expanduser().resolve()
    output_dir.mkdir(parents=True, exist_ok=True)
    for version, trades in trades_by_version.items():
        trades.to_csv(output_dir / f"{version}-trades.csv", index=False, encoding="utf-8-sig")
    one_trades.to_csv(output_dir / "v3-one-per-day-trades.csv", index=False, encoding="utf-8-sig")

    summary = {
        "strategy": "qianlong-close v1/v2/v3",
        "timing": f"T日收盘选股 -> T+1开盘买入 -> 持有{config.hold_days}可卖日收盘"
        + (f"（止损{config.stop_loss_pct}%）" if config.stop_loss_pct is not None else ""),
        "start": args.start,
        "end": args.end,
        "signal_end": signal_end,
        "load_start": load_start,
        "hold_days": config.hold_days,
        "stop_loss_pct": config.stop_loss_pct,
        "round_trip_cost_pct": config.round_trip_cost_pct(),
        "data_last_date": data_last_date,
        "universe_codes": len(codes),
        "config": asdict(config),
        "db_label": str(db_path),
        "version_compare": version_rows,
        "variants": variant_rows,
        "notes": [
            "完成交易统计排除 data_end。",
            "成本口径对齐三元研究脚本（印花税 5bps、滑点 10bps）。",
            "组合收益按信号日等权复利；多票日均分。",
            "数据库是当前上市股票集合，存在幸存者偏差。",
        ],
    }
    _write_report(
        output_dir,
        summary=summary,
        version_rows=version_rows,
        variant_rows=variant_rows,
        layers_by_version=layers_by_version,
    )
    # 同步一份到 docs，便于查阅。
    docs = PROJECT_ROOT / "docs" / "qianlong-structure-backtest.md"
    docs.write_text((output_dir / "report.md").read_text(encoding="utf-8"), encoding="utf-8")
    print(f"REPORT_DIR={output_dir}")
    return summary


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--db", default=os.environ.get("PALACE_MARKET_DB") or str(DEFAULT_DB))
    parser.add_argument("--start", default="2026-02-02")
    parser.add_argument("--end", default="2026-07-31")
    parser.add_argument("--hold-days", type=int, default=HOLDS_PRIMARY)
    parser.add_argument("--stop-loss", type=float, default=-6.0)
    parser.add_argument(
        "--output",
        default="output/qianlong-structure-2026-02-02_2026-07-31",
    )
    return parser


if __name__ == "__main__":
    run(build_parser().parse_args())
