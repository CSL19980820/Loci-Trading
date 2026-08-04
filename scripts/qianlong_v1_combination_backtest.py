"""潜龙老版本的多条件组合回测。

本脚本只读 ``market.db``，不通过 ``MarketStore`` 建立可写连接，也不写入
palace.db。信号使用仓内归档的 ``QianlongCloseePicker``，入场与成交统计
遵循回测模块的 ``next_open`` / A 股 T+1 口径。
"""
from __future__ import annotations

import argparse
from datetime import date, timedelta
import importlib.util
import json
from pathlib import Path
import sqlite3
import sys
from typing import Any, Sequence

import numpy as np
import pandas as pd

# 允许直接以 ``python scripts/...py`` 运行时导入仓库包。
PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from src.market.domain.universe import classify_board, is_delisting_name, is_st_name
from src.market.infrastructure.store_panel import MarketPanelMixin
from src.shared.paths import market_db as default_market_db
from src.strategy.domain import base as strategy_base
from scripts.qianlong_v1_backtest_report import (
    combination_table as _combination_table,
    factor_table as _factor_table,
    render_report as _render_report,
    stats as _stats,
)


HOLDS = (1, 3, 5)
DEFAULT_COST_PCT = 0.26
DEFAULT_MIN_LIST_DAYS = 60
BENCHMARK_CODE = "000300"
BOARD_ORDER = ("主板", "创业板")
TURNOVER_ORDER = ("<2%", "2-5%", "5-8%", "8-12%", "12-20%", ">=20%")
REGIME_ORDER = ("强牛", "偏强", "震荡", "偏弱", "弱熊")
GAP_ORDER = ("低开>=3%", "低开1-3%", "平开±1%", "高开1-3%", "高开>=3%")
GAP_COARSE_ORDER = ("低开", "平开", "高开")
BREADTH_ORDER = ("弱势<40%", "中性40-60%", "强势>=60%")
SIGNAL_RETURN_ORDER = ("<1%", "1-3%", ">=3%")
MARKET_DAY_ORDER = ("<=-1%", "-1%~1%", ">=1%")
COMBO_COLUMNS = ("board", "turnover_band", "market_regime", "gap_band")


class ReadOnlyPanelStore(MarketPanelMixin):
    """给公共面板加载逻辑提供只读 SQLite 连接。"""

    def __init__(self, conn: sqlite3.Connection) -> None:
        self.conn = conn


def _load_legacy_strategy() -> Any:
    """加载归档 v1 类，屏蔽归档文件末尾的策略注册副作用。"""
    path = PROJECT_ROOT / "src" / "strategy" / "application" / "backup" / "qianlong-legacy.py"
    spec = importlib.util.spec_from_file_location("_qianlong_legacy_source", path)
    if spec is None or spec.loader is None:
        raise ImportError(f"无法加载潜龙老版本源码：{path}")
    module = importlib.util.module_from_spec(spec)
    original_register = strategy_base.register
    strategy_base.register = lambda engine: engine
    try:
        spec.loader.exec_module(module)
    finally:
        strategy_base.register = original_register
    return module.QianlongCloseePicker()


def _ro_connect(path: Path) -> sqlite3.Connection:
    resolved = path.expanduser().resolve()
    if not resolved.is_file():
        raise FileNotFoundError(f"行情库不存在：{resolved}")
    conn = sqlite3.connect(f"file:{resolved}?mode=ro", uri=True)
    conn.row_factory = sqlite3.Row
    return conn


def _calendar(conn: sqlite3.Connection) -> list[str]:
    rows = conn.execute(
        "SELECT trade_date FROM trading_calendar ORDER BY trade_date"
    ).fetchall()
    if rows:
        return [str(row[0]) for row in rows]
    rows = conn.execute(
        "SELECT DISTINCT trade_date FROM quotes_daily ORDER BY trade_date"
    ).fetchall()
    return [str(row[0]) for row in rows]


