"""潜龙出海 V3：通达信云阳标准买点的活动向量化实现。

旧版 ``qianlong-close`` 已归档到 ``application/backup/qianlong-legacy.py``，
历史 V2 仅作为 V3 的条件来源留在版本记录中，不再单独注册到活动目录。
"""
from __future__ import annotations

from typing import Any

import pandas as pd

from src.formula import (
    COUNT,
    CROSS,
    EXIST,
    MA,
    REF,
    limit_ratio_panel,
    limit_up_flags,
    weighted_ref_sum,
)
from src.strategy.domain.base import SignalResult, merge_params, register

# 辰星线原式跳过 REF(YTSL,19)，并使用分母 211；两处都必须原样保留。
CHENXING_WEIGHTS: dict[int, float] = {offset: float(20 - offset) for offset in range(19)}
CHENXING_WEIGHTS[20] = 1.0
CHENXING_DIVISOR = 211.0


def ytsl(panels: dict[str, pd.DataFrame]) -> pd.DataFrame:
    """YTSL := (3*CLOSE + LOW + OPEN + HIGH) / 6。"""
    return (3 * panels["close"] + panels["low"] + panels["open"] + panels["high"]) / 6


def chenxing(panels: dict[str, pd.DataFrame]) -> pd.DataFrame:
    """按通达信原式计算辰星线。"""
    return weighted_ref_sum(ytsl(panels), CHENXING_WEIGHTS, CHENXING_DIVISOR)


def select_one_per_day(
    candidates: pd.DataFrame, strength: pd.DataFrame
) -> pd.DataFrame:
    """按当日强度保留一只候选，横截面并列时按代码列顺序稳定裁决。"""
    scores = strength.where(candidates.fillna(False))
    first_rank = scores.rank(axis=1, ascending=False, method="first")
    return (candidates.fillna(False) & first_rank.eq(1)).fillna(False)


class _QianlongCore:
    """潜龙 V3 共用的核心突破条件，不单独作为公开战法注册。"""

    def default_params(self) -> dict[str, Any]:
        return {
            "death_lookback": 15,
            "below_window": 10,
            "below_min": 3,
            "price_min": 8.0,
            "vol_boost": 1.3,
            "hold_ratio": 1.002,
        }

    def required_fields(self) -> tuple[str, ...]:
        return ("open", "high", "low", "close", "volume")

    def min_bars(self) -> int:
        # 辰星线需要 21 根，黄色线需要 26 根，EXIST(死叉,15) 再留出完整回看。
        return 46

    def compute(
        self, panels: dict[str, pd.DataFrame], params: dict[str, Any] | None = None
    ) -> SignalResult:
        p = merge_params(self, params)
        close, open_ = panels["close"], panels["open"]
        volume = panels["volume"]

        white = chenxing(panels)
        yellow = MA(close, 26)
        death_cross = CROSS(yellow, white)
        had_death = EXIST(death_cross, int(p["death_lookback"]))
        ran_below = COUNT(close < white, int(p["below_window"])) >= int(p["below_min"])

        bullish = (close > open_) & (close >= float(p["price_min"]))
        breakout = (close > white) & (REF(close, 1) <= REF(white, 1))
        volume_up = volume > MA(volume, 5) * float(p["vol_boost"])
        hold = close > white * float(p["hold_ratio"])
        breakout_day = bullish & breakout & volume_up & hold
        white_rising = white > REF(white, 1)
        raw_close = panels.get("__raw_close")
        if not isinstance(raw_close, pd.DataFrame):
            raw_close = close
        else:
            raw_close = raw_close.reindex(index=close.index, columns=close.columns)
        names = panels.get("__instrument_names__")
        ratios = limit_ratio_panel(
            raw_close,
            names if isinstance(names, dict) else None,
        )
        # Use the prior bar's close only. Passing close as the high panel turns
        # the shared sealed-limit predicate into an exact close-at-limit test.
        at_limit_up = limit_up_flags(raw_close, raw_close, ratios, tolerance=1.0)
        below_limit_up = raw_close.notna() & ~at_limit_up
        base_signal = had_death & ran_below & breakout_day & white_rising
        # CLOSE/REF(CLOSE,5) 仅作归因；V3.2 横截面排序改用白线贴近度。
        roc5 = close / REF(close, 5)
        extension = (close / white - 1.0).where(white != 0)
        closeness = (white / close).where(close != 0)

        return SignalResult(
            signals=(base_signal & below_limit_up).fillna(False),
            factors={
                "辰星线": white,
                "牵牛线": yellow,
                "曾死叉": had_death,
                "白线下运行": ran_below,
                "突破日": breakout_day,
                "白线向上": white_rising,
                "非涨停价": below_limit_up,
                "ROC5": roc5,
                "辰星线延伸": extension,
                "白线贴近度": closeness,
            },
        )


