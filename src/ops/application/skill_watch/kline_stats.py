"""skill_watch 共用：日线派生指标。

涨停判定按板块幅度走 `src.formula`，不是一刀切 9.5%——20cm 的票用 10% 判会
把普涨当涨停，主板用 20% 判则永远选不出涨停。
"""
from __future__ import annotations

from typing import Any

import numpy as np
import pandas as pd

from src.formula import limit_ratio_for, limit_up_price


def limit_up_days(frame: pd.DataFrame, *, code: str = "", name: str = "") -> int:
    """区间内收盘封住涨停的天数。"""
    if frame.empty or "close" not in frame.columns:
        return 0
    close = pd.to_numeric(frame["close"], errors="coerce")
    previous = close.shift(1)
    ratio = limit_ratio_for(code, name)
    limit_price = limit_up_price(previous, ratio)
    sealed = close >= limit_price * 0.995
    if "high" in frame.columns:
        high = pd.to_numeric(frame["high"], errors="coerce")
        sealed &= np.isclose(close, high, rtol=1e-6, atol=0.02)
    return int(sealed.fillna(False).sum())


def clean_series(frame: pd.DataFrame) -> tuple[pd.Series, pd.Series]:
    """返回对齐后的 (收盘, 成交量)，剔除停牌/缺价行。"""
    close = pd.to_numeric(frame.get("close"), errors="coerce")
    raw_volume = (
        frame["volume"] if "volume" in frame.columns else pd.Series(0.0, index=frame.index)
    )
    volume = pd.to_numeric(raw_volume, errors="coerce").fillna(0)
    valid = close.notna() & close.gt(0)
    return (
        close.loc[valid].reset_index(drop=True),
        volume.loc[valid].reset_index(drop=True),
    )


def trend_stats(
    frame: pd.DataFrame,
    *,
    code: str = "",
    name: str = "",
    min_bars: int = 25,
) -> dict[str, Any] | None:
    """龙头/回头共用的一组趋势指标；样本不足返回 None。"""
    if frame.empty or "close" not in frame.columns:
        return None
    close, volume = clean_series(frame)
    if len(close) < min_bars:
        return None

    last = float(close.iloc[-1])
    peak_position = int(close.to_numpy(dtype=float).argmax())
    peak = float(close.iloc[peak_position])
    if peak <= 0:
        return None
    pattern_close = close.tail(21).reset_index(drop=True)
    pattern_peak_position = int(pattern_close.to_numpy(dtype=float).argmax())
    pattern_peak = float(pattern_close.iloc[pattern_peak_position])
    pattern_post_peak = pattern_close.iloc[pattern_peak_position:]
    pattern_trough = float(pattern_post_peak.min())

    bar_date = ""
    if "date" in frame.columns:
        raw_close = pd.to_numeric(frame["close"], errors="coerce")
        valid_mask = raw_close.notna() & raw_close.gt(0)
        dates = frame.loc[valid_mask, "date"]
        if len(dates):
            raw = str(dates.iloc[-1]).replace("-", "")[:8]
            if len(raw) == 8 and raw.isdigit():
                bar_date = f"{raw[:4]}-{raw[4:6]}-{raw[6:8]}"

    prior_volume = float(volume.iloc[-6:-1].mean() or 1.0)
    lookback_20 = float(close.iloc[-21]) if len(close) > 21 else float(close.iloc[0])
    return {
        "close": round(last, 3),
        "bar_date": bar_date,
        "ma10": round(float(close.tail(10).mean()), 3),
        "ma20": round(float(close.tail(20).mean()), 3),
        "peak": round(peak, 3),
        "peak_position": peak_position,
        "pullback_days": max(0, len(close) - 1 - peak_position),
        "pullback_days_recent": max(
            0, len(pattern_close) - 1 - pattern_peak_position
        ),
        "pullback_depth_pct": round(
            (pattern_peak - pattern_trough) / pattern_peak * 100.0,
            2,
        ),
        "pullback_drawdown_pct": round(
            (pattern_peak - last) / pattern_peak * 100.0,
            2,
        ),
        "drawdown_pct": round((peak - last) / peak * 100.0, 2),
        "gain_20_pct": round(
            (last / lookback_20 - 1.0) * 100.0 if lookback_20 > 0 else 0.0, 2
        ),
        "today_pct": round(
            float(close.pct_change().iloc[-1] * 100.0) if len(close) > 1 else 0.0, 2
        ),
        "vol_ratio": round(float(volume.iloc[-1] / prior_volume), 2),
        "vol_shrink": round(
            float(volume.iloc[-3:].mean() or 1.0)
            / float(volume.iloc[max(0, peak_position - 5) : peak_position + 1].max() or 1.0),
            2,
        ),
        "strong_days": limit_up_days(frame, code=code, name=name),
    }


__all__ = ["clean_series", "limit_up_days", "trend_stats"]
