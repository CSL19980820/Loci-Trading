"""倍量阴次日低开：开盘可知的形态、低位/均线评分与板块去重。"""
from __future__ import annotations

from math import isfinite
from typing import Any

import numpy as np
import pandas as pd

from src.market import is_st_name
from src.strategy.application.execution_profile import ExecutionProfile
from src.strategy.domain.base import SignalResult, StrategyError, merge_params, register


MA_PERIODS = (5, 10, 20)
MA_DISTANCE_SATURATION = 0.03
TREND_MA_PERIOD = 20
TREND_SLOPE_SESSIONS = 5
MIN_SELECTION_SCORE = 50.0
NUMERICAL_EPSILON = 1e-12


class DoubleYinLowOpenV1:
    slug = "double-volume-yin-low-open-v1"
    name = "倍量阴低开优选"
    description = (
        "沪深主板前日涨≥8%，昨日收倍量阴，今日低开且开盘价>6元；"
        "排除弱趋势反弹与大阳实体完全失守，按趋势30/支撑30/低位20/均线20评分，"
        "行业及相邻板块去重后默认最多选两只，宁缺勿滥。"
    )
    entry_instructions = (
        "盘后预选默认16:30，保存未经次日低开/价格/评分过滤的全量形态候选快照；"
        "次日选股默认09:26，只读取这批股票的外部实时行情；两个时点可在调度配置中调整。今日只使用开盘价。"
        "仅沪深主板，T-2日涨幅≥8%，并收实体阳线；"
        "T-1日收阴且成交量至少为T-2的2倍，不要求高开。"
        "T日开盘低于昨日收盘且高于6元；截至T-2的近10交易日涨幅≤30%。"
        "大涨前MA20下降且当时收盘低于MA20，或昨日MA20下降且昨收/今日开盘均低于MA20，直接排除。"
        "昨日收盘或今日开盘跌破大阳开盘价，视为大阳实体完全失守并排除；影线破低只扣分。"
        "趋势30分：大涨前MA20不下降、当时收盘不低于MA20、昨日MA20不下降、开盘不低于昨日MA20，各7.5分。"
        "支撑30分：今日开盘在大阳实体内的保留比例×20，加昨日最低价不低于大阳最低价10分。"
        "排除ST、退市、非沪深主板及名称缺失股票；至少61根有效日K。"
        "低位分=20×(1−开盘价在截至昨日60日高低区间的位置)，截断0至20；"
        "均线分=20×(1−距截至昨日MA5/10/20最近均线的相对距离/3%)，截断0至20；超过3%只归零。"
        "总分至少50才成为合格候选，中点和贴线不单独否决。"
        "总分保留四位，同分按代码升序；行业或相邻板块组任一相交不能同时入选。"
        "缺板块信息的候选保留评分但不进入精选；默认最多选2只，不足不补。"
        "评分表示规则匹配程度，未证明胜率或收益，也不自动执行买入。"
    )
    entry_timing = "open"
    adjust = "none"
    execution_adjust = "none"
    requires_realtime_inputs = True
    requires_instrument_names = True
    screen_managed_job = True
    screen_allowed_boards = ("main",)
    screen_rank_factor = "score"
    screen_default_top_n = 2
    screen_push_wecom = True
    screen_schedule_configurable = True
    screen_staggered = False
    screen_schedule = {
        "mode": "once", "run_hour": 9, "run_minute": 26,
        "interval_minutes": 10,
        "window_start_hour": 9, "window_start_minute": 26,
        "window_end_hour": 9, "window_end_minute": 26,
    }
    screen_prepare_schedule = {"mode": "once", "run_hour": 16, "run_minute": 30}
    screen_job_config = {
        "trading_days_only": True, "snapshot_time": "09:26",
        "snapshot_grace_minutes": 5, "requires_realtime_inputs": True, "catch_up": False,
    }
    strategy_revision = "builtin:double-volume-yin-low-open-v1:3.1"
    version = "v3"
    version_history = [
        {"version": "v1", "status": "archived", "source": "builtin:double-volume-yin-low-open-v1:1"},
        {"version": "v2", "status": "archived", "source": "builtin:double-volume-yin-low-open-v1:2"},
        {"version": "v3", "status": "active", "source": "builtin"},
    ]
    default_universe = {"preset": "default_a_share", "boards": ["main"]}
    range_prime_enabled = False

    def default_params(self) -> dict[str, Any]:
        return {
            "recent_days": 10,
            "max_recent_gain_pct": 30.0,
            "volume_ratio": 2.0,
            "price_floor": 6.0,
            "top_n": 2,
            "position_lookback": 60,
        }

    def _params(self, params: dict[str, Any] | None) -> dict[str, Any]:
        resolved = merge_params(self, params)
        for key in ("recent_days", "top_n", "position_lookback"):
            value = resolved[key]
            if isinstance(value, bool) or not isinstance(value, int) or value < 1:
                raise StrategyError(f"{key} 必须是正整数")
        for key in ("max_recent_gain_pct", "volume_ratio", "price_floor"):
            value = resolved[key]
            if isinstance(value, bool) or not isinstance(value, (int, float)) or not isfinite(value):
                raise StrategyError(f"{key} 必须是有限数值")
            if value < 0 or (key == "volume_ratio" and value < 1):
                raise StrategyError(f"{key} 超出允许范围")
        return resolved

    def required_fields(self) -> tuple[str, ...]:
        return ("open", "high", "low", "close", "volume")

    def min_bars(self) -> int:
        return 61

    def history_bars(self, params: dict[str, Any] | None = None) -> int:
        resolved = self._params(params)
        return max(self.min_bars(), resolved["recent_days"] + 3,
                   resolved["position_lookback"] + 1, max(MA_PERIODS) + 1,
                   TREND_MA_PERIOD + TREND_SLOPE_SESSIONS + 3)

    def execution_profile(self, params: dict[str, Any] | None = None) -> ExecutionProfile:
        return ExecutionProfile(
            pure=True, causal=True, column_mode="coupled", origin="finite",
            lookback_bars=self.history_bars(params),
            metadata_fields=("__instrument_names__", "__sector_groups__"),
        )

    def compute(
        self, panels: dict[str, pd.DataFrame], params: dict[str, Any] | None = None,
    ) -> SignalResult:
        resolved = self._params(params)
        for field in self.required_fields():
            if not isinstance(panels.get(field), pd.DataFrame):
                raise StrategyError(f"倍量阴低开优选缺少行情字段：{field}")
        open_ = panels["open"]
        if not open_.index.is_unique or not open_.columns.is_unique:
            raise StrategyError("倍量阴低开优选需要唯一的交易日和证券代码")
        frames = {
            field: panels[field].reindex(index=open_.index, columns=open_.columns)
            for field in self.required_fields()
        }
        close, high, low, volume = (frames[field] for field in ("close", "high", "low", "volume"))
        names = panels.get("__instrument_names__")
        if not isinstance(names, dict):
            raise StrategyError("倍量阴低开优选需要证券名称，不能跳过ST/退市过滤")
        raw_groups = panels.get("__sector_groups__", {})
        if not isinstance(raw_groups, dict):
            raw_groups = {}
        groups = {}
        for code in open_.columns:
            values = raw_groups.get(str(code))
            if isinstance(values, (list, tuple)) and values and all(
                isinstance(value, str) and value.strip() for value in values
            ):
                groups[code] = frozenset(value.strip() for value in values)
            else:
                groups[code] = frozenset()

        main = pd.Series({code: _a_share_code(code, ("00", "60")) for code in open_.columns})
        clean = pd.Series({
            code: bool(str(names.get(str(code)) or "").strip())
            and not is_st_name(str(names.get(str(code)) or ""))
            and "退" not in str(names.get(str(code)) or "")
            for code in open_.columns
        })
        # 只检查截至昨日的完整窗口；今日的C/H/L/V不影响开盘决策或任何因子。
        valid_history = (
            np.isfinite(open_) & np.isfinite(close) & np.isfinite(high) & np.isfinite(low)
            & np.isfinite(volume) & open_.gt(0) & close.gt(0) & low.gt(0) & volume.ge(0)
            & high.ge(open_) & high.ge(close) & low.le(open_) & low.le(close)
        )
        required_history = self.history_bars(resolved) - 1
        history_ok = valid_history.shift(1).rolling(required_history).sum().eq(required_history)
        previous_close = close.shift(1)
        anchor_close = close.shift(2)
        anchor_gain = ((anchor_close / close.shift(3) - 1) * 100).round(2)
        recent_gain = ((anchor_close / close.shift(resolved["recent_days"] + 2) - 1) * 100).round(2)
        volume_ratio = volume.shift(1) / volume.shift(2).where(volume.shift(2).gt(0))
        up_day = anchor_gain.ge(8) & main & anchor_close.gt(open_.shift(2))
        yin_day = previous_close.lt(open_.shift(1))
        double_volume = volume.shift(2).gt(0) & volume.shift(1).gt(0) & volume_ratio.ge(resolved["volume_ratio"])
        low_open = np.isfinite(open_) & open_.gt(resolved["price_floor"]) & open_.lt(previous_close)
        recent_ok = recent_gain.le(resolved["max_recent_gain_pct"])
        historical_candidates = (history_ok & clean & main & up_day & yin_day
                                 & double_volume & recent_ok).fillna(False).astype(bool)
        # 趋势先看大阳出现之前，避免一次反弹把下降均线临时拉成向上。
        prior_ma20 = close.shift(1).rolling(TREND_MA_PERIOD).mean()
        before_rally_ma20 = close.shift(3).rolling(TREND_MA_PERIOD).mean()
        before_rally_change = (before_rally_ma20 / before_rally_ma20.shift(TREND_SLOPE_SESSIONS) - 1) * 100
        prior_change = (prior_ma20 / prior_ma20.shift(TREND_SLOPE_SESSIONS) - 1) * 100
        # 相同价格的rolling求和在全历史/有限窗口会有尾差，横盘不应因此失分。
        before_rally_direction = before_rally_change.ge(-NUMERICAL_EPSILON * 100)
        prior_direction = prior_change.ge(-NUMERICAL_EPSILON * 100)
        before_price_distance = close.shift(3) / before_rally_ma20 - 1
        before_rally_price_support = before_price_distance.ge(-NUMERICAL_EPSILON)
        weak_before_rally = (before_rally_change.lt(-NUMERICAL_EPSILON * 100)
                             & before_price_distance.lt(-NUMERICAL_EPSILON))
        historical_trend = (np.isfinite(before_rally_ma20) & np.isfinite(before_rally_change)
                            & ~weak_before_rally).fillna(False).astype(bool)
        yesterday_ma_distance = previous_close / prior_ma20 - 1
        opening_ma_distance = open_ / prior_ma20 - 1
        yesterday_ma_support = yesterday_ma_distance.ge(-NUMERICAL_EPSILON)
        opening_ma_support = opening_ma_distance.ge(-NUMERICAL_EPSILON)
        weak_current = (prior_change.lt(-NUMERICAL_EPSILON * 100)
                        & yesterday_ma_distance.lt(-NUMERICAL_EPSILON)
                        & opening_ma_distance.lt(-NUMERICAL_EPSILON))
        trend_ok = (historical_trend & np.isfinite(prior_change) & ~weak_current).fillna(False).astype(bool)
        trend_score = (before_rally_direction.astype(float) + before_rally_price_support.astype(float)
                       + prior_direction.astype(float) + opening_ma_support.astype(float)) * 7.5

        body_midpoint = (open_.shift(2) + anchor_close) / 2
        yesterday_body_support = previous_close.ge(body_midpoint)
        opening_body_support = open_.ge(body_midpoint)
        yesterday_low_support = low.shift(1).ge(low.shift(2))
        anchor_open = open_.shift(2)
        support_ok = (previous_close.ge(anchor_open) & open_.ge(anchor_open)).fillna(False).astype(bool)
        body_retained = ((open_ - anchor_open) / (anchor_close - anchor_open).where(
            anchor_close.gt(anchor_open))).clip(0, 1)
        support_score = body_retained * 20 + yesterday_low_support.astype(float) * 10
        opening_candidates = (historical_candidates & low_open).fillna(False).astype(bool)

        window_low = low.shift(1).rolling(resolved["position_lookback"]).min()
        window_high = high.shift(1).rolling(resolved["position_lookback"]).max()
        width = window_high - window_low
        position = ((open_ - window_low) / width.where(width.gt(0))).clip(0, 1)
        low_score = (1 - position) * 20
        best_distance = pd.DataFrame(np.inf, index=open_.index, columns=open_.columns)
        best_period = pd.DataFrame(np.nan, index=open_.index, columns=open_.columns)
        best_ma = best_period.copy()
        for period in MA_PERIODS:
            ma = close.shift(1).rolling(period).mean()
            distance = (open_ / ma.where(ma.gt(0)) - 1).abs()
            better = np.isfinite(distance) & distance.lt(best_distance)
            best_distance = best_distance.where(~better, distance)
            best_period = best_period.where(~better, period)
            best_ma = best_ma.where(~better, ma)
        ma_score = (1 - best_distance / MA_DISTANCE_SATURATION).clip(0, 1) * 20
        # 百分比除法会把恰好3%表示为0.030000000000000027；仅容忍浮点误差。
        ma_distance_ok = best_distance.le(MA_DISTANCE_SATURATION + 1e-12).fillna(False).astype(bool)
        quality_score = (low_score + ma_score + trend_score + support_score).clip(0, 100)
        score_ok = (np.isfinite(quality_score) & quality_score.ge(MIN_SELECTION_SCORE)).fillna(False).astype(bool)
        candidates = (opening_candidates & trend_ok & support_ok & score_ok).fillna(False).astype(bool)
        score = quality_score.where(candidates).round(4)
        candidate_rank = score.reindex(columns=sorted(score.columns, key=str)).rank(
            axis=1, ascending=False, method="first",
        ).reindex(columns=score.columns)
        selected = pd.DataFrame(False, index=open_.index, columns=open_.columns)
        selected_rank = pd.DataFrame(np.nan, index=open_.index, columns=open_.columns)
        sector_excluded = selected.copy()
        quota_full = selected.copy()
        sector_complete = pd.DataFrame(
            np.broadcast_to([bool(groups[code]) for code in open_.columns], open_.shape),
            index=open_.index, columns=open_.columns,
        )
        for day in open_.index:
            used: set[str] = set()
            picked = 0
            codes = score.loc[day].dropna().index.tolist()
            codes.sort(key=lambda code: (-score.at[day, code], str(code)))
            for code in codes:
                if not groups[code]:
                    continue
                if used.intersection(groups[code]):
                    sector_excluded.at[day, code] = True
                    continue
                if picked >= resolved["top_n"]:
                    quota_full.at[day, code] = True
                    continue
                picked += 1
                used.update(groups[code])
                selected.at[day, code] = True
                selected_rank.at[day, code] = picked

        return SignalResult(signals=selected, factors={
            "score": score,
            "低位分(20)": low_score.where(opening_candidates).round(4),
            "临近均线分(20)": ma_score.where(opening_candidates).round(4),
            "趋势分(30)": trend_score.where(opening_candidates).round(4),
            "支撑分(30)": support_score.where(opening_candidates).round(4),
            "开盘质量总分": quality_score.where(opening_candidates).round(4),
            "最低评分合格": score_ok,
            "大阳实体保留比例": body_retained.where(opening_candidates).round(6),
            "大涨前弱趋势": weak_before_rally.fillna(False).astype(bool),
            "当前弱趋势": weak_current.fillna(False).astype(bool),
            "大阳实体失守": (previous_close.lt(anchor_open) | open_.lt(anchor_open)).fillna(False).astype(bool),
            "区间位置": position.where(candidates).round(6),
            "位置区间最低价": window_low.where(candidates),
            "位置区间最高价": window_high.where(candidates),
            "最近均线周期": best_period.where(candidates),
            "最近均线价格": best_ma.where(candidates).round(6),
            "均线偏离(%)": (best_distance * 100).where(candidates).round(4),
            "低开幅度(%)": ((open_ / previous_close - 1) * 100).where(candidates).round(4),
            "大涨日涨幅(%)": anchor_gain,
            "倍量阴量比": volume_ratio.round(4),
            "近期累计涨幅(%)": recent_gain,
            "候选名次": candidate_rank,
            "精选名次": selected_rank,
            "条件候选": candidates,
            "基础开盘候选": opening_candidates,
            "历史形态候选": historical_candidates,
            "均线距离合格": ma_distance_ok,
            "历史趋势合格": historical_trend,
            "趋势方向合格": trend_ok,
            "支撑质量合格": support_ok,
            "大涨前MA20": before_rally_ma20.round(6),
            "昨日MA20": prior_ma20.round(6),
            "开盘距最近均线(%)": (best_distance * 100).where(opening_candidates).round(4),
            "大涨前20日均线五日变化(%)": before_rally_change.round(4),
            "20日均线五日变化(%)": prior_change.round(4),
            "大阳实体中点": body_midpoint,
            "昨日守住20日均线": yesterday_ma_support.fillna(False).astype(bool),
            "开盘守住20日均线": opening_ma_support.fillna(False).astype(bool),
            "昨日守住大阳实体中点": yesterday_body_support.fillna(False).astype(bool),
            "开盘守住大阳实体中点": opening_body_support.fillna(False).astype(bool),
            "昨日未跌破大阳低点": yesterday_low_support.fillna(False).astype(bool),
            "行业数据完整": sector_complete,
            "同板块排除": sector_excluded,
            "精选名额已满": quota_full,
            "前日大涨收阳": up_day.fillna(False).astype(bool),
            "昨日收阴": yin_day.fillna(False).astype(bool),
            "昨日倍量": double_volume.fillna(False).astype(bool),
            "今日低开且高于价格门槛": low_open.fillna(False).astype(bool),
            "近期涨幅未超限": recent_ok.fillna(False).astype(bool),
            "有效历史满足": history_ok,
        })


def _a_share_code(code: Any, prefixes: tuple[str, ...]) -> bool:
    value = str(code)
    return len(value) == 6 and value.isascii() and value.isdigit() and value.startswith(prefixes)


register(DoubleYinLowOpenV1())
