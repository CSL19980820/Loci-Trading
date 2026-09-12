"""用户日线原稿的逐票实现；14:50 用当时累计 OHLCV，不外推全天量。

停牌对应的全空面板行不构成日 K；部分字段缺失保留行位，并使受影响
锚点窗口失败关闭。浮点比较按原表达式执行，未声称原生通达信数值验收。
"""
from __future__ import annotations

from typing import Any, Mapping

import numpy as np
import pandas as pd

from src.formula import ZTPRICE
from src.strategy.domain.base import SignalResult, StrategyError, merge_params


_FIELDS = ("open", "high", "low", "close", "volume")
_FACTORS = (
    "CY", "ZTJ", "ZT", "DZ", "QD", "T", "N", "BCP", "BOP", "BVL",
    "MIDP", "YB", "BARSCOUNT", "QD_COUNT", "SJ", "HL", "WH", "SX",
    "WD", "ZQ", "WZ", "XG", "DATA_OK", "PRE",
)


class ImpulsePullbackTailV1:
    slug = "impulse-pullback-tail-v1"
    name = "涨停大涨回落转强·十日"
    description = "主板10%涨停、创业板收阳且大涨启动，整理回落后重新转强。"
    entry_timing = "next_open"
    entry_instructions = (
        "交易日14:50按当时日线快照筛选候选，使用截至采集时的实际累计成交量。"
        "研究执行规则为次交易日开盘入场，买入日计第1日、第10个市场交易日收盘退出。"
        "涨停开盘不买、跌停收盘或停牌时延期退出；20万元、最多5仓、100股整手。"
        "历史验证使用已审计14:50数据集和逐日收盘估值；定时任务只筛选，不执行买卖。"
        "原生通达信同输入对照仍待验证。"
    )
    adjust = "none"
    screen_managed_job = False
    strict_live_ohlcv = True
    default_universe = {"preset": "default_a_share", "boards": ["chi_next"], "min_list_days": 0}
    warmup_bars = 120
    strategy_revision = "impulse-pullback-tail-v1:2"
    backtest_config = {
        "hold_days": 9, "stop_loss_pct": None, "take_profit_pct": None,
        "commission_bps": 3, "stamp_duty_bps": 10, "slippage_bps": 7,
        "benchmark": None, "strict_limit_prices": True, "economic_returns": True,
        "signal_dataset": "impulse-1450-20250101-20260911-v1",
        "valuation_end": "2026-09-11", "start": "2025-01-01", "end": "2026-09-11",
        "account_model": "daily_close", "initial_capital": 200000,
        "max_positions": 5, "lot_size": 100,
        "split": {"train_start": "2025-01-01", "train_end": "2025-12-31",
                  "oos_start": "2026-01-01", "oos_end": "2026-09-11"},
    }

    def default_params(self) -> dict[str, Any]:
        return {"DF": 0.10, "TS": 10, "SL": 0.80, "ZF": 0.03}

    def required_fields(self) -> tuple[str, ...]:
        return _FIELDS

    def min_bars(self) -> int:
        return 60

    def compute(
        self, panels: dict[str, pd.DataFrame], params: dict[str, Any] | None = None,
    ) -> SignalResult:
        p = self._validated_params(params)
        reference = _validate_panels(panels)
        values = {name: np.full(reference.shape, np.nan) for name in _FACTORS}
        values["XG"].fill(0)
        values["DATA_OK"].fill(0)
        matrices = [panels[name].to_numpy(float) for name in _FIELDS]
        for begin in range(0, len(reference.columns), 128):
            stop = begin + 128
            bars = np.stack([matrix[:, begin:stop] for matrix in matrices], axis=2)
            present = ~np.isnan(bars).all(axis=2)
            rows, columns = np.nonzero(present)
            if not rows.size:
                continue
            # 每票独立压缩停牌行，部分损坏行保留；补齐尾部不映回输出。
            compressed_rows = np.cumsum(present, axis=0)[rows, columns] - 1
            compressed = np.full(bars.shape, np.nan)
            compressed[compressed_rows, columns] = bars[rows, columns]
            cy = np.array([str(code).startswith("30") for code in reference.columns[begin:stop]])
            computed = _compute_batch(compressed, cy, p)
            for name, result in computed.items():
                values[name][rows, begin + columns] = result[compressed_rows, columns]
        factors = {
            name: pd.DataFrame(array, index=reference.index, columns=reference.columns)
            for name, array in values.items()
        }
        return SignalResult(signals=factors["XG"].eq(1), factors=factors)

    def live_candidate_codes(
        self, panels: dict[str, pd.DataFrame], trade_date: str,
        params: dict[str, Any] | None = None,
    ) -> list[str]:
        """只检查原式事前必要条件，不读取今日K，也不构造假今日K。"""
        p = self._validated_params(params)
        reference = _validate_panels(panels)
        if reference.empty:
            return []
        historical = reference.index < trade_date
        candidates = []
        for column, code in enumerate(reference.columns):
            bars = np.column_stack([
                panels[name].iloc[:, column].loc[historical].to_numpy(float) for name in _FIELDS
            ])
            bars = bars[~np.isnan(bars).all(axis=1)]
            if len(bars) < 59:
                continue
            o, h, l, c, v = bars.T
            available = np.flatnonzero(np.isfinite(c))
            if not available.size or len(c) - available[0] < 59:
                continue
            _, _, _, qd = _start_flags(bars, str(code).startswith("30"), p["DF"])
            starts = np.flatnonzero(qd)
            if not starts.size:
                continue
            anchor = int(starts[-1])
            t = len(c) - anchor
            if not 3 <= t <= p["TS"]:
                continue
            if not np.isfinite(bars[max(0, anchor - 1):]).all():
                continue
            middle = (c[anchor] + o[anchor]) / 2
            minimum = np.min(c[anchor + 1:])
            if (c[anchor] > o[anchor] and h[anchor] > l[anchor]
                    and minimum < c[anchor] and minimum >= middle
                    and np.sum(v[anchor + 1:]) / (t - 1) <= v[anchor] * p["SL"]
                    and l[-1] >= l[-2]):
                candidates.append(str(code))
        return candidates

    def compute_asof(
        self, panels: dict[str, pd.DataFrame],
        snapshots: Mapping[tuple[str, str], tuple[float, ...] | None],
        *, start: str, end: str, params: dict[str, Any] | None = None,
    ) -> SignalResult:
        """逐日只替换当根，历史仍用已完成日K；事前候选缺快照即拒绝。"""
        p = self._validated_params(params)
        reference = _validate_panels(panels)
        factors = self.compute(panels, p).factors
        pre = factors["PRE"].eq(1)
        pre.loc[(pre.index < start) | (pre.index > end), :] = False
        signals = pd.DataFrame(False, index=reference.index, columns=reference.columns)
        rows, columns = np.nonzero(pre.to_numpy(bool))
        raw_by_column: dict[int, tuple[np.ndarray, np.ndarray]] = {}
        for row, column in zip(rows.tolist(), columns.tolist()):
            key = (str(reference.index[row]), str(reference.columns[column]))
            if key not in snapshots:
                raise StrategyError(f"14:50历史快照缺失：{key[1]} / {key[0]}")
            snapshot = snapshots[key]
            if snapshot is None:  # 已有独立证据确认停牌，不能补成一根K。
                continue
            if len(snapshot) != 5 or not np.isfinite(snapshot).all():
                raise StrategyError(f"14:50历史快照OHLCV无效：{key[1]} / {key[0]}")
            if column not in raw_by_column:
                bars = np.column_stack([
                    panels[field].iloc[:, column].to_numpy(float) for field in _FIELDS
                ])
                raw_by_column[column] = (bars, np.flatnonzero(~np.isnan(bars).all(axis=1)))
            bars, positions = raw_by_column[column]
            prior = bars[positions[np.searchsorted(positions, row) - 1]]
            o, _h, low, close, volume = snapshot
            # PRE已包含全部历史条件；只重算WH/WD/ZQ/WZ里的当根比较。
            signals.iat[row, column] = bool(
                low >= factors["MIDP"].iat[row, column] and low >= prior[2]
                and close > o and close > prior[1] and volume > prior[4]
                and close <= factors["BCP"].iat[row, column] * (1 + p["ZF"])
            )
        return SignalResult(signals=signals, factors={})

    def _validated_params(self, params: dict[str, Any] | None) -> dict[str, Any]:
        p = merge_params(self, params)
        for name in ("DF", "SL", "ZF"):
            value = p[name]
            if isinstance(value, bool) or not isinstance(value, (int, float)):
                raise StrategyError(f"{name} 必须是有限非负数")
            if not np.isfinite(value) or value < 0:
                raise StrategyError(f"{name} 必须是有限非负数")
        if isinstance(p["TS"], bool) or not isinstance(p["TS"], int) or p["TS"] < 3:
            raise StrategyError("TS 必须是至少3的整数")
        return p


