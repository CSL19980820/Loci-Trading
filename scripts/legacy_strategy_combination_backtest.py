"""三个归档战法的多条件组合回测入口。"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import sqlite3
import sys
from typing import Any

import numpy as np
import pandas as pd

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from scripts.legacy_strategy_combination_common import (
    BOARD_ORDER,
    COMBO_COLUMNS,
    GAP_ORDER,
    HOLDS,
    REGIME_ORDER,
    STRATEGIES,
    TURNOVER_ORDER,
    ReadOnlyPanelStore,
    StrategySpec,
    combination_table as _combination_table,
    empty_events as _empty_events,
    factor_table as _factor_table,
    finite as _finite,
    gap_band as _gap_band,
    gap_coarse as _gap_coarse,
    load_legacy_module as _load_legacy_module,
    load_snapshot as _load_snapshot,
    load_stock_meta as _load_stock_meta,
    market_features as _market_features,
    ro_connect as _ro_connect,
    resolve_window as _resolve_window,
    calendar as _calendar,
    signal_return_band as _signal_return_band,
    turnover_band as _turnover_band,
)
from scripts.legacy_strategy_combination_report import (
    render_report as _render_report,
    robust_combinations as _robust_combinations,
)
from scripts.qianlong_v1_backtest_report import stats as _stats
from src.shared.paths import market_db as default_market_db


DEFAULT_COST_PCT = 0.26
DEFAULT_MIN_LIST_DAYS = 60
BENCHMARK_CODE = "000300"


def _run_strategy(
    spec: StrategySpec,
    strategy: Any,
    panels: dict[str, pd.DataFrame],
    meta: dict[str, dict[str, str]],
    market: pd.DataFrame,
    window: dict[str, Any],
    cost_pct: float,
) -> tuple[pd.DataFrame, dict[str, Any], dict[str, pd.DataFrame]]:
    working = dict(panels)
    working["__instrument_names__"] = {
        code: str(info.get("name", "")) for code, info in meta.items()
    }
    signal_frame = strategy.compute(working).signals
    signal_frame = signal_frame.reindex(panels["close"].index).fillna(False)
    signal_frame = signal_frame[
        (signal_frame.index >= window["signal_start"])
        & (signal_frame.index <= window["signal_end"])
    ].fillna(False)

    dates = list(panels["close"].index)
    date_to_pos = {str(day): index for index, day in enumerate(dates)}
    close, open_, high, low = (panels[key] for key in ("close", "open", "high", "low"))
    volume, turnover = panels["volume"], panels["turnover"]
    total_signals = int(signal_frame.to_numpy(dtype=bool).sum())
    unbuyable = 0
    unbuyable_reasons: dict[str, int] = {}
    valid_entry_ids: set[str] = set()
    rows: list[dict[str, Any]] = []

    signal_rows, signal_cols = np.nonzero(signal_frame.to_numpy(dtype=bool))
    for row, col in zip(signal_rows, signal_cols):
        signal_date, code = str(signal_frame.index[row]), str(signal_frame.columns[col])
        base_close = close.at[signal_date, code]
        entry_pos = date_to_pos.get(signal_date, -1) + 1
        reason = ""
        if entry_pos <= 0 or entry_pos >= len(dates):
            reason = "次日超出数据范围"
        else:
            entry_date = str(dates[entry_pos])
            entry_open, entry_high = open_.at[entry_date, code], high.at[entry_date, code]
            entry_low, entry_volume = low.at[entry_date, code], volume.at[entry_date, code]
            if not (_finite(base_close) and float(base_close) > 0):
                reason = "信号日无收盘价"
            elif not (_finite(entry_open) and float(entry_open) > 0):
                reason = "次日无开盘价"
            elif not (_finite(entry_volume) and float(entry_volume) > 0):
                reason = "次日停牌"
            elif _finite(entry_high) and _finite(entry_low) and np.isclose(float(entry_high), float(entry_low)):
                reason = "次日一字板买不进"
        if reason:
            unbuyable += 1
            unbuyable_reasons[reason] = unbuyable_reasons.get(reason, 0) + 1
            continue

        entry_date = str(dates[entry_pos])
        entry_open = float(open_.at[entry_date, code])
        base_close_float = float(base_close)
        event_id = f"{signal_date}_{code}"
        valid_entry_ids.add(event_id)
        gap = entry_open / base_close_float - 1.0
        signal_open = open_.at[signal_date, code]
        signal_return = (
            float(base_close_float / float(signal_open) - 1.0)
            if _finite(signal_open) and float(signal_open) > 0
            else np.nan
        )
        market_row = market.loc[signal_date]
        entry_close = close.at[entry_date, code]
        common = {
            "strategy": spec.key,
            "strategy_name": spec.name,
            "event_id": event_id,
            "signal_date": signal_date,
            "entry_date": entry_date,
            "code": code,
            "name": meta.get(code, {}).get("name", ""),
            "board": meta.get(code, {}).get("board", ""),
            "turnover": float(turnover.at[signal_date, code]) if _finite(turnover.at[signal_date, code]) else np.nan,
            "turnover_band": _turnover_band(turnover.at[signal_date, code]),
            "signal_return_pct": round(signal_return * 100, 4) if _finite(signal_return) else np.nan,
            "signal_return_band": _signal_return_band(signal_return),
            "market_regime": str(market_row["market_regime"]),
            "benchmark_ret20_pct": round(float(market_row["benchmark_ret20"] * 100), 4) if _finite(market_row["benchmark_ret20"]) else np.nan,
            "breadth": float(market_row["breadth"]) if _finite(market_row["breadth"]) else np.nan,
            "breadth_band": str(market_row["breadth_band"]),
            "market_day_return_pct": round(float(market_row["benchmark_day_return"] * 100), 4) if _finite(market_row["benchmark_day_return"]) else np.nan,
            "market_day_band": str(market_row["market_day_band"]),
            "gap_pct": round(gap * 100, 4),
            "gap_band": _gap_band(gap),
            "gap_coarse": _gap_coarse(gap),
            "entry_price": round(entry_open, 4),
            "signal_close": round(base_close_float, 4),
            "entry_day_intraday_pct": round(float(entry_close / entry_open - 1.0) * 100, 4) if _finite(entry_close) else np.nan,
        }
        for hold in HOLDS:
            exit_pos = entry_pos + hold
            if exit_pos >= len(dates):
                continue
            exit_date, exit_close = str(dates[exit_pos]), close.at[str(dates[exit_pos]), code]
            if not (_finite(exit_close) and float(exit_close) > 0):
                continue
            gross = float(exit_close) / entry_open - 1.0
            benchmark_start = market.at[entry_date, "benchmark_close"]
            benchmark_end = market.at[exit_date, "benchmark_close"]
            benchmark_return = (
                (float(benchmark_end) / float(benchmark_start) - 1.0) * 100.0
                if _finite(benchmark_start) and _finite(benchmark_end) and float(benchmark_start) > 0
                else np.nan
            )
            high_window = high.iloc[entry_pos : exit_pos + 1][code].astype(float)
            low_window = low.iloc[entry_pos : exit_pos + 1][code].astype(float)
            max_high = high_window.replace([np.inf, -np.inf], np.nan).max()
            min_low = low_window.replace([np.inf, -np.inf], np.nan).min()
            net = gross * 100.0 - cost_pct
            rows.append({
                **common,
                "hold_days": hold,
                "exit_date": exit_date,
                "exit_close": round(float(exit_close), 4),
                "gross_return_pct": round(gross * 100.0, 4),
                "net_return_pct": round(net, 4),
                "benchmark_return_pct": round(benchmark_return, 4) if _finite(benchmark_return) else np.nan,
                "alpha_pct": round(net - benchmark_return, 4) if _finite(benchmark_return) else np.nan,
                "mfe_pct": round((float(max_high) / entry_open - 1.0) * 100, 4) if _finite(max_high) else np.nan,
                "mae_pct": round((float(min_low) / entry_open - 1.0) * 100, 4) if _finite(min_low) else np.nan,
            })

    events = pd.DataFrame(rows) if rows else _empty_events()
    hold_counts = events.groupby("event_id")["hold_days"].nunique() if not events.empty else pd.Series(dtype=int)
    event_head = events.drop_duplicates("event_id") if not events.empty else events
    factors = {
        key: _factor_table(events, key, order)
        for key, order in {
            "board": BOARD_ORDER,
            "turnover_band": TURNOVER_ORDER,
            "market_regime": REGIME_ORDER,
            "breadth_band": ("弱势<40%", "中性40-60%", "强势>=60%"),
            "gap_coarse": ("低开", "平开", "高开"),
            "gap_band": GAP_ORDER,
            "signal_return_band": ("<1%", "1-3%", ">=3%"),
            "market_day_band": ("<=-1%", "-1%~1%", ">=1%"),
        }.items()
    }
    result = {
        "strategy": spec.key,
        "strategy_name": spec.name,
        "signals_total": total_signals,
        "buyable_signals": len(valid_entry_ids),
        "events_with_results": int(hold_counts.size),
        "no_exit_signals": int(len(valid_entry_ids) - hold_counts.size),
        "partial_exit_signals": int((hold_counts < len(HOLDS)).sum()),
        "complete_h5_signals": int((hold_counts == len(HOLDS)).sum()),
        "unbuyable_signals": unbuyable,
        "unbuyable_reasons": unbuyable_reasons,
        "missing_turnover_signals": int((event_head["turnover_band"] == "缺失").sum()) if not event_head.empty else 0,
    }
    return events, result, factors


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--db", default=str(default_market_db()), help="只读 market.db 路径")
    parser.add_argument("--start", default="2023-01-01", help="信号起始日")
    parser.add_argument("--end", default=None, help="信号结束日；默认自动留出完整 H5")
    parser.add_argument("--strategies", default=",".join(STRATEGIES), help="逗号分隔：haidi,chouma,sanwai")
    parser.add_argument("--output-dir", default="output/legacy-strategy-combination-20260802", help="结果目录")
    parser.add_argument("--adjust", choices=("none", "qfq", "hfq"), default="qfq")
    parser.add_argument("--cost-pct", type=float, default=DEFAULT_COST_PCT)
    parser.add_argument("--min-list-days", type=int, default=DEFAULT_MIN_LIST_DAYS)
    parser.add_argument("--min-combo-n", type=int, default=30, help="稳健组合的每期最小样本数")
    parser.add_argument("--display-combo-n", type=int, default=10, help="报告展示组合的每期最小样本数")
    return parser


def _run(args: argparse.Namespace) -> tuple[Path, dict[str, Any]]:
    keys = [item.strip() for item in args.strategies.split(",") if item.strip()]
    if not keys or any(key not in STRATEGIES for key in keys):
        raise ValueError(f"未知战法，支持：{','.join(STRATEGIES)}")
    specs = [STRATEGIES[key] for key in keys]
    db_path = Path(args.db).expanduser().resolve()
    output_dir = Path(args.output_dir).expanduser().resolve()
    output_dir.mkdir(parents=True, exist_ok=True)
    conn: sqlite3.Connection | None = None
    try:
        conn = _ro_connect(db_path)
        days = _calendar(conn)
        window = _resolve_window(days, args.start, args.end, max(HOLDS), max(spec.min_bars for spec in specs))
        codes, meta = _load_stock_meta(conn, as_of=window["signal_end"], min_list_days=args.min_list_days)
        store = ReadOnlyPanelStore(conn)
        panels = store.load_panel(fields=("open", "high", "low", "close", "volume", "turnover"), codes=codes, start=window["load_start"], end=window["data_end"], adjust=args.adjust, min_bars=max(spec.min_bars for spec in specs))
        if panels["close"].empty:
            raise ValueError("股票池在所选区间没有行情数据")
        index_panel = store.load_panel(fields=("close",), codes=[BENCHMARK_CODE], start=window["load_start"], end=window["data_end"], adjust="none")
        if index_panel["close"].empty:
            raise ValueError(f"缺少大盘基准指数 {BENCHMARK_CODE}")
        market = _market_features(panels["close"], index_panel["close"][BENCHMARK_CODE], panels["close"].index)
        module = _load_legacy_module()
        event_frames, factor_frames, combo_frames = [], [], []
        strategy_results: dict[str, Any] = {}
        for spec in specs:
            events, result, factor_map = _run_strategy(spec, getattr(module, spec.class_name)(), panels, meta, market, window, args.cost_pct)
            event_frames.append(events)
            combo_frames.append(_combination_table(events, spec))
            for factor_key, frame in factor_map.items():
                frame = frame.copy()
                frame.insert(0, "factor", factor_key)
                frame.insert(0, "strategy_name", spec.name)
                frame.insert(0, "strategy", spec.key)
                factor_frames.append(frame)
            strategy_results[spec.key] = result
        events = pd.concat(event_frames, ignore_index=True)
        combinations = pd.concat(combo_frames, ignore_index=True)
        factors = pd.concat(factor_frames, ignore_index=True)
        robust = _robust_combinations(combinations, args.min_combo_n)
        config = {
            "db": str(db_path),
            "data_snapshot": _load_snapshot(conn),
            "adjust": args.adjust,
            "benchmark": BENCHMARK_CODE,
            "signal_start": window["signal_start"],
            "signal_end": window["signal_end"],
            "load_start": window["load_start"],
            "data_end": window["data_end"],
            "cost_pct": args.cost_pct,
            "min_list_days": args.min_list_days,
            "min_combo_n": args.min_combo_n,
            "display_combo_n": args.display_combo_n,
            "stock_codes": len(codes),
            "strategies": keys,
            "strategy_results": strategy_results,
            "combination_dimensions": {"board": list(BOARD_ORDER), "turnover_band": list(TURNOVER_ORDER), "market_regime": list(REGIME_ORDER), "gap_band": list(GAP_ORDER), "hold_days": list(HOLDS)},
        }
        events.to_csv(output_dir / "legacy-strategy-events.csv", index=False, encoding="utf-8-sig")
        combinations.to_csv(output_dir / "legacy-strategy-combinations.csv", index=False, encoding="utf-8-sig")
        factors.to_csv(output_dir / "legacy-strategy-factor-slices.csv", index=False, encoding="utf-8-sig")
        robust.to_csv(output_dir / "legacy-strategy-robust-combinations.csv", index=False, encoding="utf-8-sig")
        (output_dir / "legacy-strategy-config.json").write_text(json.dumps(config, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        report = _render_report(output_dir=output_dir, config=config, events=events, factors=factors, combinations=combinations, robust=robust)
        return report, config
    finally:
        if conn is not None:
            conn.close()


def main() -> int:
    report, config = _run(_parser().parse_args())
    print(f"report={report}")
    print("window={signal_start}..{signal_end} stocks={stock_codes} strategies={strategies}".format(**config))
    events = pd.read_csv(report.parent / "legacy-strategy-events.csv")
    for key, result in config["strategy_results"].items():
        print(f"strategy={key} signals={result['signals_total']} buyable={result['buyable_signals']} unbuyable={result['unbuyable_signals']}")
        for hold in HOLDS:
            print(f"{key} hold={hold} {_stats(events[(events['strategy'] == key) & (events['hold_days'] == hold)])}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
