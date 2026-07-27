"""策略引擎的统一接口与注册表。

一个策略要能回答四件事：需要哪些行情字段、至少要几根 K 线、参数是什么、
以及给定面板怎么算出信号。有了这层抽象，选股、回测、复盘、前端展示都能
对同一个接口编程，新增战法不必再改四处调用点。

## 入场约定（entry）是策略的一部分，不是回测器的选项

同一套形态条件，"9:25 竞价筛、当日开盘买"和"盘后筛、次日开盘买"是两个
完全不同的策略，收益天差地别。项目此前的手工回测就吃过这个亏：用当日
盘中数据做当日决策，回测收益虚高。所以入场时点必须由策略自己声明，
回测器照着执行，不给调用方"随便选一个"的机会。
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Protocol, runtime_checkable

import pandas as pd


class StrategyError(RuntimeError):
    """策略自身的可预期错误（参数非法、字段缺失等）。"""


#: 入场时点约定。
#: - ``open``  信号当日开盘成交。仅当策略只用到当日开盘价及更早的数据时合法
#:            （典型是 9:25 集合竞价筛选）。
#: - ``close`` 信号当日收盘成交（尾盘 14:50 左右选、收盘价买）。用到当日
#:            收盘价本身是合法的——决策发生在收盘前几分钟，价格已基本定型。
#:            但用到当日**最高/最低**就仍属前视：那要等收盘才确定。
#: - ``next_open`` 信号次日开盘成交。策略用到了当日收盘/最高/最低时最稳妥的
#:            选择，也是盘后选股的默认口径。
ENTRY_TIMINGS = ("open", "close", "next_open")


@dataclass
class SignalResult:
    """一次策略计算的产出。

    factors 不是可选的装饰：选中一只票时必须能回答"因为哪几条成立"，
    否则复盘时无法归因，也无法判断是规则有效还是运气。
    """

    signals: pd.DataFrame
    factors: dict[str, pd.DataFrame] = field(default_factory=dict)

    def picks_on(self, trade_date: str) -> list[str]:
        """取某个交易日选中的代码。"""
        if trade_date not in self.signals.index:
            return []
        row = self.signals.loc[trade_date]
        return sorted(row.index[row.fillna(False).astype(bool)].tolist())

    def explain(self, trade_date: str, code: str) -> dict[str, Any]:
        """某只票在某天各个中间因子的取值，用于"为什么选中/为什么落选"。"""
        out: dict[str, Any] = {}
        for name, panel in self.factors.items():
            if trade_date in panel.index and code in panel.columns:
                value = panel.at[trade_date, code]
                out[name] = None if pd.isna(value) else (
                    bool(value) if isinstance(value, (bool,)) else float(value)
                )
        return out


@runtime_checkable
class StrategyEngine(Protocol):
    """所有战法的统一形状。"""

    slug: str
    name: str
    description: str
    entry_timing: str

    def default_params(self) -> dict[str, Any]:
        """参数默认值。前端的参数表单与回测的调参都读这里。"""
        ...

    def required_fields(self) -> tuple[str, ...]:
        """需要的面板字段，供 load_panel 只取必要列。"""
        ...

    def min_bars(self) -> int:
        """指标窗口填满所需的最少 K 线根数，次新股据此排除。"""
        ...

    def compute(
        self, panels: dict[str, pd.DataFrame], params: dict[str, Any] | None = None
    ) -> SignalResult:
        """对全市场面板算信号。返回的 signals 与输入面板同形。"""
        ...


_REGISTRY: dict[str, StrategyEngine] = {}


def register(engine: StrategyEngine) -> StrategyEngine:
    """注册一个策略。重复注册同一 slug 直接报错，避免静默覆盖。"""
    if engine.slug in _REGISTRY:
        raise StrategyError(f"策略 slug 重复：{engine.slug}")
    _REGISTRY[engine.slug] = engine
    return engine


def get(slug: str) -> StrategyEngine:
    if slug not in _REGISTRY:
        raise StrategyError(f"未注册的策略：{slug}（已注册：{sorted(_REGISTRY)}）")
    return _REGISTRY[slug]


def all_strategies() -> list[StrategyEngine]:
    return [_REGISTRY[slug] for slug in sorted(_REGISTRY)]


def describe_all() -> list[dict[str, Any]]:
    """给 API / 前端策略中心用的元数据列表。"""
    return [
        {
            "slug": engine.slug,
            "name": engine.name,
            "description": engine.description,
            "entry_timing": engine.entry_timing,
            "required_fields": list(engine.required_fields()),
            "min_bars": engine.min_bars(),
            "params": engine.default_params(),
        }
        for engine in all_strategies()
    ]


def merge_params(engine: StrategyEngine, params: dict[str, Any] | None) -> dict[str, Any]:
    """用默认参数补齐调用方传入的部分参数，并拒绝未知参数。

    静默忽略拼错的参数名，会让人以为调过参了其实没有——回测结论就此作废。
    """
    defaults = engine.default_params()
    if not params:
        return dict(defaults)
    unknown = set(params) - set(defaults)
    if unknown:
        raise StrategyError(f"策略 {engine.slug} 不认识的参数：{sorted(unknown)}")
    merged = dict(defaults)
    merged.update(params)
    return merged