def _first_on_or_after(days: Sequence[str], target: str) -> int:
    for index, day in enumerate(days):
        if day >= target:
            return index
    return len(days) - 1


def _resolve_window(
    days: Sequence[str], start: str, end: str | None, max_hold: int
) -> dict[str, Any]:
    if not days:
        raise ValueError("行情库没有交易日")
    start_pos = _first_on_or_after(days, start)
    requested_end_pos = (
        len(days) - 1 if not end else _first_on_or_after(days, end)
    )
    # T 信号日 + 次日入场 + hold 个可卖交易日必须在库内。
    last_complete_pos = len(days) - 1 - 1 - max_hold
    signal_end_pos = min(requested_end_pos, last_complete_pos)
    if signal_end_pos < start_pos:
        raise ValueError("所选区间没有同时具备次日入场和完整持有期的数据")
    warmup = 70
    load_start_pos = max(0, start_pos - warmup)
    data_end_pos = min(len(days) - 1, signal_end_pos + 1 + max_hold)
    return {
        "signal_start": days[start_pos],
        "signal_end": days[signal_end_pos],
        "load_start": days[load_start_pos],
        "data_end": days[data_end_pos],
        "start_pos": start_pos,
        "signal_end_pos": signal_end_pos,
    }


def _load_stock_meta(
    conn: sqlite3.Connection, *, as_of: str, min_list_days: int
) -> tuple[list[str], dict[str, dict[str, str]]]:
    rows = conn.execute(
        """
        SELECT code, name, status, list_date
        FROM instruments
        WHERE instrument_type = 'STOCK'
        ORDER BY code
        """
    ).fetchall()
    as_of_date = date.fromisoformat(as_of)
    cutoff = as_of_date - timedelta(days=min_list_days)
    codes: list[str] = []
    meta: dict[str, dict[str, str]] = {}
    for row in rows:
        code = str(row["code"] or "").zfill(6)
        name = str(row["name"] or "")
        board = classify_board(code)
        if board not in {"main", "chi_next"}:
            continue
        if str(row["status"] or "normal") in {"suspended", "delisted"}:
            continue
        if is_st_name(name) or is_delisting_name(name):
            continue
        listed = str(row["list_date"] or "")[:10]
        if listed:
            try:
                if date.fromisoformat(listed) > cutoff:
                    continue
            except ValueError:
                pass
        board_label = "创业板" if board == "chi_next" else "主板"
        codes.append(code)
        meta[code] = {"name": name, "board": board_label}
    return codes, meta


def _finite(value: Any) -> bool:
    try:
        return bool(np.isfinite(float(value)))
    except (TypeError, ValueError):
        return False


def _turnover_band(value: Any) -> str:
    if not _finite(value):
        return "缺失"
    number = float(value)
    if number < 0.02:
        return "<2%"
    if number < 0.05:
        return "2-5%"
    if number < 0.08:
        return "5-8%"
    if number < 0.12:
        return "8-12%"
    if number < 0.20:
        return "12-20%"
    return ">=20%"


def _gap_band(value: Any) -> str:
    if not _finite(value):
        return "缺失"
    number = float(value)
    if number < -0.03:
        return "低开>=3%"
    if number < -0.01:
        return "低开1-3%"
    if number < 0.01:
        return "平开±1%"
    if number < 0.03:
        return "高开1-3%"
    return "高开>=3%"


def _gap_coarse(value: Any) -> str:
    if not _finite(value):
        return "缺失"
    number = float(value)
    if number < -0.01:
        return "低开"
    if number < 0.01:
        return "平开"
    return "高开"


def _signal_return_band(value: Any) -> str:
    if not _finite(value):
        return "缺失"
    number = float(value)
    if number < 0.01:
        return "<1%"
    if number < 0.03:
        return "1-3%"
    return ">=3%"


def _market_day_band(value: Any) -> str:
    if not _finite(value):
        return "缺失"
    number = float(value)
    if number <= -0.01:
        return "<=-1%"
    if number < 0.01:
        return "-1%~1%"
    return ">=1%"


