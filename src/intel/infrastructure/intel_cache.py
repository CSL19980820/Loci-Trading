"""外部 MCP 情报快照缓存（market.db，可整表删除重建）。

三条纪律写在这里，改之前先读：

1. **写 key 不变**：``args_hash`` 仍是 ``sha256({"tool", "arguments"})[:24]``。
   ``market/infrastructure/tape/cache.py`` 里有一份同算法的副本，两边必须算出
   同一个 digest，否则 tape provider 读不到 ``call_mcp_tool`` 写的行。**动这个
   函数的字节序列 = 让全库既有快照一次性失效**（= 一轮真调用、真扣配额）。
2. **读 key 可复用**：同一工具同一交易日，各子系统各自拼参数，只因为
   ``limit=80/60/100/20`` 这种「回多少行」的差异就各写一行——实测
   ``theme_intraday_capital`` 一天 4 行互不复用，等于缓存对它没生效。读侧因此
   在精确 key 之外再做一次**覆盖度复用**：身份参数（哪一天、哪个工具、哪批
   标的）相同、且已缓存那份的覆盖度**不小于**本次要求时直接兑现。
   为什么不干脆把 limit 踢出写 key：那样宽窄两个入口会互相顶掉对方的行
   （tape 的 20 覆盖不了配方的 80，配方的 80 覆盖不了收盘的 100），5 分钟一轮
   的盯盘和 15 分钟一轮的配方会把彼此的缓存反复作废，比现在更费配额。
   **行照旧一变体一行，复用只发生在读侧。**
3. **失败也要留痕**：负缓存行走独立 key 命名空间（``kind=error``）。一次失败
   不会顶掉上一份还能用的成功快照，成功写入则立刻解除同 key 的冷却。
"""
from __future__ import annotations

import hashlib
import json
import logging
from datetime import datetime, timezone
from typing import Any

from src.market import MarketStore

_TZ = timezone.utc

logger = logging.getLogger(__name__)


# --------------------------------------------------------------------------
# 覆盖度参数：只决定「回多少行 / 回多细」，不决定「这是哪一天的什么事实」
# --------------------------------------------------------------------------
#: 数值型：大的覆盖小的。缺席 = 服务端默认条数，**不可比**（谁也不知道默认是
#: 20 还是 500），所以缺席只与缺席互相兑现。
_NUMERIC_COVERAGE_ARGS: tuple[str, ...] = ("limit", "maxRows", "max_rows", "topN", "top_n")
#: 布尔型：``True`` 覆盖 ``False``（多带一个可选字段不会让事实变少）。缺席按 False。
_FLAG_COVERAGE_ARGS: tuple[str, ...] = ("includeBoomReason", "includeDetail", "withDetail")
#: 有序枚举：细的覆盖粗的。缺席按 ``standard``——``wudao_provider`` 正是
#: ``setdefault("detailLevel", "standard")``，所以「没写」与「写了 standard」
#: 是同一次请求，不该算成两份缓存。认不出来的取值退回严格相等。
_DETAIL_LADDER: dict[str, float] = {
    "minimal": 0.0,
    "basic": 0.0,
    "simple": 0.0,
    "standard": 1.0,
    "normal": 1.0,
    "detailed": 2.0,
    "full": 3.0,
}
_RANKED_COVERAGE_ARGS: dict[str, tuple[dict[str, float], float]] = {
    "detailLevel": (_DETAIL_LADDER, 1.0),
    "detail_level": (_DETAIL_LADDER, 1.0),
}
#: 纯传输编码：``format=json|text`` 只改正文长相，不改事实。载荷里 ``text`` 与
#: ``structured`` 两份都在、消费方读的是 ``structured``，所以它既不进身份 key
#: 也不做覆盖度校验。
_TRANSPORT_ARGS: tuple[str, ...] = ("format",)
#: 「一批代码」是集合不是序列：顺序不同不该算两份缓存。只归一这几个已知键。
_CODE_LIST_ARGS: tuple[str, ...] = ("codes", "stockCodes", "stock_codes")

COVERAGE_ARGS: tuple[str, ...] = (
    *_NUMERIC_COVERAGE_ARGS,
    *_FLAG_COVERAGE_ARGS,
    *tuple(_RANKED_COVERAGE_ARGS),
)

