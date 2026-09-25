"""适配器注册表。

代码即注册表：增删源改本文件，不搞 JSON / SQLite 映射。
"""
from __future__ import annotations

from typing import Iterable

from src.market.infrastructure.adapters.base import MarketAdapter
from src.market.infrastructure.adapters.baostock_adapter import BaostockAdapter
from src.market.infrastructure.adapters.eastmoney_adapter import EastmoneyAdapter
from src.market.infrastructure.adapters.exchange_list_adapter import ExchangeListAdapter
from src.market.infrastructure.adapters.hithink_adapter import (
    HithinkAdapter,
    hithink_adapter_enabled,
)
from src.market.infrastructure.adapters.sina_adapter import SinaAdapter
from src.market.infrastructure.adapters.tdx_adapter import TdxAdapter
from src.market.infrastructure.adapters.tencent_adapter import TencentAdapter
from src.market.infrastructure.adapters.wudao_adapter import WudaoAdapter, wudao_adapter_enabled


def _build_default() -> list[MarketAdapter]:
    adapters: list[MarketAdapter] = [
        TdxAdapter(),
        HithinkAdapter(),
        WudaoAdapter(),
    ]
    adapters.extend(
        [
            TencentAdapter(),
            EastmoneyAdapter(),
            BaostockAdapter(),
            SinaAdapter(),
            ExchangeListAdapter(),
        ]
    )
    return adapters


def _runtime_enabled(adapter: MarketAdapter) -> bool:
    """运行时可选源判定；配置变化无需重启进程或重建注册表。"""
    if adapter.meta.id == WudaoAdapter.meta.id:
        return wudao_adapter_enabled()
    if adapter.meta.id == HithinkAdapter.meta.id:
        return hithink_adapter_enabled()
    return True


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
    return [adapter for adapter in _registry() if _runtime_enabled(adapter)]


def get_adapter(adapter_id: str) -> MarketAdapter:
    for adapter in _registry():
        if adapter.meta.id == adapter_id:
            return adapter
    raise KeyError(f"未知适配器 id={adapter_id!r}")


def adapters_for_lane(lane: str) -> list[MarketAdapter]:
    return [a for a in _registry() if lane in a.meta.lanes and _runtime_enabled(a)]


def _config(config: dict | None) -> dict:
    from src.shared.paths import load_config

    return config if isinstance(config, dict) else load_config()


def _provider_entry(config: dict, provider_id: str) -> dict:
    raw = config.get("lane_providers")
    entry = raw.get(provider_id) if isinstance(raw, dict) else None
    return entry if isinstance(entry, dict) else {}


def provider_master_enabled(provider_id: str, *, config: dict | None = None) -> bool:
    """源总开关；缺省启用。"""
    entry = _provider_entry(_config(config), provider_id)
    return bool(entry.get("enabled", True))


def lane_provider_enabled(provider_id: str, lane: str, *, config: dict | None = None) -> bool:
    """该源在该 lane 上是否可用：源总开关 + 逐 lane 覆盖，两级都过才算启用。"""
    cfg = _config(config)
    if not provider_master_enabled(provider_id, config=cfg):
        return False
    overrides = _provider_entry(cfg, provider_id).get("lanes")
    if isinstance(overrides, dict) and lane in overrides:
        return bool(overrides[lane])
    return True


def provider_disabled_lanes(provider_id: str, *, config: dict | None = None) -> list[str]:
    """被单独关掉的 lane；只报该源真正承载的 lane，顺序随 meta.lanes。"""
    overrides = _provider_entry(_config(config), provider_id).get("lanes")
    if not isinstance(overrides, dict):
        return []
    owned = get_adapter(provider_id).meta.lanes
    return [lane for lane in owned if lane in overrides and not bool(overrides[lane])]


def lane_disabled_provider_ids(lane: str, *, config: dict | None = None) -> list[str]:
    """本可承载该 lane、却被开关关掉的源；顺序随注册表。

    与 ``provider_disabled_lanes`` 互为转置：那个按源问「关了哪些 lane」，
    这个按 lane 问「关了哪些源」，用于失败时说清哪些源压根没跑过。
    """
    cfg = _config(config)
    return [
        adapter.meta.id
        for adapter in adapters_for_lane(lane)
        if not lane_provider_enabled(adapter.meta.id, lane, config=cfg)
    ]


def enabled_adapter_ids(lane: str, *, config: dict | None = None) -> list[str]:
    """该 lane 的有效 adapter 顺序（源/逐 lane 开关 + 可选用户选源策略）。"""
    cfg = _config(config)
    enabled: list[str] = [
        adapter.meta.id
        for adapter in adapters_for_lane(lane)
        if lane_provider_enabled(adapter.meta.id, lane, config=cfg)
    ]

    policy = lane_route_policy(lane, config=cfg)
    provider_id = policy.get("provider_id")
    if policy["mode"] != "manual" or provider_id not in enabled:
        # 配置文件可能由旧版本或用户手工改坏；读取路径保持可用，写接口会拒绝它。
        return enabled
    if not policy["fallback"]:
        return [provider_id]
    return [provider_id, *[adapter_id for adapter_id in enabled if adapter_id != provider_id]]


def lane_route_policy(lane: str, *, config: dict | None = None) -> dict[str, object]:
    """读取单个 lane 的兼容策略，畸形/缺失配置一律按自动模式处理。"""
    from src.shared.paths import load_config

    source = config if config is not None else load_config()
    raw_routes = source.get("lane_routes") if isinstance(source, dict) else None
    raw = raw_routes.get(lane) if isinstance(raw_routes, dict) else None
    if not isinstance(raw, dict) or raw.get("mode") != "manual":
        return {"mode": "auto", "fallback": bool(raw.get("fallback")) if isinstance(raw, dict) else False}
    provider_id = raw.get("provider_id")
    if not isinstance(provider_id, str) or not provider_id.strip():
        return {"mode": "auto", "fallback": False}
    return {
        "mode": "manual",
        "provider_id": provider_id.strip(),
        "fallback": bool(raw.get("fallback")),
    }


def list_catalog() -> list[dict]:
    """给 API 用的名片列表（id / label / lanes / description）。

    ``wudao`` 日 K 适配器与悟道 MCP 同源，不单独占一张数据源牌——目录只露
    ``mcp:wudao``；路由层仍可通过 ``enabled_adapter_ids`` 使用它。
    """
    return [
        adapter.catalog_entry()
        for adapter in all_adapters()
        if adapter.meta.id != WudaoAdapter.meta.id
    ]
