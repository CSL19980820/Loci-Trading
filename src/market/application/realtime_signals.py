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

**这条链拆在三个文件里**（原来是一个 899 行的文件，规则表和引擎的变更频率
完全不同，混在一起谁都不敢改）：

- ``realtime_rules.py`` —— 规则契约、参数规格、六条判定、注册表。**加一条
  规则只该动这里。**
- ``realtime_rule_config.py`` —— ops.db 里的阈值覆盖怎么进内存（读取、TTL
  缓存、对外形状），被 API 路由与引擎两边共用。
- 本文件 —— 引擎调度：面板缓存、去抖、涨速采样、进程单例。

对外契约没变：三个模块的公开符号全部从本模块重导出，``__all__`` 就是那份
清单，调用方不必知道拆过。
"""
from __future__ import annotations

from datetime import date, datetime, timedelta
import logging
import math
import threading
from typing import Any, Callable, Mapping

import numpy as np
import pandas as pd

from src.market.application.realtime_rules import (
  RULES,
    RULES_BY_ID,
    ParamSpec,
    Rule,
    RuleContext,
    RuleParamError,
    _num,
    limit_up_price,
)
from src.market.application.realtime_rule_config import (
    RULE_CONFIG_TTL_SECONDS,
    RuleSetting,
    cached_tenant_count,
    invalidate_rule_settings,
    load_rule_settings,
  rule_catalog,
    rule_settings,
    rule_view,
)
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
    """历史列 + 今日未完成 bar。面板若已含今日（收盘后同步过）就用实时值覆盖。

    返回 **RangeIndex** 序列而不是日期索引：全部规则只按位置取值（``MA`` /
    ``HHV`` / ``CROSS`` / ``.iloc[-1]``），日期索引唯一的作用就是让每次
    ``pd.concat`` 多付一次索引对齐。500 只票每 tick 要走这里 1000 次，实测
    ``concat`` 版本占整轮 ``evaluate`` 的四成。
    """
    column = None if frame is None else frame.get(code)
    if column is None or len(column) == 0:
        return pd.Series([float(today)], dtype="float64")
    values = column.to_numpy(dtype="float64", copy=False)
    # 面板由 pivot(index="trade_date") 产出，按交易日升序；今日只可能落在最后
    # 一格。用位置判断代替 base.index != day 的全表字符串比较。
    if column.index[-1] == day:
        values = values[:-1]
    values = values[~np.isnan(values)]
    out = np.empty(values.size + 1, dtype="float64")
    out[: values.size] = values
    out[values.size] = float(today)
    return pd.Series(out, copy=False)


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
        cached_tenants = cached_tenant_count()
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
