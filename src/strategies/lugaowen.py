"""卢高文六个涨停战法：把 lugw_tdx_formulas.md 的通达信公式翻译成向量化信号。

源文件已经把"能量化"和"不能量化"分得很清楚，这里严格照它的边界来：

- **照抄的**：涨停/一字/连板识别、高开区间、不破某价、5 日线、缩量放量、
  筹码集中度与筹码峰突破。
- **按原式近似的**：源文件已经声明"龙头/妖股"只能用近期涨停数与阶段涨幅
  近似，"低位"只能用均线与区间回撤近似。这里保留它的近似方式，不自作
  主张换一套——换了就不是这个战法了。
- **明确不做的**：盘中分时黄线、站稳 20 分钟、尾盘炸板次数。它们属于分时
  规则，日线面板上没有对应数据，硬凑只会得到一个看着能跑、实则无意义的
  信号。

## 共同前提

六个公式都以同一段涨停识别开头（见 src/formula/board.py）。涨跌停幅度
按板块区分：主板 10%、创业板与科创板 20%、北交所 30%、ST 5%。判错幅度
的后果不是精度问题——20cm 的票按 10% 判就永远选不出来。

## 入场时点

全部是 ``next_open``：这些公式用到当日收盘、最高、最低，只有收盘后才能
确定，因此最早只能次日开盘成交。标 ``open`` 就是拿收盘后才知道的信息
去做当日交易。
"""
from __future__ import annotations

from typing import Any

import pandas as pd

from src.formula import (
    ABS,
    BARSLAST,
    COUNT,
    HHV,
    LLV,
    MA,
    MAX,
    MIN,
    REF,
    chip_cost_series,
    limit_ratio_panel,
    limit_up_flags,
)
from src.strategies.base import SignalResult, merge_params, register


class _LugaowenBase:
    """六个战法共享的涨停识别与元数据。"""

    entry_timing = "next_open"

    #: 由调用方注入的证券名称表，用于识别 ST。缺失时按非 ST 处理——
    #: 这会让 ST 股按 10% 判涨停，可能漏选，但不会误选。
    names: dict[str, str] | None = None

    def required_fields(self) -> tuple[str, ...]:
        return ("open", "high", "low", "close", "volume")

    def min_bars(self) -> int:
        return 70

    def _limit_up(self, panels: dict[str, pd.DataFrame]) -> tuple[pd.DataFrame, pd.DataFrame]:
        ratios = limit_ratio_panel(panels["close"], self.names)
        return limit_up_flags(panels["close"], panels["high"], ratios), ratios


class SanwaiYousan(_LugaowenBase):
    """公式 1 · 三外有三：三连板后浅调整不破前板价。"""

    slug = "lugw-sanwai"
    name = "卢高文·三外有三"
    description = "连续三个涨停后调整 2-5 天，不深跌、不破第二板价，回到第三板价附近"

    def default_params(self) -> dict[str, Any]:
        return {
            "adjust_min": 2,       # 调整天数下限
            "adjust_max": 5,       # 调整天数上限
            "stop_ratio": 0.98,    # 调整期最低价不得跌破基准价的比例
            "upper_ratio": 1.08,   # 现价不得高于第三板价的比例
            "strict": False,       # True 时用第三板价而非第二板价作为止损基准
        }

    def compute(self, panels, params=None) -> SignalResult:
        p = merge_params(self, params)
        close, low = panels["close"], panels["low"]
        zt, _ = self._limit_up(panels)

        three = zt & REF(zt, 1).fillna(False) & REF(zt, 2).fillna(False)
        bars = BARSLAST(three)

        # 原式的 REF(C,N) 是"N 根之前的收盘"，N 逐行不同，必须逐列位移。
        third_close = _shift_by(close, bars)
        second_close = _shift_by(close, bars + 1)
        window_low = _rolling_min_by(low, bars.clip(lower=1))

        base = third_close if p["strict"] else second_close
        adjusting = (bars >= p["adjust_min"]) & (bars <= p["adjust_max"])
        holds = window_low >= base * p["stop_ratio"]
        near = (close >= second_close) & (close <= third_close * p["upper_ratio"])

        signals = (adjusting & holds & near).fillna(False)
        return SignalResult(
            signals=signals,
            factors={
                "三连板": three, "距三连板": bars,
                "第三板价": third_close, "第二板价": second_close,
                "调整期最低": window_low,
            },
        )


