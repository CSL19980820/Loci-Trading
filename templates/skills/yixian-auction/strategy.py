"""首板次日开盘筛选。历史条件严格滞后一根，今日只读取 open。"""
from __future__ import annotations

import math
from typing import Any

import numpy as np
import pandas as pd

from src.formula import COUNT, CROSS, EMA, HHV, LLV, MA, REF, SMA, ZTPRICE

FIELDS = ("open", "high", "low", "close", "volume")
DEFAULTS = {
    "N": 16, "R": 1.0, "JQ": 3, "DL_LOOKBACK": 5, "DL_COUNT": 1,
    "VOL_MA": 60, "KDJ_N": 9, "K_SMOOTH": 3, "D_SMOOTH": 3,
    "MACD_FAST": 12, "MACD_SLOW": 26, "MACD_SIGNAL": 9,
    "DIF_MIN": 0.0, "DEA_MIN": 0.0, "MIN_BARS": 65,
    "LIMIT_RATIO": 0.10, "OPEN_MIN": -5.0, "OPEN_MAX": 0.5,
}
INTS = {key for key, value in DEFAULTS.items() if isinstance(value, int)}


def validated(params: dict[str, Any] | None) -> dict[str, Any]:
    p = {**DEFAULTS, **(params or {})}
    if set(p) != set(DEFAULTS):
        raise ValueError("存在未知指标参数")
    for key, value in p.items():
        if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
            raise ValueError(f"{key} 必须是有限数值")
        if key in INTS and (not isinstance(value, int) or not 1 <= value <= 1000):
            raise ValueError(f"{key} 必须是 1～1000 的整数")
    if p["R"] <= 0 or not 0 < p["LIMIT_RATIO"] <= 1:
        raise ValueError("R 必须大于 0，LIMIT_RATIO 必须在 (0, 1] 内")
    if p["OPEN_MIN"] > p["OPEN_MAX"] or p["OPEN_MIN"] <= -100:
        raise ValueError("开盘涨幅下限须大于 -100 且不得超过上限")
    if p["MACD_FAST"] >= p["MACD_SLOW"]:
        raise ValueError("MACD_FAST 必须小于 MACD_SLOW")
    if p["DL_COUNT"] > p["DL_LOOKBACK"]:
        raise ValueError("地量次数不能大于回看天数")
    return p


def history_bars(params: dict[str, Any]) -> int:
    p = validated(params)
    # 递推均线留 12 倍周期预热；随用户周期同步扩大，不用固定 65 根截断。
    return int(max(p["MIN_BARS"], p["N"] + p["DL_LOOKBACK"] + 1, p["VOL_MA"],
                   p["KDJ_N"] + 12 * (p["K_SMOOTH"] + p["D_SMOOTH"]) + p["JQ"],
                   12 * (p["MACD_SLOW"] + p["MACD_SIGNAL"])) + 1)


