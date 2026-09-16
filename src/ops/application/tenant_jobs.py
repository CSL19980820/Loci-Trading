
"""按租户执行定时任务：谁的任务，就在谁的库里跑。

调度器是**进程内**单例，而 ``ops.db`` 早就随租户分库了（见 ``src/shared/tenancy.py``：
多租户不是「每张表加一列 user_id」，而是「换一个 data 根」）。调度器启动时只
``OpsStore(db_path)`` 打开**一个**库——那是主租户的库。结果子租户
``data/tenants/<id>/ops.db`` 里的任务从来没被装载过：用户在运维页建了选股任务，
UI 上写着「下次触发 15:30」，实际永远不会触发，而且不报错。

本模块给出三件事：``SYSTEM_JOB_KINDS``（哪些 kind 只该跑一份）、
``list_active_tenants``（谁的任务该被装载）、``run_tenant_job``（在正确的租户里执行）。
"""
from __future__ import annotations

import logging
import os
from collections.abc import Iterator
from datetime import datetime
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

from src.ops.application.jobs import JobContext, run_job
from src.ops.application.trading_schedule import is_interval_run_allowed
from src.ops.infrastructure.store import OpsStore
from src.shared.paths import data_dir, identity_db
from src.shared.tenancy import (
    PRIMARY_TENANT,
    list_tenant_ids,
    normalize_tenant,
    tenant_scope,
)

logger = logging.getLogger(__name__)

#: 装载的租户总数上限；再多就该把调度拆成独立进程，而不是硬塞进 web 进程。
DEFAULT_MAX_SCHEDULED_TENANTS = 50

#: 同时执行的**租户级**任务数上限，同时也是 APScheduler ``tenant`` executor 的
#: 线程池宽度。4 核机器上 50 个用户同一分钟选股，不设闸门就是 50 条线程一起抢
#: CPU 与热库读连接，谁都跑不完。
DEFAULT_TENANT_JOB_CONCURRENCY = 2

#: 同时执行的**系统级**任务数上限，也就是 APScheduler ``default`` executor 的
#: 线程池宽度。系统池与租户池**物理隔离**：租户任务再多也只能占满自己那个池，
#: 挤不掉行情同步。此前两者共用 APScheduler 默认的 10 条线程，50 个租户 15:30
#: 同时到期就把线程池全占了，日终重刷根本排不上队。
DEFAULT_SYSTEM_JOB_CONCURRENCY = 4

#: 身份库单页扫描量与总扫描上限（名单异常膨胀时不至于把启动拖死）。
_USER_PAGE = 200
_USER_SCAN_LIMIT = 5000

#: 只在主租户跑一份的 kind。
#:
#: 判据（照着这条加减，别凭感觉）：**它们写的是全局共享的 ``market.db`` /
#: ``market_hot.db``，不是租户私有库**。按租户各跑一份的后果是确定的两条：
#: (1) N 个线程同时写同一个 SQLite 文件，撞写锁，busy_timeout 耗尽后整批同步
#: 失败，谁都拿不到数据；(2) N 份并发请求打同一个上游行情源，直接被限频封成
#: 403，连主租户原本能跑通的那一份也一起挂掉。
#:
#: 行情是**公共事实**，一份就够；选股/盯盘/提醒/情报是**私人事实**，各跑各的。
SYSTEM_JOB_KINDS: frozenset[str] = frozenset(
    {
        "sync",  # 行情同步：写 market.db + 打上游
        "exchange_calendar",  # 公共日历只更新一份
        "hot_rebuild",  # 热库重建：从 market.db 派生 market_hot.db
        "data_quality",  # 行情库体检：全量扫 market.db
        "prune",  # 运维清理：见下方「prune 的例外」
        "intraday_capture",  # 盘中留存采集：上游没有历史，重复抓只会被限频
    }
)

