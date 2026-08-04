"""潜龙出海 v1/v2/v3 结构对比回测（收益率优先）。

只读 market.db。v1/v2 来自归档 legacy；v3 用当前内置实现。
入场统一为次日开盘；结构切片含换手率、次日开盘、形态（信号日涨幅）、
市场参与度（上涨家数，代理「有仓/活跃度」）等。
"""
from __future__ import annotations

import argparse
import importlib.util
import json
import sys
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from src.shared.paths import market_db as default_market_db
from src.strategy.application.price_constraints import attach_raw_limit_close
from src.strategy.application.qianlong import QianlongCloseePickerV3
from src.strategy.domain import base as strategy_base
from scripts.qianlong_v1_backtest_report import stats as _stats
from scripts.qianlong_structure_report import VERSIONS, render_report
from scripts.qianlong_v1_combination_backtest import (
    BENCHMARK_CODE,
    DEFAULT_COST_PCT,
    DEFAULT_MIN_LIST_DAYS,
    HOLDS,
    ReadOnlyPanelStore,
    _calendar,
    _finite,
    _gap_band,
    _gap_coarse,
    _load_stock_meta,
    _market_features,
    _resolve_window,
    _ro_connect,
    _signal_return_band,
    _turnover_band,
)

FOCUS_HOLD = 3


def _load_legacy() -> tuple[Any, Any]:
    path = PROJECT_ROOT / "src/strategy/application/backup/qianlong-legacy.py"
    spec = importlib.util.spec_from_file_location("_qianlong_legacy_source", path)
    if spec is None or spec.loader is None:
        raise ImportError(f"无法加载：{path}")
    module = importlib.util.module_from_spec(spec)
    original = strategy_base.register
    strategy_base.register = lambda engine: engine
    try:
        spec.loader.exec_module(module)
    finally:
        strategy_base.register = original
    return module.QianlongCloseePicker(), module.QianlongCloseePickerV2()


def _build_events(
    *,
    signal_frame: pd.DataFrame,
    panels: dict[str, pd.DataFrame],
    market: pd.DataFrame,
    meta: dict[str, dict[str, str]],
    window: dict[str, Any],
    cost_pct: float,
) -> tuple[pd.DataFrame, dict[str, Any]]:
    close, open_ = panels["close"], panels["open"]
    high, low, volume, turnover = (
        panels["high"],
        panels["low"],
        panels["volume"],
        panels["turnover"],
    )
    dates = list(close.index)
    date_to_pos = {str(day): i for i, day in enumerate(dates)}
    signal_frame = signal_frame[
        (signal_frame.index >= window["signal_start"])
        & (signal_frame.index <= window["signal_end"])
    ].fillna(False)
    total = int(signal_frame.to_numpy(dtype=bool).sum())
    unbuyable = 0
    reasons: dict[str, int] = {}
    valid_ids: set[str] = set()
    rows: list[dict[str, Any]] = []

    signal_rows, signal_cols = np.nonzero(signal_frame.to_numpy(dtype=bool))
    signal_dates = list(signal_frame.index)
    signal_codes = list(signal_frame.columns)
    for row, col in zip(signal_rows, signal_cols):
        signal_date = str(signal_dates[row])
        code = str(signal_codes[col])
        base_close = close.at[signal_date, code]
        entry_pos = date_to_pos.get(signal_date, -1) + 1
        reason = ""
        if entry_pos <= 0 or entry_pos >= len(dates):
            reason = "次日超出数据范围"
        else:
            entry_date = str(dates[entry_pos])
            entry_open = open_.at[entry_date, code]
            entry_high = high.at[entry_date, code]
            entry_low = low.at[entry_date, code]
            entry_volume = volume.at[entry_date, code]
            if not (_finite(base_close) and float(base_close) > 0):
                reason = "信号日无收盘价"
            elif not (_finite(entry_open) and float(entry_open) > 0):
                reason = "次日无开盘价"
            elif not (_finite(entry_volume) and float(entry_volume) > 0):
                reason = "次日停牌"
            elif (
                _finite(entry_high)
                and _finite(entry_low)
                and np.isclose(float(entry_high), float(entry_low))
            ):
                reason = "次日一字板买不进"
        if reason:
            unbuyable += 1
            reasons[reason] = reasons.get(reason, 0) + 1
            continue

        entry_date = str(dates[entry_pos])
        entry_open = float(open_.at[entry_date, code])
        base_close_float = float(base_close)
        event_id = f"{signal_date}_{code}"
        valid_ids.add(event_id)
        gap = entry_open / base_close_float - 1.0
        signal_open = open_.at[signal_date, code]
        signal_return = (
            float(base_close_float / float(signal_open) - 1.0)
            if _finite(signal_open) and float(signal_open) > 0
            else np.nan
        )
        market_row = market.loc[signal_date]
        common = {
            "event_id": event_id,
            "signal_date": signal_date,
            "entry_date": entry_date,
            "code": code,
            "name": meta.get(code, {}).get("name", ""),
            "board": meta.get(code, {}).get("board", ""),
            "turnover": (
                float(turnover.at[signal_date, code])
                if _finite(turnover.at[signal_date, code])
                else np.nan
            ),
            "turnover_band": _turnover_band(turnover.at[signal_date, code]),
            "signal_return_band": _signal_return_band(signal_return),
            "market_regime": str(market_row["market_regime"]),
            "breadth_band": str(market_row["breadth_band"]),
            "market_day_band": str(market_row["market_day_band"]),
            "gap_pct": round(gap * 100, 4),
            "gap_band": _gap_band(gap),
            "gap_coarse": _gap_coarse(gap),
            "entry_price": round(entry_open, 4),
        }
        for hold in HOLDS:
            exit_pos = entry_pos + hold
            if exit_pos >= len(dates):
                continue
            exit_date = str(dates[exit_pos])
            exit_close = close.at[exit_date, code]
            if not (_finite(exit_close) and float(exit_close) > 0):
                continue
            gross = float(exit_close) / entry_open - 1.0
            net = gross * 100.0 - cost_pct
            rows.append(
                {
                    **common,
                    "hold_days": hold,
                    "exit_date": exit_date,
                    "gross_return_pct": round(gross * 100.0, 4),
                    "net_return_pct": round(net, 4),
                    "alpha_pct": np.nan,
                    "mfe_pct": np.nan,
                    "mae_pct": np.nan,
                }
            )

    events = pd.DataFrame(rows)
    summary = {
        "signals_total": total,
        "buyable_signals": len(valid_ids),
        "unbuyable_signals": unbuyable,
        "unbuyable_reasons": reasons,
    }
    return events, summary


