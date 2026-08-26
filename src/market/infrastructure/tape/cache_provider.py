"""既有 intel_snapshots 的 tape 缓存 provider。

**为什么它排在悟道前面**：见 ``registry.py`` 里那段注释（两条在产链路根本没
注入 store，每一轮都在白扣配额）。本模块只保证一件事——它兑现的缓存，绝不比
「悟道 provider 自己去读同一张表」那条路更陈。两边时效口径必须一致，否则调换
顺序就等于偷偷放宽了时效。
"""
from __future__ import annotations

from dataclasses import replace
from typing import Any

from src.market.domain.tape import TapeProvenance, TapeRequest, TapeResult
from src.market.infrastructure.adapters.types import TAPE_LANES
from src.market.infrastructure.tape.cache import read_tape_cache
from src.market.infrastructure.tape.local_provider import _close_owned, _store_from_request
from src.market.infrastructure.tape.wudao_provider import TOOL_BY_LANE, wudao_tool_arguments


#: 调用方没给 TTL 时的默认复用上限（分钟）。盯盘一轮 5 分钟，取同一量级。
DEFAULT_TAPE_CACHE_TTL_MINUTES = 5


def _clamped(arguments: dict[str, Any]) -> dict[str, Any]:
    """悟道写缓存前会过一遍参数裁剪；取 key 必须用裁剪后的同一份。"""
    try:
        from src.intel import clamp_mcp_arguments

        return dict(clamp_mcp_arguments(arguments))
    except Exception:
        return dict(arguments)


def _session_policy() -> tuple[Any, Any, Any] | None:
    """intel 侧的收盘态判定 + 盘中 TTL 钳制（惰性导入，避开 intel ↔ market 环）。

    为什么借 intel 的而不是自己写一套：``call_mcp_tool`` 读的就是同一张
    ``intel_snapshots``，它那套口径是「盘中 TTL 压到 10 分钟、收盘后不复用盘中抓的
    半截数据」。本 provider 现在排在悟道前面，这里要是另写一份判定，改个顺序就等于
    悄悄换了一套时效标准——而且两份判定迟早对不上。

    import-linter 只保护 ``src.intel.infrastructure``，``src.intel.application``
    不在 protected 名单里，这条依赖过门禁。取不到就退回本模块的保守默认值。
    """
    try:
        from src.intel.application.fetch import (
            _cache_matches_session,
            _effective_cache_max_age,
            _settled_at,
        )
    except Exception:
        return None
    return _settled_at, _effective_cache_max_age, _cache_matches_session


def _freshness(request: TapeRequest) -> tuple[int, bool, Any]:
    """(生效 TTL 分钟, 收盘态, 会话校验函数)。intel 不可用时退回改动前的行为。

    关键是 TTL 那一步：调用方给 120 分钟（盘后档）时，悟道那条路会在盘中把它压回
    10 分钟，而这里原来是照单全收 —— 排到前面就成了「盘中兑现两小时前的快照」。
    """
    requested = int(request.cache_max_age_minutes or DEFAULT_TAPE_CACHE_TTL_MINUTES)
    policy = _session_policy()
    if policy is None:
        return requested, False, None
    settled_at, effective_max_age, matches_session = policy
    try:
        settled = bool(settled_at())
        max_age = effective_max_age(requested, settled=settled)
    except Exception:
        return requested, False, None
    return int(max_age or requested), settled, matches_session


class CachedTapeProvider:
    """读取 market.db 中同一工具/日期的可重建情报快照。"""

    provider_id = "cache"
    label = "情报缓存"
    lanes = TAPE_LANES

    def supports(self, lane: str) -> bool:
        return lane in self.lanes

    @staticmethod
    def _key_arguments(request: TapeRequest, tool: str) -> list[dict[str, Any]]:
        """先按请求原参数，再按悟道 lane 实际写入的参数取 key。

        **这里只能做精确 key**：把 limit=80 的那一行复用给 limit=20 的请求要用
        intel 侧的覆盖度规则（``intel_cache.cache_identity_key``），而
        ``src.intel.infrastructure`` 是 import-linter 的 protected 模块，market 不
        能深掏。tape lane 的跨入口复用因此走另一条路：悟道 provider 调
        ``call_mcp_tool(cache=True, market_store=…)``，由 intel 自己那套读侧去做
        复用。详见 ``src/market/README.md`` 盘口情报 tape 段。
        """
        keys: list[dict[str, Any]] = [dict(request.effective_arguments)]
        if TOOL_BY_LANE.get(request.lane) == tool:
            wudao_args = _clamped(wudao_tool_arguments(request, tool))
            if wudao_args not in keys:
                keys.append(wudao_args)
        return keys

    @staticmethod
    def _usable(cached: TapeResult, *, settled: bool, matches: Any) -> bool:
        """这份缓存能不能当盘口事实兑现。

        两道闸：

        - **失败载荷不算事实**。intel 侧把负缓存写在独立 key 命名空间，正常读不到；
          这里再挡一道，老库里可能还留着直接写进正缓存的失败行。
        - **收盘后不认盘中抓的半截数据**。与 ``call_mcp_tool`` 同一个函数判定，
        不在这里另写一份。
        """
        payload = cached.data if isinstance(cached.data, dict) else dict()
        if payload.get("is_error"):
            return False
        if matches is None or not settled:
            return True
        probe = dict(payload)
        if not probe.get("cache_fetched_at"):
            probe["cache_fetched_at"] = cached.provenance.fetched_at or ""
        try:
            return bool(matches(probe, settled=settled))
        except Exception:
            return True

    def _read(self, request: TapeRequest) -> TapeResult | None:
        if not request.cache:
            return None
        max_age, settled, matches = _freshness(request)
        tools = tuple(
            dict.fromkeys(
                tool
                for tool in (request.tool, TOOL_BY_LANE.get(request.lane))
                if str(tool or "").strip()
            )
        )
        for tool in tools:
            candidate = replace(request, tool=tool)
            store, owned = _store_from_request(candidate)
            if store is None:
                return None
            try:
                for arguments in self._key_arguments(candidate, tool):
                    cached = read_tape_cache(
                        store,
                        candidate,
                        tool=tool,
                        arguments=arguments,
                        max_age_minutes=max_age,
                    )
                    if cached is None:
                        continue
                    if not self._usable(cached, settled=settled, matches=matches):
                        continue
                    return cached
            except Exception:
                pass
            finally:
                _close_owned(store, owned)
        return None

    def is_available(self, request: TapeRequest) -> tuple[bool, str]:
        if not request.requested_date:
            return False, "cache_requires_trade_date"
        return (
            (True, "")
            if self._read(request) is not None
            else (False, "tape_cache_miss")
        )

    def fetch(self, request: TapeRequest) -> TapeResult:
        cached = self._read(request)
        if cached is None:
            return TapeResult(
                data=None,
                provenance=TapeProvenance(
                    provider_id=self.provider_id,
                    lane=request.lane,
                    requested_date=request.requested_date,
                    degraded=True,
                    warnings=("tape_cache_miss",),
                ),
                error="tape cache miss",
            )
        provenance = replace(
            cached.provenance,
            provider_id=self.provider_id,
            lane=request.lane,
            requested_date=request.requested_date,
            from_cache=True,
        )
        return TapeResult(data=cached.data, provenance=provenance, error=cached.error)


__all__ = ["CachedTapeProvider", "DEFAULT_TAPE_CACHE_TTL_MINUTES"]
