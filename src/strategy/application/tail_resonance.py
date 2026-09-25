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
from src.strategy.application.score_percentile import SCORE_PERCENTILE, pooled_percentile
from src.strategy.domain.base import SignalResult, merge_params, register

#: 市场宽度低于该阈值时整日空仓（组合收益优化：避开极弱市日）。
WEAK_BREADTH_SKIP = 0.40
#: 未复权收盘价低于该阈值不入选、不进观察（仙股流动性差）。
PRICE_MIN = 6.0
#: 候选池 0–100 评分的参照期：近 60 个交易日（含当日）三源候选的横截面评分分布。
SCORE_POOL_DAYS = 60


def _once_schedule(hour: int, minute: int) -> dict[str, Any]:
    return {
        "mode": "once",
        "run_hour": hour,
        "run_minute": minute,
        "interval_minutes": 10,
        "window_start_hour": 9,
        "window_start_minute": 30,
        "window_end_hour": hour,
        "window_end_minute": minute,
    }


_SANYUAN_RULES = (
    "分别计算 MA25 突破、"
    "双阴反包、双子 K 三条分支，任一成立即为候选。对全部候选应用后置闸门："
    "双阴反包，或市场上涨家数≥60%，"
    "或 T 日换手率 8%≤turnover<12%，或 CLV<0.5；"
    "另要求未复权收盘价≥6 元（仙股不入正式信号、不进观察）；"
    "若当日市场上涨家数占比 <40%，整日空仓（不选股）；"
    "否则通过闸门后再按评分 "
    "4*r1+2*r5+1.5*r20+0.35*CLV+0.12*MIN(volume_ratio,4) "
    "降序取前两只（V2.6：在 V2.5 弱市空仓之上加现价门槛）。"
    "T+1 按开盘价买入，若开盘一字涨停则跳过，T+2 收盘卖出；"
    "不追高二次筛选、不补仓，信号日收盘前不能使用次日数据。"
)


