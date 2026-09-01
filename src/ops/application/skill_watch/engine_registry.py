"""战法扫描引擎注册表：target + 能力声明（表驱动，禁止 slug 字面量丛林）。"""
from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True)
class EngineSpec:
    """单引擎能力声明。新增第 4 战法：加一条注册 + 能力字段即可。"""

    target: str
    needs_market_store: bool = False
    #: 引擎自己维护跨轮状态时置 True，runner 会注入 ops store。
    needs_ops_store: bool = False
    uses_market_gate: bool = False
    emits_observe: bool = False
    eod_rescan: bool = False
    label_zh: str = ""
    default_push_wecom: bool = True
    #: True = **只有出可执行候选时才推企微**（空 picks、仅观察都不算），无信号轮次静默。
    #: 盘中每 10 分钟一轮，而 runner 的 summary 有 "无新信号" 兜底、signals 里
    #: 还常年躺着 watch_only/gate_empty，默认逻辑会每轮都推。高频引擎必须置 True，
    #: 否则一天刷十几条"无新信号"或「仅观察」。失败/跳过仍会推原因，不受此影响。
    push_only_when_actionable: bool = False
    signals: frozenset[str] = field(default_factory=frozenset)


_DRAGON_RETURN_SIGNALS = frozenset(
    {
        "paper_candidate",
        "gate_empty",
        "invalidated",
        "watch_only",
        "leader_watch",
        "leader_weak",
        "theme_interval_weak",
        "theme_interval_degraded",
    }
)
_LEADER_MAP_SIGNALS = frozenset(
    {
        "leader_watch",
        "leader_weak",
        "gate_empty",
        "watch_only",
        "theme_interval_weak",
        "theme_interval_degraded",
    }
)
_LIMIT_UP_SIGNALS = frozenset(
    {
        "paper_candidate",
        "gate_empty",
        "watch_only",
        "sell_hint",
    }
)

_DRAGON_RETURN = EngineSpec(
    target="dragon_return:scan_dragon_return",
    needs_market_store=True,
    uses_market_gate=True,
    emits_observe=True,
    eod_rescan=True,
    label_zh="龙回头",
    default_push_wecom=True,
    signals=_DRAGON_RETURN_SIGNALS,
)
_LEADER_MAP = EngineSpec(
    target="leader_map:scan_leader_map",
    needs_market_store=True,
    uses_market_gate=True,
    emits_observe=False,
    eod_rescan=False,
    label_zh="龙头地图",
    default_push_wecom=False,
    signals=_LEADER_MAP_SIGNALS,
)
_LIMIT_UP = EngineSpec(
    target="limit_up_momentum:scan_limit_up_momentum",
    needs_market_store=False,
    uses_market_gate=False,
    emits_observe=False,
    eod_rescan=False,
    label_zh="涨停动量",
    default_push_wecom=False,
    signals=_LIMIT_UP_SIGNALS,
)

#: 引擎别名 → 能力声明（含 kebab / snake 兼容键）
ENGINE_REGISTRY: dict[str, EngineSpec] = {
    "dragon_return": _DRAGON_RETURN,
    "dragon-return": _DRAGON_RETURN,
    "leader_map": _LEADER_MAP,
    "market-leader-map": _LEADER_MAP,
    "theme_rotation": _LEADER_MAP,
    "theme-leader-rotation": _LEADER_MAP,
    "limit_up_momentum": _LIMIT_UP,
    "limit-up-momentum": _LIMIT_UP,
}


def engine_spec(engine_or_slug: str) -> EngineSpec | None:
    return ENGINE_REGISTRY.get(str(engine_or_slug or "").strip())


def engine_target(engine: str) -> str | None:
    spec = engine_spec(engine)
    return spec.target if spec else None


def engines_using_market_gate() -> frozenset[str]:
    return frozenset(k for k, spec in ENGINE_REGISTRY.items() if spec.uses_market_gate)


def eod_rescan_skill_for(slug: str) -> str | None:
    """日终重扫应调用的 skill slug；同闸门族共享 eod_rescan 引擎。"""
    spec = engine_spec(slug)
    if spec is None:
        return None
    if spec.eod_rescan:
        return str(slug).strip()
    if not spec.uses_market_gate:
        return None
    for key, other in ENGINE_REGISTRY.items():
        if other.eod_rescan and "-" in key:
            return key
    return None


def watch_label_map() -> dict[str, str]:
    """slug → 中文短名（唯一表；notify / labels / 推送默认共用）。"""
    out: dict[str, str] = {}
    for key, spec in ENGINE_REGISTRY.items():
        if "-" in key and spec.label_zh:
            out[key] = spec.label_zh
    return out


def default_watch_push_wecom(slug: str) -> bool:
    spec = engine_spec(slug)
    if spec is None:
        return True
    return bool(spec.default_push_wecom)


def push_only_when_actionable(slug: str) -> bool:
    """该战法是否「无可执行候选就不推企微」。未知 slug 保持旧行为（推）。"""
    spec = engine_spec(slug)
    if spec is None:
        return False
    return bool(spec.push_only_when_actionable)


__all__ = [
    "ENGINE_REGISTRY",
    "EngineSpec",
    "default_watch_push_wecom",
    "push_only_when_actionable",
    "engine_spec",
    "engine_target",
    "engines_using_market_gate",
    "eod_rescan_skill_for",
    "watch_label_map",
]
