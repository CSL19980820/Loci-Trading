"""独立尾盘 14:50 候选研究。

信号采用日 K 可复现代理：T 日 14:50 观察到的价格/量能用 T 日日线近似，
技术因子只使用截至 T 的已完成 K。脚本只读 ``market.db``，不注册活动战法。
"""
from __future__ import annotations

import argparse
from concurrent.futures import ThreadPoolExecutor
from dataclasses import asdict, dataclass
import json
import os
from pathlib import Path
import sqlite3
from typing import Any, Iterable

import numpy as np
import pandas as pd

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in os.sys.path:
    os.sys.path.insert(0, str(PROJECT_ROOT))

from src.backtest import (
    BacktestConfig,
    PortfolioResearchConfig,
    analyze_portfolio,
    run_backtest,
    run_backtest_fast,
)
from src.formula import ATR, MA, REF, RSI, ROC, limit_up_flags
from src.market.domain.universe import classify_board, is_st_name
from scripts.sanyuan_tail_resonance_research import _load_days, _read_only_connection


@dataclass(frozen=True, slots=True)
class Tail1450Params:
    roc_min: float = 0.0
    roc_max: float = 10.0
    rsi_min: float = 50.0
    rsi_max: float = 74.0
    clv_min: float = 0.70
    volume_ratio_min: float = 1.0
    turnover_min: float = 0.01
    turnover_max: float = 0.08
    amount_min: float = 30_000_000.0
    atr_pct_max: float = 0.10
    price_min: float = 5.0
    limit_buffer: float = 0.02
    top_n: int = 2


def _load_universe(
    conn: sqlite3.Connection, *, as_of: str, boards: set[str]
) -> tuple[list[str], dict[str, dict[str, str]]]:
    rows = conn.execute(
        "SELECT code,name,list_date,delist_date,status,instrument_type FROM instruments"
    ).fetchall()
    as_of_date = pd.Timestamp(as_of)
    codes: list[str] = []
    meta: dict[str, dict[str, str]] = {}
    for row in rows:
        code = str(row[0]).zfill(6)
        name = str(row[1] or "")
        if classify_board(code) not in boards or is_st_name(name):
            continue
        if str(row[4] or "normal") in {"suspended", "delisted"}:
            continue
        listed = str(row[2] or "")[:10]
        if listed:
            try:
                if (as_of_date - pd.Timestamp(listed)).days < 60:
                    continue
            except (TypeError, ValueError):
                pass
        codes.append(code)
        meta[code] = {"name": name, "board": classify_board(code)}
    return sorted(set(codes)), meta


def _panel_from_flat(
    flat: pd.DataFrame, *, dates: Iterable[str], codes: list[str], field: str
) -> pd.DataFrame:
    if flat.empty:
        return pd.DataFrame(index=pd.Index(list(dates), name="trade_date"), columns=codes)
    panel = flat.pivot(index="trade_date", columns="code", values=field)
    panel.index = panel.index.astype(str)
    panel.columns = panel.columns.astype(str).str.zfill(6)
    return panel.reindex(index=list(dates), columns=codes).astype("float32")


def _load_panels(
    conn: sqlite3.Connection,
    *,
    load_start: str,
    load_end: str,
    dates: list[str],
    codes: list[str],
) -> tuple[dict[str, pd.DataFrame], dict[str, pd.DataFrame]]:
    fields = ["open", "high", "low", "close", "volume", "amount", "turnover"]
    date_index = [day for day in dates if load_start <= day <= load_end]
    placeholders = ",".join("?" for _ in codes)
    raw: dict[str, pd.DataFrame] = {}
    for field in fields:
        flat = pd.read_sql_query(
            f"SELECT trade_date,code,{field} FROM quotes_daily "
            f"WHERE trade_date>=? AND trade_date<=? AND code IN ({placeholders})",
            conn,
            params=[load_start, load_end, *codes],
            dtype={field: "float32"},
        )
        flat["code"] = flat["code"].astype(str).str.zfill(6)
        raw[field] = _panel_from_flat(
            flat, dates=date_index, codes=codes, field=field
        )
        del flat

    factors = pd.read_sql_query(
        "SELECT code,trade_date,hfq_factor FROM adjust_factors WHERE trade_date<=?",
        conn,
        params=[load_end],
    )
    factors["code"] = factors["code"].astype(str).str.zfill(6)
    factors = factors[factors["code"].isin(set(codes))]
    if factors.empty:
        ratio = pd.DataFrame(1.0, index=date_index, columns=codes, dtype="float32")
    else:
        sparse = factors.pivot(index="trade_date", columns="code", values="hfq_factor")
        sparse.index = sparse.index.astype(str)
        sparse.columns = sparse.columns.astype(str).str.zfill(6)
        aligned = (
            sparse.reindex(sparse.index.union(pd.Index(date_index)))
            .sort_index()
            .ffill()
            .bfill()
            .reindex(date_index)
            .reindex(columns=codes)
            .astype("float32")
            .fillna(1.0)
        )
        ratio = aligned.div(aligned.iloc[-1].replace(0.0, 1.0), axis=1)
    qfq = {field: raw[field].copy() for field in fields}
    for field in ("open", "high", "low", "close"):
        qfq[field] = raw[field] * ratio
    return qfq, raw


