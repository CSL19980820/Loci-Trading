"""Causal first-wave setups and an explicitly labelled price-resonance proxy.

Research only: not registered as a managed strategy. A setup fixes D0 facts on
D1; D2 execution is decided separately from the data actually available then.
No present-day sector membership is projected into historical dates.
"""
from __future__ import annotations

from collections.abc import Iterator
from dataclasses import asdict, dataclass
from typing import Any

import numpy as np
import pandas as pd


@dataclass(frozen=True)
class FirstWaveConfig:
    base_days: int = 20
    base_range_max: float = 0.25
    prior_gain_max: float = 0.15
    breakout_volume_min: float = 1.2
    wave_min_days: int = 1
    wave_max_days: int = 30
    wave_gain_min: float = 0.20
    wave_gain_max: float = 0.60
    slope_min_daily: float = 0.01
    wave_volume_min: float = 1.2
    wave_volume_max: float = 2.5
    wave_failure_drawdown: float = 0.08
    terminal_volume_min: float = 2.0
    adjustment_volume_max: float = 2 / 3

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def detect_first_waves(
    bars: pd.DataFrame, *, code: str = "", config: FirstWaveConfig | None = None,
) -> list[dict[str, Any]]:
    """Scan chronologically; report rejected waves as well as ready setups.

    Small pauses before the wave reaches 20% do not demand an uninterrupted
    series of up days. Below MA10 or an 8% drawdown invalidates that first wave;
    after reaching 20%, its first down close is D1 even if its volume fails.
    A failed episode cannot be relabelled after seeing a later second rally.
Inputs use a market-session index; missing/suspended bars interrupt a wave.
"""
    p = config or FirstWaveConfig()
    factor = bars["factor"].to_numpy(dtype=float)
    close = bars["close"].to_numpy(dtype=float) * factor
    high = bars["high"].to_numpy(dtype=float) * factor
    low = bars["low"].to_numpy(dtype=float) * factor
    volume = bars["volume"].to_numpy(dtype=float)
    valid = np.isfinite(close + high + low + volume + factor) & (low > 0) & (factor > 0) & (volume > 0)
    close = np.where(valid, close, np.nan)
    high = np.where(valid, high, np.nan)
    low = np.where(valid, low, np.nan)
    volume = np.where(valid, volume, np.nan)
    cs, hs, ls, vs = (pd.Series(a) for a in (close, high, low, volume))
    prior_high = hs.rolling(p.base_days).max().shift(1).to_numpy()
    prior_low = ls.rolling(p.base_days).min().shift(1).to_numpy()
    prior_volume = vs.rolling(p.base_days).mean().shift(1).to_numpy()
    prior_gain = cs.shift(1).to_numpy() / cs.shift(p.base_days).to_numpy() - 1
    ma10 = cs.rolling(10).mean().to_numpy()
    breakout = (
        valid & (close > prior_high)
        & (prior_high / prior_low - 1 <= p.base_range_max)
        & (prior_gain <= p.prior_gain_max)
        & (volume >= prior_volume * p.breakout_volume_min)
    )
    return _scan_first_waves(
        close, high, low, volume, valid, prior_low, prior_volume, ma10,
        breakout, bars.index.astype(str).tolist(), code, p,
    )


