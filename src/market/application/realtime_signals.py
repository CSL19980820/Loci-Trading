"""实时策略信号引擎（盘中未定稿信号）。

三条铁律，改这个文件之前先读完：

1. **绝不写行情库 / 研究库。** 不调 ``apply_today_spot``、不请求
   ``board?persist=true``、不落 research run card。整条实时链对 ``market.db``
   与 research 库是**纯读**路径，大屏只消费不生产。

   **这条铁律说的不是「不写任何库」。** ops.db 里的 ``signal_journal``（信号
   日志）与 ``signal_rule_config``（规则阈值）是**用户明确要的功能**，而且属于
   运维事实而非行情事实：整表删光，行情数据一个字节都不会错，丢的只是「我
   昨天收到过什么提醒」「我把涨速阈值调到了几」。把两者混为一谈，下一个人就
   会把这个功能当成违约给删掉——所以这段话必须留在这里。

   落库的**写入点也不在本模块**：引擎保持纯函数（进快照、出信号列表），写
   ``signal_journal`` 发生在 ``api/stream_router.py`` 的 ``_evaluate_once``
   之后；读 ``signal_rule_config`` 走本模块的带缓存访问器 ``rule_settings()``。
2. **每条信号都带 ``provisional: true``。** 盘中 close 每 tick 都在变，CROSS 类
   信号会被下一 tick 抹掉又长出来。消费方必须当「候选」看，不是成交依据。
3. **复权口径统一 ``adjust="none"``。** 面板默认 qfq，而 live 报价是**不复权**的
   成交价。把 qfq 面板和不复权现价接在一起，除权日附近的 MA/MACD 会在接缝处
   出现假金叉——宁可整条链都用不复权，也不要两种口径混算。

数据：``open_market_hot()`` + ``MarketStore.load_panel(adjust="none")`` 取历史日 K
面板。**日 K 当日不变，所以整个交易日只加载一次并缓存复用**；尾部再追加一根
「今日未完成 bar」（来自 live 报价）。

规则表驱动（``RULES`` 注册表），一条规则一个函数，禁 if 丛林。**阈值不写死在
函数体里**：每条规则声明自己的 ``ParamSpec``（默认值 + 合法区间 + 人话标签），
``check(ctx, params)`` 从入参里取。默认值**永远写在代码里**，ops.db 只存被改过
的那几个键——反过来做（首启把默认值灌进库）会把默认值钉死在旧版本上，以后改
默认值、给规则加参数，老用户全都吃不到。

去抖语义抄 ``ops/application/alert_rules.py:120 _can_trigger``，但 key 里**必须
带租户**：行情是全局共享事实，「谁已经被提醒过」却是私人事实。同 (租户, code,
rule, 交易日) 只报一次；标记为可重复的规则再叠一层 cooldown。去抖全部内存实现
（重启即失忆）；**落库那一层另有一道确定性主键去重**，两者互不替代，见
``src/ops/infrastructure/store_signals.signal_dedup_id``。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
import logging
import math
import threading
import time
from typing import Any, Callable, Mapping

import pandas as pd

from src.formula.domain.functions import CROSS, HHV, MA
from src.formula.domain.indicators import MACD_DEA, MACD_DIF
from src.shared.tenancy import current_tenant

logger = logging.getLogger(__name__)

#: 可重复规则上，同一 (code, rule) 的最小间隔。
DEFAULT_COOLDOWN_SECONDS = 300.0
#: 面板回溯的自然日数：够 MACD(26,9) 稳定下来（≈130 根日 K）。
HISTORY_CALENDAR_DAYS = 200
#: 涨速自算时允许的最大采样间隔；超过就认为两笔之间断过，不给涨速。
SPEED_WINDOW_SECONDS = 120.0
#: 整条实时链的复权口径。见模块 docstring 第 3 条。
LIVE_ADJUST = "none"
#: 去抖表的条目上限。行情是全局共享事实，但「谁已经被提醒过」是私人事实，
#: 所以 key 里带租户；租户一多，条目数就是 租户 x 代码 x 规则。超出上限按写入
#: 顺序丢最旧的，最坏情况只是某条信号被重复报一次，不会串味也不会撑爆内存。
MAX_FIRED_KEYS = 50_000

#: 规则配置缓存的存活秒数。``evaluate()`` 是每 tick 跑的热路径，每次开一次
#: ops.db 连接去读 6 行配置是不可接受的开销。
#:
#: 为什么有了 PUT 主动失效还要 TTL：失效只对**本进程**有效。桌面端与服务端
#: 可能是两个进程（甚至两台机器共享一份库），别的进程改了配置，这里只能靠
#: TTL 兜底。30 秒是折中：调一次阈值最多等半分钟生效，而热路径上每租户每
#: 30 秒才多一次 6 行的查询。
RULE_CONFIG_TTL_SECONDS = 30.0


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


def _rule_ma_golden_cross(ctx: RuleContext, params: Mapping[str, float]) -> str | None:
    fast_n, slow_n = int(params["fast"]), int(params["slow"])
    fast, slow = MA(ctx.close, fast_n), MA(ctx.close, slow_n)
    if not bool(CROSS(fast, slow).iloc[-1]):
        return None
    return (
        f"MA{fast_n} {fast.iloc[-1]:.2f} 上穿 MA{slow_n} {slow.iloc[-1]:.2f}；末根是今日未完成 bar"
    )


def _rule_macd_golden_cross(ctx: RuleContext, params: Mapping[str, float]) -> str | None:
    fast_n, slow_n = int(params["fast"]), int(params["slow"])
    signal_n = int(params["signal"])
    dif = MACD_DIF(ctx.close, fast_n, slow_n)
    dea = MACD_DEA(ctx.close, fast_n, slow_n, signal_n)
    if not bool(CROSS(dif, dea).iloc[-1]):
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


@dataclass(frozen=True)
class RuleSetting:
    """ops.db 里**被改过的**那一行。``params`` 只含覆盖键，不含默认值。"""

    rule_id: str
    enabled: bool
    params: dict[str, float]
    updated_at: str = ""


_CONFIG_LOCK = threading.Lock()
#: tenant -> (取到的时刻, 该租户的覆盖表)。
_CONFIG_CACHE: dict[str, tuple[float, dict[str, RuleSetting]]] = {}


def load_rule_settings(tenant: str) -> dict[str, RuleSetting]:
    """从 ops.db 读本租户的规则覆盖。**没有行 = 全部用代码里的默认值**。"""
    from src.ops import OpsStore

    with OpsStore() as store:
        rows = store.list_signal_rule_config(tenant=tenant)
    out: dict[str, RuleSetting] = dict()
    for row in rows:
        rule_id = str(row.get("rule_id") or "")
        if rule_id not in RULES_BY_ID:
            # 规则已从注册表里删掉，配置行留着不管：它不影响任何现存规则，而
            # 主动删除会让「回滚一个版本」丢掉用户改过的阈值。
            continue
        raw = row.get("params")
        out[rule_id] = RuleSetting(
            rule_id=rule_id,
            enabled=bool(row.get("enabled", True)),
            params=dict(raw) if isinstance(raw, dict) else {},
            updated_at=str(row.get("updated_at") or ""),
        )
    return out


def rule_settings(
    tenant: str,
    *,
    loader: Callable[[str], dict[str, RuleSetting]] | None = None,
    now: float | None = None,
) -> dict[str, RuleSetting]:
    """带缓存的配置读取。热路径（每 tick）走这里，别直接 ``load_rule_settings``。"""
    stamp = time.monotonic() if now is None else float(now)
    with _CONFIG_LOCK:
        cached = _CONFIG_CACHE.get(tenant)
        if cached is not None and (stamp - cached[0]) < RULE_CONFIG_TTL_SECONDS:
            return cached[1]
    fetch = loader or load_rule_settings
    try:
        settings = fetch(tenant)
    except Exception as exc:
        # 读不到配置时**沿用上一份已知good**，而不是回落「全部默认」：后者会让
        # 用户刚停用的规则在库抖一下之后又开始推送，比少刷新一次糟得多。
        previous = cached[1] if cached is not None else dict()
        logger.warning("实时信号规则配置读取失败，沿用上一份（%d 条）：%s", len(previous), exc)
        settings = previous
    with _CONFIG_LOCK:
        _CONFIG_CACHE[tenant] = (stamp, settings)
    return settings


def invalidate_rule_settings(tenant: str | None = None) -> None:
    """PUT 之后必须调它，否则改完阈值最多要等一个 TTL 才生效。

    不传租户 = 全清（测试、换库、以及「不确定改的是谁」时的安全选择）。
    """
    with _CONFIG_LOCK:
        if tenant is None:
            _CONFIG_CACHE.clear()
        else:
            _CONFIG_CACHE.pop(tenant, None)


def rule_view(rule: Rule, setting: RuleSetting | None) -> dict[str, Any]:
    """一条规则的对外形状：默认值、当前生效值、被改过的键，三者都给。

    只给「当前生效值」是不够的——前端要能显示「这个值是你改的，点这里恢复默认」，
    就必须同时看到 ``defaults`` 与 ``overrides``。
    """
    overrides = dict(setting.params) if setting is not None else {}
    resolved = rule.resolve(overrides)
    return {
        "rule_id": rule.id,
        "label": rule.label,
        "description": rule.description,
        "enabled": bool(setting.enabled) if setting is not None else True,
        "repeatable": rule.repeatable,
        "direction": rule.direction,
        "strength": rule.strength,
        "min_bars": rule.bars_needed(resolved),
        "params": resolved,
        "defaults": rule.defaults,
        "overrides": overrides,
        "param_specs": [spec.to_dict() for spec in rule.params],
        "updated_at": setting.updated_at if setting is not None else "",
        "customized": setting is not None,
    }


def rule_catalog(settings: Mapping[str, RuleSetting] | None = None) -> list[dict[str, Any]]:
    """整张规则表的对外形状，顺序 = 注册表顺序（前端不必自己排）。"""
    table = dict(settings or {})
    return [rule_view(rule, table.get(rule.id)) for rule in RULES]


PanelLoader = Callable[[list[str]], dict[str, pd.DataFrame]]
SettingsLoader = Callable[[str], dict[str, RuleSetting]]


def default_panel_loader(codes: list[str]) -> dict[str, pd.DataFrame]:
    """热库日 K 面板，**``adjust="none"``**（见模块 docstring 第 3 条）。"""
    from src.market.infrastructure.store_hot import open_market_hot

    start = (date.today() - timedelta(days=HISTORY_CALENDAR_DAYS)).isoformat()
    with open_market_hot() as store:
        return store.load_panel(
            fields=("high", "low", "close", "volume"),
            codes=list(codes),
            start=start,
            adjust=LIVE_ADJUST,
        )


def _tail_series(frame: pd.DataFrame | None, code: str, day: str, today: float) -> pd.Series:
    """历史列 + 今日未完成 bar。面板若已含今日（收盘后同步过）就用实时值覆盖。"""
    if frame is None or getattr(frame, "empty", True) or code not in frame.columns:
        base = pd.Series(dtype=float)
    else:
        base = frame[code].dropna()
        base = base[base.index != day]
    return pd.concat([base, pd.Series({day: float(today)}, dtype=float)])


def _volume_ratio(row: dict[str, Any], volume: pd.Series) -> float:
    """量比：优先用源给的（东财截面自带「量比」列）。

    缺失时退回「当日累计量 / 近 5 日均量」——盘中它是个**保守下界**（早盘偏小），
    宁可漏报也不要靠猜时间进度去放大分子。
    """
    declared = _num(row.get("volume_ratio"))
    if declared > 0:
        return declared
    if len(volume) < 6:
        return 0.0
    mean5 = float(volume.iloc[-6:-1].mean())
    if not math.isfinite(mean5) or mean5 <= 0:
        return 0.0
    return float(volume.iloc[-1]) / mean5


def _signal_row(
    ctx: RuleContext,
    rule: Rule,
    detail: str,
    moment: datetime,
    cooldown: float,
    params: Mapping[str, float],
) -> dict[str, Any]:
    return {
        "code": ctx.code,
        "name": ctx.name,
        # ``rule`` 是老键（SSE 契约里一直是它），``rule_id`` 是落库与新契约用的名字。
        # 两个都给：改老键会打断已经在跑的前端，多一个键谁都不疼。
        "rule": rule.id,
        "rule_id": rule.id,
        "rule_label": rule.label,
        "title": f"{ctx.name}({ctx.code}) {rule.label}".strip(),
        "direction": rule.direction,
        "strength": rule.strength,
        "trade_date": ctx.trade_date,
        # 与 store_signals.JOURNAL_TIME_FORMAT 同格式。保留策略与排序全靠字符串
        # 比较，换成 ISO8601 会让新行被当成过期行删掉。
        "at": moment.strftime("%Y-%m-%d %H:%M:%S"),
        "price": ctx.price,
        "pct": ctx.pct,
        "detail": detail,
        "bars": ctx.bars,
        # 命中时**实际生效**的阈值。出过一次「用户以为改了、其实缓存没刷」的事故
        # 就知道它值这几个字节：信号自己说清楚它是按哪个阈值命中的。
        "params": dict(params),
        # 盘中未定稿：close 还会变，CROSS 类信号会被下一 tick 抹掉又长出来。
        "provisional": True,
        "adjust": LIVE_ADJUST,
        "source": "live_hub",
        "repeatable": rule.repeatable,
        "cooldown_seconds": cooldown if rule.repeatable else 0.0,
    }


class RealtimeSignalEngine:
    """轻量实时规则引擎。不调重的选股引擎；**自己不写任何库**，只读规则配置。"""

    def __init__(
        self,
        *,
        panel_loader: PanelLoader | None = None,
        cooldown_seconds: float = DEFAULT_COOLDOWN_SECONDS,
        rules: tuple[Rule, ...] = RULES,
        settings_loader: SettingsLoader | None = None,
    ) -> None:
        self._loader = panel_loader or default_panel_loader
        self._cooldown = float(cooldown_seconds)
        self._rules = tuple(rules)
        #: 默认走模块级带缓存的访问器；测试注入纯函数即可，不必开库。
        self._settings = settings_loader or rule_settings
        self._lock = threading.Lock()
        self._panel: dict[str, pd.DataFrame] = dict()
        self._panel_day: str = ""
        self._panel_codes: frozenset[str] = frozenset()
        #: key = (租户, 代码, 规则, 交易日)。少了第一维，A 命中一条不可重复规则后
        #: B 当天就永远收不到同一条信号，而且没有任何提示。
        self._fired: dict[tuple[str, str, str, str], float] = dict()
        self._fired_day: str = ""
        self._ticks: dict[str, tuple[float, float]] = dict()
        self._loads = 0

    def evaluate(
        self, rows: list[dict[str, Any]], *, now: datetime | None = None
    ) -> list[dict[str, Any]]:
        """对一批 live 报价跑全部**启用中**的规则，返回本轮新命中的信号。"""
        moment = now or datetime.now()
        day = moment.strftime("%Y-%m-%d")
        stamp = moment.timestamp()
        # 谁已经被提醒过是**私人事实**：同一条行情，A 收过不代表 B 收过。
        # 规则开关与阈值同理，所以配置也按租户读。
        tenant = current_tenant()
        quotes = [row for row in rows or [] if str(row.get("code") or "").strip()]
        if not quotes:
            return []
        settings = self._resolve_settings(tenant)
        panel = self._ensure_panel([str(row["code"]).strip() for row in quotes], day)
        out: list[dict[str, Any]] = []
        for row in quotes:
            ctx = self._context(row, panel, day=day, stamp=stamp)
            if ctx is None:
                continue
            out.extend(
                self._fire_rules(
                    ctx,
                    day=day,
                    stamp=stamp,
                    moment=moment,
                    tenant=tenant,
                    settings=settings,
                )
            )
        return out

    def _resolve_settings(self, tenant: str) -> dict[str, RuleSetting]:
        """配置读不到时按「全部默认、全部启用」跑，绝不因为配置炸掉整轮行情。"""
        try:
            return dict(self._settings(tenant) or {})
        except Exception as exc:
            logger.warning("实时信号规则配置不可用，本轮全部按默认值跑：%s", exc)
            return {}

    def _fire_rules(
        self,
        ctx: RuleContext,
        *,
        day: str,
        stamp: float,
        moment: datetime,
        tenant: str,
        settings: Mapping[str, RuleSetting],
    ) -> list[dict[str, Any]]:
        hits: list[dict[str, Any]] = []
        for rule in self._rules:
            setting = settings.get(rule.id)
            if setting is not None and not setting.enabled:
                # 停用：**直接跳过**。不算指标、不占去抖位，于是重新启用的当天
                # 不会因为「今天已经报过了」而继续静默。
                continue
            params = rule.resolve(setting.params if setting is not None else None)
            if ctx.bars < rule.bars_needed(params):
                continue
            if not self._can_fire(tenant, ctx.code, rule, day, stamp):
                continue
            try:
                detail = rule.check(ctx, params)
            except Exception as exc:  # 单条规则炸掉不许带走整轮
                logger.warning("实时规则 %s 在 %s 上失败：%s", rule.id, ctx.code, exc)
                continue
            if not detail:
                continue
            self._remember((tenant, ctx.code, rule.id, day), stamp, day)
            hits.append(_signal_row(ctx, rule, detail, moment, self._cooldown, params))
        return hits

    def _remember(self, key: tuple[str, str, str, str], stamp: float, day: str) -> None:
        """记一笔已提醒。顺手换日清理 + 兜住内存上限。"""
        with self._lock:
            if self._fired_day != day:
                # 换日：昨天的去抖状态一律作废，别让它按租户堆一辈子。
                self._fired = {k: v for k, v in self._fired.items() if k[3] == day}
                self._fired_day = day
            overflow = len(self._fired) + 1 - MAX_FIRED_KEYS
            if overflow > 0:
                for stale in list(self._fired)[:overflow]:
                    self._fired.pop(stale, None)
            self._fired[key] = stamp

    def _can_fire(self, tenant: str, code: str, rule: Rule, day: str, stamp: float) -> bool:
        """同 (租户, code, rule, 交易日) 只报一次；可重复规则再叠 cooldown。"""
        with self._lock:
            last = self._fired.get((tenant, code, rule.id, day))
        if last is None:
            return True
        if not rule.repeatable:
            return False
        return (stamp - last) >= self._cooldown

    def _ensure_panel(self, codes: list[str], day: str) -> dict[str, pd.DataFrame]:
        """日 K 当日不变：同一交易日、同一批代码只加载一次。"""
        wanted = frozenset(codes)
        with self._lock:
            if self._panel_day == day and wanted <= self._panel_codes:
                return self._panel
            merged = wanted | (self._panel_codes if self._panel_day == day else frozenset())
        try:
            panel = self._loader(sorted(merged))
        except Exception as exc:
            logger.warning("实时信号面板加载失败，本轮只跑不需历史的规则：%s", exc)
            panel, merged = dict(), frozenset()
        with self._lock:
            self._panel, self._panel_day, self._panel_codes = panel, day, merged
            self._loads += 1
        return panel

    def _context(
        self, row: dict[str, Any], panel: dict[str, pd.DataFrame], *, day: str, stamp: float
    ) -> RuleContext | None:
        code = str(row.get("code") or "").strip()
        price = _num(row.get("price"))
        if not code or price <= 0:
            return None
        name = str(row.get("name") or "")
        prev_close = _num(row.get("prev_close"), price) or price
        volume_series = _tail_series(panel.get("volume"), code, day, _num(row.get("volume")))
        return RuleContext(
            code=code,
            name=name,
            trade_date=day,
            price=price,
            high=_num(row.get("high"), price) or price,
            low=_num(row.get("low"), price) or price,
            prev_close=prev_close,
            pct=_num(row.get("pct")),
            limit_up=limit_up_price(code, name, prev_close),
            speed=self._speed(code, price, stamp, row),
            volume_ratio=_volume_ratio(row, volume_series),
            close=_tail_series(panel.get("close"), code, day, price),
            volume=volume_series,
        )

    def _speed(self, code: str, price: float, stamp: float, row: dict[str, Any]) -> float:
        """涨速：优先用源给的（东财截面自带「涨速」列），否则用相邻两次采样自算。"""
        declared = _num(row.get("speed"))
        with self._lock:
            previous = self._ticks.get(code)
            self._ticks[code] = (stamp, price)
        if declared:
            return declared
        if previous is None:
            return 0.0
        last_stamp, last_price = previous
        if last_price <= 0 or (stamp - last_stamp) > SPEED_WINDOW_SECONDS:
            return 0.0
        return (price - last_price) / last_price * 100.0

    def reset(self) -> None:
        """清空去抖状态与面板缓存（换日 / 测试用）。"""
        with self._lock:
            self._fired.clear()
            self._fired_day = ""
            self._ticks.clear()
            self._panel, self._panel_day, self._panel_codes = {}, "", frozenset()

    def stats(self) -> dict[str, Any]:
        with _CONFIG_LOCK:
            cached_tenants = len(_CONFIG_CACHE)
        with self._lock:
            return {
                "rules": [
                    {
                        "id": r.id,
                        "label": r.label,
                        "description": r.description,
                        "direction": r.direction,
                        "repeatable": r.repeatable,
                        "defaults": r.defaults,
                    }
                    for r in self._rules
                ],
                "fired_keys": len(self._fired),
                "fired_tenants": len({key[0] for key in self._fired}),
                "fired_day": self._fired_day,
                "max_fired_keys": MAX_FIRED_KEYS,
                "panel_day": self._panel_day,
                "panel_codes": len(self._panel_codes),
                "panel_loads": self._loads,
                "cooldown_seconds": self._cooldown,
                "adjust": LIVE_ADJUST,
                "rule_config_ttl_seconds": RULE_CONFIG_TTL_SECONDS,
                "rule_config_cached_tenants": cached_tenants,
            }


_ENGINE_LOCK = threading.Lock()
_ENGINE: RealtimeSignalEngine | None = None


def get_signal_engine() -> RealtimeSignalEngine:
    """进程级单例：去抖状态与面板缓存必须跨请求共享，否则去抖形同虚设。"""
    global _ENGINE
    with _ENGINE_LOCK:
        if _ENGINE is None:
            _ENGINE = RealtimeSignalEngine()
        return _ENGINE


def reset_signal_engine() -> None:
    """丢掉单例。**顺手清规则配置缓存**——测试换了库还留着上一份配置最难查。"""
    global _ENGINE
    with _ENGINE_LOCK:
        _ENGINE = None
    invalidate_rule_settings()


__all__ = [
    "DEFAULT_COOLDOWN_SECONDS",
    "LIVE_ADJUST",
    "MAX_FIRED_KEYS",
    "RULES",
    "RULES_BY_ID",
    "RULE_CONFIG_TTL_SECONDS",
    "ParamSpec",
    "RealtimeSignalEngine",
    "Rule",
    "RuleContext",
    "RuleParamError",
    "RuleSetting",
    "default_panel_loader",
    "get_signal_engine",
    "invalidate_rule_settings",
    "limit_up_price",
    "load_rule_settings",
    "reset_signal_engine",
    "rule_catalog",
    "rule_settings",
    "rule_view",
]