class QianlongCloseePickerV3(_QianlongCore):
    """潜龙出海 V3.2：核心突破 + 换手 3.5%-8% + 弱市空仓 + 每日白线贴近度 Top2。"""

    slug = "qianlong-close-v3"
    name = "潜龙出海（V3.2）"
    description = (
        "V3.2：V2 核心突破 + T 日换手 3.5%-8% + 非涨停价；"
        "上涨家数<45% 整日空仓，否则按刚站上辰星线取 Top2；"
        "次日开盘买入，持有 3 日，止损 -7%"
    )
    entry_instructions = (
        "T 日收盘后选出：潜龙核心突破成立、未触及涨停价、换手率 3.5%≤turnover<8%；"
        "若当日市场上涨家数占比 <45%，整日空仓；"
        "否则按白线贴近度（辰星线/CLOSE）降序最多保留 2 只，即刚站上白线、延伸最小的票。"
        "T+1 按开盘价买入（一字涨停买不进则跳过）；"
        "成交后持有 3 个交易日，期间跌破入场价 7% 止损，否则到期收盘卖出。"
        "不看分时分批、不补仓。"
    )
    entry_timing = "next_open"
    requires_raw_limit_price = True
    screen_rank_factor = "白线贴近度"
    screen_top_n = 2
    screen_hold_days = 3
    screen_stop_loss_pct = -7.0
    strategy_revision = "builtin:qianlong-close-v3.2"
    version = "v3.2"
    version_history = [
        {
            "version": "v1",
            "status": "archived",
            "source": "application/backup/qianlong-legacy.py",
        },
        {"version": "v2", "status": "archived", "source": "builtin:qianlong-close-v2"},
        {"version": "v3", "status": "archived", "source": "builtin:qianlong-close-v3"},
        {"version": "v3.1", "status": "archived", "source": "builtin:qianlong-close-v3.1"},
        {"version": "v3.2", "status": "active", "source": "builtin"},
    ]
    backtest_metrics: dict[str, Any] | None = {
        "trades": 1021,
        "win_rate": 47.7,
        "avg_net_return": 0.4127,
        "median_net_return": -0.2234,
        "payoff_ratio": 1.31,
        "completed_trades": 1021,
        "portfolio_return_pct": 81.9594,
        "max_drawdown_pct": -30.7208,
        "occupancy_pct": 43.19,
    }
    backtest_config = {
        "start": "2021-01-04",
        "end": "2026-08-12",
        "adjust": "qfq",
        "hold_days": 3,
        "stop_loss_pct": -7.0,
        "take_profit_pct": None,
        "commission_bps": 3.0,
        "stamp_duty_bps": 5.0,
        "slippage_bps": 10.0,
        "benchmark": None,
        "portfolio_model": "overlapping_equal_weight_sleeves",
        "portfolio_return_pct": 81.9594,
        "max_drawdown_pct": -30.7208,
        "occupancy_pct": 43.19,
        "completed_trades": 1021,
        "signal_days": 587,
        "weak_breadth_skip": 0.45,
        "turnover_min": 0.035,
        "turnover_max": 0.08,
        "screen_top_n": 2,
        "screen_rank_factor": "白线贴近度",
        "universe": {"preset": "default_a_share", "boards": ["main", "chi_next"]},
        "note": "V3.2 排序改为辰星线延伸升序；数字来自 2021-01-04~2026-08-12 全样本对照，不是 2026 半年窗。",
    }
    default_universe = {"preset": "default_a_share", "boards": ["main", "chi_next"]}

    def default_params(self) -> dict[str, Any]:
        return {
            **super().default_params(),
            "turnover_min": 0.035,
            "turnover_max": 0.08,
            "weak_breadth_skip": 0.45,
            "top_n": 2,
        }

    def required_fields(self) -> tuple[str, ...]:
        return (*super().required_fields(), "turnover")

    def compute(
        self, panels: dict[str, pd.DataFrame], params: dict[str, Any] | None = None
    ) -> SignalResult:
        p = merge_params(self, params)
        core = super().compute(panels, params)
        close = panels["close"]
        turnover = panels["turnover"].astype(float)
        turnover_ok = (turnover >= float(p["turnover_min"])) & (
            turnover < float(p["turnover_max"])
        )
        eligible = (core.signals & turnover_ok).fillna(False)

        previous_close = REF(close, 1)
        valid_close = close.notna() & previous_close.notna()
        advancing = (close > previous_close) & valid_close
        valid_count = valid_close.sum(axis=1)
        breadth = advancing.sum(axis=1).div(valid_count.where(valid_count > 0))
        breadth_panel = pd.DataFrame(
            {code: breadth for code in close.columns}, index=close.index
        )
        weak_skip = p.get("weak_breadth_skip")
        if weak_skip is None:
            market_ok = pd.DataFrame(True, index=close.index, columns=close.columns)
        else:
            market_ok = breadth_panel.ge(float(weak_skip)).fillna(False)
        tradable = (eligible & market_ok).fillna(False)

        closeness = core.factors["白线贴近度"]
        top_n = int(p.get("top_n") or 0)
        if top_n > 0:
            rank = closeness.where(tradable).rank(
                axis=1, ascending=False, method="first"
            )
            selected = (tradable & rank.le(top_n)).fillna(False)
            watch_rank = closeness.where(eligible & ~market_ok).rank(
                axis=1, ascending=False, method="first"
            )
            watch_selected = (
                eligible & ~market_ok & watch_rank.le(top_n)
            ).fillna(False)
        else:
            selected = tradable
            watch_selected = (eligible & ~market_ok).fillna(False)

        return SignalResult(
            signals=selected,
            watch_signals=watch_selected,
            factors={
                **core.factors,
                "换手率(%)": turnover * 100.0,
                "换手过滤": turnover_ok,
                "条件候选": eligible,
                "市场上涨家数占比": breadth_panel,
                "弱市可交易": market_ok,
                "每日前二": selected,
                "弱市低吸观察": watch_selected,
            },
        )


register(QianlongCloseePickerV3())
