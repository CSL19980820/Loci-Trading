"""三源尾盘共振：三个公开选股公式的尾盘合并实现。

公式来源：
- https://www.guhai.com.cn/html/GS/tong-hua-shun/80641.html
- https://www.gszx.com.cn/html/tongdaxingongshi/gs211492.html
- https://www.logic88.cn/130328.html

日线回测在信号日收盘后 15:30 确认，次日开盘成交，T+2 收盘退出。
"""
from __future__ import annotations

from typing import Any

import pandas as pd

from src.formula import CROSS, EMA, MA, REF
from src.strategy.domain.base import SignalResult, merge_params, register


class SanyuanTailResonance:
    """三源候选取原始 Top2，再按 V2 后置闸门确认。"""

    slug = "sanyuan-tail-v1"
    name = "三源尾盘共振"
    description = (
        "V2：同花顺 MA25 突破、通达信双阴反包、双子 K 共振三路 OR，"
        "原始评分取前两只后再过后置闸门；15:30 收盘后选股，次日开盘买入，T+2 收盘卖出"
    )
    entry_instructions = (
        "T 日收盘后 15:30 执行；日线实现使用已完成的 T 日 OHLCV，原始公式 FROMOPEN>=210 "
        "仅作来源说明，不作为调度或成交时点，"
        "分别计算 MA25 突破、"
        "双阴反包、双子 K 三条分支，任一成立即为候选；同日按评分 "
        "4*r1+2*r5+1.5*r20+0.35*CLV+0.12*MIN(volume_ratio,4) "
        "降序先保留原始前两只。V2 仅对这两只应用后置闸门：双阴反包，或市场上涨家数≥60%，"
        "或 T 日换手率 8%≤turnover<12%，或 CLV<0.5；闸门失败不递补第三名。"
        "T+1 按开盘价买入，若开盘一字涨停则跳过，T+2 收盘卖出；"
        "不追高二次筛选、不补仓，信号日收盘前不能使用次日数据。"
    )
    entry_timing = "next_open"
    execution_adjust = "none"
    screen_schedule = {
        "mode": "once",
        "run_hour": 15,
        "run_minute": 30,
        "interval_minutes": 10,
        "window_start_hour": 9,
        "window_start_minute": 30,
        "window_end_hour": 15,
        "window_end_minute": 30,
    }
    screen_top_n = 2
    # 回测器的 hold_days 从实际买入日计；T+1 买入、T+2 卖出是 1 个持仓日。
    screen_hold_days = 1
    screen_stop_loss_pct = None
    strategy_revision = "builtin:sanyuan-tail-v2"
    version = "v2"
    version_history = [
        {"version": "v1", "status": "archived", "source": "builtin:sanyuan-tail-v1"},
        {"version": "v2", "status": "active", "source": "builtin"},
    ]
    backtest_metrics: dict[str, Any] | None = {
        # 主口径为最近完整半年；组合层严格两仓各 50%，不把逐笔与组合口径混写。
        "trades": 138,
        "win_rate": 53.62,
        "avg_net_return": 1.1859,
        "profit_factor": 1.4039,
        "avg_win": 7.687,
        "avg_loss": -6.3311,
        "payoff_ratio": 1.2142,
        "completed_trades": 138,
        "portfolio_trades": 86,
        "portfolio_win_rate": 51.16,
        "portfolio_payoff_ratio": 1.4361,
        "portfolio_profit_factor": 1.5045,
        "portfolio_return_pct": 95.2232,
        "max_drawdown_pct": -34.3005,
        "occupancy_pct": 73.5,
        "full_period": {
            "start": "2024-01-02",
            "end": "2026-07-31",
            "trades": 717,
            "portfolio_trades": 448,
            "win_rate": 47.0,
            "avg_net_return": 0.807,
            "payoff_ratio": 1.4144,
            "profit_factor": 1.2543,
            "portfolio_return_pct": 638.4489,
            "max_drawdown_pct": -64.1855,
            "occupancy_pct": 72.0,
        },
    }
    backtest_config = {
        "start": "2026-02-02",
        "end": "2026-07-31",
        "signal_end": "2026-07-29",
        "adjust": "qfq",
        "execution_adjust": "none",
        # next_open 在 T+1 开盘成交；T+2 收盘退出等于从买入日持有 1 天。
        "hold_days": 1,
        "stop_loss_pct": None,
        "take_profit_pct": None,
        "commission_bps": 3.0,
        "stamp_duty_bps": 5.0,
        "slippage_bps": 10.0,
        "benchmark": None,
        "portfolio_model": "per_signal_day_equal_weight_two_slots",
        "portfolio_return_pct": 95.2232,
        "max_drawdown_pct": -34.3005,
        "occupancy_pct": 73.5,
        "completed_trades": 138,
        "signal_days": 86,
        "target_days": 117,
        "data_end_excluded": True,
        "universe": {"preset": "default_a_share", "boards": ["main", "chi_next"]},
        "full_period_validation": {
            "start": "2024-01-02",
            "end": "2026-07-31",
            "signal_end": "2026-07-29",
            "completed_trades": 717,
            "portfolio_return_pct": 638.4489,
            "max_drawdown_pct": -64.1855,
            "occupancy_pct": 72.0,
        },
    }
    default_universe = {"preset": "default_a_share", "boards": ["main", "chi_next"]}
    warmup_bars = 100

    def default_params(self) -> dict[str, Any]:
        return {}

    def required_fields(self) -> tuple[str, ...]:
        return ("open", "high", "low", "close", "volume", "turnover")

    def min_bars(self) -> int:
        return 25

    def compute(
        self, panels: dict[str, pd.DataFrame], params: dict[str, Any] | None = None
    ) -> SignalResult:
        merge_params(self, params)
        open_, high, low = panels["open"], panels["high"], panels["low"]
        close, volume = panels["close"], panels["volume"]

        ma25 = MA(close, 25)
        branch_a = CROSS(close, ma25)

        t1 = REF(close, 2) < REF(close, 3)
        t2 = (REF(close, 1) < REF(close, 2)) & REF(close < open_, 1)
        t3 = REF(open_, 1) < REF(close, 2)
        t4 = close > REF(close, 2)
        t5 = low > REF(low, 1)
        t6 = volume > REF(volume, 1)
        branch_b = t1 & t2 & t3 & t4 & t5 & t6

        ma3 = MA(close, 3)
        ma8 = MA(close, 8)
        ma10 = MA(close, 10)
        ma20 = MA(close, 20)
        k1 = (close + low + high) / 1.5
        k2 = EMA(k1, 3)
        k3 = EMA(k2, 2.5)
        branch_c = CROSS(k2, k3) & (
            (close > ma3)
            & (ma3 > REF(ma3, 1))
            & (ma8 > ma20)
            & (ma20 > REF(ma20, 1))
            & (close > REF(close, 1))
            & (low < ma8)
            & (close > ma8)
            & (ma10 > REF(ma10, 1))
        )

        candidates = (branch_a | branch_b | branch_c).fillna(False)
        r1 = _relative_change(close, REF(close, 1))
        r5 = _relative_change(close, REF(close, 5))
        r20 = _relative_change(close, REF(close, 20))
        spread = high - low
        clv = ((2 * close - high - low) / spread).where(spread != 0, 0.0)
        volume_ratio = _relative_ratio(volume, MA(volume, 20))
        score = 4 * r1 + 2 * r5 + 1.5 * r20 + 0.35 * clv + 0.12 * volume_ratio.clip(upper=4.0)
        rank = score.where(candidates).rank(axis=1, ascending=False, method="first")
        raw_top2 = (candidates & rank.le(2)).fillna(False)

        # 市场宽度只用 T 日与上一交易日的收盘比较，并广播回个股列。
        # 先确定原始 Top2，再应用闸门，避免闸门失败时偷补第 3 名。
        previous_close = REF(close, 1)
        valid_close = close.notna() & previous_close.notna()
        advancing = (close > previous_close) & valid_close
        valid_count = valid_close.sum(axis=1)
        breadth = advancing.sum(axis=1).div(valid_count.where(valid_count > 0))
        breadth_panel = pd.DataFrame(
            {code: breadth for code in close.columns}, index=close.index
        )
        turnover = panels["turnover"].astype(float)
        gate_branch_b = branch_b.fillna(False)
        gate_breadth = breadth_panel.ge(0.60).fillna(False)
        gate_turnover = ((turnover >= 0.08) & (turnover < 0.12)).fillna(False)
        gate_clv = clv.lt(0.5).fillna(False)
        gate = (gate_branch_b | gate_breadth | gate_turnover | gate_clv).fillna(False)
        selected = (raw_top2 & gate).fillna(False)

        return SignalResult(
            signals=selected,
            factors={
                "A_MA25突破": branch_a,
                "B_双阴反包": branch_b,
                "C_双子K": branch_c,
                "三源候选": candidates,
                "横截面评分": score,
                "原始每日前二": raw_top2,
                "市场上涨家数占比": breadth_panel,
                "闸门_双阴反包": gate_branch_b,
                "闸门_上涨家数>=60%": gate_breadth,
                "闸门_换手8%-12%": gate_turnover,
                "闸门_CLV<0.5": gate_clv,
                "后置闸门": gate,
                "每日前二": selected,
            },
        )


def _relative_ratio(current: pd.DataFrame, previous: pd.DataFrame) -> pd.DataFrame:
    """计算 current / previous，并屏蔽零分母。"""
    return current.div(previous).where(previous != 0)


def _relative_change(current: pd.DataFrame, previous: pd.DataFrame) -> pd.DataFrame:
    return _relative_ratio(current, previous) - 1.0


register(SanyuanTailResonance())
