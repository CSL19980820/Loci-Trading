"""每用户**自建**定时任务条数配额（identity ``user_quotas.job_slots``）。

为什么要有这个闸门
------------------
定时任务是「按时间自动占用整台机器」的权利：一条 ``*/1`` 的 cron 就能让一个
普通成员每分钟拉起一轮选股。额度必须挂在**人**身上，和 LLM Token 一样
（形状照抄 ``src/ai/application/quota.py``，两处口径保持一致：正数是硬顶、
负数是不限、0 表示「用系统默认」）。

关键取舍（改之前先读完这三条）
------------------------------
1. **托管任务不占额度。** 子租户开箱就有 7~8 条托管任务（候选 T+N 跟踪、
   3 条 ``screen:<slug>``、3 档情报采集、价格提醒扫描）。它们是系统给的，
   不是用户建的；算进额度的话，新用户第一次登录、``ensure_tenant_jobs``
   刚跑完就已经超额，连一条自己的任务都建不了。名单来源是
   ``src/ops/infrastructure/store_helpers.py`` 的 ``MANAGED_*`` 常量
   （外加情报 / 价格提醒 / 盘中留存三个模块里的同类常量）**加上 ``screen:``
   前缀**——战法目录是会增减的，按前缀判据才不会每加一个战法就漏一次。
2. **闸门只能放在 API 层**（``src/ops/api/jobs.py`` 的 create），
   **绝不能放进 ``OpsStore.create_job`` / ``ensure_job``**。
   ``ensure_managed_jobs._ensure_step`` 对异常只打一行 warning：闸门放到存储层，
   启动时的托管确保会在超额租户上**静默失败**——用户的选股任务从此不再存在，
   页面上却什么都不说。存储层是托管任务的必经之路，治理手段不该长在那儿。
3. **身份库不可用时降级为默认值。** identity.db 打不开 / schema 没建 /
   该租户没有账号，一律回落 :data:`DEFAULT_JOB_SLOTS`，绝不因为读不到配额就把
   任务 CRUD 整个卡死。配额是治理手段，不是业务前提。

边界：跨上下文只走包根 ``from src.identity import IdentityStore``，禁止深路径。
"""
from __future__ import annotations

import logging
from collections.abc import Mapping
from typing import Any

logger = logging.getLogger(__name__)

#: 拿不到 ``job_slots`` 时的兜底条数上限。与 identity ``DEFAULT_QUOTAS`` 一致。
DEFAULT_JOB_SLOTS = 5

#: identity ``user_quotas`` 的列名，一字不差。
QUOTA_KEY = "job_slots"

#: 对外统一用负数表达「不限」（identity 里的 0 含义是「用系统默认」，不能混）。
UNLIMITED = -1

#: 托管任务名前缀。``screen:<slug>`` 由 ``ensure_managed_screen_jobs`` 按活动
#: 战法目录增删，条数随目录变化，只能按前缀判，不能列名单。
MANAGED_JOB_PREFIXES: tuple[str, ...] = ("screen:",)

#: 托管任务名散落在各 ``ensure_*`` 模块里的常量（store_helpers 之外的那几个）。
_EXTRA_MANAGED_SOURCES: tuple[tuple[str, tuple[str, ...]], ...] = (
    (
        "src.ops.application.ensure_intel_jobs",
        ("MANAGED_INTEL_OPEN", "MANAGED_INTEL_INTRADAY", "MANAGED_INTEL_CLOSE"),
    ),
    (
        "src.ops.application.ensure_intel_brief_jobs",
        (
            "MANAGED_BRIEF_OPEN",
            "MANAGED_BRIEF_MIDDAY",
            "MANAGED_BRIEF_CLOSE",
            "MANAGED_BRIEF_EVENING",
        ),
    ),
    ("src.ops.application.ensure_alert_scan_job", ("MANAGED_ALERT_SCAN",)),
    (
        "src.ops.application.ensure_intraday_capture_job",
        ("MANAGED_INTRADAY_CAPTURE",),
    ),
)


class JobQuotaExceeded(RuntimeError):
    """当前用户自建的定时任务条数已达上限。"""


def managed_job_names() -> frozenset[str]:
    """系统托管任务名的全集。**这些任务不占用户额度。**

    从各 ``ensure_*`` 模块的常量现取，不在这里抄第二份字面量：抄一份就意味着
    改名时有一处会忘，而忘掉的后果是用户的托管任务开始吃自己的额度。
    """
    names: set[str] = set()
    try:
        from src.ops.infrastructure import store_helpers

        for attr in dir(store_helpers):
            if not attr.startswith("MANAGED_") or attr.endswith("_CRON"):
                continue
            value = getattr(store_helpers, attr)
            if isinstance(value, str) and value.strip():
                names.add(value.strip())
    except Exception as exc:  # noqa: BLE001 — 名单读不到只会少豁免，不该抛
        logger.debug("读取 store_helpers 托管任务名失败：%s", exc)

    for module_path, attrs in _EXTRA_MANAGED_SOURCES:
        try:
            module = __import__(module_path, fromlist=list(attrs))
        except Exception as exc:  # noqa: BLE001
            logger.debug("读取 %s 的托管任务名失败：%s", module_path, exc)
            continue
        for attr in attrs:
            value = getattr(module, attr, "")
            if isinstance(value, str) and value.strip():
                names.add(value.strip())
    return frozenset(names)


