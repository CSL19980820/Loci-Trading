"""悟道 MCP 日配额与分池预算（structured / skill）。

- 总量默认 5000/天、50/分（与套餐一致，可用环境变量覆盖）
- structured 池默认 3000：托管 intel_fetch 任务
- skill 池默认 2000：Agent / skill 临机调用
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
import os
import threading
import time
from typing import Any, Literal

from src.intel.infrastructure.wudao_settings import wudao_quota_config
from src.ops import OpsStore
from src.shared.paths import ops_db

McpQuotaPool = Literal["structured", "skill"]

_TZ = timezone(timedelta(hours=8))
_THREAD_LOCK = threading.RLock()
_MINUTE_WINDOW: list[float] = []
#: 已放行但尚未记账的在途调用（pool → 过期时刻）。日计数落在 ops.db 且只在
#: 调用成功后 +1，并发扫描会在同一个旧计数上各自过闸，把池子打穿；这里在进程内
#: 先占位。超时兜底：调用最长 60s（McpClient DEFAULT_TIMEOUT），失败路径不记账，
#: 占位到期自动释放，不需要调用方显式回滚。
_INFLIGHT_TTL_SECONDS = 120.0
_INFLIGHT: dict[str, list[float]] = {"structured": [], "skill": []}

#: 每分钟名额的滑动窗口长度（供测试收窄）
_MINUTE_WINDOW_SECONDS = 60.0
#: 等名额的上限。窗口本身就是 60s，等更久说明不是节流而是别的问题。
_MINUTE_WAIT_MAX_SECONDS = 65.0


class McpQuotaError(RuntimeError):
    """配额或限速用尽。"""


@dataclass(frozen=True)
class McpQuotaLimits:
    daily_total: int
    structured: int
    skill: int
    per_minute: int


def _env_int(name: str, default: int) -> int:
    raw = os.environ.get(name, "").strip()
    if not raw:
        return default
    try:
        return max(0, int(raw))
    except ValueError:
        return default


def quota_limits() -> McpQuotaLimits:
    cfg = wudao_quota_config()
    daily = _env_int("LOCI_MCP_QUOTA_DAILY", cfg["daily_total"])
    structured = _env_int("LOCI_MCP_QUOTA_STRUCTURED", cfg["daily_structured"])
    skill = _env_int("LOCI_MCP_QUOTA_SKILL", cfg["daily_skill"])
    per_minute = _env_int("LOCI_MCP_RATE_PER_MIN", cfg["per_minute"])
    if structured + skill > daily:
        skill = max(0, daily - structured)
    return McpQuotaLimits(
        daily_total=daily,
        structured=structured,
        skill=skill,
        per_minute=per_minute,
    )


def trade_date_today() -> str:
    return datetime.now(_TZ).date().isoformat()


def _read_counts(trade_date: str) -> dict[str, int]:
    path = ops_db()
    if not path.is_file():
        return {"structured": 0, "skill": 0}
    with OpsStore(path) as store:
        return store.read_mcp_quota_counts(trade_date)


def quota_snapshot(*, trade_date: str | None = None) -> dict[str, Any]:
    day = trade_date or trade_date_today()
    limits = quota_limits()
    counts = _read_counts(day)
    total_used = counts["structured"] + counts["skill"]
    return {
        "trade_date": day,
        "limits": {
            "daily_total": limits.daily_total,
            "structured": limits.structured,
            "skill": limits.skill,
            "per_minute": limits.per_minute,
        },
        "used": {
            "structured": counts["structured"],
            "skill": counts["skill"],
            "total": total_used,
        },
        "remaining": {
            "structured": max(0, limits.structured - counts["structured"]),
            "skill": max(0, limits.skill - counts["skill"]),
            "total": max(0, limits.daily_total - total_used),
        },
    }


def _minute_slot_wait(per_minute: int, now: float) -> float:
    """距下一个可用名额还差几秒；0 表示当前可发。调用方须持 ``_THREAD_LOCK``。"""
    global _MINUTE_WINDOW
    if per_minute <= 0:
        return 0.0
    _MINUTE_WINDOW = [stamp for stamp in _MINUTE_WINDOW if stamp >= now - _MINUTE_WINDOW_SECONDS]
    if len(_MINUTE_WINDOW) < per_minute:
        return 0.0
    # 最早那次调用滑出窗口时就腾出一个名额
    return max(0.0, _MINUTE_WINDOW[0] + _MINUTE_WINDOW_SECONDS - now)


def clear_quota_reservations() -> None:
    """丢弃全部在途占位与每分钟名额窗口；供测试与运维热恢复使用。"""
    global _MINUTE_WINDOW
    with _THREAD_LOCK:
        for pending in _INFLIGHT.values():
            pending.clear()
        _MINUTE_WINDOW = []


def _prune_inflight(now: float) -> None:
    for pool, pending in _INFLIGHT.items():
        _INFLIGHT[pool] = [deadline for deadline in pending if deadline > now]


def acquire_quota(pool: McpQuotaPool) -> dict[str, Any]:
    """占用一次配额。日配额用尽抛 McpQuotaError；每分钟名额满则**排队等待**。

    检查与占位在同一把锁里完成，避免多线程读到同一个旧计数后一起过闸；等待放在
    锁外，否则一个被节流的调用会把其它线程一起堵住。

    日配额和每分钟名额是两回事，不能同样处理：前者今天真的没了，后者只是这一
    瞬间发太快。把后者判失败等于自己的节流器把自己的活干掉——情报 Job 会因
    ``stats.failed>0`` 整体刷红，Skill 侧更糟：取数失败按红线要走失败关闭，
    一次限流就能把结论改成空仓。
    """
    limits = quota_limits()
    day = trade_date_today()
    pool_limit = limits.structured if pool == "structured" else limits.skill
    give_up_at = time.monotonic() + _MINUTE_WAIT_MAX_SECONDS
    while True:
        with _THREAD_LOCK:
            now = time.monotonic()
            _prune_inflight(now)
            counts = _read_counts(day)
            inflight = {name: len(pending) for name, pending in _INFLIGHT.items()}
            pool_used = counts[pool] + inflight.get(pool, 0)
            total_used = (
                counts["structured"] + counts["skill"] + inflight["structured"] + inflight["skill"]
            )
            if pool_limit > 0 and pool_used >= pool_limit:
                label = "结构化采集" if pool == "structured" else "Skill/助手"
                raise McpQuotaError(f"{label}池今日配额已用尽（{pool_used}/{pool_limit}）")
            if limits.daily_total > 0 and total_used >= limits.daily_total:
                raise McpQuotaError(f"MCP 日总配额已用尽（{total_used}/{limits.daily_total}）")
            wait = _minute_slot_wait(limits.per_minute, now)
            if wait <= 0.0:
                _MINUTE_WINDOW.append(now)
                _INFLIGHT[pool].append(now + _INFLIGHT_TTL_SECONDS)
                break
        remaining = give_up_at - time.monotonic()
        if remaining <= 0.0:
            raise McpQuotaError("MCP 每分钟名额等待超时，请降低并发后重试")
        # 睡到最早那次调用滑出窗口；多线程同时醒来由锁内复检兜住。
        time.sleep(min(wait, remaining) + 0.01)
    return quota_snapshot(trade_date=day)


def record_quota_call(pool: McpQuotaPool) -> dict[str, Any]:
    """成功调用后记账。"""
    day = trade_date_today()
    now = datetime.now(_TZ).isoformat(timespec="seconds")
    with _THREAD_LOCK:
        with OpsStore(ops_db()) as store:
            store.increment_mcp_quota_call(trade_date=day, pool=pool, updated_at=now)
        # 先落库再释放占位，否则中间窗口会被并发调用当成"还有余额"。
        if _INFLIGHT[pool]:
            _INFLIGHT[pool].pop(0)
    return quota_snapshot(trade_date=day)