#: prune 的例外（唯一一个不完全符合上面判据的 kind，别当成笔误改掉）：
#: 它删的既有全局产物（盘中留存带目录，ADR-014），也有**租户私有**的
#: ``job_runs`` / ``leader_roles``。放进系统级是取「不重复删全局目录」这一头，
#: 代价是子租户的 job_runs 没人清。当前每租户任务量小、``keep_per_job`` 默认 200,
#: 量级可控；等子租户任务多起来，正确做法是把 prune 拆成 system 段（留存带目录）
#: 与 tenant 段（job_runs / leader_roles），而不是简单地把它挪出这个集合。


def _env_int(name: str, default: int, *, minimum: int = 1) -> int:
    """读整数环境变量。**每次调用都重读**：import 期求值的常量会把进程钉死在
    启动那一刻的值上，测试也没法 monkeypatch。"""
    raw = os.environ.get(name, "").strip()
    if not raw:
        return default
    try:
        value = int(raw)
    except ValueError:
        logger.warning("环境变量 %s=%r 不是整数，回退默认值 %s", name, raw, default)
        return default
    if value < minimum:
        logger.warning("环境变量 %s=%s 小于下限 %s，按下限处理", name, value, minimum)
        return minimum
    return value


def max_scheduled_tenants() -> int:
    return _env_int("LOCI_MAX_SCHEDULED_TENANTS", DEFAULT_MAX_SCHEDULED_TENANTS)


def tenant_job_concurrency() -> int:
    """租户任务线程池宽度 = 租户任务并发上限（APScheduler ``tenant`` executor）。"""
    return _env_int("LOCI_TENANT_JOB_CONCURRENCY", DEFAULT_TENANT_JOB_CONCURRENCY)


def system_job_concurrency() -> int:
    """系统任务线程池宽度（APScheduler ``default`` executor）。

    系统池只装主租户的任务：行情同步、热库重建、库体检、清理、盘中留存。它与
    租户池**物理隔离**，所以 50 个租户在 15:30 同时到期也挤不掉 15:10 的日终重刷。
    """
    return _env_int("LOCI_SYSTEM_JOB_CONCURRENCY", DEFAULT_SYSTEM_JOB_CONCURRENCY)


def is_system_job_kind(kind: Any) -> bool:
    return str(kind or "").strip() in SYSTEM_JOB_KINDS


def _identity_tenant_ids() -> list[str] | None:
    """身份库里 ``status='active'`` 用户的 ``tenant_id``。

    ``None`` = **身份库不可用**（未初始化 / 打不开 / 读不动），调用方据此降级为只跑
    主租户。``[]`` 是另一回事：库好好的，只是没有活跃子用户。两者最终都只跑主租户，
    但不能混为一谈——前者要告警，后者是正常的单机形态。
    """
    try:
        path = Path(identity_db())
    except Exception:  # noqa: BLE001 — 配置炸了不能拖垮调度装载
        logger.warning("解析 identity.db 路径失败，租户名单降级为仅主租户", exc_info=True)
        return None
    if not path.exists():
        # 不能让 IdentityStore 顺手把空库建出来：这里是只读盘点路径。
        logger.debug("identity.db 不存在（%s），租户名单降级为仅主租户", path)
        return None
    try:
        # 跨上下文只走包根，禁止深路径：``src.identity.infrastructure`` 受
        # .importlinter 的 protect-identity-infra 合约保护（同 ai/application/quota.py）。
        from src.identity import IdentityStore
    except Exception:  # noqa: BLE001 — identity 上下文缺失时 ops 仍要能调度
        logger.warning("identity 模块不可用，租户名单降级为仅主租户", exc_info=True)
        return None
    try:
        out: list[str] = []
        with IdentityStore(path) as store:
            offset = 0
            while offset < _USER_SCAN_LIMIT:
                page = store.list_users(limit=_USER_PAGE, offset=offset, status="active")
                if not page:
                    break
                out.extend(str(getattr(user, "tenant_id", "") or "") for user in page)
                if len(page) < _USER_PAGE:
                    break
                offset += _USER_PAGE
        return out
    except Exception:  # noqa: BLE001 — 身份库锁死/损坏时主租户任务照跑
        logger.warning("读取 identity.db 名单失败，租户名单降级为仅主租户", exc_info=True)
        return None


