"""缩量回调后二次突破：固定条件、固定评分和每日全池前二。"""
from __future__ import annotations

from typing import Any

import numpy as np
import pandas as pd

from src.formula import BARSCOUNT, COUNT, HHV, MA, REF, ZTPRICE, limit_ratio_panel
from src.strategy.application.execution_profile import ExecutionProfile
from src.strategy.domain.base import SignalResult, StrategyError, merge_params, register


DAILY_PICK_LIMIT = 2
DEPENDENCY_BARS = 14
VOLUME_CONTRACTION_SATURATION = 0.5
PULLBACK_DEPTH_ZERO_SCORE = 0.10
BREAKOUT_VOLUME_SATURATION = 3.0
MOMENTUM_LOOKBACK = 10
MOMENTUM_SATURATION = 0.20


class ContractionRebreakoutV1:
    slug = "contraction-rebreakout-v1"
    name = "缩量回调后二次突破"
    description = (
        "在统一股票池内计算，至少 31 根有效日 K；前期强阳后连续两日缩量回调，"
        "再收阳放量突破此前五日高点，剔除收盘涨停股；按动量与形态评分每日最多选前 2 只。"
    )
    entry_instructions = (
        "以收盘后完整日 K 确认信号，形态对应固定通达信公式，并剔除收盘涨停股。"
        "T-12 至 T-3 十个交易日内至少有一天收阳且相对前收上涨不少于 5%；"
        "T-2、T-1 连续收盘下降，两日成交量均严格低于各自当日 5 日均量。"
        "T 日收阳且上涨不少于 3%，收盘严格高于 T-5 至 T-1 最高价，"
        "成交量不少于 T-1 的 1.5 倍；有效收盘日 K 超过 30 根。"
        "股票范围由统一股票池配置决定，战法内不再限制板块、名称或绝对股价；"
        "公式所需最近 14 根日 K 必须 OHLC 有限、为正且价格范围合法，成交量为正。"
        "形态默认使用前复权日 K；涨停价按证券适用幅度、未复权前收盘逢五进一到分计算，"
        "未复权收盘须低于涨停价，低一分钱即可保留，盘中触板回落仍可入选。"
        "候选按 0–100 分降序，每日最多取 2 只，"
        "不足两只不补足，同分按代码升序，总分保留四位。"
        "10日动量 40 分=40×(当日收盘/10日前收盘−1)/20%，上涨 20% 封顶、非正得零分；"
        "回调缩量 15 分=15×(1−两回调日各自成交量/5日均量的平均值)/0.5，"
        "平均量比不高于 0.5 满分；回调深度 15 分=15×(1−回调深度/10%)，"
        "回调深度=1−T-1收盘/T-3收盘，达到 10% 得零分。"
        "再突破放量 10 分=10×(当日/前日成交量−1)/2，3 倍量封顶；"
        "收盘位置 20 分=20×(收盘−最低)/(最高−最低)。"
        "各项按 0 至对应满分截断。该权重根据 2026-09-29 的已知案例校准，"
        "评分只使用信号日及之前数据；案例命中及同历史区间回测属于样本内，"
        "不代表胜率或预期收益，尚未通过独立样本外验证。"
        "盘中结果是未完成日 K 的预览，须收盘后确认。"
        "本指标不预设持有期或止盈止损，最早在下一交易日开盘入场；"
        "次日涨跌停、停牌及实际成交能力由回测或交易执行检查。"
    )
    entry_timing = "next_open"
    adjust = "qfq"
    execution_adjust = "none"
    requires_raw_limit_price = True
    requires_instrument_names = True
    source_evidence_summary = True
    screen_managed_job = False
    screen_top_n = DAILY_PICK_LIMIT
    screen_rank_factor = "score"
    strategy_revision = 'builtin:contraction-rebreakout-v1:3'
    version = 'v1.2'
    version_history = [
        {
            "version": "v1",
            "status": "archived",
            "source": "builtin:contraction-rebreakout-v1:1",
        },
        {
            "version": "v1.1",
            "status": "archived",
            "source": "builtin:contraction-rebreakout-v1:2",
            "backtest_metrics": {
                "trades": 185,
                "win_rate": 38.92,
                "avg_net_return": -0.2855,
                "payoff_ratio": 1.43,
                "profit_factor": 0.911,
                "avg_win": 7.5495,
                "avg_loss": -5.2778,
            },
            "backtest_config": {
                "hold_days": 3,
                "stop_loss_pct": -6.0,
                "take_profit_pct": None,
                "commission_bps": 3.0,
                "stamp_duty_bps": 5,
                "slippage_bps": 5.0,
                "benchmark": "000300",
                "strict_limit_prices": True,
                "economic_returns": True,
                "valuation_end": "2026-09-30",
                "mode": "trade",
                "start": "2026-01-01",
                "end": "2026-09-30",
                "universe": {
                    "preset": "default_a_share",
                    "boards": ["chi_next"],
                    "min_list_days": 0,
                },
                "hold_days_convention": "入场后经过3个交易日，即入场第4日收盘；先触及止损则提前退出",
                "review_note": "revision "
                "2：剔除收盘涨停并按2026-09-29广康/芒果已知案例校准评分；2026年1至9月真实行情样本内复盘，每日全池评分前2，已平仓统计；当前证券目录有历史成员偏差，未做独立样本外验证，不代表未来预测成功",
            },
        },
        {"version": "v1.2", "status": "active", "source": "builtin"},
    ]
    # 2026-10-03 核验的历史复盘快照；只用于展示和回测模板，不改变选股计算。
    backtest_metrics = None
    backtest_config = {
        "hold_days": 3,
        "stop_loss_pct": -6.0,
        "take_profit_pct": None,
        "commission_bps": 3.0,
        "stamp_duty_bps": 5,
        "slippage_bps": 5.0,
        "benchmark": "000300",
        "strict_limit_prices": True,
        "economic_returns": True,
        "mode": "trade",
        "hold_days_convention": "入场后经过3个交易日，即入场第4日收盘；先触及止损则提前退出",
        "start": "2026-01-01",
        "end": "2026-09-30",
    }

    range_prime_enabled = False

    def default_params(self) -> dict[str, Any]:
        return {}

    def required_fields(self) -> tuple[str, ...]:
        return ("open", "high", "low", "close", "volume")

    def min_bars(self) -> int:
        return 31

    def execution_profile(self, params: dict[str, Any] | None = None) -> ExecutionProfile:
        merge_params(self, params)
        # BARSCOUNT 依赖原始输入起点；每日前二依赖完整股票轴。
        return ExecutionProfile(
            pure=True, causal=True, column_mode="coupled", origin="sensitive",
            metadata_fields=("__raw_close", "__instrument_names__"),
        )

    def compute(
        self, panels: dict[str, pd.DataFrame], params: dict[str, Any] | None = None,
    ) -> SignalResult:
        merge_params(self, params)
        close = panels["close"]
        open_, high, low, volume = (
            panels[field].reindex(index=close.index, columns=close.columns)
            for field in ("open", "high", "low", "volume")
        )
        raw_close = panels.get("__raw_close")
        if not isinstance(raw_close, pd.DataFrame):
            raise StrategyError("缩量回调后二次突破需要未复权收盘价，不能用复权价格判断涨停")
        raw_close = raw_close.reindex(index=close.index, columns=close.columns)
        names = panels.get("__instrument_names__")
        if not isinstance(names, dict):
            raise StrategyError("缩量回调后二次突破需要证券名称，用于确定真实涨停幅度")
        previous_raw_close = REF(raw_close, 1)
        with np.errstate(over="ignore", invalid="ignore"):
            limit_up = ZTPRICE(previous_raw_close, limit_ratio_panel(raw_close, names))
            close_cents = np.floor(raw_close * 100 + 0.5 + 1e-9)
            limit_cents = np.floor(limit_up * 100 + 0.5 + 1e-9)
        raw_valid = (
            np.isfinite(raw_close) & raw_close.gt(0)
            & np.isfinite(previous_raw_close) & previous_raw_close.gt(0)
            & np.isfinite(close_cents) & np.isfinite(limit_cents)
        )
        below_limit = raw_valid & close_cents.lt(limit_cents)
        # 不同首个有效日会让 BARSCOUNT 的 where 按股票拆块；合并同 dtype 块，
        # 避免后续布尔组合逐列调度，保留整数/浮点列及缺失值的原有口径。
        bars = BARSCOUNT(close.where(np.isfinite(close) & close.gt(0))).copy()
        valid = (
            np.isfinite(close) & np.isfinite(open_) & np.isfinite(high) & np.isfinite(low)
            & np.isfinite(volume) & volume.gt(0) & close.gt(0) & open_.gt(0) & low.gt(0)
            & high.ge(close) & high.ge(open_) & low.le(close) & low.le(open_)
        ).rolling(DEPENDENCY_BARS).sum().eq(DEPENDENCY_BARS)

        with np.errstate(divide="ignore", invalid="ignore", over="ignore"):
            growth = close / REF(close, 1)
            impulse = growth.ge(1.05) & close.gt(open_)
            impulse_count = REF(COUNT(impulse, 10), 3)
            prior_high = REF(HHV(high, 5), 1)
            volume_mean = MA(volume, 5)
            volume_ratio = volume / REF(volume, 1)
            contraction_ratio = (
                REF(volume / volume_mean, 1) + REF(volume / volume_mean, 2)
            ) / 2
            pullback_depth = 1 - REF(close, 1) / REF(close, 3)
            momentum = close / REF(close, MOMENTUM_LOOKBACK) - 1

        prior_impulse = impulse_count.gt(0)
        pullback = REF(close, 1).lt(REF(close, 2)) & REF(close, 2).lt(REF(close, 3))
        contraction = REF(volume, 1).lt(REF(volume_mean, 1)) & REF(volume, 2).lt(REF(volume_mean, 2))
        breakout = close.gt(prior_high)
        expansion = volume.ge(REF(volume, 1) * 1.5)
        bullish_growth = close.gt(open_) & growth.ge(1.03)
        finite_ratios = (
            REF(COUNT(np.isfinite(growth), 10), 3).eq(10)
            & np.isfinite(growth) & np.isfinite(volume_ratio)
            & np.isfinite(contraction_ratio) & np.isfinite(pullback_depth)
            & np.isfinite(momentum)
        )
        base = valid & bars.gt(30) & finite_ratios & below_limit
        candidates = (
            base & prior_impulse & pullback & contraction & breakout & expansion & bullish_growth
        ).fillna(False).astype(bool)

        day_range = high - low
        components = {
            "10日动量分(40)": (momentum / MOMENTUM_SATURATION).clip(0, 1) * 40,
            "回调缩量分(15)": ((1 - contraction_ratio) / VOLUME_CONTRACTION_SATURATION).clip(0, 1) * 15,
            "回调深度分(15)": (1 - pullback_depth / PULLBACK_DEPTH_ZERO_SCORE).clip(0, 1) * 15,
            "再突破放量分(10)": ((volume_ratio - 1) / (BREAKOUT_VOLUME_SATURATION - 1)).clip(0, 1) * 10,
            "收盘位置分(20)": ((close - low) / day_range.where(day_range.gt(0))).clip(0, 1) * 20,
        }
        score = sum(components.values()).where(candidates)
        score = score.where(np.isfinite(score)).clip(0, 100).round(4)
        rank = score.reindex(columns=sorted(score.columns, key=str)).rank(
            axis=1, ascending=False, method="first",
        ).reindex(columns=score.columns)
        selected = (candidates & rank.le(DAILY_PICK_LIMIT)).fillna(False).astype(bool)
        return SignalResult(signals=selected, factors={
            "score": score, **components, "候选排名": rank,
            "条件候选": candidates, "每日前二": selected,
            "基础过滤": base, "前期强阳": prior_impulse, "两日回调": pullback,
            "回调缩量": contraction, "收盘突破前五日高点": breakout,
            "当日放量": expansion, "阳线涨幅确认": bullish_growth,
            "有效日K根数": bars, "前期强阳次数": impulse_count,
            "前五日最高价": prior_high, "回调均量比": contraction_ratio,
            "回调深度(%)": pullback_depth * 100, "突破量比": volume_ratio,
            "当日涨幅(%)": (growth - 1) * 100,
            "10日动量(%)": momentum * 100,
            "突破幅度(%)": (close / prior_high - 1) * 100,
            "收盘非涨停": below_limit, "未复权收盘价": raw_close,
            "涨停价": limit_up, "距涨停(元)": limit_up - raw_close,
        })

    def compute_projection(
        self, panels: dict[str, pd.DataFrame], params: dict[str, Any] | None,
        dates: list[str],
    ) -> SignalResult:
        """复用完整计算，保留计数起点和完整股票池的排名语义。"""
        from src.strategy.application.compute_runtime import project_result

        return project_result(self.compute(panels, params), dates)


register(ContractionRebreakoutV1())
