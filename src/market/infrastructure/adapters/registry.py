"""适配器注册表。

代码即注册表：增删源改本文件，不搞 JSON / SQLite 映射。
"""
from __future__ import annotations

from typing import Iterable

from src.market.infrastructure.adapters.base import MarketAdapter
from src.market.infrastructure.adapters.eastmoney_adapter import EastmoneyAdapter
from src.market.infrastructure.adapters.exchange_list_adapter import ExchangeListAdapter
from src.market.infrastructure.adapters.sina_adapter import SinaAdapter
from src.market.infrastructure.adapters.tencent_adapter import TencentAdapter


def _build_default() -> list[MarketAdapter]:
    return [
        SinaAdapter(),
        EastmoneyAdapter(),
        TencentAdapter(),
        ExchangeListAdapter(),
    ]


#: 进程内默认实例；测试可 ``register_adapter`` / 替换。
_REGISTRY: list[MarketAdapter] | None = None


def _registry() -> list[MarketAdapter]:
    global _REGISTRY
    if _REGISTRY is None:
        _REGISTRY = _build_default()
    return _REGISTRY


def reset_registry(adapters: Iterable[MarketAdapter] | None = None) -> None:
    """测试用：重置或注入整表。``None`` 恢复默认注册表。"""
    global _REGISTRY
    _REGISTRY = list(adapters) if adapters is not None else None


def all_adapters() -> list[MarketAdapter]:
    return list(_registry())


def get_adapter(adapter_id: str) -> MarketAdapter:
    for adapter in _registry():
        if adapter.meta.id == adapter_id:
            return adapter
    raise KeyError(f"未知适配器 id={adapter_id!r}")


def adapters_for_lane(lane: str) -> list[MarketAdapter]:
    return [a for a in _registry() if lane in a.meta.lanes]


def enabled_adapter_ids(lane: str) -> list[str]:
    """该 lane 下启用中的 adapter id（尊重 loci.config ``lane_providers``）。"""
    from src.shared.paths import load_config

    raw = load_config().get("lane_providers")
    prefs = raw if isinstance(raw, dict) else {}
    out: list[str] = []
    for adapter in adapters_for_lane(lane):
        entry = prefs.get(adapter.meta.id)
        if isinstance(entry, dict) and "enabled" in entry and not bool(entry["enabled"]):
            continue
        out.append(adapter.meta.id)
    return out


def list_catalog() -> list[dict]:
    """给 API 用的名片列表（id / label / lanes / description）。"""
    return [a.catalog_entry() for a in _registry()]
