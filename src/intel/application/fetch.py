"""带配额、缓存的 MCP 工具调用。"""
from __future__ import annotations

import json
import logging
from datetime import datetime
from typing import Any, Literal

from src.intel.application.arg_clamp import clamp_mcp_arguments_with_notes
from src.intel.infrastructure.builtin_wudao_mcp import (
    is_resident_wudao_server,
    wudao_availability,
)
from src.intel.infrastructure.intel_cache import (
    read_cached_error,
    read_cached_snapshot,
    write_cached_error,
    write_cached_snapshot,
)
from src.intel.infrastructure.mcp import McpClient, McpError
from src.intel.infrastructure.quota import (
    McpQuotaError,
    McpQuotaPool,
    acquire_quota,
    quota_snapshot,
    record_quota_call,
    trade_date_today,
)
from src.market import MarketStore

logger = logging.getLogger(__name__)


#: 盘中缓存的最长复用分钟数。当日数据在收盘前一直在变（半截日 K、随时会被砸开的
#: 封板、每分钟刷新的情绪指标），几十分钟的 TTL 等于把一份过期快照反复兑现；
#: 只有收盘定稿后才允许调用方给的长 TTL 生效。
_INTRADAY_CACHE_MAX_AGE_MINUTES = 10

#: 写进缓存载荷的收盘态标记；读侧据此拒绝「把盘中半截数据当收盘定稿复用」。
SESSION_STATE_KEY = "session_state"
SESSION_LIVE = "live"
SESSION_SETTLED = "settled"

#: 失败结果的负缓存冷却（分钟）。**没有它，一次失败会在每一轮重试里被原样复现**：
#: `_rejected_before_execution` 之外的业务错误（「今日无数据」「该股停牌」）是照
#: `record_quota_call` 的，于是每次重试都真调一次、真扣一次额，一天几十轮全花在
#: 一个已知打不通的调用上。写法参考东财行业图的失败冷却
#: （`market/infrastructure/em_industry.py::_EM_INDUSTRY_FAIL_COOLDOWN_SEC`）。
#:
#: 冷却长度分两类，理由不同：
#:
#: - **参数被服务端直接拒**：同一份参数必然再被拒，与「数据还没出来」无关，给长
#:   冷却。它本来就不扣配额，这里省的是延迟、日志噪音和一次次白跑的建连。
#: - **业务错误**：可能只是这一刻还没出数（9:25 问涨停池）。盘中给分钟级冷却，
#:   数据一出来就能被抓到；收盘后当日结论基本定稿，给长一点。
#:
#: 两个逃生口：`cache=False` 的调用永不读负缓存；成功写入会立刻清掉同 key 的
#: 冷却行（`write_cached_snapshot`），不留惩罚期。
_REJECTED_ERROR_COOLDOWN_MINUTES = 60
_INTRADAY_ERROR_COOLDOWN_MINUTES = 5
_SETTLED_ERROR_COOLDOWN_MINUTES = 30


def _settled_at(when: datetime | None = None) -> bool:
    """该时刻（默认此刻）是否已过当日收盘。

    复用 ops 的会话时钟（``src/ops/application/session_clock.py``），不再写第二份
    交易时段判定。两个坑写在这里：

    - ``phase == "closed"`` 还包含 11:30–13:00 午休。午休时当日数据只是暂停变动，
      **不是定稿**，所以要再看一眼钟点是否已到 15:00。
    - 判定不出来（模块缺失、时间戳畸形）一律按**未收盘**处理：宁可多打一次，
      也不能把半截数据钉成权威收盘值。

    会话时钟只认钟点、不认交易日历，周末 15:00 后同样算 settled——这与
    ``trade_date_today()`` 本就按自然日取缓存键的口径一致，不新增错位。
    """
    try:
        # 惰性深引用 ops 的叶子模块：它只依赖标准库，不会把 ops 的调度栈拖进来，
        # 更不会在 import 期与 src.ops -> src.intel 的懒加载互相成环。
        from src.ops.application.session_clock import session_clock

        clock = session_clock(when)
    except Exception as exc:  # noqa: BLE001 — 时钟不可用不该改变取数结论
        logger.debug("会话时钟不可用，按盘中处理：%s", exc)
        return False
    return clock.phase == "closed" and clock.now.hour >= 15