def _market_regime(ret20: Any, close: Any, ma20: Any) -> str:
    if not (_finite(ret20) and _finite(close) and _finite(ma20)):
        return "数据不足"
    rising = float(close) >= float(ma20)
    change = float(ret20)
    if change >= 0.05 and rising:
        return "强牛"
    if change <= -0.05 and not rising:
        return "弱熊"
    if change > 0 and rising:
        return "偏强"
    if change < 0 and not rising:
        return "偏弱"
    return "震荡"


def _breadth_band(value: Any) -> str:
    if not _finite(value):
        return "数据不足"
    number = float(value)
    if number < 0.40:
        return "弱势<40%"
    if number < 0.60:
        return "中性40-60%"
    return "强势>=60%"


def _market_features(
    close: pd.DataFrame, benchmark: pd.Series, dates: pd.Index
) -> pd.DataFrame:
    index_close = benchmark.reindex(dates).ffill()
    index_ret = index_close.pct_change()
    ma20 = index_close.rolling(20, min_periods=20).mean()
    ret20 = index_close / index_close.shift(20) - 1.0

    previous = close.shift(1)
    valid = close.notna() & previous.notna()
    daily = close / previous - 1.0
    valid_count = valid.sum(axis=1).replace(0, np.nan)
    breadth = ((daily > 0) & valid).sum(axis=1) / valid_count

    result = pd.DataFrame(index=dates)
    result["benchmark_close"] = index_close
    result["benchmark_day_return"] = index_ret
    result["benchmark_ret20"] = ret20
    result["benchmark_ma20"] = ma20
    result["market_regime"] = [
        _market_regime(ret20.get(day), index_close.get(day), ma20.get(day))
        for day in dates
    ]
    result["breadth"] = breadth
    result["breadth_band"] = breadth.map(_breadth_band)
    result["market_day_band"] = index_ret.map(_market_day_band)
    return result


