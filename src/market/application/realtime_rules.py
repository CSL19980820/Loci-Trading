"""实时信号的规则表：规则契约、参数规格、六条判定与注册表。

从 ``realtime_signals`` 拆出来的原因是那个文件到了 899 行，而这一段的变更
频率与引擎完全不同——**加一条规则只该动这里**（一个 ``_rule_*`` 函数 + 注册表
里一行），不该让人翻过三百行的引擎实现。

判定函数一律「命中返回 detail 文案、未命中返回 None」，不抛异常、不写库、
不读配置：阈值由引擎解析好后作为 ``params`` 传进来。
"""
from __future__ import annotations

from dataclasses import dataclass, field
import logging
import math
from typing import Any, Callable, Mapping

import pandas as pd

from src.formula.domain.functions import EMA, HHV, MA
from src.formula.domain.indicators import MACD_DIF

logger = logging.getLogger(__name__)



def _num(value: Any, default: float = 0.0) -> float:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return default
    return number if math.isfinite(number) else default


def _round_half_up(value: float, digits: int = 2) -> float:
    """逢五进一。交易所的涨跌停价就是这么取的，而 Python 的 round() 是银行家

    舍入，直接用会让一批票的涨停价差一分钱，「是否临近涨停」跟着判错。
    """
    scale = 10.0**digits
    return math.floor(value * scale + 0.5 + 1e-9) / scale


def limit_up_price(code: str, name: str, prev_close: float) -> float:
    """涨停价。ST 5% / 创业板 · 科创板 20% / 北证 30% / 其余 10%。"""
    if prev_close <= 0:
        return 0.0
    from src.market.domain.universe import classify_board, is_st_name

    if is_st_name(name):
        ratio = 0.05
    else:
        bucket = classify_board(code)
        ratio = {"star": 0.20, "chi_next": 0.20, "bse": 0.30}.get(bucket, 0.10)
    return _round_half_up(prev_close * (1.0 + ratio))


@dataclass(frozen=True)
class RuleContext:
    """一条规则看到的全部输入。序列**已含今日未完成 bar**（尾部最后一根）。"""

    code: str
    name: str
    trade_date: str
    price: float
    high: float
    low: float
    prev_close: float
    pct: float
    limit_up: float
    speed: float
    volume_ratio: float
    close: pd.Series
    volume: pd.Series

    @property
    def bars(self) -> int:
        return int(len(self.close))


class RuleParamError(ValueError):
    """规则参数校验失败。``str(exc)`` 就是给用户看的人话原因，API 直接 400 它。"""


@dataclass(frozen=True)
class ParamSpec:
    """一个可调阈值：默认值 + 合法区间 + 人话标签。

    ``minimum`` / ``maximum`` 都是**闭区间**。要表达「必须为正」就把 minimum 写成
    一个有意义的最小步进（如 0.1），别写 0 再指望调用方自己判——「涨速阈值 0%」
    等于每 tick 都命中，是能把大屏刷爆的配置。
    """

    key: str
    label: str
    default: float
    minimum: float
    maximum: float
    unit: str = ""
    integer: bool = False

    def coerce(self, value: Any) -> float:
        """校验并归一。失败抛 ``RuleParamError``，消息直接给用户看。"""
        if value is None or isinstance(value, bool):
            raise RuleParamError(f"参数 {self.key}（{self.label}）必须是数字，收到 {value!r}")
        try:
            number = float(value)
        except (TypeError, ValueError):
            raise RuleParamError(
                f"参数 {self.key}（{self.label}）必须是数字，收到 {value!r}"
            ) from None
        if not math.isfinite(number):
            raise RuleParamError(f"参数 {self.key}（{self.label}）必须是有限数字")
        if number < self.minimum or number > self.maximum:
            raise RuleParamError(
                f"参数 {self.key}（{self.label}）必须在 {self.minimum} ~ {self.maximum}"
                f"{self.unit} 之间，收到 {number}"
            )
        if self.integer and float(int(number)) != number:
            raise RuleParamError(f"参数 {self.key}（{self.label}）必须是整数，收到 {number}")
        return float(int(number)) if self.integer else float(number)

    def to_dict(self) -> dict[str, Any]:
        return {
            "key": self.key,
            "label": self.label,
            "default": self.default,
            "min": self.minimum,
            "max": self.maximum,
            "unit": self.unit,
            "integer": self.integer,
        }