def active_tenant_roster(
    *,
    max_tenants: int | None = None,
    data_root: Path | None = None,
) -> dict[str, Any]:
    """该装载哪些租户，外加截断/降级的事实供观测。

    主租户**永远在列且永远排第一**：系统级任务挂在它身上，它掉了等于行情停更。
    """
    limit = max_scheduled_tenants() if max_tenants is None else max(1, int(max_tenants))
    root = Path(data_root) if data_root is not None else data_dir()

    identity_ids = _identity_tenant_ids()
    if identity_ids is None:
        return {
            "tenants": [PRIMARY_TENANT],
            "total": 1,
            "truncated": False,
            "degraded": True,
        }

    # 身份库是权威名单，磁盘是「这个人到底有没有过数据」。取交集的理由：刚注册
    # 还没进过任何页面的用户没有 ops.db，为他建库只为跑一轮空选股，纯属给每个新
    # 注册用户白送一堆 job_runs 噪声。
    on_disk = set(list_tenant_ids(root))
    seen: set[str] = {PRIMARY_TENANT}
    candidates: list[str] = []
    for raw in identity_ids:
        try:
            tenant_id = normalize_tenant(raw)
        except Exception:  # noqa: BLE001 — 单条脏数据不该拖垮整份名单
            logger.warning("跳过非法租户 id %r", raw)
            continue
        if tenant_id in seen or tenant_id not in on_disk:
            continue
        seen.add(tenant_id)
        candidates.append(tenant_id)

    # 排序只为让截断稳定可复现：同样的名单每次装载同样的前 N 个。
    candidates.sort()
    total = len(candidates) + 1  # +1 = 主租户
    truncated = total > limit
    if truncated:
        logger.warning(
            "活跃租户 %s 个，超过 LOCI_MAX_SCHEDULED_TENANTS=%s，只装载前 %s 个；其余"
            "租户的定时任务不会触发。要么调高上限，要么把调度拆成独立进程。",
            total,
            limit,
            limit,
        )
        candidates = candidates[: max(0, limit - 1)]

    return {
        "tenants": [PRIMARY_TENANT, *candidates],
        "total": total,
        "truncated": truncated,
        "degraded": False,
    }


def list_active_tenants(
    *,
    max_tenants: int | None = None,
    data_root: Path | None = None,
) -> list[str]:
    """该装载定时任务的租户 id；首项恒为主租户。"""
    roster = active_tenant_roster(max_tenants=max_tenants, data_root=data_root)
    return list(roster["tenants"])


def tenant_job_rows(
    tenant_id: str, *, db_path: str | Path | None = None
) -> list[dict[str, Any]]:
    """某个租户**该被装载**的启用任务行。子租户自动滤掉系统级 kind。"""
    resolved = normalize_tenant(tenant_id)
    primary = resolved == PRIMARY_TENANT
    with tenant_scope(resolved):
        # 子租户必须传 None：``PALACE_OPS_DB`` 这类环境变量只对主租户生效，硬塞
        # db_path 会让所有租户写进同一个文件，隔离当场失效。
        with OpsStore(db_path if primary else None) as store:
            rows = store.list_jobs(enabled_only=True)
    if primary:
        return rows
    return [row for row in rows if not is_system_job_kind(row.get("kind"))]


def iter_tenant_plans(
    *,
    max_tenants: int | None = None,
    data_root: Path | None = None,
    db_path: str | Path | None = None,
    tenants: list[str] | None = None,
) -> Iterator[tuple[str, dict[str, Any]]]:
    """产出 ``(tenant_id, job_row)``：主租户全部任务 + 其他租户的非系统级任务。"""
    roster = (
        list(tenants)
        if tenants is not None
        else list_active_tenants(max_tenants=max_tenants, data_root=data_root)
    )
    for tenant_id in roster:
        try:
            rows = tenant_job_rows(tenant_id, db_path=db_path)
        except Exception:  # noqa: BLE001 — 一个租户的库坏了不该让别人也不调度
            logger.warning("读取租户 %s 的任务表失败，本轮跳过", tenant_id, exc_info=True)
            continue
        for row in rows:
            yield tenant_id, row


