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
        # CLOSE/REF(CLOSE,5)：选股输出与入库按此降序，最强排最前。
        roc5 = close / REF(close, 5)

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
            },
        )


class QianlongCloseePickerV3(_QianlongCore):
    """潜龙出海 V3：在历史 V2 核心突破形态上加入换手率过滤。"""

    slug = "qianlong-close-v3"
    name = "潜龙出海（V3）"
    description = (
        "V3：保留 V2 的 15 日死叉回看、收盘价≥8 元和放量突破，"
        "新增 T 日换手率 2%-8% 与非涨停价过滤；盘后选股，次日按开盘情景执行"
    )
    entry_instructions = (
        "T 日 14:50 后只保留未触及涨停价的候选，收盘后确认，T+1 执行：平开±1%优先按开盘价轻仓试仓；低开1%-3%只在不破辰星线、"
        "开盘后承接稳定时分批买入；高开1%-3%不追开盘，回落至开盘价附近再观察；高开或低开≥3%跳过。"
        "单票先试 1 层，跌破辰星线且收盘确认或相对买入价回撤 6% 失效，不补仓摊平。"
    )
    entry_timing = "next_open"
    requires_raw_limit_price = True
    #: 选股结果按 ROC5 降序输出（最高排最前）。
    screen_rank_factor = "ROC5"
    strategy_revision = "builtin:qianlong-close-v3"
    version = "v3"
    version_history = [
        {
            "version": "v1",
            "status": "archived",
            "source": "application/backup/qianlong-legacy.py",
        },
        {"version": "v2", "status": "archived", "source": "builtin:qianlong-close-v2"},
        {"version": "v3", "status": "candidate", "source": "builtin"},
    ]
    backtest_metrics = {
        "trades": 567,
        "win_rate": 46.91,
        "avg_net_return": 0.4923,
        "profit_factor": 1.213,
    }
    backtest_config = {
        "start": "2026-02-01",
        "end": "2026-07-31",
        "adjust": "qfq",
        "hold_days": 3,
        "stop_loss_pct": -6.0,
        "take_profit_pct": None,
        "benchmark": None,
        "universe": {"preset": "default_a_share", "boards": ["main", "chi_next"]},
    }
    default_universe = {"preset": "default_a_share", "boards": ["main", "chi_next"]}

    def default_params(self) -> dict[str, Any]:
        return {
            **super().default_params(),
            "turnover_min": 0.02,
            "turnover_max": 0.08,
        }

    def required_fields(self) -> tuple[str, ...]:
        return (*super().required_fields(), "turnover")

    def compute(
        self, panels: dict[str, pd.DataFrame], params: dict[str, Any] | None = None
    ) -> SignalResult:
        p = merge_params(self, params)
        core = super().compute(panels, params)
        turnover = panels["turnover"].astype(float)
        turnover_ok = (turnover >= float(p["turnover_min"])) & (
            turnover < float(p["turnover_max"])
        )
        return SignalResult(
            signals=(core.signals & turnover_ok).fillna(False),
            factors={
                **core.factors,
                "换手率(%)": turnover * 100.0,
                "换手2%-8%": turnover_ok,
            },
        )


class QianlongTailPickerV1(QianlongCloseePickerV3):
    """潜龙尾盘版：T 日收盘选股并只保留当日 ROC5 最强的一只。"""

    slug = "qianlong-tail-v1"
    name = "潜龙尾盘（V1）"
    description = (
        "尾盘版：潜龙突破条件 + 换手2%-8% + T 日非涨停价，"
        "同日按 ROC5 最强只留一只，T 日收盘成交、T+1 退出"
    )
    entry_instructions = (
        "14:50 后计算 T 日信号，先剔除按板块涨停价封住的个股，再按 ROC5（CLOSE/REF(CLOSE,5)）"
        "从当日候选中只留一只；T 日按未复权收盘价理想化成交。T+1 最高价触及买入价+3%止盈，"
        "最低价触及-6%止损，若两者同日触发先按止损，均未触发则 T+1 收盘卖出。"
        "单票一次建仓，不补仓。"
    )
    entry_timing = "close"
    execution_adjust = "none"
    screen_rank_factor = "ROC5"
    # 尾盘信号必须在收盘前落地；托管任务按该声明在 14:50 执行。
    screen_schedule = {
        "mode": "once",
        "run_hour": 14,
        "run_minute": 50,
        "interval_minutes": 10,
        "window_start_hour": 9,
        "window_start_minute": 30,
        "window_end_hour": 14,
        "window_end_minute": 50,
    }
    screen_top_n = 1
    strategy_revision = "builtin:qianlong-tail-v1"
    version = "v1"
    version_history = [
        {"version": "v1", "status": "candidate", "source": "builtin"},
    ]
    backtest_metrics = {
        "trades": 100,
        "win_rate": 67.0,
        "avg_net_return": 0.5366,
        "profit_factor": 1.567,
    }
    backtest_config = {
        "start": "2026-02-02",
        "end": "2026-07-30",
        "signal_adjust": "qfq",
        "execution_adjust": "none",
        "selection": "one_per_day:max(CLOSE/REF(CLOSE,5))",
        "hold_days": 1,
        "stop_loss_pct": -6.0,
        "take_profit_pct": 3.0,
        "commission_bps": 3.0,
        "stamp_duty_bps": 10.0,
        "slippage_bps": 5.0,
        "benchmark": None,
        "universe": {"preset": "default_a_share", "boards": ["main", "chi_next"]},
    }

    def default_params(self) -> dict[str, Any]:
        params = super().default_params()
        params["price_min"] = 10.0
        return params

    def compute(
        self, panels: dict[str, pd.DataFrame], params: dict[str, Any] | None = None
    ) -> SignalResult:
        result = super().compute(panels, params)
        strength = panels["close"] / REF(panels["close"], 5)
        selected = select_one_per_day(result.signals, strength)
        return SignalResult(
            signals=selected,
            factors={
                **result.factors,
                "ROC5": strength,
                "每日首选": selected,
            },
        )


register(QianlongCloseePickerV3())
register(QianlongTailPickerV1())