RuleCheck = Callable[[RuleContext, Mapping[str, float]], "str | None"]


@dataclass(frozen=True)
class Rule:
    """注册表条目。``check(ctx, params)`` 命中返回 detail 文案，未命中返回 None。

    ``description`` 是给**前端直接展示**的人话口径，不是给程序员的注释：用户要在
    设置页看懂「我把这个数字调大会发生什么」。
    """

    id: str
    label: str
    min_bars: int
    repeatable: bool
    check: RuleCheck
    description: str = field(default="", kw_only=True)
    #: 建议动作 "long" / "watch" / "exit"。**词表由消费方钉死**（前端
    #: marketStream.parseSignalItem 只认这三个，别的一律落回 "long"）——用
    #: "bullish"/"bearish" 会让炸板在界面上显示成「买入」，而且不报错。
    #: 它只影响展示，不参与命中判定。
    direction: str = field(default="watch", kw_only=True)
    #: 规则**先验**权重（0~1），用于前端排序与着色。**不是胜率预测**，也不随
    #: 行情变化——盘中未定稿信号本来就没有可信的强度可算。
    strength: float = field(default=0.5, kw_only=True)
    params: tuple[ParamSpec, ...] = field(default=(), kw_only=True)
    #: 参数会改变所需 bar 数时给一个换算（如 slow=60 就得有 61 根）。
    bars_for: Callable[[Mapping[str, float]], int] | None = field(default=None, kw_only=True)
    #: 跨参数校验（如 fast 必须小于 slow）。返回人话原因即视为不合法。
    cross_check: Callable[[Mapping[str, float]], "str | None"] | None = field(
        default=None, kw_only=True
    )

    @property
    def defaults(self) -> dict[str, float]:
        """代码里的默认阈值。**唯一的真相源**，库里只存与它不同的那几个键。"""
        return {spec.key: spec.default for spec in self.params}

    @property
    def specs_by_key(self) -> dict[str, ParamSpec]:
        return {spec.key: spec for spec in self.params}

    def resolve(self, overrides: Mapping[str, Any] | None = None) -> dict[str, float]:
        """默认值 + 覆盖值。**未知键与坏值一律忽略**，不让脏配置炸掉整轮。

        PUT 时已经 400 挡过一次；这里再兜一层，是因为库里可能留着旧版本写下的键
        （那条规则的参数后来改过名）。热路径宁可用默认值，也不能抛异常。
        """
        values = dict(self.defaults)
        specs = self.specs_by_key
        for key, raw in dict(overrides or dict()).items():
            spec = specs.get(str(key))
            if spec is None:
                continue
            try:
                values[spec.key] = spec.coerce(raw)
            except RuleParamError:
                logger.warning("规则 %s 的库内参数 %s=%r 非法，回落默认值", self.id, key, raw)
        return values

    def bars_needed(self, params: Mapping[str, float]) -> int:
        """这套参数需要多少根 bar。参数没动过时就是 ``min_bars``。"""
        if self.bars_for is None:
            return int(self.min_bars)
        try:
            return max(1, int(self.bars_for(params)))
        except Exception:
            return int(self.min_bars)

    def validate(self, raw: Mapping[str, Any]) -> dict[str, float]:
        """PUT 用的严格校验：未知键 / 坏值 / 越界 / 跨参数冲突全部抛人话原因。"""
        specs = self.specs_by_key
        out: dict[str, float] = {}
        for key, value in dict(raw or {}).items():
            name = str(key)
            spec = specs.get(name)
            if spec is None:
                allowed = "、".join(specs) or "（本规则没有可调参数）"
                raise RuleParamError(f"规则「{self.label}」没有参数 {name!r}；可调的是：{allowed}")
            out[name] = spec.coerce(value)
        merged = {**self.defaults, **out}
        if self.cross_check is not None:
            reason = self.cross_check(merged)
            if reason:
                raise RuleParamError(reason)
        return out