def _scan_first_waves(
    close: np.ndarray, high: np.ndarray, low: np.ndarray, volume: np.ndarray,
    valid: np.ndarray, prior_low: np.ndarray, prior_volume: np.ndarray,
    ma10: np.ndarray, breakout: np.ndarray, dates: list[str], code: str,
    p: FirstWaveConfig,
) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    consumed_until = -1
    for start in np.flatnonzero(breakout):
        start = int(start)
        if start <= consumed_until:
            continue
        end = min(start + p.wave_max_days, len(close) - 1)
        # A prefix without an observed D1 must remain pending, not become a
        # rejected historical episode just because the data ends there.
        d1 = None
        episode_failure = ""
        peak = high[start]
        for j in range(start + 1, end + 1):
            if not valid[j]:
                d1, episode_failure = j, "interrupted_wave"
                break
            gain = peak / prior_low[start] - 1
            if gain > p.wave_gain_max:
                d1, episode_failure = j, "wave_too_extended"
                break
            if gain >= p.wave_gain_min and close[j] < close[j - 1]:
                d1 = j
                break
            if close[j] < ma10[j] or close[j] < peak * (1 - p.wave_failure_drawdown):
                d1, episode_failure = j, "wave_trend_failed"
                break
            peak = max(peak, high[j])
        if d1 is None:
            if end - start < p.wave_max_days:
                continue
            consumed_until = end
            rows.append({"code": code, "start_date": dates[start], "status": "wave_timeout", "d0_date": dates[end]})
            continue
        consumed_until = d1 + p.base_days - 1
        d0 = d1 - 1
        row: dict[str, Any] = {
            "code": code, "start_date": dates[start], "d0_date": dates[d0], "d1_date": dates[d1],
            "d2_date": dates[d1 + 1] if d1 + 1 < len(dates) else "",
            "start_index": start, "d0_index": d0, "d1_index": d1, "d2_index": d1 + 1,
            "anchor_date": dates[start - p.base_days + int(np.nanargmin(low[start - p.base_days:start]))],
            "anchor_price": float(prior_low[start]), "wave_days": d1 - start,
            "status": "setup_ready",
        }
        if episode_failure:
            row["status"] = episode_failure
            rows.append(row)
            continue
        row["wave_gain"] = float(np.max(high[start:d1]) / prior_low[start] - 1)
        row["wave_volume_ratio"] = float(np.mean(volume[start:d1]) / prior_volume[start])
        row["terminal_volume_ratio"] = float(volume[d0] / volume[d0 - 1])
        row["adjustment_volume_ratio"] = float(volume[d1] / volume[d0])
        slope_prices = close[start - 1:d1]
        if len(slope_prices) >= 2:
            x = np.arange(len(slope_prices), dtype=float)
            x -= x.mean()
            row["slope_daily"] = float(np.expm1(x @ np.log(slope_prices) / (x @ x)))
        else:
            row["slope_daily"] = 0.0
        checks = (
            (p.wave_min_days <= row["wave_days"] <= p.wave_max_days, "wave_duration"),
            (p.wave_gain_min <= row["wave_gain"] <= p.wave_gain_max, "wave_gain"),
            (row["slope_daily"] >= p.slope_min_daily, "wave_slope"),
            (p.wave_volume_min <= row["wave_volume_ratio"] <= p.wave_volume_max, "wave_volume"),
            (row["terminal_volume_ratio"] >= p.terminal_volume_min, "terminal_volume"),
            (row["adjustment_volume_ratio"] <= p.adjustment_volume_max + 1e-12, "adjustment_volume"),
        )
        row["status"] = next((reason for ok, reason in checks if not ok), "setup_ready")
        rows.append(row)
    return rows


def _detect_first_waves_panel(
    close: np.ndarray, high: np.ndarray, low: np.ndarray, volume: np.ndarray,
    index: pd.Index, codes: list[str], positions: np.ndarray, config: FirstWaveConfig,
) -> Iterator[tuple[int, list[dict[str, Any]]]]:
    """Compute rolling inputs together, then use the same chronological scan."""
    dates = index.astype(str).tolist()
    for offset in range(0, len(positions), 512):
        chunk = positions[offset:offset + 512]
        c, h, l, v = (values[:, chunk] for values in (close, high, low, volume))
        valid = np.isfinite(c + h + l + v + 1.0) & (l > 0) & (v > 0)
        c, h, l, v = (np.where(valid, values, np.nan) for values in (c, h, l, v))
        cs, hs, ls, vs = (pd.DataFrame(values) for values in (c, h, l, v))
        prior_high = hs.rolling(config.base_days).max().shift(1).to_numpy()
        prior_low = ls.rolling(config.base_days).min().shift(1).to_numpy()
        prior_volume = vs.rolling(config.base_days).mean().shift(1).to_numpy()
        prior_gain = cs.shift(1).to_numpy() / cs.shift(config.base_days).to_numpy() - 1
        ma10 = cs.rolling(10).mean().to_numpy()
        breakout = (
            valid & (c > prior_high)
            & (prior_high / prior_low - 1 <= config.base_range_max)
            & (prior_gain <= config.prior_gain_max)
            & (v >= prior_volume * config.breakout_volume_min)
        )
        for column in np.flatnonzero(breakout.any(axis=0)):
            position = int(chunk[column])
            yield position, _scan_first_waves(
                c[:, column], h[:, column], l[:, column], v[:, column],
                valid[:, column], prior_low[:, column], prior_volume[:, column],
                ma10[:, column], breakout[:, column], dates, codes[position], config,
            )


