"""悟道 tape provider（可选）。

模块加载期不触碰 ``src.intel``；没有悟道包、配置或凭据时，provider 返回
degraded 结果，让 router 继续尝试其它 provider。
"""
from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from src.market.domain.tape import TapeProvenance, TapeRequest, TapeResult
from src.market.infrastructure.adapters.types import (
    LANE_AUCTION_SNAPSHOT,
    LANE_BROKEN_LIMIT_UP,
    LANE_LIMIT_UP_POOL,
    LANE_MARKET_EMOTION,
    LANE_THEME_BOARD,
    LANE_THEME_MEMBERS,
)
from src.market.infrastructure.tape.wudao_parse import (
    extract_freshness,
    parse_lane_payload,
    quality_warnings,
)


#: 悟道正文过长会被 MCP 客户端截断；截断后 JSON 解析必然失败。
TRUNCATED_WARNING = "wudao_payload_truncated"
UNPARSED_ERROR = "wudao_payload_unparsed"


TOOL_BY_LANE: dict[str, str] = {
    LANE_MARKET_EMOTION: "short_term_emotion",
    LANE_LIMIT_UP_POOL: "limit_up_filter",
    LANE_BROKEN_LIMIT_UP: "broken_limit_up",
    LANE_THEME_BOARD: "theme_intraday_capital",
    LANE_THEME_MEMBERS: "theme_stocks",
    LANE_AUCTION_SNAPSHOT: "auction_opening_snapshot",
    "sector_analysis": "sector_analysis",
    "theme_concept_board": "theme_intraday_capital",
}

#: 键名映射的真相在 ``src.intel.application.wudao_keys``——那张表每一行都经过
#: 真实调用双向验证。这里曾自己维护一份，与 intel 侧、以及 skill_watch 里的
#: 硬编码三份并存，结果 broken_limit_up / limit_up_ladder / limit_up_filter
#: 三个键全写成了服务端不认的 tradeDate——整条调用被 INVALID_ARGUMENTS 拒掉，
#: 本 provider 把它读成「悟道没数据」，lane 静默降级。
#:
#: intel 反向依赖 market，模块级导入会成环，所以延迟到调用时取。


def _keys():
    """悟道键名表（延迟导入，避开 intel ↔ market 环）。"""
    from src.intel.application import wudao_keys

    return wudao_keys


def date_arg_by_tool() -> dict[str, str]:
    """兼容旧读法；新代码直接用 ``_keys().date_argument(tool, day)``。"""
    return dict(_keys().DATE_ARG_BY_TOOL)


def _first_date(arguments: dict[str, Any]) -> str:
    """调用方给的交易日（任一别名）；都没给返回空串。"""
    for alias in _keys().DATE_ALIASES:
        value = str(arguments.get(alias) or "").strip()
        if value:
            return value
    return ""


def wudao_tool_arguments(request: TapeRequest, tool: str) -> dict[str, Any]:
    """lane 请求 → 悟道工具参数。缓存 provider 要按同一份参数算 key。"""
    keys = _keys()
    # 交易日**归一成一个键**：调用方（如 legacy_bridge 透传的旧 scanner 参数）可能
    # 已经带了 date / trade_date，再补一个 tradeDate 就是一次请求两个日期键，
    # schema 只声明其中一个 → 整条 INVALID_ARGUMENTS。先摘干净，再按表补规范键。
    arguments = keys.strip_dates(dict(request.effective_arguments))
    day = request.requested_date or _first_date(dict(request.effective_arguments))
    arguments.update(keys.date_argument(tool, day))
    if request.codes:
        arguments.setdefault("codes", list(request.codes))
    if request.limit is not None:
        arguments.setdefault("limit", request.limit)
    arguments.setdefault("format", "json")
    arguments.setdefault("detailLevel", "standard")
    return arguments


def structured_root(payload: Any) -> dict[str, Any] | None:
    """取 MCP 结构化段；拿不到就是解析失败，不能当「查到了但没数据」。"""
    if not isinstance(payload, dict):
        return None
    root = payload.get("structured")
    return dict(root) if isinstance(root, dict) and root else None


#: **tape lane 记哪个配额池**：这条链路服务的是战法盯盘（`skill_watch` 扫描、纸面舱
#: 闸门），按「谁发起的」分池就该记 skill，而不是日常情报配方那个 structured 池。
#:
#: 盯盘 cron 是 ``*/5 9-14``（72 轮/日），一轮 3~8 条 lane，tape 缓存只有 5 分钟——
#: 一个盯盘战法就能吃掉几百次。压在 structured 3000/日 上会把 `intel_fetch` 的三档
#: 配方挤爆，而 skill 池 2000/日常年闲置。
#:
#: **可参数化，别再写死**：调用方可在 ``TapeRequest.context["quota_pool"]`` 指定池
#: （例如盘后离线补数据想记 structured）。未知值忽略并回落默认池——记到一个不存在
#: 的池等于这批调用不受任何预算约束。
DEFAULT_TAPE_QUOTA_POOL = "skill"
QUOTA_POOLS = ("structured", "skill")


def tape_quota_pool(request: TapeRequest) -> str:
    """本次 tape 请求记哪个配额池（默认 ``DEFAULT_TAPE_QUOTA_POOL``）。"""
    context = request.context if isinstance(request.context, Mapping) else {}
    pool = str(context.get("quota_pool") or "").strip().lower()
    return pool if pool in QUOTA_POOLS else DEFAULT_TAPE_QUOTA_POOL