#: 覆盖度复用时最多回扫多少行。同一 (trade_date, tool) 正常只有 2~4 行；
#: 给个上限是不让脏库把一次读缓存拖成全表扫。
_REUSE_SCAN_LIMIT = 24

#: 负缓存的 key 命名空间。空串 = 正缓存（**字节序列必须与旧版一致**，见模块头）。
_ERROR_KIND = "error"

#: 负缓存载荷里记冷却时长的字段：不同失败类型冷却不同，读侧要照写侧记的算。
ERROR_COOLDOWN_KEY = "error_cooldown_minutes"
#: 兜底冷却（分钟）：老行没记 ``ERROR_COOLDOWN_KEY`` 时按它算。
DEFAULT_ERROR_COOLDOWN_MINUTES = 5


def _args_hash(tool: str, arguments: dict[str, Any] | None, *, kind: str = "") -> str:
    """存储 key。``kind`` 为空时的字节序列**不得改动**（见模块头第 1 条）。"""
    body: dict[str, Any] = {"tool": tool, "arguments": arguments or dict()}
    if kind:
        body["kind"] = kind
    payload = json.dumps(body, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()[:24]


def _normalized_day(value: Any) -> str:
    """``20260807`` / ``2026-08-07`` 归一成一种写法；只用于算身份 key。"""
    text = str(value or "").strip()
    digits = "".join(ch for ch in text if ch.isdigit())
    if len(digits) >= 8:
        return f"{digits[:4]}-{digits[4:6]}-{digits[6:8]}"
    return text


def _normalized_dates(tool: str, arguments: dict[str, Any]) -> dict[str, Any]:
    """交易日别名归一到 ``wudao_keys`` 认的那一个键（单一真相源）。

    ``tradeDate`` / ``date`` / ``trade_date`` 指的是同一天，但各调用点写法不同，
    不归一就是同一天算出两个 key。``wudao_keys`` 那张表是实测双向验证过的，
    别在这里再抄一份。
    """
    try:
        from src.intel.application.wudao_keys import (
            DATE_ALIASES,
            date_argument,
            strip_dates,
        )
    except Exception as exc:  # noqa: BLE001 — 键名表不可用不该让取数失败
        logger.debug("悟道键名表不可用，缓存 key 不做日期归一：%s", exc)
        return dict(arguments)
    day = ""
    for alias in DATE_ALIASES:
        value = _normalized_day(arguments.get(alias))
        if value:
            day = value
            break
    if not day:
        return dict(arguments)
    out = strip_dates(arguments)
    # 不收日期的工具（sector_analysis）返回空 dict：日期本来就靠 trade_date 列锁。
    out.update(date_argument(tool, day))
    return out


def canonical_cache_arguments(
    tool: str,
    arguments: dict[str, Any] | None,
) -> dict[str, Any]:
    """算**身份 key** 用的参数：摘掉传输/覆盖度参数，日期与代码集合归一。

    「身份」= 这次要的是哪一天、哪个工具、哪批标的、什么口径；不含「要几行」。
    """
    args = {
        key: value
        for key, value in dict(arguments or dict()).items()
        if value is not None and key not in _TRANSPORT_ARGS and key not in COVERAGE_ARGS
    }
    for key in _CODE_LIST_ARGS:
        value = args.get(key)
        if isinstance(value, (list, tuple, set)):
            args[key] = sorted(str(item) for item in value)
    return _normalized_dates(tool, args)


def cache_identity_key(tool: str, arguments: dict[str, Any] | None) -> str:
    """同工具同交易日的**复用键**：不同入口只要问的是同一份事实就相等。

    存储 key（``_args_hash``）仍按完整参数一变体一行；这个键决定「哪些行之间
    可以互相兑现」。测试与 tape 缓存 provider 都用它，别再各算一份。
    """
    return _args_hash(tool, canonical_cache_arguments(tool, arguments))


def coverage_arguments(arguments: dict[str, Any] | None) -> dict[str, Any]:
    """本次请求的覆盖度诉求（要几行、要不要那几个可选字段）。"""
    args = dict(arguments or dict())
    return {key: args[key] for key in COVERAGE_ARGS if args.get(key) is not None}


def _numeric(value: Any) -> float | None:
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _coverage_rank(name: str, arguments: dict[str, Any]) -> float | None:
    """该参数的可比刻度；``None`` = 认不出来，读侧退回严格相等。"""
    value = arguments.get(name)
    if name in _NUMERIC_COVERAGE_ARGS:
        # 缺席 = 服务端默认条数，与任何显式条数都不可比。
        return None if value is None else _numeric(value)
    if name in _FLAG_COVERAGE_ARGS:
        return 1.0 if bool(value) else 0.0
    ladder, absent_rank = _RANKED_COVERAGE_ARGS[name]
    if value is None:
        return absent_rank
    return ladder.get(str(value).strip().lower())


def coverage_covers(
    cached_arguments: dict[str, Any] | None,
    wanted_arguments: dict[str, Any] | None,
) -> bool:
    """已缓存那份的覆盖度是否**不小于**本次要求。

    只有「缓存里那份是本次要求的超集」才算命中：宁可多回几行，也不能把
    limit=60 的半张榜当成 limit=100 的全榜发下去。
    """
    cached = dict(cached_arguments or dict())
    wanted = dict(wanted_arguments or dict())
    for name in COVERAGE_ARGS:
        cached_rank = _coverage_rank(name, cached)
        wanted_rank = _coverage_rank(name, wanted)
        if cached_rank is None or wanted_rank is None:
            if cached.get(name) != wanted.get(name):
                return False
            continue
        if cached_rank < wanted_rank:
            return False
    return True


def ensure_intel_cache_table(store: MarketStore) -> None:
    """DDL 归属 market.db；经 MarketStore 幂等补齐，禁止旁路 CREATE。"""
    store.ensure_intel_snapshots_schema()


def cache_age_minutes(fetched_at: str) -> float | None:
    """快照距今多久（分钟）。时间戳缺失或不可解析返回 None。

    旧库可能留下不带时区的 ``fetched_at``；naive 与 aware 相减会抛
    ``TypeError``，必须在这里收口，否则会顺着 call_mcp_tool 炸到调用方。
    """
    text = str(fetched_at or "").strip()
    if not text:
        return None
    try:
        stamp = datetime.fromisoformat(text.replace("Z", "+00:00"))
        return (datetime.now(stamp.tzinfo or _TZ) - stamp).total_seconds() / 60.0
    except (TypeError, ValueError):
        return None


def _fresh_enough(age: float | None, max_age_minutes: int | None) -> bool:
    if max_age_minutes is None or max_age_minutes <= 0:
        return True
    # 算不出年龄的快照按不可用处理：宁可回源，也不把来历不明的旧数据当新的。
    return age is not None and age <= max_age_minutes


def _payload_of(row: Any) -> dict[str, Any] | None:
    try:
        payload = json.loads(str(row["payload_json"] or "null"))
    except json.JSONDecodeError:
        return None
    return payload if isinstance(payload, dict) else None


def _stamped(payload: dict[str, Any], fetched_at: str, age: float | None) -> dict[str, Any]:
    # 缓存必须自报时点：调用方/模型据此判断「这是几点的快照」，不当实时用。
    return {
        **payload,
        "cache_fetched_at": fetched_at,
        "cache_age_minutes": round(age, 1) if age is not None else None,
    }


def read_cached_snapshot(
    store: MarketStore,
    *,
    trade_date: str,
    tool: str,
    arguments: dict[str, Any] | None,
    max_age_minutes: int | None = None,
) -> dict[str, Any] | None:
    """先按精确参数命中，再按覆盖度复用同交易日的其它变体（见模块头第 2 条）。"""
    ensure_intel_cache_table(store)
    row = store.conn.execute(
        """
        SELECT payload_json, fetched_at FROM intel_snapshots
        WHERE trade_date = ? AND tool = ? AND args_hash = ?
        """,
        (trade_date, tool, _args_hash(tool, arguments)),
    ).fetchone()
    if row is not None:
        fetched_at = str(row["fetched_at"] or "")
        age = cache_age_minutes(fetched_at)
        payload = _payload_of(row)
        if payload is not None and _fresh_enough(age, max_age_minutes):
            return _stamped(payload, fetched_at, age)
    # 精确 key 未命中/太旧，不代表这份事实今天没抓过：可能是别的入口用更宽的
    # 参数抓过一份（open 的 limit=80 完全够 intraday 的 limit=60 用）。
    return _read_reusable_snapshot(
        store,
        trade_date=trade_date,
        tool=tool,
        arguments=arguments,
        max_age_minutes=max_age_minutes,
    )


def _read_reusable_snapshot(
    store: MarketStore,
    *,
    trade_date: str,
    tool: str,
    arguments: dict[str, Any] | None,
    max_age_minutes: int | None,
) -> dict[str, Any] | None:
    """同交易日同工具里找一份「身份相同、覆盖度够」的快照。

    只认载荷里自报了 ``arguments`` 的行（``call_mcp_tool`` 写的都有）。旧行与
    ``tape/cache.py::write_tape_cache`` 写的行没有这个字段，覆盖度无从判断，
    一律跳过——只走精确 key，行为与改动前一致。
    """
    wanted_identity = cache_identity_key(tool, arguments)
    rows = store.conn.execute(
        """
        SELECT payload_json, fetched_at FROM intel_snapshots
        WHERE trade_date = ? AND tool = ?
        ORDER BY fetched_at DESC
        LIMIT ?
        """,
        (trade_date, tool, _REUSE_SCAN_LIMIT),
    ).fetchall()
    for row in rows:
        payload = _payload_of(row)
        if payload is None or payload.get("is_error"):
            continue
        stored_args = payload.get("arguments")
        if not isinstance(stored_args, dict):
            continue
        if cache_identity_key(tool, stored_args) != wanted_identity:
            continue
        if not coverage_covers(stored_args, arguments):
            continue
        fetched_at = str(row["fetched_at"] or "")
        age = cache_age_minutes(fetched_at)
        if not _fresh_enough(age, max_age_minutes):
            continue
        stamped = _stamped(payload, fetched_at, age)
        # 复用了别的入口那一份：核账的人和读正文的人都得看得见这件事。
        stamped["cache_reused_arguments"] = dict(stored_args)
        return stamped
    return None


def list_latest_snapshots(
    store: MarketStore,
    *,
    trade_date: str,
    tools: list[str] | None = None,
) -> dict[str, dict[str, Any]]:
    """按工具取该交易日最新一条快照（忽略 args_hash；同工具多参取最新 fetched_at）。

    返回 ``{tool: 载荷 / fetched_at / server / args_hash}``；可整表删除重建。
    负缓存行（失败载荷）不参与投影——盘面摘要要的是事实，不是一条错误正文。
    """
    ensure_intel_cache_table(store)
    day = str(trade_date or "").strip()
    if not day:
        return dict()
    wanted = set(str(t).strip() for t in (tools or []) if str(t).strip())
    sql = (
        "SELECT tool, args_hash, server, payload_json, fetched_at "
        "FROM intel_snapshots WHERE trade_date = ? "
        "ORDER BY fetched_at DESC"
    )
    rows = store.conn.execute(sql, (day,)).fetchall()
    out: dict[str, dict[str, Any]] = dict()
    for row in rows:
        tool = str(row["tool"] or "").strip()
        if not tool or tool in out:
            continue
        if wanted and tool not in wanted:
            continue
        payload = _payload_of(row)
        if payload is None or payload.get("is_error"):
            continue
        out[tool] = {
            "payload": payload,
            "fetched_at": str(row["fetched_at"] or ""),
            "server": str(row["server"] or ""),
            "args_hash": str(row["args_hash"] or ""),
        }
    return out


def _upsert_snapshot(
    store: MarketStore,
    *,
    trade_date: str,
    tool: str,
    digest: str,
    server: str,
    payload: dict[str, Any],
) -> None:
    now = datetime.now(_TZ).isoformat(timespec="seconds")
    store.conn.execute(
        """
        INSERT INTO intel_snapshots(
            trade_date, tool, args_hash, server, payload_json, fetched_at
        ) VALUES(?, ?, ?, ?, ?, ?)
        ON CONFLICT(trade_date, tool, args_hash) DO UPDATE SET
            server = excluded.server,
            payload_json = excluded.payload_json,
            fetched_at = excluded.fetched_at
        """,
        (trade_date, tool, digest, server, json.dumps(payload, ensure_ascii=False), now),
    )
    store.conn.commit()


def write_cached_snapshot(
    store: MarketStore,
    *,
    trade_date: str,
    tool: str,
    arguments: dict[str, Any] | None,
    server: str,
    payload: dict[str, Any],
) -> None:
    ensure_intel_cache_table(store)
    _upsert_snapshot(
        store,
        trade_date=trade_date,
        tool=tool,
        digest=_args_hash(tool, arguments),
        server=server,
        payload=payload,
    )
    # 成功立刻解除同 key 的失败冷却，不留惩罚期（与 em_industry 同一条口径）。
    clear_cached_error(store, trade_date=trade_date, tool=tool, arguments=arguments)


def write_cached_error(
    store: MarketStore,
    *,
    trade_date: str,
    tool: str,
    arguments: dict[str, Any] | None,
    server: str,
    payload: dict[str, Any],
    cooldown_minutes: int,
) -> None:
    """写负缓存：冷却期内同一份参数不再真调、也不再扣额。

    行走 ``kind=error`` 的独立命名空间，**不会**顶掉同参数上一份还能用的成功
    快照——「这次调用失败了」和「上午那份数据还在」是两件事。
    """
    ensure_intel_cache_table(store)
    minutes = int(cooldown_minutes or DEFAULT_ERROR_COOLDOWN_MINUTES)
    body = {**payload, ERROR_COOLDOWN_KEY: max(1, minutes)}
    _upsert_snapshot(
        store,
        trade_date=trade_date,
        tool=tool,
        digest=_args_hash(tool, arguments, kind=_ERROR_KIND),
        server=server,
        payload=body,
    )


def read_cached_error(
    store: MarketStore,
    *,
    trade_date: str,
    tool: str,
    arguments: dict[str, Any] | None,
) -> dict[str, Any] | None:
    """冷却期内的失败快照；冷却已过（或算不出年龄）返回 None = 该回源了。

    冷却时长按**写侧记在载荷里的那一份**算：参数被拒和业务错误不是一个量级，
    读侧不该自己再猜一个 TTL。
    """
    ensure_intel_cache_table(store)
    row = store.conn.execute(
        """
        SELECT payload_json, fetched_at FROM intel_snapshots
        WHERE trade_date = ? AND tool = ? AND args_hash = ?
        """,
        (trade_date, tool, _args_hash(tool, arguments, kind=_ERROR_KIND)),
    ).fetchone()
    if row is None:
        return None
    payload = _payload_of(row)
    if payload is None:
        return None
    fetched_at = str(row["fetched_at"] or "")
    age = cache_age_minutes(fetched_at)
    cooldown = _numeric(payload.get(ERROR_COOLDOWN_KEY))
    if cooldown is None or cooldown <= 0:
        cooldown = float(DEFAULT_ERROR_COOLDOWN_MINUTES)
    if age is None or age > cooldown:
        return None
    stamped = _stamped(payload, fetched_at, age)
    stamped["error_cached"] = True
    stamped["retry_after_minutes"] = round(max(0.0, cooldown - age), 1)
    return stamped


def clear_cached_error(
    store: MarketStore,
    *,
    trade_date: str,
    tool: str,
    arguments: dict[str, Any] | None,
) -> None:
    """解除同参数的失败冷却。"""
    store.conn.execute(
        "DELETE FROM intel_snapshots WHERE trade_date = ? AND tool = ? AND args_hash = ?",
        (trade_date, tool, _args_hash(tool, arguments, kind=_ERROR_KIND)),
    )
    store.conn.commit()


__all__ = [
    "COVERAGE_ARGS",
    "DEFAULT_ERROR_COOLDOWN_MINUTES",
    "ERROR_COOLDOWN_KEY",
    "cache_age_minutes",
    "cache_identity_key",
    "canonical_cache_arguments",
    "clear_cached_error",
    "coverage_arguments",
    "coverage_covers",
    "ensure_intel_cache_table",
    "list_latest_snapshots",
    "read_cached_error",
    "read_cached_snapshot",
    "write_cached_error",
    "write_cached_snapshot",
]
