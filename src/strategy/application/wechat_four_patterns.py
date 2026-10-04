"""Experimental, article-derived daily reversal/continuation signals.

Source: https://mp.weixin.qq.com/s/nEaStkjoKRzxwD_xYfDVrg
The article supplies sketches, not numeric thresholds. All thresholds below are
research assumptions frozen before this experiment, not quotations or an edge
claim. Not registered as a production strategy. Signals use completed daily bars
only; execute no earlier than the following market session.
"""
from __future__ import annotations

from typing import Any

import numpy as np
import pandas as pd

from src.strategy.domain.base import SignalResult, StrategyError, merge_params

PATTERNS = ("contraction", "ma_cross", "platform", "trend_pullback")


def select_top_two(candidate: pd.DataFrame, score: pd.DataFrame, limit: int = 2) -> pd.DataFrame:
    """Cap the *entire* cross-section, not each pattern. Ties use code order."""
    if isinstance(limit, bool) or not isinstance(limit, int) or not 1 <= limit <= 2:
        raise StrategyError("daily_limit must be 1 or 2; increasing it is forbidden")
    columns = sorted(candidate.columns)
    mask = candidate.reindex(columns=columns).fillna(False).astype(bool)
    scores = score.reindex(index=mask.index, columns=columns)
    mask &= np.isfinite(scores)
    rank = scores.where(mask).rank(axis=1, ascending=False, method="first")
    return (mask & rank.le(limit)).reindex(columns=candidate.columns)


