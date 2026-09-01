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

#: ---------------------------------------------------------------------------
#: 为什么这两个进程级缓存都按租户分桶（结论 + 依据，改之前先读完）
#:
#: 依据：悟道的**凭据是按租户存的**。token 只来自 ``mcp.json``
#: （``src/intel/infrastructure/mcp_config._target_path`` → ``paths.mcp_json_path()``
#: → ``paths._tenant_scoped``），子租户拿到的是 ``data/tenants/<uid>/mcp.json``，
#: 而且 ``_tenant_scoped`` 明确规定 ``PALACE_MCP_JSON`` 这类环境变量**只对主租户
#: 生效**，子租户不会回落到主租户那份文件。也就是说：一个租户 = 一个悟道账号 =
#: 服务端各算各的 5000/天、50/分。没有任何共用账号的路径。
#:
#: ``loci.config.json``（``wudao_quota_config()``）是全局文件，但它存的是**限额
#: 数字**（套餐档位），不是**用量**。所有人同一个套餐 → 同一组上限，这与「用量
#: 各算各的」并不矛盾，别把它当成「配额是全局的」的证据。
#:
#: 结论：日计数（``_read_counts`` 读按租户的 ops.db）、在途占位、每分钟名额窗口
#: **三者口径必须一致，全部按租户**。改之前的代码里前者按租户、后两者按进程，
#: 这个不一致才是真 bug：租户 B 的在途调用会把 A 的已用额度撞高，A 收到假的
#: 「配额已用尽」；B 的 50 次/分也会白白吃掉 A 的本地节流名额，把 A 拖去排队。
#:
#: 反过来说：**哪天真的改成全平台共用一个悟道账号**（凭据挪出 mcp.json 到全局
#: 配置），这三者就得一起改回全局——只改一个又会回到今天这种撕裂状态。
#: ---------------------------------------------------------------------------

#: 租户 → 每分钟名额滑动窗口。本地节流器保护的是**该租户自己那个悟道账号**的
#: 50 次/分，所以按租户分桶；进程级单窗口会让并发租户互相限速。
_MINUTE_WINDOW: dict[str, list[float]] = {}
#: 已放行但尚未记账的在途调用（``(租户, pool)`` → 过期时刻）。日计数落在 ops.db
#: 且只在调用成功后 +1，并发扫描会在同一个旧计数上各自过闸，把池子打穿；这里在
#: 进程内先占位。超时兜底：调用最长 60s（McpClient DEFAULT_TIMEOUT），失败路径
#: 不记账，占位到期自动释放，不需要调用方显式回滚。
#:
#: **key 必须含租户**（同 ``ops/application/notify_registry._recent``）：
#: ``_read_counts()`` 读的是按租户的 ops.db，占位若按进程记，两个口径相加就是
#: 拿 B 的在途量去扣 A 的余额。
_INFLIGHT_TTL_SECONDS = 120.0
_INFLIGHT: dict[tuple[str, str], list[float]] = {}

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


def _tenant() -> str:
    """进程级配额缓存的租户维度。

    照 ``src/ops/application/notify_registry._tenant`` 的范式：容错导入、失败退
    空串。配额判定不该因为租户模块出问题就把整条取数停掉；退空串只会让所有人
    共用一个桶（等于旧行为），不会串到别人的桶里去。
    """
    try:
        from src.shared.tenancy import current_tenant

        return current_tenant()
    except Exception:
        return ""


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


def _minute_slot_wait(tenant: str, per_minute: int, now: float) -> float:
    """距该租户下一个可用名额还差几秒；0 表示当前可发。调用方须持 ``_THREAD_LOCK``。

    ``tenant`` 由调用方传入而不是这里现取：acquire_quota 已经在循环开头取过一次，
    同一轮判定必须用同一个租户，免得中途上下文变了导致「判 A 的闸、占 B 的位」。
    """
    if per_minute <= 0:
        return 0.0
    recent = _MINUTE_WINDOW.get(tenant, [])
    window = [stamp for stamp in recent if stamp >= now - _MINUTE_WINDOW_SECONDS]
    if window:
        _MINUTE_WINDOW[tenant] = window
    else:
        # 窗口空了就把桶删掉，长跑进程不该按历史租户数无限长胖。
        _MINUTE_WINDOW.pop(tenant, None)
    if len(window) < per_minute:
        return 0.0
    # 最早那次调用滑出窗口时就腾出一个名额
    return max(0.0, window[0] + _MINUTE_WINDOW_SECONDS - now)