def _effective_cache_max_age(requested: int | None, *, settled: bool) -> int | None:
    """收盘后才允许长 TTL；盘中把 TTL 压到分钟级。"""
    if settled:
        return requested
    if requested is None or requested <= 0 or requested > _INTRADAY_CACHE_MAX_AGE_MINUTES:
        return _INTRADAY_CACHE_MAX_AGE_MINUTES
    return requested


def _cache_matches_session(cached: dict[str, Any], *, settled: bool) -> bool:
    """收盘后不认「盘中抓的当日快照」。

    缓存键只锁到交易日，10:03 抓的当日 bar 和 15:40 抓的收盘 bar 落在同一行。
    不区分收盘态，盘后读到的就是半截 bar，却被当成权威收盘价往下游发。
    盘中读盘中快照没问题（TTL 已压到分钟级），只拦「已收盘 ← 盘中数据」这一向。
    """
    if not settled:
        return True
    state = str(cached.get(SESSION_STATE_KEY) or "").strip()
    if state:
        return state == SESSION_SETTLED
    # 旧行 / 其它写入方（如 tape 的 write_tape_cache）没有这个标记，退回看抓取时刻。
    fetched_at = str(cached.get("cache_fetched_at") or "").strip()
    if not fetched_at:
        # 既无标记又无时刻的载荷只可能是调用方手工注入的：维持旧行为兑现，
        # 不在这里制造一次无声的行为漂移。
        return True
    try:
        stamp = datetime.fromisoformat(fetched_at.replace("Z", "+00:00"))
    except (TypeError, ValueError):
        return False
    if stamp.tzinfo is None:
        return False  # 无时区的旧时间戳不可信，按盘中抓的处理
    return _settled_at(stamp)


#: 能明确判定「服务端没真跑这次调用」的错误特征（参数校验类）。悟道对
#: ``additionalProperties: false`` 的拒绝是工具结果 ``isError=true`` + 正文错误码，
#: 不是 JSON-RPC error，所以只能靠正文识别。
#: **刻意保守**：只有命中这些特征才不记账。业务错误（「今日无数据」「该股停牌」）
#: 说明服务端真的执行了检索、真的消耗了供应商额度，把它们一起免单会让本地计数
#: 低于服务端计数——本地以为还有余量、实际已被限流，比多扣几次更难查。
_NOT_EXECUTED_ERROR_MARKERS = (
    "invalid_arguments",
    "invalid arguments",
    "invalid_argument",
    "invalid_params",
    "validation_error",
    "missing_required",
    "unrecognized key",
    "unknown argument",
    "additionalproperties",
    "参数非法",
    "参数错误",
    "参数校验",
    "缺少必填",
    "未知参数",
)


def _rejected_before_execution(result: dict[str, Any]) -> bool:
    """这次 is_error 是否属于「参数被直接拒、服务端没执行」。"""
    if not result.get("is_error"):
        return False
    text = str(result.get("text") or "").lower()
    return any(marker in text for marker in _NOT_EXECUTED_ERROR_MARKERS)

def _parse_tool_payload(text: str) -> dict[str, Any] | None:
    raw = str(text or "").strip()
    if not raw:
        return None
    try:
        payload = json.loads(raw)
    except json.JSONDecodeError:
        # 正文里夹了一段 JSON 时再试一次（部分 MCP 先写 headline 再跟 JSON）
        start = raw.find("{")
        end = raw.rfind("}")
        if start < 0 or end <= start:
            return None
        try:
            payload = json.loads(raw[start : end + 1])
        except json.JSONDecodeError:
            return None
    if not isinstance(payload, dict):
        return None
    # format=json 常见外壳：{"tool","success","data":{...}}
    data = payload.get("data")
    if isinstance(data, dict) and (
        "tool" in payload or "success" in payload or "meta" in payload
    ):
        return data
    return payload