def _validate_panels(panels: dict[str, pd.DataFrame]) -> pd.DataFrame:
    if any(name not in panels for name in _FIELDS):
        raise StrategyError("回落转强需要 open/high/low/close/volume 字段")
    reference = panels["close"]
    for name in _FIELDS:
        panel = panels[name]
        if not isinstance(panel, pd.DataFrame) or not panel.index.equals(reference.index):
            raise StrategyError(f"{name} 日期索引与close不一致")
        if not panel.columns.equals(reference.columns):
            raise StrategyError(f"{name} 股票索引与close不一致")
    if not reference.index.is_unique or not reference.index.is_monotonic_increasing:
        raise StrategyError("日K日期必须唯一且按时间升序")
    return reference


def _start_flags(
    bars: np.ndarray, cy: bool | np.ndarray, df: float,
) -> tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray]:
    o, h, _, c, _ = np.moveaxis(bars, -1, 0)
    previous = np.concatenate((np.full((1, *c.shape[1:]), np.nan), c[:-1]), axis=0)
    frame = pd.DataFrame(previous) if c.ndim == 2 else pd.Series(previous)
    ztj = ZTPRICE(frame, 0.10).to_numpy()
    zt = (np.abs(c - ztj) < 0.005) & (c == h)
    dz = (c >= previous * (1 + df)) & (c > o)
    return ztj, zt, dz, np.where(cy, dz, zt)


