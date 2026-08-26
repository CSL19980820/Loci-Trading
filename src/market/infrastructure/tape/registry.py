"""盘口情报 provider 注册表。

provider 的启停和手选回退继续复用 market adapter 的
``lane_providers`` / ``lane_routes`` 配置语义，不引入第二套配置协议。
"""
from __future__ import annotations

from collections.abc import Iterable
from typing import Any

from src.market.infrastructure.adapters.registry import (
    lane_provider_enabled,
    lane_route_policy,
)
from src.market.infrastructure.tape.base import (
    provider_id_of,
    supports_lane,
)
from src.market.infrastructure.tape.cache_provider import CachedTapeProvider
from src.market.infrastructure.tape.local_provider import LocalTapeProvider
from src.market.infrastructure.tape.wudao_provider import WudaoTapeProvider


_REGISTRY: list[Any] | None = None


def _registry() -> list[Any]:
    global _REGISTRY
    if _REGISTRY is None:
        # 顺序是 缓存 → 悟道 → 本地，**缓存在悟道之前**。理由和风险都写在这里，
        # 因为「缓存优先」听上去就像「盘中拿昨天的数据」：
        #
        # 1. 为什么要调：`WudaoTapeProvider` 只肯用调用方注入的 store
        #  （`_cache_store`：不自己开库，避免跨线程连接与意外写盘），而在产三条
        #    链路里有两条**根本没注入**——`skill_watch/market_regime.py` 的
        #    `make_legacy_tape_call()` 和 `jobs/paper_quant_support.py` 直接传的
        #    `legacy_call_tool`。没有 store，`call_mcp_tool(cache=True)` 整段是空转：
        #    每轮盯盘都真调、都真扣 skill 池。而悟道健康时它总是第一个返回健康结果，
        #    排在它后面的缓存 provider 永远走不到——这才是「缓存成了死代码」的真身。
        #  `CachedTapeProvider` 会自己开只读连接（`_store_from_request`），正好补上。
        # 2. 为什么不会拿到昨天的数据：缓存行的主键含 `trade_date`，
        #    `read_tape_cache` 按 `WHERE trade_date = request.requested_date` 取，
        #    还会再比一次载荷自报的 `actualTradeDate`。跨交易日兑现在结构上不可能。
        # 3. 盘中会不会更陈：不会。`cache_provider._freshness` 借的是 intel 那套
        #    （盘中 TTL 压到 10 分钟、收盘后不认盘中抓的半截数据），与悟道 provider
        #    内部 `call_mcp_tool` 读同一张表时用的是**同一个函数**。默认 TTL 5 分钟
        #    还比 intel 盘中上限的 10 分钟更严——顺序调换后只会更新，不会更旧。
        # 4. 命中它会不会换了数据形状：不会。生产上唯一的消费者是
        #  `legacy_bridge._raw_payload`，悟道 DTO 走 `dto.payload`、缓存外壳走
        #    `payload["structured"]`，两者都归到同一个 structured root。
        #
        # 缓存未命中时 `is_available` 返回 False，router 直接落到悟道，行为不变。
        _REGISTRY = [CachedTapeProvider(), WudaoTapeProvider(), LocalTapeProvider()]
    return _REGISTRY


def reset_registry(providers: Iterable[Any] | None = None) -> None:
    """测试/宿主装配用；``None`` 恢复默认 tape provider 队列。"""
    global _REGISTRY
    _REGISTRY = list(providers) if providers is not None else None


def register_provider(provider: Any) -> None:
    """追加一个 provider；同 id 以最新注册的实现覆盖。"""
    provider_id = provider_id_of(provider)
    if not provider_id:
        raise ValueError("tape provider 缺少 provider_id")
    current = [item for item in _registry() if provider_id_of(item) != provider_id]
    current.append(provider)
    reset_registry(current)


def all_providers() -> list[Any]:
    return list(_registry())


def providers_for_lane(
    lane: str,
    *,
    config: dict[str, Any] | None = None,
) -> list[Any]:
    """按既有 lane 配置返回有序 provider。

    自动模式保持注册顺序；手动模式把指定 provider 放在首位，只有
    ``fallback=true`` 才继续尝试后续 provider。
    """
    candidates: list[Any] = []
    seen: set[str] = set()
    for provider in _registry():
        provider_id = provider_id_of(provider)
        if (
            not provider_id
            or provider_id in seen
            or not supports_lane(provider, lane)
            or not lane_provider_enabled(provider_id, lane, config=config)
        ):
            continue
        seen.add(provider_id)
        candidates.append(provider)

    policy = lane_route_policy(lane, config=config)
    if policy.get("mode") != "manual":
        return candidates
    selected_id = str(policy.get("provider_id") or "").strip()
    selected = next(
        (provider for provider in candidates if provider_id_of(provider) == selected_id),
        None,
    )
    if selected is None:
        return candidates
    if not bool(policy.get("fallback")):
        return [selected]
    return [selected, *[provider for provider in candidates if provider is not selected]]


__all__ = [
    "all_providers",
    "register_provider",
    "providers_for_lane",
    "reset_registry",
]
