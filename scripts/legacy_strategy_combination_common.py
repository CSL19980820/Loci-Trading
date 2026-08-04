"""归档战法组合回测的行情、分箱与面板公共工具。"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date, timedelta
import importlib.util
from itertools import product
from pathlib import Path
import sqlite3
from typing import Any, Sequence

import numpy as np
import pandas as pd

from scripts.qianlong_v1_backtest_report import stats
from src.market.domain.universe import classify_board, is_delisting_name, is_st_name
from src.market.infrastructure.store_panel import MarketPanelMixin
from src.strategy.domain import base as strategy_base


HOLDS = (1, 3, 5)
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


@dataclass(frozen=True)
class StrategySpec:
    key: str
    name: str
    class_name: str
    min_bars: int


STRATEGIES = {
    "haidi": StrategySpec("haidi", "海底捞月", "HaidiLaoyue", 130),
    "chouma": StrategySpec("chouma", "筹码峰突破", "ChoumaTupo", 130),
    "sanwai": StrategySpec("sanwai", "三外有三", "SanwaiYousan", 130),
}


class ReadOnlyPanelStore(MarketPanelMixin):
    """复用面板加载逻辑，但保持连接为 SQLite 只读模式。"""

    def __init__(self, conn: sqlite3.Connection) -> None:
        self.conn = conn


def load_legacy_module() -> Any:
    path = Path(__file__).resolve().parents[1] / "src" / "strategy" / "application" / "backup" / "lugaowen-legacy.py"
    module_spec = importlib.util.spec_from_file_location("_lugaowen_legacy_source", path)
    if module_spec is None or module_spec.loader is None:
        raise ImportError(f"无法加载归档战法源码：{path}")
    module = importlib.util.module_from_spec(module_spec)
    original_register = strategy_base.register
    strategy_base.register = lambda engine: engine
    try:
        module_spec.loader.exec_module(module)
    finally:
        strategy_base.register = original_register
    return module


def ro_connect(path: Path) -> sqlite3.Connection:
    resolved = path.expanduser().resolve()
    if not resolved.is_file():
        raise FileNotFoundError(f"行情库不存在：{resolved}")
    conn = sqlite3.connect(f"file:{resolved}?mode=ro", uri=True)
    conn.row_factory = sqlite3.Row
    return conn


def calendar(conn: sqlite3.Connection) -> list[str]:
    rows = conn.execute(
        "SELECT trade_date FROM trading_calendar ORDER BY trade_date"
    ).fetchall()
    if rows:
        return [str(row[0]) for row in rows]
    rows = conn.execute(
        "SELECT DISTINCT trade_date FROM quotes_daily ORDER BY trade_date"
    ).fetchall()
    return [str(row[0]) for row in rows]


def resolve_window(
    days: Sequence[str], start: str, end: str | None, max_hold: int, warmup: int
) -> dict[str, Any]:
    if not days:
        raise ValueError("行情库没有交易日")
    start_pos = next((i for i, day in enumerate(days) if day >= start), len(days) - 1)
    requested_end_pos = (
        len(days) - 1
        if not end
        else next((i for i, day in enumerate(days) if day >= end), len(days) - 1)
    )
    last_complete_pos = len(days) - 1 - 1 - max_hold
    signal_end_pos = min(requested_end_pos, last_complete_pos)
    if signal_end_pos < start_pos:
        raise ValueError("所选区间没有同时具备次日入场和完整持有期的数据")
    return {
        "signal_start": days[start_pos],
        "signal_end": days[signal_end_pos],
        "load_start": days[max(0, start_pos - warmup)],
        "data_end": days[min(len(days) - 1, signal_end_pos + 1 + max_hold)],
    }


def load_stock_meta(
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
    cutoff = date.fromisoformat(as_of) - timedelta(days=min_list_days)
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
        codes.append(code)
        meta[code] = {"name": name, "board": "创业板" if board == "chi_next" else "主板"}
    return codes, meta


def finite(value: Any) -> bool:
    try:
        return bool(np.isfinite(float(value)))
    except (TypeError, ValueError):
        return False


def turnover_band(value: Any) -> str:
    if not finite(value):
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


def gap_band(value: Any) -> str:
    if not finite(value):
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


def gap_coarse(value: Any) -> str:
    if not finite(value):
        return "缺失"
    number = float(value)
    if number < -0.01:
        return "低开"
    if number < 0.01:
        return "平开"
    return "高开"


def signal_return_band(value: Any) -> str:
    if not finite(value):
        return "缺失"
    number = float(value)
    if number < 0.01:
        return "<1%"
    if number < 0.03:
        return "1-3%"
    return ">=3%"


def market_day_band(value: Any) -> str:
    if not finite(value):
        return "缺失"
    number = float(value)
    if number <= -0.01:
        return "<=-1%"
    if number < 0.01:
        return "-1%~1%"
    return ">=1%"


def market_regime(ret20: Any, close: Any, ma20: Any) -> str:
    if not (finite(ret20) and finite(close) and finite(ma20)):
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


def breadth_band(value: Any) -> str:
    if not finite(value):
        return "数据不足"
    number = float(value)
    if number < 0.40:
        return "弱势<40%"
    if number < 0.60:
        return "中性40-60%"
    return "强势>=60%"


def market_features(
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
        market_regime(ret20.get(day), index_close.get(day), ma20.get(day))
        for day in dates
    ]
    result["breadth"] = breadth
    result["breadth_band"] = breadth.map(breadth_band)
    result["market_day_band"] = index_ret.map(market_day_band)
    return result


def factor_table(events: pd.DataFrame, column: str, order: Sequence[str]) -> pd.DataFrame:
    rows: list[dict[str, Any]] = []
    for hold in HOLDS:
        subset = events[events["hold_days"] == hold]
        for value in order:
            selected = subset[subset[column] == value] if column in subset else subset.iloc[0:0]
            rows.append({"hold_days": hold, "condition": value, **stats(selected)})
    return pd.DataFrame(rows)


def combination_table(events: pd.DataFrame, spec: StrategySpec) -> pd.DataFrame:
    rows: list[dict[str, Any]] = []
    for hold in HOLDS:
        subset = events[events["hold_days"] == hold]
        groups = {
            tuple(key): value
            for key, value in subset.groupby(list(COMBO_COLUMNS), dropna=False)
        }
        for values in product(BOARD_ORDER, TURNOVER_ORDER, REGIME_ORDER, GAP_ORDER):
            group = groups.get(values, subset.iloc[0:0])
            rows.append(
                {
                    "strategy": spec.key,
                    "strategy_name": spec.name,
                    "hold_days": hold,
                    **dict(zip(COMBO_COLUMNS, values)),
                    **stats(group),
                }
            )
    return pd.DataFrame(rows)


def load_snapshot(conn: sqlite3.Connection) -> dict[str, Any]:
    values = {str(row["key"]): str(row["value"]) for row in conn.execute("SELECT key, value FROM meta")}
    row = conn.execute(
        "SELECT COUNT(*) AS n, MIN(trade_date) AS first_date, MAX(trade_date) AS last_date FROM quotes_daily"
    ).fetchone()
    values["quotes_rows_readonly"] = int(row["n"] or 0)
    values["quotes_first_date"] = str(row["first_date"] or "")
    values["quotes_last_date"] = str(row["last_date"] or "")
    return values


def empty_events() -> pd.DataFrame:
    return pd.DataFrame(
        columns=[
            "strategy", "strategy_name", "event_id", "signal_date", "entry_date", "code",
            "name", "board", "turnover", "turnover_band", "signal_return_pct",
            "signal_return_band", "market_regime", "benchmark_ret20_pct", "breadth",
            "breadth_band", "market_day_return_pct", "market_day_band", "gap_pct",
            "gap_band", "gap_coarse", "entry_price", "signal_close",
            "entry_day_intraday_pct", "hold_days", "exit_date", "exit_close",
            "gross_return_pct", "net_return_pct", "benchmark_return_pct", "alpha_pct",
            "mfe_pct", "mae_pct",
        ]
    )
