"""三源 / 潜龙 / RSI 分段式买入 vs 一次性买入研究。

「分段式买入」口径：入场日拆两段 ——
- 第一段（权重 w1）：按策略原入场价成交（三源/潜龙 = T+1 开盘；rsi = T+1 原低吸价）
- 第二段（权重 w2）：在原入场价下方再回撤 dip_pct 挂单；低开按开盘成交、
  盘中触价按挂单价、全天未触价收盘兜底（保证总仓位 100%，
  只比较买入方式，不比较仓位大小）。

退出 / 止损 / 止盈 / 成本全部复用 ``src.backtest`` 经典引擎（不走加速旁路），
信号与入场时点由策略自身声明，避免口径漂移。

用法：
    python scripts\\staged_entry_research.py [--start 2023-01-01] [--output-dir output/staged-entry-research-20260806]
"""
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
    ReadOnlyPanelStore,
    calendar,
    load_snapshot,
    load_stock_meta,
    resolve_window,
    ro_connect,
)
from src.backtest import BacktestConfig, BacktestResult, run_backtest
from src.strategy import get
from src.strategy.application.price_constraints import attach_raw_limit_close
from src.strategy.domain.base import signal_history_bars

#: 需要复权信号 + 未复权执行的策略（三源 V2 用原始价成交）。
EXECUTION_ADJUST_NONE = {"sanyuan-tail-v1"}

FIELDS = ("open", "high", "low", "close", "volume", "turnover")

#: 变体网格：(第一段权重, 第二段权重, 第二段回撤)
STAGED_GRID = (
    (0.5, 0.5, 0.02),  # 主口径：对半开，回撤 2%
    (0.3, 0.7, 0.02),
    (0.7, 0.3, 0.02),
    (0.5, 0.5, 0.01),
    (0.5, 0.5, 0.03),
)


def _config_from_engine(engine: Any) -> BacktestConfig:
    """从策略声明的 backtest_config 构造引擎配置，缺失键走引擎默认。"""
    bc = dict(getattr(engine, "backtest_config", None) or {})
    keys = (
        "hold_days",
        "stop_loss_pct",
        "take_profit_pct",
        "commission_bps",
        "stamp_duty_bps",
        "slippage_bps",
        "allow_limit_up_entry",
        "benchmark",
    )
    kwargs = {key: bc[key] for key in keys if key in bc and bc[key] is not None}
    return BacktestConfig(**kwargs)


def _trim_signals(signals: pd.DataFrame, window: dict[str, Any]) -> pd.DataFrame:
    keep = (signals.index >= window["signal_start"]) & (
        signals.index <= window["signal_end"]
    )
    return signals[keep].fillna(False)


def _staged_open_panel(
    panels: dict[str, pd.DataFrame],
    w1: float,
    w2: float,
    dip_pct: float,
) -> pd.DataFrame:
    """对 next_open 类策略构造「有效开盘价」：第一段开盘 + 第二段回撤挂单。

    全面板逐格构造，不依赖信号位置，无前视：使用的是入场日当天的
    open/high/low/close，而入场日本身就是决策执行日。
    """
    open_, low, close = panels["open"], panels["low"], panels["close"]
    p2_limit = open_ * (1.0 - dip_pct)
    fill2 = pd.DataFrame(
        np.where(
            open_.to_numpy(dtype=float) <= p2_limit.to_numpy(dtype=float),
            open_.to_numpy(dtype=float),
            np.where(
                low.to_numpy(dtype=float) <= p2_limit.to_numpy(dtype=float),
                p2_limit.to_numpy(dtype=float),
                close.to_numpy(dtype=float),
            ),
        ),
        index=open_.index,
        columns=open_.columns,
    )
    return w1 * open_ + w2 * fill2