class WechatFourPatternsStrategy:
    slug = "wechat-four-patterns-research"
    name = "四形态量价确认（研究，每日最多2只）"
    version = "research-v1"
    entry_timing = "next_open"
    execution_adjust = "none"
    description = "缩量支撑、均线金叉、平台突破、趋势回踩；非生产策略。"
    entry_instructions = "收盘计算，次日开盘尝试；当日总名单最多2只，未成交不递补。"

    def default_params(self) -> dict[str, Any]:
        return {
            "daily_limit": 2,
            "pattern": "all",
            "min_amount": 50_000_000.0,
            "breadth_floor": 0.45,
            "min_market_count": 500,
            "max_day_return": 0.07,
            "max_five_day_return": 0.15,
            "max_twenty_day_return": 0.35,
        }

    def required_fields(self) -> tuple[str, ...]:
        return ("open", "high", "low", "close", "volume", "amount")

    def min_bars(self) -> int:
        return 120

    def compute(self, panels: dict[str, pd.DataFrame], params: dict[str, Any] | None = None) -> SignalResult:
        p = merge_params(self, params)
        limit = p["daily_limit"]
        if isinstance(limit, bool) or not isinstance(limit, int) or not 1 <= limit <= 2:
            raise StrategyError("daily_limit must be 1 or 2")
        if p["pattern"] not in ("all", *PATTERNS):
            raise StrategyError("unknown pattern")
        if not 0 <= float(p["breadth_floor"]) <= 1:
            raise StrategyError("breadth_floor must be in [0, 1]")
        if float(p["min_amount"]) < 0 or int(p["min_market_count"]) < 1:
            raise StrategyError("invalid liquidity/market-count threshold")
        for key in self.required_fields() + ("__eligible",):
            if key not in panels:
                raise StrategyError(f"missing panel: {key}; historical eligibility must be explicit")
        c = panels["close"]
        if not c.index.is_unique or not c.index.is_monotonic_increasing or not c.columns.is_unique:
            raise StrategyError("dates must be increasing and unique; codes must be unique")
        for key in self.required_fields() + ("__eligible",):
            if not panels[key].index.equals(c.index) or not panels[key].columns.equals(c.columns):
                raise StrategyError(f"misaligned panel: {key}")
        o, h, lo, v, amount = (panels[key] for key in ("open", "high", "low", "volume", "amount"))
        eligible = panels["__eligible"].fillna(False).astype(bool)
        mainboard = pd.Series([str(x).startswith(("00", "60")) for x in c.columns], index=c.columns)
        valid = c.gt(0) & o.gt(0) & lo.gt(0) & h.ge(c) & h.ge(o) & lo.le(c) & lo.le(o) & v.gt(0)
        valid &= np.isfinite(c) & np.isfinite(o) & np.isfinite(h) & np.isfinite(lo) & np.isfinite(v)
        ma = {n: c.where(valid).rolling(n, min_periods=n).mean() for n in (5, 10, 20, 30, 60)}
        prior_volume = v.where(valid).shift(1).rolling(20, min_periods=20).mean()
        volume_ratio = v / prior_volume
        contraction = v.where(valid).shift(1).rolling(3, min_periods=3).mean() / prior_volume
        r1 = c / c.shift(1) - 1
        r5 = c / c.shift(5) - 1
        r20 = c / c.shift(20) - 1
        close_location = ((c - lo) / (h - lo).replace(0, np.nan)).clip(0, 1)
        observations = valid.cumsum()
        universe_now = valid & eligible & mainboard & observations.ge(self.min_bars())
        breadth = ((c > ma[20]) & universe_now).sum(axis=1) / universe_now.sum(axis=1).replace(0, np.nan)
        market_ok = breadth.ge(float(p["breadth_floor"])) & universe_now.sum(axis=1).ge(int(p["min_market_count"]))
        base = universe_now & valid.rolling(20, min_periods=20).sum().eq(20)
        base &= amount.ge(float(p["min_amount"])) & amount.shift(1).rolling(20).mean().ge(float(p["min_amount"]))
        base &= c.gt(o) & close_location.ge(0.60) & r1.gt(0) & r1.le(float(p["max_day_return"]))
        base &= r5.le(float(p["max_five_day_return"])) & r20.le(float(p["max_twenty_day_return"]))
        base &= c.ge(ma[20]) & c.le(ma[20] * 1.12)

        support = (
            lo.shift(1).ge(ma[20].shift(1) * 0.97) & lo.shift(1).le(ma[20].shift(1) * 1.03)
        )
        support |= lo.shift(1).ge(ma[30].shift(1) * 0.97) & lo.shift(1).le(ma[30].shift(1) * 1.03)
        contraction_pattern = support & contraction.le(0.8) & volume_ratio.ge(1.2) & volume_ratio.le(2.5)
        contraction_pattern &= c.gt(h.shift(1)) & c.ge(ma[5]) & ma[20].ge(ma[20].shift(5) * 0.99)

        cross = ma[5].shift(1).le(ma[10].shift(1)) & ma[5].gt(ma[10])
        cross &= ma[20].gt(ma[30]) & ma[30].gt(ma[30].shift(5)) & c.ge(ma[5])
        cross &= volume_ratio.ge(1.0) & volume_ratio.le(2.5)

        resistance = h.shift(1).rolling(20, min_periods=20).max()
        floor = lo.shift(1).rolling(20, min_periods=20).min()
        platform = (resistance / floor - 1).le(0.18) & c.gt(resistance) & c.le(resistance * 1.03)
        platform &= volume_ratio.ge(1.2) & volume_ratio.le(2.5) & close_location.ge(0.65)

        trend = ma[5].gt(ma[10]) & ma[10].gt(ma[20]) & ma[20].gt(ma[30]) & ma[30].gt(ma[60])
        trend &= ma[20].gt(ma[20].shift(5))
        prior_low = lo.shift(1).rolling(3, min_periods=3).min()
        touched = prior_low.le(ma[10].shift(1) * 1.02) & prior_low.ge(ma[20].shift(1) * 0.97)
        depth = 1 - prior_low / resistance
        pullback = trend & touched & depth.ge(0.03) & depth.le(0.12) & contraction.le(0.9)
        pullback &= c.gt(h.shift(1)) & c.ge(ma[5]) & volume_ratio.ge(1.0) & volume_ratio.le(2.5)

        raw = dict(zip(PATTERNS, (contraction_pattern, cross, platform, pullback)))
        count = sum(x.fillna(False).astype(int) for x in raw.values())
        candidate = count.gt(0) if p["pattern"] == "all" else raw[str(p["pattern"])].fillna(False)
        candidate = (candidate & base).mul(market_ok, axis=0).astype(bool)
        score = count * 100 + close_location * 10 + r20.clip(-0.35, 0.35) * 10
        score += (1 - (volume_ratio - 1.5).abs().clip(0, 1)) * 2
        signals = select_top_two(candidate, score, limit)
        factors = {f"pattern_{k}": val.fillna(False) for k, val in raw.items()}
        factors.update({
            "candidate": candidate, "score": score, "pattern_count": count,
            "volume_ratio": volume_ratio, "contraction_ratio": contraction,
            "close_location": close_location, "return_20d": r20,
            "market_breadth": pd.DataFrame(np.repeat(breadth.to_numpy()[:, None], len(c.columns), axis=1), index=c.index, columns=c.columns),
        })
        return SignalResult(signals=signals, factors=factors)