def _crossed_now(fast: pd.Series, slow: pd.Series) -> bool:
    """``CROSS(fast, slow).iloc[-1]`` 的标量快路径。

    ``CROSS`` 要为整条序列产出布尔列（内部 4 个中间 Series），而规则只看最后
    一格。NaN 语义与 pandas 一致：任何一边缺值时比较恒为 False。
    与 ``CROSS`` 的等价性由 ``tests/market/test_realtime_signal_internals.py`` 钉死。
    """
    a = fast.to_numpy(dtype="float64", copy=False)
    b = slow.to_numpy(dtype="float64", copy=False)
    if a.size < 2 or b.size < 2:
        return False
    return bool(a[-1] > b[-1] and a[-2] <= b[-2])


def _rule_ma_golden_cross(ctx: RuleContext, params: Mapping[str, float]) -> str | None:
    fast_n, slow_n = int(params["fast"]), int(params["slow"])
    fast, slow = MA(ctx.close, fast_n), MA(ctx.close, slow_n)
    if not _crossed_now(fast, slow):
        return None
    return (
        f"MA{fast_n} {fast.iloc[-1]:.2f} 上穿 MA{slow_n} {slow.iloc[-1]:.2f}；末根是今日未完成 bar"
    )


def _rule_macd_golden_cross(ctx: RuleContext, params: Mapping[str, float]) -> str | None:
    fast_n, slow_n = int(params["fast"]), int(params["slow"])
    signal_n = int(params["signal"])
    dif = MACD_DIF(ctx.close, fast_n, slow_n)
    # MACD_DEA 的定义就是 EMA(MACD_DIF(...), signal)。直接调它会把上面这两次
    # EMA 原样重算一遍——热路径上每 tick 每票都要走，不能白付。
    dea = EMA(dif, signal_n)
    if not _crossed_now(dif, dea):
        return None
    return f"DIF {dif.iloc[-1]:.3f} 上穿 DEA {dea.iloc[-1]:.3f}；末根是今日未完成 bar"


def _rule_volume_breakout(ctx: RuleContext, params: Mapping[str, float]) -> str | None:
    lookback = int(params["lookback"])
    if ctx.volume_ratio < float(params["volume_ratio"]):
        return None
    prior = float(HHV(ctx.close, lookback).shift(1).iloc[-1])
    if not math.isfinite(prior) or ctx.price <= prior:
        return None
    return f"量比 {ctx.volume_ratio:.2f}，现价 {ctx.price:.2f} 突破前 {lookback} 日高 {prior:.2f}"


def _rule_fast_surge(ctx: RuleContext, params: Mapping[str, float]) -> str | None:
    if ctx.speed < float(params["speed_pct"]):
        return None
    return f"涨速 {ctx.speed:.2f}%（采样窗内），现价 {ctx.price:.2f}"


def _rule_near_limit_up(ctx: RuleContext, params: Mapping[str, float]) -> str | None:
    if ctx.limit_up <= 0 or ctx.price <= 0:
        return None
    gap = (ctx.limit_up - ctx.price) / ctx.limit_up * 100.0
    if gap < 0 or gap >= float(params["gap_pct"]):
        return None
    return f"距涨停 {gap:.2f}%（涨停价 {ctx.limit_up:.2f}，现价 {ctx.price:.2f}）"


def _rule_broken_limit_up(ctx: RuleContext, params: Mapping[str, float]) -> str | None:
    """炸板：今日最高摸到过涨停，但现价已经打开。"""
    tolerance = float(params["tolerance"])
    if ctx.limit_up <= 0 or ctx.high <= 0:
        return None
    if ctx.high < ctx.limit_up - tolerance or ctx.price >= ctx.limit_up - tolerance:
        return None
    return f"曾封板（最高 {ctx.high:.2f} 达涨停 {ctx.limit_up:.2f}），现价回落至 {ctx.price:.2f}"