def _run(args: argparse.Namespace) -> tuple[Path, dict[str, Any]]:
    db_path = Path(args.db).expanduser().resolve()
    output_dir = Path(args.output_dir).expanduser().resolve()
    output_dir.mkdir(parents=True, exist_ok=True)
    conn = _ro_connect(db_path)
    try:
        days = _calendar(conn)
        window = _resolve_window(days, args.start, args.end, max(HOLDS))
        codes, meta = _load_stock_meta(
            conn, as_of=window["signal_end"], min_list_days=args.min_list_days
        )
        panel_store = ReadOnlyPanelStore(conn)
        panels = panel_store.load_panel(
            fields=("open", "high", "low", "close", "volume", "turnover"),
            codes=codes,
            start=window["load_start"],
            end=window["data_end"],
            adjust=args.adjust,
            min_bars=46,
        )
        if panels["close"].empty:
            raise ValueError("股票池在所选区间没有行情数据")
        index_panel = panel_store.load_panel(
            fields=("close",),
            codes=[BENCHMARK_CODE],
            start=window["load_start"],
            end=window["data_end"],
            adjust="none",
        )
        if index_panel["close"].empty:
            raise ValueError(f"缺少大盘基准指数 {BENCHMARK_CODE}")

        strategy = _load_legacy_strategy()
        signal_result = strategy.compute(panels)
        signal_frame = signal_result.signals
        signal_frame = signal_frame[
            (signal_frame.index >= window["signal_start"])
            & (signal_frame.index <= window["signal_end"])
        ].fillna(False)
        dates = list(panels["close"].index)
        date_to_pos = {str(day): index for index, day in enumerate(dates)}
        market = _market_features(
            panels["close"], index_panel["close"][BENCHMARK_CODE], panels["close"].index
        )

        close = panels["close"]
        open_ = panels["open"]
        high = panels["high"]
        low = panels["low"]
        volume = panels["volume"]
        turnover = panels["turnover"]
        total_signals = int(signal_frame.to_numpy(dtype=bool).sum())
        unbuyable = 0
        unbuyable_reasons: dict[str, int] = {}
        valid_entry_ids: set[str] = set()
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
                elif _finite(entry_high) and _finite(entry_low) and np.isclose(
                    float(entry_high), float(entry_low)
                ):
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
            common = {
                "event_id": event_id,
                "signal_date": signal_date,
                "entry_date": entry_date,
                "code": code,
                "name": meta.get(code, {}).get("name", ""),
                "board": meta.get(code, {}).get("board", ""),
                "turnover": float(turnover.at[signal_date, code])
                if _finite(turnover.at[signal_date, code])
                else np.nan,
                "turnover_band": _turnover_band(turnover.at[signal_date, code]),
                "signal_return_pct": round(signal_return * 100, 4)
                if _finite(signal_return)
                else np.nan,
                "signal_return_band": _signal_return_band(signal_return),
                "market_regime": str(market_row["market_regime"]),
                "benchmark_ret20_pct": round(float(market_row["benchmark_ret20"] * 100), 4)
                if _finite(market_row["benchmark_ret20"])
                else np.nan,
                "breadth": float(market_row["breadth"])
                if _finite(market_row["breadth"])
                else np.nan,
                "breadth_band": str(market_row["breadth_band"]),
                "market_day_return_pct": round(float(market_row["benchmark_day_return"] * 100), 4)
                if _finite(market_row["benchmark_day_return"])
                else np.nan,
                "market_day_band": str(market_row["market_day_band"]),
                "gap_pct": round(gap * 100, 4),
                "gap_band": _gap_band(gap),
                "gap_coarse": _gap_coarse(gap),
                "entry_price": round(entry_open, 4),
                "signal_close": round(base_close_float, 4),
                "next_day_intraday_pct": round(
                    float(close.at[entry_date, code] / entry_open - 1.0) * 100, 4
                )
                if _finite(close.at[entry_date, code])
                else np.nan,
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
                net = gross * 100.0 - args.cost_pct
                benchmark_start = market.at[entry_date, "benchmark_close"]
                benchmark_end = market.at[exit_date, "benchmark_close"]
                benchmark_return = (
                    (float(benchmark_end) / float(benchmark_start) - 1.0) * 100.0
                    if _finite(benchmark_start)
                    and _finite(benchmark_end)
                    and float(benchmark_start) > 0
                    else np.nan
                )
                high_window = high.iloc[entry_pos : exit_pos + 1][code].astype(float)
                low_window = low.iloc[entry_pos : exit_pos + 1][code].astype(float)
                max_high = high_window.replace([np.inf, -np.inf], np.nan).max()
                min_low = low_window.replace([np.inf, -np.inf], np.nan).min()
                row_data = {
                    **common,
                    "hold_days": hold,
                    "exit_date": exit_date,
                    "exit_close": round(float(exit_close), 4),
                    "gross_return_pct": round(gross * 100.0, 4),
                    "net_return_pct": round(net, 4),
                    "benchmark_return_pct": round(benchmark_return, 4)
                    if _finite(benchmark_return)
                    else np.nan,
                    "alpha_pct": round(net - benchmark_return, 4)
                    if _finite(benchmark_return)
                    else np.nan,
                    "mfe_pct": round((float(max_high) / entry_open - 1.0) * 100, 4)
                    if _finite(max_high)
                    else np.nan,
                    "mae_pct": round((float(min_low) / entry_open - 1.0) * 100, 4)
                    if _finite(min_low)
                    else np.nan,
                }
                rows.append(row_data)

        events = pd.DataFrame(rows)
        if events.empty:
            raise ValueError("潜龙老版本在所选区间没有可成交信号")
        hold_counts = events.groupby("event_id")["hold_days"].nunique()
        events_with_results = int(hold_counts.size)
        no_exit_signals = int(len(valid_entry_ids) - events_with_results)
        partial_exit_signals = int((hold_counts < len(HOLDS)).sum())
        complete_h5_signals = int((hold_counts == len(HOLDS)).sum())
        event_head = events.drop_duplicates("event_id")
        factors = {
            "board": _factor_table(events, "board", BOARD_ORDER),
            "turnover_band": _factor_table(events, "turnover_band", TURNOVER_ORDER),
            "market_regime": _factor_table(events, "market_regime", REGIME_ORDER),
            "breadth_band": _factor_table(events, "breadth_band", BREADTH_ORDER),
            "gap_coarse": _factor_table(events, "gap_coarse", GAP_COARSE_ORDER),
            "gap_band": _factor_table(events, "gap_band", GAP_ORDER),
            "signal_return_band": _factor_table(
                events, "signal_return_band", SIGNAL_RETURN_ORDER
            ),
            "market_day_band": _factor_table(events, "market_day_band", MARKET_DAY_ORDER),
        }
        combinations = _combination_table(events)
        config = {
            "db": str(db_path),
            "data_snapshot": {
                str(row["key"]): str(row["value"])
                for row in conn.execute("SELECT key, value FROM meta")
            },
            "adjust": args.adjust,
            "strategy": "qianlong-close legacy / QianlongCloseePicker",
            "benchmark": BENCHMARK_CODE,
            "signal_start": window["signal_start"],
            "signal_end": window["signal_end"],
            "load_start": window["load_start"],
            "data_end": window["data_end"],
            "cost_pct": args.cost_pct,
            "min_list_days": args.min_list_days,
            "stock_codes": len(codes),
            "signals_total": total_signals,
            "buyable_signals": len(valid_entry_ids),
            "events_with_results": events_with_results,
            "no_exit_signals": no_exit_signals,
            "partial_exit_signals": partial_exit_signals,
            "complete_h5_signals": complete_h5_signals,
            "unbuyable_signals": unbuyable,
            "unbuyable_reasons": unbuyable_reasons,
            "missing_turnover_signals": int((event_head["turnover_band"] == "缺失").sum()),
            "turnover_note": "仓内小数口径，0.05 表示 5%",
            "combination_dimensions": {
                "board": list(BOARD_ORDER),
                "turnover_band": list(TURNOVER_ORDER),
                "market_regime": list(REGIME_ORDER),
                "gap_band": list(GAP_ORDER),
                "hold_days": list(HOLDS),
            },
        }
        events.to_csv(output_dir / "qianlong-v1-events.csv", index=False, encoding="utf-8-sig")
        combinations.to_csv(
            output_dir / "qianlong-v1-combinations.csv", index=False, encoding="utf-8-sig"
        )
        (output_dir / "qianlong-v1-config.json").write_text(
            json.dumps(config, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
        )
        report = _render_report(
            output_dir=output_dir,
            config=config,
            events=events,
            factors=factors,
            combinations=combinations,
        )
        return report, config
    finally:
        conn.close()


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--db", default=str(default_market_db()), help="只读 market.db 路径")
    parser.add_argument("--start", default="2023-01-01", help="信号起始日")
    parser.add_argument("--end", default=None, help="信号结束日；默认自动留出完整 H5")
    parser.add_argument(
        "--output-dir",
        default="output/qianlong-v1-combination-20260801",
        help="结果目录",
    )
    parser.add_argument("--adjust", choices=("none", "qfq", "hfq"), default="qfq")
    parser.add_argument("--cost-pct", type=float, default=DEFAULT_COST_PCT)
    parser.add_argument("--min-list-days", type=int, default=DEFAULT_MIN_LIST_DAYS)
    return parser


def main() -> int:
    args = _parser().parse_args()
    report, config = _run(args)
    print(f"report={report}")
    print(
        "signals={signals_total} buyable={buyable_signals} unbuyable={unbuyable_signals} "
        "window={signal_start}..{signal_end}".format(**config)
    )
    for hold in HOLDS:
        print(
            "hold={hold} "
            "{stats}".format(
                hold=hold,
                stats=_stats(
                    pd.read_csv(report.parent / "qianlong-v1-events.csv")
                    .query("hold_days == @hold")
                ),
            )
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