def _safe_rank(panel: pd.DataFrame) -> pd.DataFrame:
    return panel.rank(axis=1, pct=True, method="first").fillna(0.0)


def build_tail_1450_factors(
    qfq: dict[str, pd.DataFrame],
    raw: dict[str, pd.DataFrame],
) -> dict[str, pd.DataFrame]:
    """预计算参数扫描共享的 PIT 面板。"""
    close, high, low = qfq["close"], qfq["high"], qfq["low"]
    volume = raw["volume"]
    spread = (high - low).replace(0.0, np.nan)
    clv = ((close - low) / spread).clip(0.0, 1.0)
    roc5 = ROC(close, 5)
    rsi14 = RSI(close, 14)
    atr_pct = ATR(high, low, close, 14) / close
    vol_ratio = volume / MA(volume, 20)
    ma5, ma20, ma60 = MA(close, 5), MA(close, 20), MA(close, 60)
    trend = (ma5 > ma20) & (ma20 > ma60) & (close > ma5)
    breadth = (close > REF(close, 1)).mean(axis=1)
    market_ok = pd.DataFrame(
        np.repeat((breadth >= 0.40).to_numpy()[:, None], len(close.columns), axis=1),
        index=close.index,
        columns=close.columns,
    )
    ratios = pd.DataFrame(
        np.repeat(
            [[0.20 if code.startswith(("300", "301", "688")) else 0.10 for code in close.columns]],
            len(close),
            axis=0,
        ),
        index=close.index,
        columns=close.columns,
    )
    raw_close = raw["close"]
    return {
        "clv": clv,
        "roc5": roc5,
        "rsi14": rsi14,
        "atr_pct": atr_pct,
        "vol_ratio": vol_ratio,
        "trend": trend,
        "market_ok": market_ok,
        "sealed": limit_up_flags(raw_close, raw["high"], ratios, tolerance=0.995),
        "limit_price": (raw_close.shift(1) * (1.0 + ratios)).round(2),
        "one_word": pd.DataFrame(
            np.isclose(raw["high"], raw["low"], equal_nan=False),
            index=close.index,
            columns=close.columns,
        ),
    }