def _fast_slow_order(params: Mapping[str, float]) -> str | None:
    """快线必须短于慢线，否则「金叉」这个词没有意义（会变成永久空转）。"""
    if int(params["fast"]) >= int(params["slow"]):
        return (
            f"快线周期 fast={int(params['fast'])} 必须小于慢线周期"
            f" slow={int(params['slow'])}，否则「金叉」没有意义"
        )
    return None


#: 规则注册表。加规则只在这里加一行 + 一个函数，不要往引擎里塞 if。
#: 每条规则的默认阈值就在这张表里——**库里只存被改过的键**，见模块 docstring。
RULES: tuple[Rule, ...] = (
    Rule(
        "ma_golden_cross",
        "均线金叉",
        21,
        False,
        _rule_ma_golden_cross,
        description="MA5 上穿 MA20，末根为今日未完成 bar（盘中会反复抹去重生，只作候选）",
        direction="long",
        strength=0.5,
        params=(
            ParamSpec("fast", "快线周期", 5, 2, 120, unit=" 日", integer=True),
            ParamSpec("slow", "慢线周期", 20, 3, 250, unit=" 日", integer=True),
        ),
        bars_for=lambda p: int(p["slow"]) + 1,
        cross_check=_fast_slow_order,
    ),
    Rule(
        "macd_golden_cross",
        "MACD 金叉",
        35,
        False,
        _rule_macd_golden_cross,
        description="DIF 上穿 DEA（MACD 金叉），末根为今日未完成 bar",
        direction="long",
        strength=0.55,
        params=(
            ParamSpec("fast", "快线 EMA", 12, 2, 120, unit=" 日", integer=True),
            ParamSpec("slow", "慢线 EMA", 26, 3, 250, unit=" 日", integer=True),
            ParamSpec("signal", "信号线", 9, 2, 120, unit=" 日", integer=True),
        ),
        bars_for=lambda p: int(p["slow"]) + int(p["signal"]),
        cross_check=_fast_slow_order,
    ),
    Rule(
        "volume_breakout",
        "放量突破",
        21,
        False,
        _rule_volume_breakout,
        description="量比达到阈值，且现价突破前 20 日的最高收盘价",
        direction="long",
        strength=0.65,
        params=(
            ParamSpec("volume_ratio", "量比阈值", 2.0, 0.1, 50.0),
            ParamSpec("lookback", "回看天数", 20, 2, 250, unit=" 日", integer=True),
        ),
        bars_for=lambda p: int(p["lookback"]) + 1,
    ),
    Rule(
        "fast_surge",
        "快速拉升",
        1,
        True,
        _rule_fast_surge,
        description="两次采样之间涨速超过阈值（源自带涨速优先，否则用相邻两笔自算）",
        direction="watch",
        strength=0.6,
        params=(ParamSpec("speed_pct", "涨速阈值", 2.0, 0.1, 20.0, unit="%"),),
    ),
    Rule(
        "near_limit_up",
        "临近涨停",
        1,
        True,
        _rule_near_limit_up,
        description="现价距涨停价不足 1%，但还没封上（已封板不报）",
        direction="watch",
        strength=0.7,
        params=(ParamSpec("gap_pct", "距涨停幅度", 1.0, 0.1, 10.0, unit="%"),),
    ),
    Rule(
        "broken_limit_up",
        "炸板",
        1,
        False,
        _rule_broken_limit_up,
        description="今日最高价摸到过涨停，现价已经打开（炸板）",
        direction="exit",
        strength=0.6,
        params=(ParamSpec("tolerance", "封板容差", 0.005, 0.0, 1.0, unit=" 元"),),
    ),
)
RULES_BY_ID: dict[str, Rule] = {rule.id: rule for rule in RULES}