def is_managed_job(row: Mapping[str, Any]) -> bool:
    """这一行任务是不是系统托管的（= 不占额度）。

    判据两条：名字在 :func:`managed_job_names` 里，或者名字以 ``screen:`` 开头。
    """
    name = str(row.get("name") or "").strip()
    if not name:
        return False
    if name in managed_job_names():
        return True
    return any(name.startswith(prefix) for prefix in MANAGED_JOB_PREFIXES)


def _current_user_id() -> str:
    """当前租户对应的 identity 用户 id；查不到返回空串（调用方据此降级）。

    库文件不存在时**直接返回**，不去 open：``IdentityStore()`` 会顺手把空库建
    出来，而这是一条只读的配额查询路径，不该在磁盘上留下副作用。
    """
    from src.shared.paths import identity_db
    from src.shared.tenancy import current_tenant

    tenant = current_tenant()
    try:
        if not identity_db().exists():
            return ""
        from src.identity import IdentityStore

        with IdentityStore() as store:
            row = store.conn.execute(
                "SELECT id FROM users WHERE tenant_id = ?", (tenant,)
            ).fetchone()
    except Exception as exc:  # noqa: BLE001 — 身份库不可用绝不能卡死任务 CRUD
        logger.debug("identity 不可用，任务配额回退默认值：%s", exc)
        return ""
    return str(row["id"]) if row is not None else ""


def current_job_quota() -> int:
    """当前用户能自建多少条定时任务。

    正数是硬顶，负数（:data:`UNLIMITED`）是不限，**永远不会是 0**：identity 里的
    0 表示「用系统默认」，直接当成 0 条会把所有没配过额度的用户锁死。
    身份库任何一环读不出来，都退回 :data:`DEFAULT_JOB_SLOTS`。
    """
    user_id = _current_user_id()
    if not user_id:
        return DEFAULT_JOB_SLOTS
    try:
        from src.identity import IdentityStore

        with IdentityStore() as store:
            raw = dict(store.get_quota(user_id)).get(QUOTA_KEY, 0)
    except Exception as exc:  # noqa: BLE001
        logger.debug("读取 job_slots 失败，回退默认值：%s", exc)
        return DEFAULT_JOB_SLOTS
    try:
        value = int(raw or 0)
    except (TypeError, ValueError):
        value = 0
    if value == 0:
        return DEFAULT_JOB_SLOTS
    return value if value > 0 else UNLIMITED


def count_user_jobs(store: Any) -> int:
    """当前租户的**非托管**任务条数。读不动就按 0 计（降级优先于正确）。"""
    try:
        rows = store.list_jobs()
    except Exception as exc:  # noqa: BLE001
        logger.debug("统计自建任务条数失败，按 0 计：%s", exc)
        return 0
    return sum(1 for row in rows if not is_managed_job(row))


def check_job_quota(store: Any) -> None:
    """新建任务前的闸门。超额抛 :class:`JobQuotaExceeded`。

    **只在 API 层调用**（见模块头第 2 条）：托管任务的确保路径经过
    ``OpsStore.create_job`` / ``ensure_job``，把闸门放那儿会让启动期的托管确保
    静默失败——``_ensure_step`` 对异常只打一行 warning。
    """
    limit = current_job_quota()
    if limit < 0:
        return
    used = count_user_jobs(store)
    if used >= limit:
        raise JobQuotaExceeded(
            f"自建定时任务已达上限（{used} / {limit} 条）。"
            "请先删除不用的任务，或联系管理员提高 job_slots 配额；"
            "系统托管任务（选股 / 情报 / 候选跟踪等）不占用这个额度。"
        )


def job_quota_status(store: Any) -> dict[str, Any]:
    """给前端的额度概况：``{used, limit, unlimited, managed}``。

    ``managed`` 是被豁免的托管任务条数——不报出来的话，用户看到「5 条上限」
    却在列表里数出 12 条任务，只会以为额度算错了。
    """
    limit = current_job_quota()
    try:
        rows = list(store.list_jobs())
    except Exception as exc:  # noqa: BLE001
        logger.debug("读取任务列表失败，额度概况按空表计：%s", exc)
        rows = []
    managed = sum(1 for row in rows if is_managed_job(row))
    return {
        "used": len(rows) - managed,
        "limit": limit,
        "unlimited": limit < 0,
        "managed": managed,
    }


__all__ = [
    "DEFAULT_JOB_SLOTS",
    "JobQuotaExceeded",
    "MANAGED_JOB_PREFIXES",
    "QUOTA_KEY",
    "UNLIMITED",
    "check_job_quota",
    "count_user_jobs",
    "current_job_quota",
    "is_managed_job",
    "job_quota_status",
    "managed_job_names",
]