def _run(args: argparse.Namespace) -> Path:
    db_path = Path(args.db).expanduser().resolve()
    output_dir = Path(args.output_dir).expanduser().resolve()
    output_dir.mkdir(parents=True, exist_ok=True)
    report_path = Path(args.report).expanduser().resolve()

    conn = _ro_connect(db_path)
    try:
        days = _calendar(conn)
        window = _resolve_window(days, args.start, args.end, max(HOLDS))
        codes, meta = _load_stock_meta(
            conn, as_of=window["signal_end"], min_list_days=args.min_list_days
        )
        store = ReadOnlyPanelStore(conn)
        panels = store.load_panel(
            fields=("open", "high", "low", "close", "volume", "turnover"),
            codes=codes,
            start=window["load_start"],
            end=window["data_end"],
            adjust=args.adjust,
            min_bars=46,
        )
        if panels["close"].empty:
            raise ValueError("股票池无行情")
        names = {code: meta[code]["name"] for code in codes if code in meta}
        panels["__instrument_names__"] = names  # type: ignore[assignment]
        attach_raw_limit_close(
            store,
            panels,
            enabled=True,
            adjust=args.adjust,
            codes=codes,
            start=window["load_start"],
            end=window["data_end"],
            min_bars=46,
        )
        index_panel = store.load_panel(
            fields=("close",),
            codes=[BENCHMARK_CODE],
            start=window["load_start"],
            end=window["data_end"],
            adjust="none",
        )
        if index_panel["close"].empty:
            raise ValueError(f"缺少基准 {BENCHMARK_CODE}")
        market = _market_features(
            panels["close"],
            index_panel["close"][BENCHMARK_CODE],
            panels["close"].index,
        )

        v1, v2 = _load_legacy()
        engines = {"v1": v1, "v2": v2, "v3": QianlongCloseePickerV3()}
        by_version: dict[str, dict[str, Any]] = {}
        for version, engine in engines.items():
            result = engine.compute(panels)
            events, summary = _build_events(
                signal_frame=result.signals,
                panels=panels,
                market=market,
                meta=meta,
                window=window,
                cost_pct=args.cost_pct,
            )
            if events.empty:
                raise ValueError(f"{version} 无可成交事件")
            events.to_csv(
                output_dir / f"qianlong-{version}-events.csv",
                index=False,
                encoding="utf-8-sig",
            )
            by_version[version] = {
                "events": events,
                "summary": summary,
                "slug": getattr(engine, "slug", version),
            }
            print(
                f"{version}: signals={summary['signals_total']} "
                f"buyable={summary['buyable_signals']} "
                f"h3={_stats(events[events['hold_days'] == FOCUS_HOLD])}"
            )

        config = {
            "db": str(db_path),
            "output_dir": str(output_dir),
            "data_snapshot": {
                str(row["key"]): str(row["value"])
                for row in conn.execute("SELECT key, value FROM meta")
            },
            "adjust": args.adjust,
            "signal_start": window["signal_start"],
            "signal_end": window["signal_end"],
            "cost_pct": args.cost_pct,
            "stock_codes": len(codes),
            "versions": {
                v: {
                    "slug": by_version[v]["slug"],
                    **by_version[v]["summary"],
                }
                for v in VERSIONS
            },
        }
        (output_dir / "qianlong-structure-config.json").write_text(
            json.dumps(config, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        return render_report(
            output_path=report_path,
            config=config,
            by_version=by_version,
        )
    finally:
        conn.close()


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--db", default=str(default_market_db()))
    parser.add_argument("--start", default="2026-02-01")
    parser.add_argument("--end", default="2026-07-31")
    parser.add_argument(
        "--output-dir", default="output/qianlong-structure-2026H1"
    )
    parser.add_argument(
        "--report", default="docs/qianlong-structure-backtest.md"
    )
    parser.add_argument("--adjust", choices=("none", "qfq", "hfq"), default="qfq")
    parser.add_argument("--cost-pct", type=float, default=DEFAULT_COST_PCT)
    parser.add_argument("--min-list-days", type=int, default=DEFAULT_MIN_LIST_DAYS)
    return parser


def main() -> int:
    report = _run(_parser().parse_args())
    print(f"report={report}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
