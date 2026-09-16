"""可选的原始成交价/经济价格契约；不包含成交循环。"""
from __future__ import annotations

import numpy as np
import pandas as pd

from src.formula import limit_up_price


def adjustment_factors(
    panels: dict[str, pd.DataFrame], reference: pd.DataFrame, *, required: bool,
) -> np.ndarray:
    panel = panels.get("__adjust_factor")
    if panel is None:
        if required:
            raise ValueError("economic_returns 要求执行面板 __adjust_factor")
        return np.ones(reference.shape, dtype=float)
    if not isinstance(panel, pd.DataFrame) or not panel.index.equals(reference.index) or not panel.columns.equals(reference.columns):
        raise ValueError("__adjust_factor 必须与执行价格面板完全对齐")
    values = panel.to_numpy(dtype=float)
    if not (np.isfinite(values).all() and (values > 0).all()):
        raise ValueError("__adjust_factor 必须全部为有限正数")
    return values


def strict_price_masks(
    open_prices: np.ndarray, close_prices: np.ndarray, factors: np.ndarray, codes: list[str],
    volume: np.ndarray | None = None,
) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """用最近有效原始前收及对应因子，求当日实际价格坐标的涨跌停参考。"""
    valid = np.isfinite(close_prices) & (close_prices > 0)
    if volume is not None:
        valid &= volume > 0
    closes = pd.DataFrame(close_prices).where(valid)
    previous = closes.ffill().shift(1).to_numpy()
    previous_factor = pd.DataFrame(factors).where(closes.notna()).ffill().shift(1).to_numpy()
    reference = previous * previous_factor / factors
    known = np.isfinite(reference) & (reference > 0)
    ratios = np.array([.20 if str(code).startswith("30") else .10 for code in codes])
    upper = limit_up_price(reference, ratios)
    lower = limit_up_price(reference, -ratios)
    return open_prices >= upper - .005, (close_prices <= lower + .005) | ~known, known