def _resolve_structured(result: dict[str, Any]) -> dict[str, Any] | None:
    direct = result.get("structured")
    if isinstance(direct, dict) and direct:
        data = direct.get("data")
        if isinstance(data, dict) and ("tool" in direct or "success" in direct):
            # 解包成服务端的 ``data`` 段（消费方读的都是 rows/summary 这一层），但
            # ``rawData`` 是 ``data`` 的**兄弟节点**，直接丢会把 ``detailLevel=raw`` 唯一
            # 多出来的那份东西整段抹掉——悟道简报的全文（``rawData[0].content.fullContent``）
            # 就在那里，抹掉之后推出去的「简报」只剩一句核心摘要。
            #
            # 为什么不改成「让消费方自己去 text 里再解一次 JSON」：``McpClient`` 对正文有
            # ``MAX_TOOL_RESULT_CHARS=12_000`` 的截断，raw 档 JSON 正文实测 41KB，截断后
            # 必然解不出结构，这条路走不通（线上实测过一次，只拿到 410 字的兜底摘要）。
            #
            # ``rawData`` 只有显式 ``detailLevel=raw`` 才会出现（配方与 tape lane 都不用
            # raw），所以这行对既有工具的载荷形状零影响。
            raw_data = direct.get("rawData")
            if raw_data is not None and "rawData" not in data:
                return {**data, "rawData": raw_data}
            return data
        return direct
    return _parse_tool_payload(str(result.get("text") or ""))


def _read_cache_or_none(
    store: MarketStore,
    *,
    trade_date: str,
    tool: str,
    arguments: dict[str, Any] | None,
    max_age_minutes: int | None,
) -> dict[str, Any] | None:
    """缓存不可读时按未命中处理：情报快照可重建，不该拖垮取数。"""
    try:
        return read_cached_snapshot(
            store,
            trade_date=trade_date,
            tool=tool,
            arguments=arguments,
            max_age_minutes=max_age_minutes,
        )
    except Exception as exc:  # noqa: BLE001 — 缓存故障不改变取数结论
        logger.warning("情报缓存读取失败（按未命中处理）%s：%s", tool, exc)
        return None


def _write_cache_quietly(
    store: MarketStore,
    *,
    trade_date: str,
    tool: str,
    arguments: dict[str, Any] | None,
    server: str,
    payload: dict[str, Any],
) -> None:
    """写缓存失败不能吞掉已经扣过配额的成功结果。"""
    try:
        write_cached_snapshot(
            store,
            trade_date=trade_date,
            tool=tool,
            arguments=arguments,
            server=server,
            payload=payload,
        )
    except Exception as exc:  # noqa: BLE001 — 缓存可重建
        logger.warning("情报缓存写入失败（已忽略）%s：%s", tool, exc)


def _error_cooldown_minutes(*, rejected: bool, settled: bool) -> int:
    """这次失败该冷却多久（分钟）。"""
    if rejected:
        return _REJECTED_ERROR_COOLDOWN_MINUTES
    return _SETTLED_ERROR_COOLDOWN_MINUTES if settled else _INTRADAY_ERROR_COOLDOWN_MINUTES


def _read_error_cache_or_none(
    store: MarketStore,
    *,
    trade_date: str,
    tool: str,
    arguments: dict[str, Any] | None,
) -> dict[str, Any] | None:
    """负缓存不可读时按未命中处理：冷却是省钱手段，不是取数结论。"""
    try:
        return read_cached_error(
            store,
            trade_date=trade_date,
            tool=tool,
            arguments=arguments,
        )
    except Exception as exc:  # noqa: BLE001 — 缓存故障不改变取数结论
        logger.warning("情报失败缓存读取失败（按未命中处理）%s：%s", tool, exc)
        return None


def _write_error_cache_quietly(
    store: MarketStore,
    *,
    trade_date: str,
    tool: str,
    arguments: dict[str, Any] | None,
    server: str,
    payload: dict[str, Any],
    cooldown_minutes: int,
) -> None:
    """写负缓存失败只记日志：这次已经扣掉的额退不回来，但结论照常返回调用方。"""
    try:
        write_cached_error(
            store,
            trade_date=trade_date,
            tool=tool,
            arguments=arguments,
            server=server,
            payload=payload,
            cooldown_minutes=cooldown_minutes,
        )
    except Exception as exc:  # noqa: BLE001 — 缓存可重建
        logger.warning("情报失败缓存写入失败（已忽略）%s：%s", tool, exc)


def unavailable_mcp_payload(
    tool: str,
    arguments: dict[str, Any] | None,
    *,
    server: str,
    reason: str,
) -> dict[str, Any]:
    """悟道等可选 MCP 不可用时的统一软失败体：不抛错、不扣配额。"""
    text = str(reason or "MCP 不可用").strip() or "MCP 不可用"
    return {
        "tool": tool,
        "arguments": arguments or {},
        "server": server,
        "text": text,
        "is_error": True,
        "unavailable": True,
        "unavailable_reason": text,
        "cached": False,
        "structured": None,
        "quota": quota_snapshot(),
    }


