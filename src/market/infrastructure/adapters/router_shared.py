"""路由层共享小工具。

放这里纯粹是为了让 ``router`` 与 ``router_probe`` 都能用，
同时不互相 import 成环。
"""
from __future__ import annotations

from collections.abc import Sequence

from src.market.infrastructure.adapters.base import MarketAdapter
from src.market.infrastructure.adapters.registry import adapters_for_lane, get_adapter


def _resolve_adapters(
    lane: str, adapter_ids: Sequence[str] | None
) -> list[MarketAdapter]:
    """把 adapter id 列表解析成实例；``None`` 表示取该 lane 的全部启用源。"""
    if adapter_ids is None:
        return adapters_for_lane(lane)
    out: list[MarketAdapter] = []
    for aid in adapter_ids:
        adapter = get_adapter(aid)
        if lane in adapter.meta.lanes:
            out.append(adapter)
    return out