class WudaoTapeProvider:
    provider_id = "wudao"
    label = "悟道"
    lanes = tuple(TOOL_BY_LANE)

    def supports(self, lane: str) -> bool:
        return lane in TOOL_BY_LANE

    def is_available(self, _request: TapeRequest | None = None) -> tuple[bool, str]:
        """只通过 intel 包根的 availability 查询，不复制 token 逻辑。"""
        try:
            from src.intel import wudao_availability

            status = wudao_availability()
        except Exception as exc:
            return False, f"悟道 provider 不可用：{type(exc).__name__}"
        if not isinstance(status, dict):
            return False, "悟道 provider availability 无效"
        return bool(status.get("available")), str(status.get("reason") or "")

    @staticmethod
    def _arguments(request: TapeRequest, tool: str) -> dict[str, Any]:
        return wudao_tool_arguments(request, tool)

    @staticmethod
    def _cache_store(request: TapeRequest) -> Any | None:
        """只复用调用方注入的 store：不自己开库，避免跨线程连接与意外写盘。"""
        context = request.context if isinstance(request.context, Mapping) else {}
        return context.get("market_store") or context.get("store")

    def _unavailable(self, request: TapeRequest, reason: str) -> TapeResult:
        return TapeResult(
            data=None,
            provenance=TapeProvenance(
                provider_id=self.provider_id,
                lane=request.lane,
                requested_date=request.requested_date,
                as_of_date=request.as_of_date,
                degraded=True,
                warnings=(reason,),
            ),
            error=reason,
        )

    def fetch(self, request: TapeRequest) -> TapeResult:
        # lane 是唯一出口；旧别名（如 limit_up_ladder）不能绕过 canonical tool。
        tool = TOOL_BY_LANE.get(request.lane) or request.tool
        if not tool:
            return self._unavailable(request, "unsupported_tape_lane")
        available, reason = self.is_available(request)
        if not available:
            return self._unavailable(request, reason or "wudao_unavailable")

        try:
            from src.intel import BUILTIN_WUDAO_NAME, call_mcp_tool

            payload = call_mcp_tool(
                tool,
                self._arguments(request, tool),
                server=BUILTIN_WUDAO_NAME,
                pool=tape_quota_pool(request),
                cache=request.cache,
                cache_max_age_minutes=request.cache_max_age_minutes,
                # 不给 store 时 call_mcp_tool 的 cache 参数是空转：同一分钟内
                # 反复扫同一条 lane 会次次真调 MCP、次次扣配额（现在扣的是 skill 池）。
                market_store=self._cache_store(request),
            )
        except Exception as exc:
            return self._unavailable(
                request,
                f"wudao_call_failed:{type(exc).__name__}",
            )

        if not isinstance(payload, dict) or payload.get("is_error") or payload.get("unavailable"):
            message = str(
                (payload or {}).get("unavailable_reason")
                or (payload or {}).get("text")
                or "wudao_empty"
            )
            return self._unavailable(request, message[:240])

        # 结构化段缺失 = 没解析出任何可用事实（常见于正文超限被截断）。
        # 继续往下会得到一份 rows 为空却标着「今日、未降级」的结果。
        if structured_root(payload) is None:
            suffix = f":{TRUNCATED_WARNING}" if payload.get("truncated") else ""
            return self._unavailable(request, f"{UNPARSED_ERROR}{suffix}")

        try:
            freshness = extract_freshness(payload, requested=request.requested_date or "")
            warnings = [
                *quality_warnings(payload, "wudao"),
                *(str(note) for note in freshness.get("notes") or []),
                *(
                    f"wudao:clamped:{note}"
                    for note in (payload.get("clamped") or [])
                    if str(note).strip()
                ),
            ]
            data = parse_lane_payload(
                request.lane,
                payload,
                requested_date=request.requested_date,
            )
        except Exception as exc:
            return self._unavailable(
                request,
                f"wudao_parse_failed:{type(exc).__name__}",
            )
        if data is None:
            return self._unavailable(request, "wudao_payload_empty")
        stale = bool(freshness.get("stale"))
        if stale:
            warnings.append("wudao:stale_trade_date")
        return TapeResult(
            data=data,
            provenance=TapeProvenance(
                provider_id=self.provider_id,
                lane=request.lane,
                requested_date=request.requested_date,
                as_of_date=freshness.get("actual_trade_date") or request.as_of_date,
                # 命中 intel 快照时取快照抓取时刻，否则就是本次真调的时刻。
                fetched_at=str(
                    payload.get("cache_fetched_at")
                    or freshness.get("snapshot_time")
                    or ""
                )
                or None,
                # 日期错位/非当日仍返回数据，但必须标降级：router 会先试其它
                # provider，闸门也才有机会 fail-closed。
                degraded=stale,
                stale=stale,
                from_cache=bool(payload.get("cached")),
                warnings=tuple(dict.fromkeys(warnings)),
            ),
            error="wudao_stale_trade_date" if stale else None,
        )


__all__ = [
    "DEFAULT_TAPE_QUOTA_POOL",
    "TOOL_BY_LANE",
    "TRUNCATED_WARNING",
    "UNPARSED_ERROR",
    "WudaoTapeProvider",
    "structured_root",
    "tape_quota_pool",
    "wudao_tool_arguments",
]