def call_mcp_tool(
    tool: str,
    arguments: dict[str, Any] | None = None,
    *,
    server: str = "wudao",
    pool: McpQuotaPool = "skill",
    cache: bool = False,
    cache_max_age_minutes: int | None = None,
    market_store: MarketStore | None = None,
    skip_quota: bool = False,
) -> dict[str, Any]:
    """调用外部 MCP 工具；默认走 skill 池并扣配额。

    悟道未装配时：缓存命中仍返回；缓存未命中则统一软失败（``unavailable=true``），
    不抛错、不扣配额，避免拖垮盘面闸门 / 适配器回退链。

    三条与「当日数据」相关的纪律：

    - **收盘前的当日数据不是定稿**。缓存键只锁到交易日，盘中抓的半截 bar 会与
      收盘 bar 落进同一行，所以盘中 TTL 压到 ``_INTRADAY_CACHE_MAX_AGE_MINUTES``，
      且收盘后不复用盘中抓的那份（回源一次，用定稿覆盖）。
    - **废调用不扣配额**。参数被服务端直接拒（未执行）不记账；能执行到业务错误
      的仍照扣，因为供应商那边真的算了一次。
    - **失败也进缓存**。业务错误照扣配额，所以「失败不落缓存」等于每次重试都
      真调一次、真扣一次；失败结果另存一行（不顶掉还能用的成功快照），冷却期内
      直接兑现，不进配额闸门。
    """
    arguments, clamped = clamp_mcp_arguments_with_notes(arguments)
    trade_date = trade_date_today()
    store = market_store
    # 收盘态决定「这份当日数据算不算定稿」：盘中只给分钟级 TTL，且盘后不复用
    # 盘中抓的半截数据。判定一次，读写两侧共用同一个结论。
    settled = _settled_at()
    if cache and store is not None:
        cached = _read_cache_or_none(
            store,
            trade_date=trade_date,
            tool=tool,
            arguments=arguments,
            max_age_minutes=_effective_cache_max_age(cache_max_age_minutes, settled=settled),
        )
        if cached is not None and _cache_matches_session(cached, settled=settled):
            return {**cached, "cached": True, "quota": quota_snapshot()}
        if cached is not None:
            logger.info(
                "情报缓存命中但来自盘中，收盘后不复用（回源一次）%s@%s", tool, server
            )
        # 负缓存：上一次失败还在冷却期内就直接兑现那一份，不再真调、不再扣额。
        # **必须放在配额闸门之前**——业务错误是照扣配额的，晚一步就白扣一次。
        # cache=False 是逃生口：显式关掉缓存的调用永远会重试。
        cached_error = _read_error_cache_or_none(
            store,
            trade_date=trade_date,
            tool=tool,
            arguments=arguments,
        )
        if cached_error is not None:
            logger.info(
                "情报失败缓存命中，冷却中不再真调 %s@%s（还剩 %s 分钟）",
                tool,
                server,
                cached_error.get("retry_after_minutes"),
            )
            return {
                **cached_error,
                "cached": True,
                "quota_charged": False,
                "quota": quota_snapshot(),
            }

    if is_resident_wudao_server(server):
        availability = wudao_availability()
        if not availability.get("available"):
            reason = str(availability.get("reason") or "悟道 MCP 不可用")
            logger.info("call_mcp_tool 软跳过 %s@%s：%s", tool, server, reason)
            return unavailable_mcp_payload(
                tool, arguments, server=server, reason=reason
            )

    if not skip_quota:
        try:
            acquire_quota(pool)
        except McpQuotaError as exc:
            if is_resident_wudao_server(server):
                reason = str(exc) or "MCP 配额用尽"
                logger.info("call_mcp_tool 配额软跳过 %s：%s", tool, reason)
                return unavailable_mcp_payload(
                    tool, arguments, server=server, reason=reason
                )
            raise

    from src.intel.infrastructure.registry import build_client

    try:
        client = build_client(server)
    except Exception as exc:
        if is_resident_wudao_server(server):
            reason = str(exc) or "悟道 MCP 不可用"
            logger.info("call_mcp_tool 建连失败软跳过 %s：%s", tool, reason)
            return unavailable_mcp_payload(
                tool, arguments, server=server, reason=reason
            )
        raise
    if not isinstance(client, McpClient):
        raise McpError(f"{server} 不是外部 HTTP MCP，无法直接 call_tool")

    try:
        result = client.call_tool(tool, arguments)
    except Exception as exc:
        if is_resident_wudao_server(server):
            reason = str(exc) or "悟道 MCP 调用失败"
            logger.info("call_mcp_tool 调用软跳过 %s：%s", tool, reason)
            return unavailable_mcp_payload(
                tool, arguments, server=server, reason=reason
            )
        raise
    # 参数被服务端直接拒 = 这次调用根本没执行，扣配额纯属自罚。其余 is_error
    # 一律照扣（见 _NOT_EXECUTED_ERROR_MARKERS 的保守说明）。
    wasted = _rejected_before_execution(result)
    charged = not skip_quota and not wasted
    if charged:
        record_quota_call(pool)
    elif wasted:
        logger.warning(
            "MCP 参数被拒（未执行、不计配额）%s@%s：%s",
            tool,
            server,
            str(result.get("text") or "")[:200],
        )

    payload: dict[str, Any] = {
        "tool": tool,
        "arguments": arguments,
        "server": server,
        "text": result.get("text") or "",
        "is_error": bool(result.get("is_error")),
        "cached": False,
        # 正文被 MCP 客户端截断时结构化解析多半会失败，必须让调用方看得见，
        # 不能让「解析不出行」被读成「今天没有数据」。
        "truncated": bool(result.get("truncated")),
        "clamped": list(clamped),
        "structured": _resolve_structured(result),
        # 这次调用有没有真的扣掉配额；参数被拒的废调用不扣，运维核账要看得见。
        "quota_charged": charged,
        # 抓取时点的收盘态，会跟着载荷一起进缓存：读侧据此拒绝「盘中半截数据
        # 冒充收盘定稿」，别在 payload 之外另存一份。
        SESSION_STATE_KEY: SESSION_SETTLED if settled else SESSION_LIVE,
        "quota": quota_snapshot(),
    }
    if cache and store is not None:
        if not payload["is_error"]:
            _write_cache_quietly(
                store,
                trade_date=trade_date,
                tool=tool,
                arguments=arguments,
                server=server,
                payload=payload,
            )
        else:
            # 失败也落一行：不落，每一次重试都会走到这里再真调一次、再扣一次额。
            _write_error_cache_quietly(
                store,
                trade_date=trade_date,
                tool=tool,
                arguments=arguments,
                server=server,
                payload=payload,
                cooldown_minutes=_error_cooldown_minutes(rejected=wasted, settled=settled),
            )
    return payload


