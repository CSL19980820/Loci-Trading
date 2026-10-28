"""首波上涨后的 D2 回调选股战法。"""
from __future__ import annotations

from typing import Any

import numpy as np
import pandas as pd

from src.strategy.application.execution_profile import ExecutionProfile
from src.strategy.application.first_wave_pullback import (
    FirstWaveConfig,
    _detect_first_waves_panel,
    price_resonance_mainline,
)
from src.strategy.domain.base import SignalResult, StrategyError, merge_params, register


def _potential_wave_columns(
    close: np.ndarray, volume: np.ndarray, config: FirstWaveConfig,
) -> np.ndarray:
    """Keep only stocks that could have a completed D1 and an available D2.

    Every setup_ready wave has a lower D1 close, a D0 volume at least twice
    its predecessor's, and a D1/D0 volume ratio within the adjustment limit.
    The full detector still decides which of these possibilities is a wave.
    """
    with np.errstate(divide="ignore", invalid="ignore", over="ignore"):
        possible = (
            (close[2:-1] < close[1:-2])
            & (volume[1:-2] / volume[:-3] >= config.terminal_volume_min)
            & (volume[2:-1] / volume[1:-2] <= config.adjustment_volume_max + 1e-12)
        )
    return np.flatnonzero(possible.any(axis=0))