class SanyuanTailResonance:
    """三源候选过后置闸门，再按评分取 Top2；极弱市空仓。"""

    slug = "sanyuan-tail-v1"
    name = "三源尾盘共振（15:30）"
    description = (
        "V2.6：同花顺 MA25 突破、通达信双阴反包、双子 K 共振三路 OR，"
        "后置闸门过滤后按 V2.1 评分取前两只；未复权现价<6 元不入选；"
        "上涨家数<40% 整日空仓；15:30 收盘后选股，次日开盘买入，T+2 收盘卖出"
    )
    entry_instructions = (
        "T 日收盘后 15:30 执行；日线实现使用已完成的 T 日 OHLCV，原始公式 FROMOPEN>=210 "
        "仅作来源说明，不作为调度或成交时点，"
        + _SANYUAN_RULES
    )
    entry_timing = "next_open"
    execution_adjust = "none"
    requires_raw_limit_price = True
    screen_schedule = _once_schedule(15, 30)
    screen_force_spot_refresh = False
    screen_top_n = 2
    screen_rank_factor = "横截面评分"
    # 回测器的 hold_days 从实际买入日计；T+1 买入、T+2 卖出是 1 个持仓日。
    screen_hold_days = 1
    screen_stop_loss_pct = None
    strategy_revision = "builtin:sanyuan-tail-v2.6"
    version = "v2.6"
    version_history = [
        {"version": "v1", "status": "archived", "source": "builtin:sanyuan-tail-v1"},
        {"version": "v2", "status": "archived", "source": "builtin:sanyuan-tail-v2"},
        {"version": "v2.1", "status": "archived", "source": "builtin:sanyuan-tail-v2.1"},
        {"version": "v2.2", "status": "archived", "source": "builtin:sanyuan-tail-v2.2"},
        {"version": "v2.5", "status": "archived", "source": "builtin:sanyuan-tail-v2.5"},
        {"version": "v2.6", "status": "active", "source": "builtin"},
    ]
    backtest_metrics: dict[str, Any] | None = {
        # 主口径为最近完整半年；组合层严格两仓各 50%，不把逐笔与组合口径混写。
        "trades": 125,
        "win_rate": 56.0,
        "avg_net_return": 1.4159,
        "profit_factor": 1.543,
        "avg_win": 7.1858,
        "avg_loss": -5.9277,
        "payoff_ratio": 1.2122,
        "completed_trades": 125,
        "portfolio_trades": 82,
        "portfolio_win_rate": 62.2,
        "portfolio_payoff_ratio": 1.2329,
        "portfolio_profit_factor": 2.0282,
        "portfolio_return_pct": 96.9916,
        "max_drawdown_pct": -10.6157,
        "occupancy_pct": 82.9758,
        "full_period": {
            # 全样本仍为 V2.x 时代参考，未按 V2.5 弱市空仓重跑。
            "start": "2024-01-02",
            "end": "2026-07-31",
            "note": "archived_pre_v25_reference",
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
        "hold_days": 1,
        "stop_loss_pct": None,
        "take_profit_pct": None,
        "commission_bps": 3.0,
        "stamp_duty_bps": 5.0,
        "slippage_bps": 10.0,
        "benchmark": None,
        "portfolio_model": "per_signal_day_equal_weight_two_slots",
        "portfolio_return_pct": 96.9916,
        "max_drawdown_pct": -10.6157,
        "occupancy_pct": 82.9758,
        "completed_trades": 125,
        "signal_days": 44,
        "target_days": 117,
        "weak_breadth_skip": WEAK_BREADTH_SKIP,
        "data_end_excluded": True,
        "universe": {"preset": "default_a_share", "boards": ["main", "chi_next"]},
        "price_min": PRICE_MIN,
        "metrics_note": "组合数字仍为 V2.5（无价格门槛）样本，V2.6 未重跑",
        "live_clock": "15:30",
        "full_period_validation": {
            "start": "2024-01-02",
            "end": "2026-07-31",
            "signal_end": "2026-07-29",
            "note": "archived_pre_v25_reference",
            "completed_trades": 717,
            "portfolio_return_pct": 638.4489,
            "max_drawdown_pct": -64.1855,
            "occupancy_pct": 72.0,
        },
    }
    default_universe = {"preset": "default_a_share", "boards": ["main", "chi_next"]}
    warmup_bars = 100

    def default_params(self) -> dict[str, Any]:
        return {"price_min": PRICE_MIN}

    def required_fields(self) -> tuple[str, ...]:
        return ("open", "high", "low", "close", "volume", "turnover")

    def min_bars(self) -> int:
        return 25

    def compute(
        self, panels: dict[str, pd.DataFrame], params: dict[str, Any] | None = None
    ) -> SignalResult:
        p = merge_params(self, params)
        open_, high, low = panels["open"], panels["high"], panels["low"]
        close, volume = panels["close"], panels["volume"]
        # 「现价 ≥ 6 元」是绝对价格，必须用未复权价，否则前复权会让历史日整体偏移。
        raw_close = panels.get("__raw_close")
        if not isinstance(raw_close, pd.DataFrame):
            raw_close = close
        else:
            raw_close = raw_close.reindex(index=close.index, columns=close.columns)

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
        # V2.1 / V2.5：CLV 为正权重（组合收益取向，不做 V2.2 惩罚）。
        score = (
            4 * r1 + 2 * r5 + 1.5 * r20 + 0.35 * clv + 0.12 * volume_ratio.clip(upper=4.0)
        )
        raw_rank = score.where(candidates).rank(axis=1, ascending=False, method="first")
        raw_top2 = (candidates & raw_rank.le(2)).fillna(False)

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
        gate_price = raw_close.ge(float(p["price_min"])).fillna(False)
        # V2.5：上涨家数 <40% 整日空仓。
        market_ok = breadth_panel.ge(WEAK_BREADTH_SKIP).fillna(False)
        pre_market_eligible = (candidates & gate & gate_price).fillna(False)
        eligible = (pre_market_eligible & market_ok).fillna(False)
        rank = score.where(eligible).rank(axis=1, ascending=False, method="first")
        selected = (eligible & rank.le(2)).fillna(False)
        watch_eligible = (pre_market_eligible & ~market_ok).fillna(False)
        watch_rank = score.where(watch_eligible).rank(
            axis=1, ascending=False, method="first"
        )
        watch_selected = (watch_eligible & watch_rank.le(2)).fillna(False)

        return SignalResult(
            signals=selected,
            watch_signals=watch_selected,
            factors={
                # 前几项是候选池“理由”列展示的内容：先放可读的评分与成分，再放 0/1 闸门标记。
                SCORE_PERCENTILE: pooled_percentile(score, candidates, window=SCORE_POOL_DAYS),
                "横截面评分": score,
                "1日涨幅%": r1 * 100.0,
                "5日涨幅%": r5 * 100.0,
                "20日涨幅%": r20 * 100.0,
                "收盘位置CLV": clv,
                "量比(20日)": volume_ratio,
                "A_MA25突破": branch_a,
                "B_双阴反包": branch_b,
                "C_双子K": branch_c,
                "三源候选": candidates,
                "原始每日前二": raw_top2,
                "市场上涨家数占比": breadth_panel,
                "闸门_双阴反包": gate_branch_b,
                "闸门_上涨家数>=60%": gate_breadth,
                "闸门_换手8%-12%": gate_turnover,
                "闸门_CLV<0.5": gate_clv,
                "闸门_现价>=6元": gate_price,
                "未复权收盘价": raw_close,
                "后置闸门": gate,
                "弱市可交易_上涨家数>=40%": market_ok,
                "弱市前候选": pre_market_eligible,
                "闸门后候选": eligible,
                "每日前二": selected,
                "弱市低吸观察": watch_selected,
            },
        )


def _relative_ratio(current: pd.DataFrame, previous: pd.DataFrame) -> pd.DataFrame:
    """计算 current / previous，并屏蔽零分母。"""
    return current.div(previous).where(previous != 0)


def _relative_change(current: pd.DataFrame, previous: pd.DataFrame) -> pd.DataFrame:
    return _relative_ratio(current, previous) - 1.0


register(SanyuanTailResonance())