def clear_quota_reservations() -> None:
    """丢弃**全部租户**的在途占位与每分钟名额窗口；供测试与运维热恢复使用。"""
    with _THREAD_LOCK:
        _INFLIGHT.clear()
        _MINUTE_WINDOW.clear()


def _prune_inflight(now: float) -> None:
    """清掉所有租户的过期占位；空桶顺手删掉（否则租户数就是内存泄漏的量纲）。"""
    for key in list(_INFLIGHT):
        pending = [deadline for deadline in _INFLIGHT[key] if deadline > now]
        if pending:
            _INFLIGHT[key] = pending
        else:
            del _INFLIGHT[key]


def acquire_quota(pool: McpQuotaPool) -> dict[str, Any]:
    """占用一次配额。日配额用尽抛 McpQuotaError；每分钟名额满则**排队等待**。

    检查与占位在同一把锁里完成，避免多线程读到同一个旧计数后一起过闸；等待放在
    锁外，否则一个被节流的调用会把其它线程一起堵住。

    日配额和每分钟名额是两回事，不能同样处理：前者今天真的没了，后者只是这一
    瞬间发太快。把后者判失败等于自己的节流器把自己的活干掉——情报 Job 会因
    ``stats.failed>0`` 整体刷红，Skill 侧更糟：取数失败按红线要走失败关闭，
    一次限流就能把结论改成空仓。

    **每一处计数都必须是同一个租户的**：``_read_counts`` 读按租户的 ops.db，占位与
    每分钟窗口按 ``_tenant()`` 分桶（依据见模块头那段长注释）。三者错开一个，就会
    出现「A 明明没用过，却被 B 的在途调用顶成配额已用尽」。
    """
    limits = quota_limits()
    day = trade_date_today()
    pool_limit = limits.structured if pool == "structured" else limits.skill
    give_up_at = time.monotonic() + _MINUTE_WAIT_MAX_SECONDS
    while True:
        # 每轮重取：等待发生在锁外，理论上跨轮可能换了上下文。
        tenant = _tenant()
        with _THREAD_LOCK:
            now = time.monotonic()
            _prune_inflight(now)
            counts = _read_counts(day)
            structured_inflight = len(_INFLIGHT.get((tenant, "structured"), ()))
            skill_inflight = len(_INFLIGHT.get((tenant, "skill"), ()))
            inflight = {"structured": structured_inflight, "skill": skill_inflight}
            pool_used = counts[pool] + inflight[pool]
            total_used = (
                counts["structured"] + counts["skill"] + structured_inflight + skill_inflight
            )
            if pool_limit > 0 and pool_used >= pool_limit:
                label = "结构化采集" if pool == "structured" else "Skill/助手"
                raise McpQuotaError(f"{label}池今日配额已用尽（{pool_used}/{pool_limit}）")
            if limits.daily_total > 0 and total_used >= limits.daily_total:
                raise McpQuotaError(f"MCP 日总配额已用尽（{total_used}/{limits.daily_total}）")
            wait = _minute_slot_wait(tenant, limits.per_minute, now)
            if wait <= 0.0:
                _MINUTE_WINDOW.setdefault(tenant, []).append(now)
                _INFLIGHT.setdefault((tenant, pool), []).append(now + _INFLIGHT_TTL_SECONDS)
                break
        remaining = give_up_at - time.monotonic()
        if remaining <= 0.0:
            raise McpQuotaError("MCP 每分钟名额等待超时，请降低并发后重试")
        # 睡到最早那次调用滑出窗口；多线程同时醒来由锁内复检兜住。
        time.sleep(min(wait, remaining) + 0.01)
    return quota_snapshot(trade_date=day)


def record_quota_call(pool: McpQuotaPool) -> dict[str, Any]:
    """成功调用后记账。落的是**当前租户**的 ops.db 与当前租户的占位桶。"""
    day = trade_date_today()
    now = datetime.now(_TZ).isoformat(timespec="seconds")
    key = (_tenant(), pool)
    with _THREAD_LOCK:
        with OpsStore(ops_db()) as store:
            store.increment_mcp_quota_call(trade_date=day, pool=pool, updated_at=now)
        # 先落库再释放占位，否则中间窗口会被并发调用当成"还有余额"。
        pending = _INFLIGHT.get(key)
        if pending:
            pending.pop(0)
            if not pending:
                _INFLIGHT.pop(key, None)
    return quota_snapshot(trade_date=day)