def stock_factors(bars: dict[str, pd.DataFrame], p: dict[str, Any]) -> dict[str, pd.DataFrame]:
    o, h, low, c, v = (bars[field] for field in FIELDS)
    ztj = ZTPRICE(REF(c, 1), p["LIMIT_RATIO"])
    zt = (abs(c - ztj) < 0.005) & c.eq(h)
    sb = zt & ~zt.shift(1, fill_value=False)
    zm = REF(LLV(v, p["N"]), 1)
    dl = (v > 0) & (v < zm * p["R"])
    dl_count = COUNT(REF(dl, 1), p["DL_LOOKBACK"])
    vl = MA(v, p["VOL_MA"])
    rsv = (c - LLV(low, p["KDJ_N"])) / (HHV(h, p["KDJ_N"]) - LLV(low, p["KDJ_N"])).clip(lower=0.01) * 100
    k = SMA(rsv, p["K_SMOOTH"], 1)
    d = SMA(k, p["D_SMOOTH"], 1)
    kj = (COUNT(CROSS(k, d), p["JQ"]) >= 1) & (k > d)
    dif = EMA(c, p["MACD_FAST"]) - EMA(c, p["MACD_SLOW"])
    dea = EMA(dif, p["MACD_SIGNAL"])
    count = pd.DataFrame(np.broadcast_to(np.arange(1, len(c) + 1)[:, None], c.shape),
                         index=c.index, columns=c.columns)
    # 损坏历史不压缩成停牌；递推状态不可信时使该段失败关闭。
    valid = np.isfinite(v) & (v >= 0)
    for field in FIELDS[:4]:
        valid &= np.isfinite(bars[field]) & (bars[field] > 0)
    data_ok = valid.cummin()
    tj = (sb & (dl_count >= p["DL_COUNT"]) & (v > vl) & kj
          & (dif > p["DIF_MIN"]) & (dea > p["DEA_MIN"])
          & (count >= p["MIN_BARS"]) & data_ok)
    kp = (o / REF(c, 1) - 1) * 100
    # 所有解释因子也停在昨日；今日后续 OHLCV 的变化不改变当前信号。
    factors = {key: REF(value, 1) for key, value in {
        "SB": sb, "ZM": zm, "DL_COUNT": dl_count, "VL60": vl,
        "K": k, "D": d, "KJ": kj, "DIF": dif, "DEA": dea, "TJ": tj,
        "BARSCOUNT": count,
    }.items()}
    factors["KP"] = kp
    # 仅吸收除法的机器舍入误差，区间端点包含在内。
    factors["XG"] = (factors["TJ"].eq(True) & np.isfinite(o) & (o > 0)
                     & (kp >= p["OPEN_MIN"] - 1e-10) & (kp <= p["OPEN_MAX"] + 1e-10))
    return factors


def compute(panels: dict[str, pd.DataFrame], params: dict[str, Any]) -> dict:
    p = validated(params)
    if any(field not in panels for field in FIELDS):
        raise ValueError("首板次日需要 open/high/low/close/volume")
    reference = panels["open"]
    if not reference.index.is_unique or not reference.index.is_monotonic_increasing:
        raise ValueError("日 K 日期必须唯一且递增")
    for field in FIELDS:
        if not panels[field].index.equals(reference.index) or not panels[field].columns.equals(reference.columns):
            raise ValueError(f"{field} 面板索引不一致")
    factors: dict[str, np.ndarray] = {}
    matrices = [panels[field].to_numpy(float) for field in FIELDS]
    for begin in range(0, len(reference.columns), 128):
        bars = np.stack([matrix[:, begin:begin + 128] for matrix in matrices], axis=2)
        present = ~np.isnan(bars).all(axis=2)
        rows, cols = np.nonzero(present)
        if not rows.size:
            continue
        # 分块向量化，同时按每票实际 K 线压缩停牌；部分损坏行保留。
        packed_rows = np.cumsum(present, axis=0)[rows, cols] - 1
        packed = np.full(bars.shape, np.nan)
        packed[packed_rows, cols] = bars[rows, cols]
        values = stock_factors({field: pd.DataFrame(packed[:, :, i]) for i, field in enumerate(FIELDS)}, p)
        for key, value in values.items():
            if key not in factors:
                factors[key] = np.full(reference.shape, np.nan)
            factors[key][rows, begin + cols] = value.to_numpy(float)[packed_rows, cols]
    frames = {key: pd.DataFrame(value, index=reference.index, columns=reference.columns)
              for key, value in factors.items()}
    signals = frames.get("XG", pd.DataFrame(False, index=reference.index, columns=reference.columns)).eq(1)
    return {"signals": signals, "factors": frames}


def live_candidate_codes(panels: dict[str, pd.DataFrame], trade_date: str, params: dict) -> list[str]:
    prior = {field: frame.loc[frame.index < trade_date].copy() for field, frame in panels.items()
             if field in FIELDS}
    if not prior or prior["open"].empty:
        return []
    # 仅追加开盘占位用于取得 REF(TJ,1)；不生成虚构今日收盘/量。
    for field in FIELDS:
        prior[field].loc[trade_date] = np.nan
    prior["open"].loc[trade_date] = 1.0
    result = compute(prior, params)
    tj = result["factors"].get("TJ")
    return [] if tj is None else tj.columns[tj.loc[trade_date].eq(1)].tolist()


compute.history_bars = history_bars
compute.live_candidate_codes = live_candidate_codes
compute.strict_live_ohlcv = True