def _staged_dip_entry(
    panels: dict[str, pd.DataFrame],
    base: BacktestResult,
    w1: float,
    w2: float,
    dip_pct: float,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    """对 next_dip 类策略构造变体信号与有效入场价。

    成交集 = 基准 next_dip 的成交集（原策略「是否买入」的判定不变）；
    变体只改入场成本：第一段按原低吸成交价，第二段在下方回撤挂单，
    未触价收盘兜底。返回 (变体信号, 有效开盘价面板)。
    """
    dates = list(panels["close"].index)
    open_, low, close = panels["open"], panels["low"], panels["close"]
    signals2 = pd.DataFrame(False, index=panels["close"].index, columns=panels["close"].columns)
    eff_open = open_.copy()
    for trade in base.trades:
        if trade.signal_date not in signals2.index:
            continue
        if trade.code not in signals2.columns:
            continue
        signals2.at[trade.signal_date, trade.code] = True
        entry_date = trade.entry_date
        if entry_date not in open_.index:
            continue
        p1 = float(trade.entry_price)
        if not np.isfinite(p1) or p1 <= 0:
            continue
        p2_limit = p1 * (1.0 - dip_pct)
        open_e = float(open_.at[entry_date, trade.code])
        low_e = float(low.at[entry_date, trade.code])
        close_e = float(close.at[entry_date, trade.code])
        if np.isfinite(open_e) and open_e <= p2_limit:
            fill2 = open_e
        elif np.isfinite(low_e) and low_e <= p2_limit:
            fill2 = p2_limit
        else:
            fill2 = close_e
        eff_open.at[entry_date, trade.code] = w1 * p1 + w2 * fill2
    return signals2, eff_open


def _run_variant(
    signals: pd.DataFrame,
    execution_panels: dict[str, pd.DataFrame],
    engine: Any,
    cfg: BacktestConfig,
    variant: dict[str, Any],
) -> BacktestResult:
    panels = execution_panels
    # run_backtest 要求 signals 与 panels 同 index（T+1 / 持有期按位置取行）。
    # 脚本窗口提前约 100 根做预热，必须把信号行对齐回全面板位置。
    aligned_signals = signals.reindex(panels["close"].index).fillna(False)
    if variant["kind"] == "base":
        return run_backtest(
            aligned_signals,
            panels,
            entry_timing=engine.entry_timing,
            entry_price_panel=panels["close"] * (1.0 - variant["dip_pct"])
            if engine.entry_timing == "next_dip"
            else None,
            config=cfg,
            strategy_slug=engine.slug,
        )
    if variant["kind"] == "staged_open":
        eff = _staged_open_panel(panels, variant["w1"], variant["w2"], variant["dip_pct"])
        staged = dict(panels)
        staged["open"] = eff
        return run_backtest(
            aligned_signals,
            staged,
            entry_timing="next_open",
            config=cfg,
            strategy_slug=engine.slug,
        )
    if variant["kind"] == "staged_dip":
        base = variant["base_result"]
        signals2, eff = _staged_dip_entry(panels, base, variant["w1"], variant["w2"], variant["dip_pct"])
        staged = dict(panels)
        staged["open"] = eff
        return run_backtest(
            signals2,
            staged,
            entry_timing="next_open",
            config=cfg,
            strategy_slug=engine.slug,
        )
    raise ValueError(f"未知变体：{variant['kind']}")


def _pick_metrics(result: BacktestResult) -> dict[str, Any]:
    m = result.metrics
    return {
        "trades": m.get("trades", 0),
        "win_rate": m.get("win_rate"),
        "avg_net_return": m.get("avg_net_return"),
        "median_net_return": m.get("median_net_return"),
        "profit_factor": m.get("profit_factor"),
        "avg_mfe": m.get("avg_mfe"),
        "avg_mae": m.get("avg_mae"),
        "exit_reasons": m.get("exit_reasons"),
        "caution": m.get("caution"),
    }


def _run_strategy(
    engine: Any,
    signal_panels: dict[str, pd.DataFrame],
    execution_panels: dict[str, pd.DataFrame],
    window: dict[str, Any],
) -> tuple[pd.DataFrame, list[dict[str, Any]]]:
    signals = _trim_signals(engine.compute(signal_panels).signals, window)
    cfg = _config_from_engine(engine)
    base = _run_variant(signals, execution_panels, engine, cfg, {"kind": "base", "dip_pct": 0.02})

    rows: list[dict[str, Any]] = [
        {"变体": "基准一次性", **{k: v for k, v in _pick_metrics(base).items()}}
    ]
    for w1, w2, dip in STAGED_GRID:
        variant = {
            "kind": "staged_dip" if engine.entry_timing == "next_dip" else "staged_open",
            "w1": w1,
            "w2": w2,
            "dip_pct": dip,
            "base_result": base,
        }
        result = _run_variant(signals, execution_panels, engine, cfg, variant)
        label = f"分段{w1 * 100:.0f}%/{w2 * 100:.0f}%@回撤{dip * 100:.0f}%"
        rows.append({"变体": label, **{k: v for k, v in _pick_metrics(result).items()}})

    frame = pd.DataFrame(rows)
    frame.insert(0, "策略", engine.name)
    return frame, rows


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--db", default=None, help="只读 market.db 路径；默认用配置目录")
    parser.add_argument("--start", default="2023-01-01", help="信号起始日")
    parser.add_argument("--output-dir", default="output/staged-entry-research-20260806")
    parser.add_argument(
        "--strategies",
        default="sanyuan-tail-v1,qianlong-close-v3",
        help="逗号分隔的策略 slug",
    )
    return parser


def main() -> int:
    args = _parser().parse_args()
    from src.shared.paths import market_db as default_market_db

    db_path = Path(args.db or default_market_db()).expanduser().resolve()
    output_dir = Path(args.output_dir).expanduser().resolve()
    output_dir.mkdir(parents=True, exist_ok=True)

    slugs = [item.strip() for item in args.strategies.split(",") if item.strip()]
    engines = [get(slug) for slug in slugs]

    conn: sqlite3.Connection | None = None
    try:
        conn = ro_connect(db_path)
        days = calendar(conn)
        print(f"行情交易日：{len(days)}，{days[0]} .. {days[-1]}")
        max_bars = max(signal_history_bars(engine) for engine in engines)
        max_hold = max(_config_from_engine(engine).hold_days for engine in engines)
        window = resolve_window(days, args.start, None, max_hold, max_bars)
        print(
            "信号窗口：{signal_start} .. {signal_end}（数据到 {data_end}）".format(**window)
        )
        codes, meta = load_stock_meta(conn, as_of=window["signal_end"], min_list_days=60)
        store = ReadOnlyPanelStore(conn)
        signal_panels = store.load_panel(
            fields=FIELDS,
            codes=codes,
            start=window["load_start"],
            end=window["data_end"],
            adjust="qfq",
            min_bars=max_bars,
        )
        execution_panels = signal_panels
        # 三源用未复权 OHLC 模拟实际成交，指标面板保持 qfq。
        if any(slug in EXECUTION_ADJUST_NONE for slug in slugs):
            execution_panels = store.load_panel(
                fields=FIELDS,
                codes=codes,
                start=window["load_start"],
                end=window["data_end"],
                adjust="none",
                min_bars=max_bars,
            )
            execution_panels = {
                field: panel.reindex(
                    index=signal_panels["close"].index,
                    columns=signal_panels["close"].columns,
                )
                for field, panel in execution_panels.items()
            }
        attach_raw_limit_close(
            store,
            signal_panels,
            enabled=any(getattr(engine, "requires_raw_limit_price", False) for engine in engines),
            adjust="qfq",
            codes=codes,
            start=window["load_start"],
            end=window["data_end"],
            min_bars=max_bars,
        )
        if signal_panels["close"].empty:
            raise ValueError("股票池在所选区间没有行情数据")

        all_frames: list[pd.DataFrame] = []
        for engine in engines:
            frame, _rows = _run_strategy(engine, signal_panels, execution_panels, window)
            all_frames.append(frame)
            print(f"\n== {engine.name}（{engine.slug}）==")
            print(frame.to_string(index=False))

        table = pd.concat(all_frames, ignore_index=True)
        table.to_csv(output_dir / "staged-entry-comparison.csv", index=False, encoding="utf-8-sig")
        (output_dir / "staged-entry-config.json").write_text(
            json.dumps(
                {
                    "db": str(db_path),
                    "data_snapshot": load_snapshot(conn),
                    "signal_start": window["signal_start"],
                    "signal_end": window["signal_end"],
                    "load_start": window["load_start"],
                    "data_end": window["data_end"],
                    "stock_codes": len(codes),
                    "strategies": slugs,
                    "staged_grid": [{"w1": w1, "w2": w2, "dip_pct": dip} for w1, w2, dip in STAGED_GRID],
                },
                ensure_ascii=False,
                indent=2,
            )
            + "\n",
            encoding="utf-8",
        )
        print(f"\n结果目录：{output_dir}")
        return 0
    finally:
        if conn is not None:
            conn.close()


if __name__ == "__main__":
    raise SystemExit(main())