def price_resonance_mainline(
    adjusted_close: np.ndarray, volume: np.ndarray, *, target: int, asof: int,
    codes: list[str], window: int = 60, max_peers: int = 20,
    min_peers: int = 5, min_correlation: float = 0.45,
) -> dict[str, Any]:
    """Leave-one-out, historical-only proxy; never claims named theme evidence.

Peers are selected from preceding market-relative log returns, not from
future performance or today's industry labels. The target cannot supply its
own breadth, volume or group momentum confirmation.
"""
    result: dict[str, Any] = {"basis": "causal_price_resonance_proxy", "passed": False, "reason": "mainline_warmup", "peers": []}
    if asof < window:
        return result
    history = np.asarray(adjusted_close[asof - window:asof + 1], dtype=float)
    with np.errstate(divide="ignore", invalid="ignore"):
        returns = np.diff(np.log(history), axis=0)
    if not np.isfinite(returns[:, target]).all():
        result["reason"] = "target_history_missing"
        return result
    observed = np.isfinite(returns)
    market = np.nanmedian(returns, axis=1)
    relative = returns - market[:, None]
    x = relative[:, target]
    mask = observed & np.isfinite(relative)
    count = mask.sum(axis=0)
    y = np.where(mask, relative, 0.0)
    sx = (mask * x[:, None]).sum(axis=0)
    sy = y.sum(axis=0)
    safe_n = np.maximum(count, 1)
    covariance = (y * x[:, None]).sum(axis=0) - sx * sy / safe_n
    variance_x = (mask * (x * x)[:, None]).sum(axis=0) - sx * sx / safe_n
    variance_y = (y * y).sum(axis=0) - sy * sy / safe_n
    with np.errstate(divide="ignore", invalid="ignore"):
        correlation = covariance / np.sqrt(variance_x * variance_y)
    eligible = (count >= int(window * 0.75)) & np.isfinite(correlation) & (correlation >= min_correlation)
    recent_volume = np.asarray(volume[asof - 24:asof + 1], dtype=float)
    eligible &= np.isfinite(history[-25:]).all(axis=0)
    eligible &= (np.isfinite(recent_volume) & (recent_volume > 0)).all(axis=0)
    eligible[target] = False
    peer_indexes = np.flatnonzero(eligible)
    peer_indexes = sorted(peer_indexes, key=lambda k: (-correlation[k], codes[k]))[:max_peers]
    result["peer_count"] = len(peer_indexes)
    result["peers"] = [codes[k] for k in peer_indexes]
    if len(peer_indexes) < min_peers:
        result["reason"] = "too_few_correlated_peers"
        return result
    peers = np.array(peer_indexes)
    group_daily = np.mean(returns[-10:, peers], axis=1)
    peer5 = history[-1, peers] / history[-6, peers] - 1
    excess5 = float(np.expm1(group_daily[-5:].sum()) - np.expm1(market[-5:].sum()))
    excess10 = float(np.expm1(group_daily[-10:].sum()) - np.expm1(market[-10:].sum()))
    breadth = float(np.mean((peer5 > 0) & (history[-1, peers] >= np.nanmean(history[-20:, peers], axis=0))))
    vs = np.asarray(volume[asof - 24:asof + 1, peers], dtype=float)
    with np.errstate(divide="ignore", invalid="ignore"):
        ratios = np.nanmean(vs[-5:], axis=0) / np.nanmean(vs[:-5], axis=0)
    ratios = ratios[np.isfinite(ratios)]
    vr = float(np.median(ratios)) if len(ratios) else 0.0
    persistent = sum(group_daily[-5 - k:len(group_daily) - k or None].sum() > market[-5 - k:len(market) - k or None].sum() for k in range(5))
    checks = ((excess5 >= 0.02, "group_excess5"), (excess10 >= 0.03, "group_excess10"),
              (breadth >= 0.60, "group_breadth"), (vr >= 1.10, "group_volume"),
              (persistent >= 3, "group_persistence"))
    result.update(excess5=excess5, excess10=excess10, breadth=breadth, volume_ratio=vr,
                  persistence_days=int(persistent), mean_correlation=float(np.mean(correlation[peers])))
    result["reason"] = next((reason for ok, reason in checks if not ok), "passed")
    result["passed"] = result["reason"] == "passed"
    return result
