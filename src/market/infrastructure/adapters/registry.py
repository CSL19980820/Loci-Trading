"""适配器注册表。

代码即注册表：增删源改本文件，不搞 JSON / SQLite 映射。
"""
from __future__ import annotations

from typing import Iterable

from src.market.infrastructure.adapters.base import MarketAdapter
from src.market.infrastructure.adapters.eastmoney_adapter import EastmoneyAdapter
from src.market.infrastructure.adapters.exchange_list_adapter import ExchangeListAdapter
from src.market.infrastructure.adapters.sina_adapter import SinaAdapter
from src.market.infrastructure.adapters.tdx_adapter import TdxAdapter
from src.market.infrastructure.adapters.tencent_adapter import TencentAdapter


def _build_default() -> list[MarketAdapter]:
    # 日线/现价：东财优先，新浪/腾讯作补充备源（粘性竞速仍可钉住赢家）。
    # minute_bars：通达信只挂该 lane，置顶即分时最高优先；失败再东财 → 新浪。
    return [
        TdxAdapter(),
        EastmoneyAdapter(),
        SinaAdapter(),
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
    """给 API 用的名片列表（id / label / lanes / description）。"""
    return [a.catalog_entry() for a in _registry()]