class TianyiWufeng(_LugaowenBase):
    """公式 2 · 天衣无缝：低位缩量一字板，次日高开 0-3% 不破板价。"""

    slug = "lugw-tianyi"
    name = "卢高文·天衣无缝"
    description = "低位缩量一字涨停，次日高开 0-3% 且不跌破一字板收盘价"

    def default_params(self) -> dict[str, Any]:
        return {
            "low_pos_ratio": 0.80,    # 现价低于 60 日高点的比例
            "low_ma_ratio": 0.95,     # 或低于 60 日均线的比例
            "shrink_ratio": 0.80,     # 一字板成交量相对前一日的上限
            "open_low": 1.0,          # 次日开盘下限（相对一字板收盘）
            "open_high": 1.03,        # 次日开盘上限
            "protect_ratio": 0.98,    # 次日最低不得跌破一字板收盘的比例
        }

    def compute(self, panels, params=None) -> SignalResult:
        p = merge_params(self, params)
        close, open_, high, low = (panels[k] for k in ("close", "open", "high", "low"))
        volume = panels["volume"]
        zt, _ = self._limit_up(panels)

        low_position = (close < HHV(high, 60) * p["low_pos_ratio"]) | (
            close < MA(close, 60) * p["low_ma_ratio"]
        )
        one_word = zt & (high == low) & (volume < REF(volume, 1) * p["shrink_ratio"]) & low_position

        opened_ok = (open_ >= REF(close, 1) * p["open_low"]) & (
            open_ <= REF(close, 1) * p["open_high"]
        )
        protected = low >= REF(close, 1) * p["protect_ratio"]

        signals = (REF(one_word, 1).fillna(False) & opened_ok & protected).fillna(False)
        return SignalResult(
            signals=signals,
            factors={"低位": low_position, "缩量一字": one_word,
                     "高开合规": opened_ok, "守住板价": protected},
        )


class DaobaYangliu(_LugaowenBase):
    """公式 3 · 倒拔杨柳：加速中的龙头高开低走收假阴线，回踩不破 5 日线。"""

    slug = "lugw-daoba"
    name = "卢高文·倒拔杨柳"
    description = "近期强势股涨停次日高开低走收假阴线，带下影无上影，不破 5 日线"

    def default_params(self) -> dict[str, Any]:
        return {
            "leader_limit_ups": 2,   # 近 10 日涨停数下限
            "leader_gain": 1.30,     # 或相对 20 日低点的涨幅倍数
            "open_gap": 1.02,        # 高开幅度下限
            "ma5_ratio": 0.995,      # 最低价相对 5 日线的下限
            "lower_shadow": 1.20,    # 下影长度须为实体的倍数
            "upper_shadow": 0.30,    # 上影长度不得超过实体的倍数
        }

    def compute(self, panels, params=None) -> SignalResult:
        p = merge_params(self, params)
        close, open_, high, low = (panels[k] for k in ("close", "open", "high", "low"))
        zt, _ = self._limit_up(panels)

        leader = (COUNT(zt, 10) >= p["leader_limit_ups"]) | (
            close / LLV(low, 20) > p["leader_gain"]
        )
        fake_yin = (
            REF(zt, 1).fillna(False)
            & (open_ > REF(close, 1) * p["open_gap"])
            & (close < open_)
            & (close > REF(close, 1))
        )
        above_ma5 = low >= MA(close, 5) * p["ma5_ratio"]

        body = ABS(close - open_)
        # DataFrame.combine 会把整列 Series 传给函数，不是逐元素标量——
        # 用 MIN/MAX 做真正的逐元素比较。
        lower = (MIN(close, open_) - low) > body * p["lower_shadow"]
        upper = (high - MAX(close, open_)) < body * p["upper_shadow"]

        signals = (leader & fake_yin & above_ma5 & lower & upper).fillna(False)
        return SignalResult(
            signals=signals,
            factors={"强势股": leader, "假阴线": fake_yin, "守5日线": above_ma5,
                     "有下影": lower, "无上影": upper},
        )