def run_tenant_job(
    tenant_id: str,
    job_id: str,
    *,
    context: JobContext | None = None,
    trigger: str = "schedule",
    now: datetime | None = None,
    timezone: str = "Asia/Shanghai",
    db_path: str | Path | None = None,
) -> dict[str, Any] | None:
    """在目标租户的上下文里执行一个任务。

    ``None`` = 本轮没执行（任务已删 / 不在 interval 窗口 / 被拒）。异常不外抛：
    ``run_job`` 已把过程完整落进 ``job_runs``，这里只兜住调度线程。
    """
    resolved = normalize_tenant(tenant_id)
    primary = resolved == PRIMARY_TENANT
    try:
        with tenant_scope(resolved):
            with OpsStore(db_path if primary else None) as store:
                job = store.get_job(job_id)
                if job is None:
                    logger.warning("任务 %s（租户 %s）已不存在，跳过", job_id, resolved)
                    return None
                if not primary and is_system_job_kind(job.get("kind")):
                    # 兜底：装载期已滤过一次，这里再挡一次。系统级任务在子租户跑
                    # 起来就是撞 market.db 写锁 + 把上游打成 403。
                    logger.warning(
                        "拒绝在子租户 %s 执行系统级任务 %s（kind=%s）",
                        resolved,
                        job.get("name"),
                        job.get("kind"),
                    )
                    return None
                config = job.get("config")
                schedule = config.get("schedule") if isinstance(config, dict) else None
                clock = now or datetime.now(ZoneInfo(timezone))
                if not is_interval_run_allowed(schedule, now=clock):
                    logger.debug(
                        "任务 %s（租户 %s）不在 interval 窗口内，跳过", job.get("name"), resolved
                    )
                    return None
                return run_job(
                    store, job, context=context or JobContext(), trigger=trigger
                )
    except Exception:  # noqa: BLE001 — 调度线程里的最后一道兜底
        logger.exception("执行租户 %s 的任务 %s 时发生未捕获异常", resolved, job_id)
        return None


def record_tenant_job_skipped(
    tenant_id: str,
    job_id: str,
    *,
    reason: str,
    trigger: str = "schedule",
    db_path: str | Path | None = None,
) -> str | None:
    """并发槽位拿不到时，给这一轮留一条 ``skipped`` 痕迹。

    为什么要留痕：调度线程直接 return 的话，用户在运维「执行历史」里看到的是
    **什么都没发生**——任务表写着「每工作日 15:30」，那天却一条记录都没有，
    既不像成功也不像失败。落一条 skipped 才说得清「本轮没跑、原因是并发槽满」。

    失败一律吞掉：这是留痕，不是业务，写不进去不该把调度线程带走。
    """
    resolved = normalize_tenant(tenant_id)
    primary = resolved == PRIMARY_TENANT
    try:
        with tenant_scope(resolved):
            with OpsStore(db_path if primary else None) as store:
                job = store.get_job(job_id)
                if job is None:
                    return None
                run_id, claimed = store.claim_run(job, trigger=trigger)
                if not claimed:
                    # 上一轮还在跑：那条 running 记录本身就是解释，不再叠一条。
                    return None
                store.finish_run(
                    run_id,
                    status="skipped",
                    result={"reason": reason, "tenant": resolved},
                    duration_ms=0,
                )
                return run_id
    except Exception:  # noqa: BLE001 — 留痕失败不能反过来搞死调度线程
        logger.warning(
            "记录租户 %s 任务 %s 的 skipped 失败", resolved, job_id, exc_info=True
        )
        return None