class FirstWavePullbackV1:
    slug = "first-wave-pullback-v1"
    name = "首波回调 D2 买点"
    description = (
        "识别平台突破后的首波上涨，要求涨幅20%至60%、斜率和量能达标；"
        "D1 首次调整缩量，D2 守住动态MA5，并通过价格共振主线代理。"
    )
    entry_instructions = (
        "盘后日线回填使用 D2 收盘作为 MA5 守线确认，D2 首批计划买入。"
        "严格14:50报价成交和D3盘中加仓需要报价回放入口；本战法的候选池只负责识别并留存D2信号。"
        "首波从启动前20日平台突破开始，涨幅20%至60%，对数价格日涨速至少1%，"
        "上涨均量为平台均量1.2至2.5倍，D0成交量至少为前一日2倍，D1成交量不超过D0的2/3。"
        "D2动态MA5由前四个调整收盘与D2收盘构成；主线默认使用历史价格共振代理，"
        "不使用今天的行业名称替代历史题材证据。"
    )
    # 首波识别需要当日已完成的 OHLC；系统通用回测因此按次日开盘成交。
    # D2 14:50 的真实成交由独立报价回放负责，不冒充日线收盘入场。
    entry_timing = "next_open"
    adjust = "hfq"
    execution_adjust = "hfq"
    strategy_revision = "builtin:first-wave-pullback-v1:1.1"
    version = "v1"
    version_history = [{"version": "v1", "status": "active", "source": "builtin"}]
    default_universe = {"preset": "default_a_share"}
    screen_rank_factor = "score"
    screen_default_top_n = 0
    screen_managed_job = False
    # The engine is prefix-causal: one range computation yields the same signal
    # and factor rows as independently truncating every requested trade date.
    range_prime_enabled = True
    # Screening only needs the bounded source/coverage projection. Full receipt
    # and attempt detail remains available through the research entry points.
    source_evidence_summary = True
    warmup_bars = 80

    def default_params(self) -> dict[str, Any]:
        return {"mainline_mode": "price_resonance_proxy"}

    def _params(self, params: dict[str, Any] | None) -> dict[str, Any]:
        resolved = merge_params(self, params)
        mode = str(resolved["mainline_mode"]).strip()
        if mode not in {"price_resonance_proxy", "none"}:
            raise StrategyError("mainline_mode 只能是 price_resonance_proxy 或 none")
        return {"mainline_mode": mode}

    def required_fields(self) -> tuple[str, ...]:
        return ("open", "high", "low", "close", "volume")

    def min_bars(self) -> int:
        return 60

    def history_bars(self, params: dict[str, Any] | None = None) -> int:
        self._params(params)
        return self.warmup_bars

    def execution_profile(self, params: dict[str, Any] | None = None) -> ExecutionProfile:
        return ExecutionProfile(
            pure=True,
            causal=True,
            column_mode="coupled",
            origin="finite",
            lookback_bars=self.history_bars(params),
        )

    @staticmethod
    def _empty_factors(index: pd.Index, columns: pd.Index) -> dict[str, pd.DataFrame]:
        names = (
            "score", "首波涨幅", "首波斜率", "上涨均量比", "D0倍量比", "D1缩量比",
            "D2动态MA5", "D2收盘与MA5差", "主线平均相关性", "主线邻居数",
            "主线5日超额", "主线10日超额", "主线上涨广度", "主线量比",
            "主线持续天数", "D0距当前交易日", "D1距当前交易日", "启动距当前交易日",
            "首波条件通过", "主线条件通过", "D2守住MA5",
        )
        return {
            name: pd.DataFrame(np.nan, index=index, columns=columns, dtype=float)
            for name in names
        }

    @staticmethod
    def _set(factors: dict[str, pd.DataFrame], name: str, day: str, code: str, value: Any) -> None:
        if value is None:
            return
        try:
            number = float(value)
        except (TypeError, ValueError):
            return
        if np.isfinite(number):
            factors[name].at[day, code] = number

    def compute(
        self,
        panels: dict[str, pd.DataFrame],
        params: dict[str, Any] | None = None,
    ) -> SignalResult:
        resolved = self._params(params)
        for field in self.required_fields():
            if not isinstance(panels.get(field), pd.DataFrame):
                raise StrategyError(f"首波回调缺少行情字段：{field}")

        close = panels["close"]
        if not close.index.is_unique or not close.columns.is_unique:
            raise StrategyError("首波回调需要唯一的交易日和证券代码")
        frames = {
            field: panels[field].reindex(index=close.index, columns=close.columns)
            for field in self.required_fields()
        }
        index = close.index
        columns = close.columns
        selected = pd.DataFrame(False, index=index, columns=columns)
        factors = self._empty_factors(index, columns)
        code_list = [str(code) for code in columns]
        index_positions = {str(day): position for position, day in enumerate(index)}
        # Preserve the original numeric input check even though open is not used in detection.
        frames["open"].to_numpy(dtype=float)
        adjusted_close = close.to_numpy(dtype=float)
        volume_panel = frames["volume"].to_numpy(dtype=float)
        high_panel = frames["high"].to_numpy(dtype=float)
        low_panel = frames["low"].to_numpy(dtype=float)
        config = FirstWaveConfig()

        positions = _potential_wave_columns(adjusted_close, volume_panel, config)
        for column_position, waves in _detect_first_waves_panel(
            adjusted_close, high_panel, low_panel, volume_panel, index, code_list, positions, config,
        ):
            code = code_list[column_position]
            for wave in waves:
                if wave.get("status") != "setup_ready":
                    continue
                d2 = str(wave.get("d2_date") or "")
                d1 = str(wave.get("d1_date") or "")
                d0 = str(wave.get("d0_date") or "")
                start = str(wave.get("start_date") or "")
                if d2 not in index_positions or d1 not in index_positions or d0 not in index_positions:
                    continue
                d2_position = index_positions[d2]
                if d2_position < 4:
                    continue
                prior = close.iloc[d2_position - 4:d2_position, column_position].to_numpy(dtype=float)
                current = float(close.iloc[d2_position, column_position])
                if not np.isfinite(prior).all() or not np.isfinite(current):
                    continue
                dynamic_ma5 = (float(prior.sum()) + current) / 5.0
                if current < dynamic_ma5:
                    continue

                mainline: dict[str, Any] = {"passed": True, "reason": "not_required"}
                if resolved["mainline_mode"] == "price_resonance_proxy":
                    mainline = price_resonance_mainline(
                        adjusted_close,
                        volume_panel,
                        target=column_position,
                        asof=d2_position,
                        codes=code_list,
                    )
                    if not mainline.get("passed"):
                        continue

                selected.at[d2, code] = True
                self._set(factors, "首波涨幅", d2, code, wave.get("wave_gain", np.nan) * 100)
                self._set(factors, "首波斜率", d2, code, wave.get("slope_daily", np.nan) * 100)
                self._set(factors, "上涨均量比", d2, code, wave.get("wave_volume_ratio"))
                self._set(factors, "D0倍量比", d2, code, wave.get("terminal_volume_ratio"))
                self._set(factors, "D1缩量比", d2, code, wave.get("adjustment_volume_ratio"))
                self._set(factors, "D2动态MA5", d2, code, dynamic_ma5)
                self._set(factors, "D2收盘与MA5差", d2, code, (current / dynamic_ma5 - 1) * 100)
                self._set(factors, "主线平均相关性", d2, code, mainline.get("mean_correlation"))
                self._set(factors, "主线邻居数", d2, code, mainline.get("peer_count", 0))
                self._set(factors, "主线5日超额", d2, code, mainline.get("excess5", 0) * 100)
                self._set(factors, "主线10日超额", d2, code, mainline.get("excess10", 0) * 100)
                self._set(factors, "主线上涨广度", d2, code, mainline.get("breadth", 0) * 100)
                self._set(factors, "主线量比", d2, code, mainline.get("volume_ratio", 0))
                self._set(factors, "主线持续天数", d2, code, mainline.get("persistence_days", 0))
                self._set(factors, "D0距当前交易日", d2, code, d2_position - index_positions[d0])
                self._set(factors, "D1距当前交易日", d2, code, d2_position - index_positions[d1])
                if start in index_positions:
                    self._set(factors, "启动距当前交易日", d2, code, d2_position - index_positions[start])
                self._set(factors, "首波条件通过", d2, code, 1)
                self._set(factors, "主线条件通过", d2, code, 1)
                self._set(factors, "D2守住MA5", d2, code, 1)
                correlation = float(mainline.get("mean_correlation") or 0.0)
                slope_score = float(wave.get("slope_daily") or 0.0) * 100.0
                self._set(
                    factors,
                    "score",
                    d2,
                    code,
                    max(0.0, min(100.0, correlation * 100.0 if correlation else slope_score)),
                )

        factors["score"] = factors["score"].where(selected)
        return SignalResult(signals=selected, factors=factors)


register(FirstWavePullbackV1())