class HaidiLaoyue(_LugaowenBase):
    """公式 4 · 海底捞月：长期下跌后突现涨停，此后不破该涨停价。"""

    slug = "lugw-haidi"
    name = "卢高文·海底捞月"
    description = "长期下跌途中突然一根涨停，之后回踩不破涨停价，在涨停价附近介入"

    def default_params(self) -> dict[str, Any]:
        return {
            "high_ratio": 0.75,   # 涨停前一日相对 60 日高点的上限
            "window_max": 10,     # 涨停后观察窗口上限（交易日）
            "near_low": 0.99,     # 现价相对涨停价的下限
            "near_high": 1.08,    # 现价相对涨停价的上限
            "hold_ratio": 0.98,   # 期间最低价不得跌破涨停价的比例
        }

    def compute(self, panels, params=None) -> SignalResult:
        p = merge_params(self, params)
        close, high, low = panels["close"], panels["high"], panels["low"]
        zt, _ = self._limit_up(panels)

        ma20, ma60 = MA(close, 20), MA(close, 60)
        downtrend = (
            (REF(close, 1) < REF(ma20, 1))
            & (REF(ma20, 1) < REF(ma60, 1))
            & (REF(close, 1) < HHV(high, 60) * p["high_ratio"])
        )
        start = zt & downtrend
        bars = BARSLAST(start)
        base = _shift_by(close, bars)
        window_low = _rolling_min_by(low, bars.clip(lower=1))

        in_window = (bars >= 1) & (bars <= p["window_max"])
        near = (close >= base * p["near_low"]) & (close <= base * p["near_high"])
        holds = window_low >= base * p["hold_ratio"]

        signals = (in_window & near & holds).fillna(False)
        return SignalResult(
            signals=signals,
            factors={"长期下跌": downtrend, "启动涨停": start,
                     "距启动": bars, "涨停价": base, "期间最低": window_low},
        )


class FenshouKuaile(_LugaowenBase):
    """公式 5 · 分手快乐：阴线后大幅高开并封涨停，次日 3% 内试探。"""

    slug = "lugw-fenshou"
    name = "卢高文·分手快乐"
    description = "前一日收阴，次日大幅高开并封上涨停，再次日高开 0-3% 内介入"

    def default_params(self) -> dict[str, Any]:
        return {
            "gap_ratio": 1.02,      # 高开幅度下限
            "open_low": 1.0,
            "open_high": 1.03,
            "protect_ratio": 0.98,
        }

    def compute(self, panels, params=None) -> SignalResult:
        p = merge_params(self, params)
        close, open_, low = panels["close"], panels["open"], panels["low"]
        # 原式此处刻意不区分 ST 与北交所，只按 20cm / 10cm 两档——照抄。
        ratios = limit_ratio_panel(close, None).clip(upper=0.20)
        zt = limit_up_flags(close, panels["high"], ratios)

        pattern = (
            (REF(close, 1) < REF(open_, 1))
            & (open_ > REF(close, 1) * p["gap_ratio"])
            & zt
        )
        opened_ok = (open_ >= REF(close, 1) * p["open_low"]) & (
            open_ <= REF(close, 1) * p["open_high"]
        )
        protected = low >= REF(close, 1) * p["protect_ratio"]

        signals = (BARSLAST(pattern) == 1) & opened_ok & protected
        return SignalResult(
            signals=signals.fillna(False),
            factors={"阴后高开涨停": pattern, "高开合规": opened_ok, "守住启动": protected},
        )