def compute_tail_1450_signals(
    qfq: dict[str, pd.DataFrame],
    raw: dict[str, pd.DataFrame],
    meta: dict[str, dict[str, str]],
    params: Tail1450Params,
    *,
    factors: dict[str, pd.DataFrame] | None = None,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    """返回候选信号和横截面排序分数；不读取任何未来行。"""
    del meta
    close = qfq["close"]
    volume, amount, turnover = raw["volume"], raw["amount"], raw["turnover"]
    shared = factors or build_tail_1450_factors(qfq, raw)
    clv, roc5 = shared["clv"], shared["roc5"]
    rsi14, atr_pct = shared["rsi14"], shared["atr_pct"]
    vol_ratio, trend = shared["vol_ratio"], shared["trend"]
    below_buffer = raw["close"] < shared["limit_price"] * (1.0 - params.limit_buffer)
    buyable = (
        (volume > 0)
        & amount.ge(params.amount_min)
        & turnover.ge(params.turnover_min)
        & turnover.lt(params.turnover_max)
        & (close >= params.price_min)
        & ~shared["sealed"]
        & ~shared["one_word"]
        & below_buffer
    )
    signal = (
        trend
        & roc5.ge(params.roc_min)
        & roc5.le(params.roc_max)
        & rsi14.ge(params.rsi_min)
        & rsi14.le(params.rsi_max)
        & clv.ge(params.clv_min)
        & vol_ratio.ge(params.volume_ratio_min)
        & atr_pct.le(params.atr_pct_max)
        & shared["market_ok"]
        & buyable
    )
    signal = pd.DataFrame(signal, index=close.index, columns=close.columns).fillna(False)
    score = (
        _safe_rank(roc5) * 0.35
        + _safe_rank(clv) * 0.25
        + _safe_rank(vol_ratio.clip(upper=5.0)) * 0.20
        + _safe_rank(turnover) * 0.10
        + _safe_rank(-atr_pct) * 0.10
    )
    return signal, score


def select_top(signal: pd.DataFrame, score: pd.DataFrame, top_n: int) -> pd.DataFrame:
    ranked = score.where(signal).rank(axis=1, ascending=False, method="first")
    return (signal & ranked.le(top_n)).fillna(False)


def _metrics(frame: pd.DataFrame) -> dict[str, Any]:
    if frame.empty:
        return {"trades": 0}
    valid = frame[frame["exit_reason"] != "data_end"]
    if valid.empty:
        return {"trades": 0, "data_end_trades": int(len(frame))}
    net = valid["net_return_pct"].astype(float)
    wins, losses = net[net > 0], net[net <= 0]
    avg_win = float(wins.mean()) if not wins.empty else None
    avg_loss = float(losses.mean()) if not losses.empty else None
    return {
        "trades": int(len(valid)),
        "win_rate_pct": round(float((net > 0).mean() * 100), 2),
        "avg_net_return_pct": round(float(net.mean()), 4),
        "payoff_ratio": (
            None if avg_win is None or not avg_loss else round(avg_win / abs(avg_loss), 4)
        ),
        "profit_factor": (
            None if losses.empty or losses.sum() == 0 else round(float(wins.sum() / abs(losses.sum())), 4)
        ),
        "max_drawdown_pct": round(float(((1 + net.div(100)).cumprod() / (1 + net.div(100)).cumprod().cummax() - 1).min() * 100), 4),
        "data_end_trades": int(len(frame) - len(valid)),
    }


def _phase_result(
    signal: pd.DataFrame,
    raw: dict[str, pd.DataFrame],
    start: str,
    end: str,
    config: BacktestConfig,
    *,
    fast: bool = False,
) -> tuple[dict[str, Any], Any]:
    mask = pd.DataFrame(False, index=signal.index, columns=signal.columns)
    mask.loc[(mask.index >= start) & (mask.index <= end)] = signal.loc[
        (signal.index >= start) & (signal.index <= end)
    ]
    runner = run_backtest_fast if fast else run_backtest
    result = runner(
        mask,
        raw,
        entry_timing="close",
        config=config,
        strategy_slug="tail-1450-reclaim",
    )
    return _metrics(result.to_frame()), result


def _variant_grid() -> list[Tail1450Params]:
    values: list[Tail1450Params] = []
    for roc_min in (0.0, 2.0):
        for roc_max in (6.0, 10.0):
            for rsi_min in (50.0, 55.0):
                for clv_min in (0.65, 0.75):
                    for volume_min in (0.8, 1.2):
                        values.append(
                            Tail1450Params(
                                roc_min=roc_min,
                                roc_max=roc_max,
                                rsi_min=rsi_min,
                                clv_min=clv_min,
                                volume_ratio_min=volume_min,
                            )
                        )
    return values


def _rank_train_validation(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    eligible = [row for row in rows if row["validation"]["trades"] >= 30]
    return sorted(
        eligible or rows,
        key=lambda row: (
            row["validation"].get("payoff_ratio") is not None,
            row["validation"].get("payoff_ratio") or -999.0,
            row["validation"].get("win_rate_pct") or -999.0,
            row["validation"].get("profit_factor") or -999.0,
        ),
        reverse=True,
    )


def run(args: argparse.Namespace) -> dict[str, Any]:
    db_path = Path(args.db).expanduser().resolve()
    with _read_only_connection(db_path) as conn:
        days = _load_days(conn)
    all_start, all_end = args.start, args.end
    start_pos = days.index(all_start)
    load_start = days[max(0, start_pos - 80)]
    with _read_only_connection(db_path) as conn:
        codes, meta = _load_universe(conn, as_of=all_end, boards={"main", "chi_next"})
        qfq, raw = _load_panels(
            conn, load_start=load_start, load_end=all_end, dates=days, codes=codes
        )
    factors = build_tail_1450_factors(qfq, raw)
    scan_config = BacktestConfig(hold_days=5, stop_loss_pct=None, take_profit_pct=None, benchmark=None)
    train = (all_start, "2024-12-31")
    validation = ("2025-01-02", "2025-12-31")
    oos = ("2026-01-02", all_end)

    def evaluate(params: Tail1450Params) -> dict[str, Any]:
        signal, score = compute_tail_1450_signals(qfq, raw, meta, params, factors=factors)
        selected = select_top(signal, score, params.top_n)
        result = run_backtest_fast(
            selected,
            raw,
            entry_timing="close",
            config=scan_config,
            strategy_slug="tail-1450-reclaim:scan",
        )
        frame = result.to_frame()
        train_m = _metrics(frame[frame["signal_date"].between(*train)]) if not frame.empty else {"trades": 0}
        val_m = _metrics(frame[frame["signal_date"].between(*validation)]) if not frame.empty else {"trades": 0}
        return {"params": asdict(params), "train": train_m, "validation": val_m, "selected": selected}

    with ThreadPoolExecutor(max_workers=min(2, (os.cpu_count() or 2))) as pool:
        stage1 = list(pool.map(evaluate, _variant_grid()))
    ranked = _rank_train_validation(stage1)[:8]

    exit_grid = [
        (3, -3.0, 6.0),
        (5, -3.0, 6.0),
        (5, -4.0, 8.0),
        (7, -4.0, 8.0),
        (7, -5.0, 10.0),
        (10, -5.0, 10.0),
    ]
    exit_rows: list[dict[str, Any]] = []
    for base in ranked:
        params = Tail1450Params(**base["params"])
        signal, score = compute_tail_1450_signals(qfq, raw, meta, params, factors=factors)
        selected = select_top(signal, score, params.top_n)
        for hold_days, stop_loss, take_profit in exit_grid:
            config = BacktestConfig(
                hold_days=hold_days,
                stop_loss_pct=stop_loss,
                take_profit_pct=take_profit,
                benchmark=None,
            )
            result = run_backtest(
                selected,
                raw,
                entry_timing="close",
                config=config,
                strategy_slug="tail-1450-reclaim:exit-grid",
            )
            frame = result.to_frame()
            tr = _metrics(frame[frame["signal_date"].between(*train)]) if not frame.empty else {"trades": 0}
            va = _metrics(frame[frame["signal_date"].between(*validation)]) if not frame.empty else {"trades": 0}
            exit_rows.append({"params": asdict(params), "exit": asdict(config), "train": tr, "validation": va})
    chosen = max(
        exit_rows,
        key=lambda row: (
            row["validation"].get("win_rate_pct", 0) >= 50,
            row["validation"].get("payoff_ratio") is not None,
            row["validation"].get("payoff_ratio") or -999.0,
            row["validation"].get("profit_factor") or -999.0,
            row["validation"].get("trades", 0),
        ),
    )
    chosen_params = Tail1450Params(**chosen["params"])
    chosen_config = BacktestConfig(**{key: value for key, value in chosen["exit"].items() if key in asdict(BacktestConfig())})
    signal, score = compute_tail_1450_signals(qfq, raw, meta, chosen_params, factors=factors)
    selected = select_top(signal, score, chosen_params.top_n)
    oos_metrics, oos_result = _phase_result(selected, raw, *oos, chosen_config)
    oos_frame = oos_result.to_frame()
    portfolio = analyze_portfolio(
        oos_result.trades,
        config=PortfolioResearchConfig(
            initial_capital=200_000.0, max_positions=chosen_params.top_n, period="month"
        ),
        trading_dates=[day for day in days if oos[0] <= day <= oos[1]],
        strategy_slug="tail-1450-reclaim",
    ).to_dict()
    output = Path(args.output).expanduser().resolve()
    output.mkdir(parents=True, exist_ok=True)
    (output / "stage1.json").write_text(json.dumps([{k: v for k, v in row.items() if k != "selected"} for row in stage1], ensure_ascii=False, indent=2), encoding="utf-8")
    (output / "exit_grid.json").write_text(json.dumps(exit_rows, ensure_ascii=False, indent=2), encoding="utf-8")
    oos_frame.to_csv(output / "oos-trades.csv", index=False, encoding="utf-8-sig")
    summary = {
        "strategy": "tail-1450-reclaim",
        "schedule": "14:50 after snapshot; close execution proxy",
        "source_count": 52,
        "data": {"db": str(db_path), "load_start": load_start, "end": all_end, "codes": len(codes), "survivorship_note": "current instrument table; not strict historical universe"},
        "formula": "MA5>MA20>MA60, ROC5 band, RSI14 band, CLV, volume/MA20, turnover, amount, ATR14/close, breadth, non-limit buffer",
        "train": train,
        "validation": validation,
        "oos": {"range": oos, "metrics": oos_metrics},
        "chosen": {"params": asdict(chosen_params), "exit": asdict(chosen_config), "validation": chosen["validation"]},
        "portfolio_oos": portfolio,
        "selection_rule": "validation only; OOS evaluated once; no OOS parameter tuning",
    }
    (output / "summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
    print(json.dumps(summary, ensure_ascii=False, indent=2, default=str))
    return summary


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--db", default=os.environ.get("PALACE_MARKET_DB") or r"E:\entertainment_software\Loci\data\market.db")
    parser.add_argument("--start", default="2024-01-02")
    parser.add_argument("--end", default="2026-07-31")
    parser.add_argument("--output", default="output/tail-1450-reclaim-2024-01-02_2026-07-31")
    return parser


if __name__ == "__main__":
    run(build_parser().parse_args())