def _scope_note(clamped: tuple[str, ...], *, truncated: bool) -> str:
    """给模型看的取数范围回执。

    Agent 环只把 ``text`` 交给模型，``clamped`` / ``truncated`` 这些旁路字段它
    看不见——不写进正文，模型就会把「只扫了前 200 只」当成全市场结论。
    """
    parts: list[str] = []
    if clamped:
        parts.append(f"参数已被裁剪：{'，'.join(clamped)}")
    if truncated:
        parts.append("返回正文超长已截断")
    if not parts:
        return ""
    return "\n[取数范围提示] " + "；".join(parts) + "。以上不是全量，请勿据此计数或断言「没有」。"


def guarded_client_call(
    client: McpClient,
    name: str,
    arguments: dict[str, Any] | None,
    *,
    pool: McpQuotaPool = "skill",
) -> dict[str, Any]:
    """供 Agent executor 使用：扣 skill 池配额后委托 client.call_tool。"""
    args, clamped = clamp_mcp_arguments_with_notes(arguments)
    try:
        acquire_quota(pool)
        result = client.call_tool(name, args)
        # 与 call_mcp_tool 同一条口径：参数被拒的调用服务端没执行，不记账。
        wasted = _rejected_before_execution(result)
        if not wasted:
            record_quota_call(pool)
        result["quota_charged"] = not wasted
        result["quota"] = quota_snapshot()
        if clamped:
            result["clamped"] = list(clamped)
        note = _scope_note(clamped, truncated=bool(result.get("truncated")))
        if note:
            result["text"] = f"{result.get('text') or ''}{note}"
        return result
    except McpQuotaError as exc:
        return {"text": str(exc), "is_error": True, "quota_exhausted": True}