def _compute_stock(bars: np.ndarray, cy: bool, p: dict[str, Any]) -> dict[str, np.ndarray]:
    return {name: value[:, 0] for name, value in _compute_batch(bars[:, None, :], np.array([cy]), p).items()}


def _compute_batch(bars: np.ndarray, cy: np.ndarray, p: dict[str, Any]) -> dict[str, np.ndarray]:
    o, h, l, c, v = np.moveaxis(bars, -1, 0)
    count = len(c)
    out = {name: np.full(c.shape, np.nan) for name in _FACTORS}
    if not count:
        return out
    ztj, zt, dz, qd = _start_flags(bars, cy, p["DF"])
    out.update(CY=np.broadcast_to(cy, c.shape).astype(float), ZTJ=ztj, ZT=zt.astype(float),
               DZ=dz.astype(float), QD=qd.astype(float))
    valid = np.isfinite(bars).all(axis=2)
    # BARSCOUNT是从首个有效C到当前的周期数；部分损坏行不得挤掉周期。
    available = np.isfinite(c)
    rows = np.arange(count)[:, None]
    first = available.argmax(axis=0)
    out["BARSCOUNT"] = np.where(available.any(axis=0) & (rows >= first), rows - first + 1., np.nan)
    # 位移后再累计，今天即使启动也仍使用昨天之前的锚点。
    last = np.maximum.accumulate(np.concatenate((np.full_like(qd[:1], -1, dtype=int),
                                                 np.where(qd, rows, -1)[:-1])), axis=0)
    cumulative = np.concatenate((np.zeros_like(qd[:1], dtype=int), np.cumsum(qd, axis=0)))
    out["QD_COUNT"] = (cumulative[:-1] - cumulative[np.maximum(0, rows[:, 0] - min(p["TS"], count))]).astype(float)
    for name in ("WD", "ZQ", "XG", "DATA_OK", "PRE"):
        out[name].fill(0)
    out["WD"][2:] = (l[1:-1] >= l[:-2]) & (l[2:] >= l[1:-1])
    out["ZQ"][1:] = (c[1:] > o[1:]) & (c[1:] > h[:-1]) & (v[1:] > v[:-1])
    active, columns = np.nonzero(last >= 0)
    if not active.size:
        return out
    target = (active, columns)
    anchors = last[target]
    t = active - anchors
    n = np.maximum(t - 1, 1)
    anchor_target = (anchors, columns)
    bcp, bop, bvl = c[anchor_target], o[anchor_target], v[anchor_target]
    mid = (bcp + bop) / 2
    for name, value in (("T", t), ("N", n), ("BCP", bcp), ("BOP", bop),
                        ("BVL", bvl), ("MIDP", mid)):
        out[name][target] = value
    minimum, volume_sum = np.empty(len(active)), np.empty(len(active))
    # 按相同长度批量归约，保留原窗口的值/顺序/长度；不能换成浮点前缀和差。
    for width in np.unique(n):
        selected = np.flatnonzero(n == width)
        chunk = max(1, 65536 // width)
        for offset in range(0, len(selected), chunk):
            chosen = selected[offset:offset + chunk]
            window = active[chosen, None] - width + np.arange(width)
            stock = columns[chosen, None]
            minimum[chosen] = c[window, stock].min(axis=1)
            volume_sum[chosen] = v[window, stock].sum(axis=1)
    out["YB"][target] = (bcp > bop) & (h[anchor_target] > l[anchor_target])
    out["SJ"][target] = ((out["QD_COUNT"][target] > 0) & (t >= 3) & (t <= p["TS"])
                          & (out["BARSCOUNT"][target] >= 60))
    out["HL"][target] = minimum < bcp
    out["WH"][target] = (minimum >= mid) & (l[target] >= mid)
    out["SX"][target] = volume_sum / n <= bvl * p["SL"]
    out["WZ"][target] = c[target] <= bcp * (1 + p["ZF"])
    # 整数坏行前缀计数包括锚点前一日；PRE只验证今日之前的数据。
    invalid = np.concatenate((np.zeros_like(valid[:1], dtype=int), np.cumsum(~valid, axis=0)))
    begin = np.maximum(0, anchors - 1)
    out["DATA_OK"][target] = invalid[active + 1, columns] == invalid[begin, columns]
    prior_rising = (active >= 2) & (l[active - 1, columns] >= l[np.maximum(0, active - 2), columns])
    out["PRE"][target] = (
        (out["SJ"][target] == 1) & (out["YB"][target] == 1)
        & (out["HL"][target] == 1) & (out["SX"][target] == 1)
        & (minimum >= mid) & prior_rising & (invalid[target] == invalid[begin, columns])
    )
    gates = ("SJ", "YB", "HL", "WH", "SX", "WD", "ZQ", "WZ", "DATA_OK")
    out["XG"][target] = np.logical_and.reduce([out[name][target] == 1 for name in gates])
    return out


# 已下线；只保留历史研究复现，不进入活动目录。
