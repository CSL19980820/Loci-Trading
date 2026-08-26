"""换手率 / 成交量单位纯函数（无 Store 依赖，避免循环导入）。

约定：turnover 为小数（0.05 = 5%）。
"""
from __future__ import annotations

#: 换手率（小数）超过此值视为脏数据。
#: 游资接力票、新股/次新日换手可达 70%~80%；超过 1.0 (100%) 视为脏数据/单位错位。
INSANE_TURNOVER = 1.0
#: amount/(volume*close) 落在此区间 → 成交量仍是「手」。
LOT_RATIO_LO = 50.0
LOT_RATIO_HI = 150.0
#: amount/(volume*close) 落在此区间 → 成交量被多乘了 100。
INFLATED_RATIO_LO = 0.005
INFLATED_RATIO_HI = 0.02


def normalize_trade_volume(
    volume: float,
    *,
    amount: float | None,
    close: float | None,
) -> float:
    """按成交额校正成交量单位：手→股，或去掉多余的 ×100。"""
    if volume <= 0 or amount is None or close is None or amount <= 0 or close <= 0:
        return volume
    ratio = amount / (volume * close)
    if LOT_RATIO_LO <= ratio <= LOT_RATIO_HI:
        return volume * 100.0
    if INFLATED_RATIO_LO <= ratio <= INFLATED_RATIO_HI:
        return volume / 100.0
    return volume


def compute_turnover(
    *,
    volume: float | None,
    amount: float | None,
    close: float | None,
    shares: float | None,
    stored: float | None = None,
) -> float | None:
    """换手率（小数）。优先 ``amount/(close*shares)``，避开错误成交量单位。"""
    if shares is not None and shares > 0 and amount is not None and close is not None:
        if amount > 0 and close > 0:
            turnover = amount / (close * shares)
            if 0 < turnover <= INSANE_TURNOVER:
                return turnover
    if shares is not None and shares > 0 and volume is not None and volume > 0:
        vol = normalize_trade_volume(volume, amount=amount, close=close)
        turnover = vol / shares
        if 0 < turnover <= INSANE_TURNOVER:
            return turnover
    if stored is not None and 0 < float(stored) <= INSANE_TURNOVER:
        return float(stored)
    return None