class ChoumaTupo(_LugaowenBase):
    """公式 6 · 筹码低位单峰突破：集中度高的低位筹码被放量突破。"""

    slug = "lugw-chouma"
    name = "卢高文·筹码峰突破"
    description = "低位筹码单峰密集，放量突破筹码峰与 20 日高点"

    def required_fields(self) -> tuple[str, ...]:
        # 筹码分布必须有换手率——没有它就退化成简单直方图，语义完全不同。
        return ("open", "high", "low", "close", "volume", "turnover")

    def min_bars(self) -> int:
        # 筹码是逐日衰减递推的，窗口太短等于只看了最近几天的成交，
        # "低位密集"根本无从谈起。
        return 130

    def default_params(self) -> dict[str, Any]:
        return {
            "concentration": 0.18,  # (COST85-COST15)/COST50 上限，越小越密集
            "low_ratio": 0.75,      # COST50 相对 120 日高点的上限
            "volume_boost": 1.50,   # 放量倍数
            "chip_bins": 100,       # 筹码价格档位数
        }

    def compute(self, panels, params=None) -> SignalResult:
        p = merge_params(self, params)
        close, high, low = panels["close"], panels["high"], panels["low"]
        volume, turnover = panels["volume"], panels["turnover"]

        # 一次递推同时取三个分位，别对同一段行情跑三遍。
        costs = chip_cost_series(
            high, low, close, turnover, (15.0, 50.0, 85.0), bins=int(p["chip_bins"])
        )
        c15, c50, c85 = costs[15.0], costs[50.0], costs[85.0]

        concentrated = ((c85 - c15) / c50) < p["concentration"]
        low_chip = c50 < HHV(high, 120) * p["low_ratio"]
        volume_up = volume > MA(volume, 5) * p["volume_boost"]
        breakout = (close > c85) & (close > REF(HHV(high, 20), 1))

        signals = (concentrated & low_chip & volume_up & breakout).fillna(False)
        return SignalResult(
            signals=signals,
            factors={
                "COST15": c15, "COST50": c50, "COST85": c85,
                "集中度": (c85 - c15) / c50,
                "筹码低位": low_chip, "放量": volume_up, "突破筹码峰": breakout,
            },
        )


# --------------------------------------------------------------------------
# 逐行位移工具
# --------------------------------------------------------------------------

def _shift_by(frame: pd.DataFrame, offsets: pd.DataFrame) -> pd.DataFrame:
    """按逐元素的偏移量取历史值，等价于通达信 ``REF(X, N)`` 中 N 逐行变化。

    通达信允许 REF 的第二参数是变量（如 ``REF(C, BARSLAST(cond))``），
    pandas 的 shift 只接受常量。这里用行号索引一次性取值：把偏移换算成
    绝对行号再做 gather，避免对每个可能的 N 各 shift 一遍。
    """
    import numpy as np

    values = frame.to_numpy(dtype=float)
    steps = offsets.to_numpy(dtype=float)
    rows, cols = values.shape

    row_index = np.arange(rows)[:, None] - steps
    valid = np.isfinite(row_index) & (row_index >= 0)
    safe = np.where(valid, row_index, 0).astype(int)
    gathered = values[safe, np.arange(cols)[None, :]]
    return pd.DataFrame(
        np.where(valid, gathered, np.nan), index=frame.index, columns=frame.columns
    )


def _rolling_min_by(frame: pd.DataFrame, windows: pd.DataFrame) -> pd.DataFrame:
    """按逐元素的窗口长度取最小值，等价于 ``LLV(X, M)`` 中 M 逐行变化。

    实现用前缀式比较：对每个可能的回看步长做一次位移取小，步长上限取
    窗口列的最大值。窗口通常只有几天（战法本身限定调整 2-5 天），
    所以循环次数很少。
    """
    import numpy as np

    steps = windows.to_numpy(dtype=float)
    finite = steps[np.isfinite(steps)]
    max_step = int(np.nanmax(finite)) if finite.size else 0
    max_step = max(0, min(max_step, 250))  # 防御：异常大的窗口不值得展开

    result = frame.copy()
    for step in range(1, max_step + 1):
        shifted = frame.shift(step)
        applies = steps >= step
        result = pd.DataFrame(
            np.where(applies, np.fmin(result.to_numpy(dtype=float), shifted.to_numpy(dtype=float)),
                     result.to_numpy(dtype=float)),
            index=frame.index, columns=frame.columns,
        )
    return result


register(SanwaiYousan())
register(TianyiWufeng())
register(DaobaYangliu())
register(HaidiLaoyue())
register(FenshouKuaile())
register(ChoumaTupo())
