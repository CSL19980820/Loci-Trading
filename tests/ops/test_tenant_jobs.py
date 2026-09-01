
"""多租户调度：系统级任务只跑一份，用户级任务按租户各跑各的。

这套用例守的是四条会**静默**出错的线：

1. 系统级 kind 泄漏到子租户 —— N 个租户同时同步行情，撞 market.db 写锁 +
   把上游打成 403。最重要的一条。
2. 两个租户的 job id 撞名 —— APScheduler 按 id 去重，后装的会顶掉先装的，
   于是「B 注册之后 A 的选股就不跑了」，没有任何报错。
3. 租户数超上限 —— 必须截断并告警，而不是把几百个 job 硬塞进 web 进程。
4. 身份库缺失 —— 必须降级为只跑主租户，而不是整个调度器起不来。
"""
from __future__ import annotations

import logging
import os
import sqlite3
from pathlib import Path

import pytest

from src.ops.application import tenant_jobs
from src.ops.application.tenant_jobs import (
    SYSTEM_JOB_KINDS,
    active_tenant_roster,
    list_active_tenants,
    run_tenant_job,
    tenant_job_rows,
)
from src.ops.infrastructure.scheduler import JobScheduler, tenant_job_key
from src.ops.infrastructure.store import OpsStore
from src.shared.paths import data_dir, identity_db
from src.shared.tenancy import (
    PRIMARY_TENANT,
    current_tenant,
    ensure_tenant_root,
    tenant_paths,
    tenant_scope,
)


def _seed_identity(*tenant_ids: str, status: str = "active") -> None:
    """在 identity.db 里建出用户。名单权威在这里，不在磁盘上。"""
    from src.identity.infrastructure.store import IdentityStore

    with IdentityStore(identity_db()) as store:
        for tenant_id in tenant_ids:
            # 用租户 id 拼登录名：一个用例可能分几次种人，用序号会撞 UNIQUE。
            store.create_user(
                username=f"user-{tenant_id}",
                email=f"{tenant_id}@example.test",
                password_hash="x" * 16,
                password_algo="plain",
                status=status,
                tenant_id=tenant_id,
            )


def _primary_db() -> str:
    return os.environ["PALACE_OPS_DB"]


def _seed_jobs(tenant_id: str, jobs: list[tuple[str, str, str]]) -> dict[str, str]:
    """给某个租户建任务，返回 ``{任务名: job_id}``。"""
    created: dict[str, str] = {}
    if tenant_id == PRIMARY_TENANT:
        with OpsStore(_primary_db()) as store:
            for name, kind, cron in jobs:
                created[name] = store.create_job(name=name, kind=kind, cron=cron)
        return created
    ensure_tenant_root(data_dir(), tenant_id)
    with tenant_scope(tenant_id):
        with OpsStore(None) as store:
            for name, kind, cron in jobs:
                created[name] = store.create_job(name=name, kind=kind, cron=cron)
    return created


def _force_job_id(tenant_id: str, old_id: str, new_id: str) -> None:
    """把某条任务的主键改成指定值，用来人为制造跨租户 id 撞名。"""
    path: Path = tenant_paths(data_dir(), tenant_id).ops_db
    conn = sqlite3.connect(path)
    try:
        conn.execute("UPDATE jobs SET id = ? WHERE id = ?", (new_id, old_id))
        conn.commit()
    finally:
        conn.close()


def _scheduled_ids(scheduler: JobScheduler) -> set[str]:
    return {job.id for job in scheduler._scheduler.get_jobs()}


# --------------------------------------------------------------------------
# 1. 系统级 kind 绝不下放到子租户
# --------------------------------------------------------------------------


def test_system_job_kinds_are_not_loaded_for_sub_tenants() -> None:
    """子租户的行情同步任务**不得**被装载，主租户的那一份照常装。"""
    _seed_identity("alice")
    primary = _seed_jobs(
        PRIMARY_TENANT,
        [("行情同步", "sync", "35 15 * * mon-fri")],
    )
    alice = _seed_jobs(
        "alice",
        [
            # 子租户库里**确实存在**一条系统级任务（历史遗留 / 用户手建都可能），
            # 装载器必须自己挡住，不能指望库里干净。
            ("行情同步", "sync", "35 15 * * mon-fri"),
            ("热库重建", "hot_rebuild", "0 16 * * mon-fri"),
            ("盘后选股", "screen", "30 15 * * mon-fri"),
        ],
    )

    scheduler = JobScheduler(db_path=_primary_db())
    scheduler.reload()
    scheduled = _scheduled_ids(scheduler)

    # 主租户的系统级任务在。
    assert primary["行情同步"] in scheduled
    # 子租户的系统级任务全部缺席。
    assert tenant_job_key("alice", alice["行情同步"]) not in scheduled
    assert tenant_job_key("alice", alice["热库重建"]) not in scheduled
    # 子租户的用户级任务在。
    assert tenant_job_key("alice", alice["盘后选股"]) in scheduled

    # 过滤发生在装载层之前：tenant_job_rows 本身就不该吐出系统级 kind。
    kinds = {row["kind"] for row in tenant_job_rows("alice")}
    assert kinds == {"screen"}
    assert not kinds & SYSTEM_JOB_KINDS


def test_run_tenant_job_refuses_system_kind_in_sub_tenant() -> None:
    """就算有人绕过装载层直接触发，执行入口也要挡住。"""
    _seed_identity("alice")
    alice = _seed_jobs("alice", [("行情同步", "sync", "35 15 * * mon-fri")])

    assert run_tenant_job("alice", alice["行情同步"]) is None


# --------------------------------------------------------------------------
# 2. 多租户并存：都装上，且 id 不撞
# --------------------------------------------------------------------------


def test_two_tenants_each_get_their_own_screen_job() -> None:
    """两个租户的选股任务都要装上，即使它们的 job id 完全相同。"""
    _seed_identity("alice", "bob")
    alice = _seed_jobs("alice", [("盘后选股", "screen", "30 15 * * mon-fri")])
    bob = _seed_jobs("bob", [("盘后选股", "screen", "30 15 * * mon-fri")])

    # 人为制造最坏情况：两个库里是同一个主键。分库之后这完全可能发生，
    # 而 APScheduler 按 id 去重——不加租户前缀就会有一个人的任务被顶掉。
    collision = "job-collision"
    _force_job_id("alice", alice["盘后选股"], collision)
    _force_job_id("bob", bob["盘后选股"], collision)

    scheduler = JobScheduler(db_path=_primary_db())
    plan = scheduler.reload()
    scheduled = _scheduled_ids(scheduler)

    alice_key = tenant_job_key("alice", collision)
    bob_key = tenant_job_key("bob", collision)
    assert alice_key != bob_key
    assert alice_key in scheduled
    assert bob_key in scheduled

    assert plan["tenants"]["count"] == 3  # 主租户 + alice + bob
    assert plan["tenants"]["jobs"] == 2
    assert plan["tenants"]["truncated"] is False
    assert plan["tenants"]["degraded"] is False


def test_primary_job_ids_stay_bare() -> None:
    """主租户的 APScheduler id 必须还是裸 job id。

    ``/api/jobs/schedule`` 与行情同步设置页都拿裸 id 去 ``upcoming()`` 里查实况，
    加了前缀就查不到，页面上的「下次触发」会集体变空。
    """
    _seed_identity("alice")
    primary = _seed_jobs(PRIMARY_TENANT, [("盘后选股", "screen", "30 15 * * mon-fri")])
    _seed_jobs("alice", [("盘后选股", "screen", "30 15 * * mon-fri")])

    scheduler = JobScheduler(db_path=_primary_db())
    scheduler.reload()

    live = {item["id"]: item for item in scheduler.upcoming()}
    assert primary["盘后选股"] in live
    assert live[primary["盘后选股"]]["tenant"] == PRIMARY_TENANT


# --------------------------------------------------------------------------
# 3. 租户总数上限
# --------------------------------------------------------------------------


def test_tenant_roster_truncates_and_warns_over_limit(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    """超过 LOCI_MAX_SCHEDULED_TENANTS 就只装前 N 个，并且必须告警。"""
    names = ["t1", "t2", "t3", "t4", "t5"]
    _seed_identity(*names)
    for name in names:
        _seed_jobs(name, [("盘后选股", "screen", "30 15 * * mon-fri")])

    monkeypatch.setenv("LOCI_MAX_SCHEDULED_TENANTS", "3")
    with caplog.at_level(logging.WARNING, logger="src.ops.application.tenant_jobs"):
        roster = active_tenant_roster()

    # 上限是**总数**，主租户占一个名额。
    assert roster["tenants"] == [PRIMARY_TENANT, "t1", "t2"]
    assert roster["total"] == 6
    assert roster["truncated"] is True
    assert any(
        "LOCI_MAX_SCHEDULED_TENANTS" in rec.getMessage() for rec in caplog.records
    )

    # 被截断的租户，任务确实没有装上。
    scheduler = JobScheduler(db_path=_primary_db())
    plan = scheduler.reload()
    scheduled = _scheduled_ids(scheduler)
    assert plan["tenants"]["truncated"] is True
    assert plan["tenants"]["jobs"] == 2
    assert not any(key.startswith("t:t5:") for key in scheduled)


def test_tenant_limit_default_is_fifty(monkeypatch: pytest.MonkeyPatch) -> None:
    """没设环境变量时用默认值；设了脏值也不能炸，回退默认。"""
    monkeypatch.delenv("LOCI_MAX_SCHEDULED_TENANTS", raising=False)
    assert tenant_jobs.max_scheduled_tenants() == 50
    monkeypatch.setenv("LOCI_MAX_SCHEDULED_TENANTS", "not-a-number")
    assert tenant_jobs.max_scheduled_tenants() == 50

    monkeypatch.delenv("LOCI_TENANT_JOB_CONCURRENCY", raising=False)
    assert tenant_jobs.tenant_job_concurrency() == 2
    monkeypatch.setenv("LOCI_TENANT_JOB_CONCURRENCY", "8")
    assert tenant_jobs.tenant_job_concurrency() == 8


def test_scheduler_reload_reports_concurrency_gate(monkeypatch: pytest.MonkeyPatch) -> None:
    """并发闸门按环境变量重建，reload 后即生效，不用重启进程。"""
    monkeypatch.setenv("LOCI_TENANT_JOB_CONCURRENCY", "3")
    scheduler = JobScheduler(db_path=_primary_db())
    plan = scheduler.reload()
    assert plan["tenants"]["concurrency"] == 3


# --------------------------------------------------------------------------
# 4. 身份库缺失 -> 降级为只跑主租户
# --------------------------------------------------------------------------


def test_missing_identity_db_degrades_to_primary_only() -> None:
    """身份库不存在时只跑主租户，而且**不许**顺手把空库建出来。"""
    # 磁盘上有租户目录（老数据 / 手工拷贝），但身份库没有 —— 此时不能凭磁盘
    # 猜名单：谁被停用、谁被删号，只有 identity.db 知道。
    _seed_jobs("ghost", [("盘后选股", "screen", "30 15 * * mon-fri")])
    assert not identity_db().exists()

    roster = active_tenant_roster()
    assert roster["tenants"] == [PRIMARY_TENANT]
    assert roster["degraded"] is True
    assert list_active_tenants() == [PRIMARY_TENANT]
    # 只读盘点路径不得产生副作用。
    assert not identity_db().exists()

    scheduler = JobScheduler(db_path=_primary_db())
    plan = scheduler.reload()
    assert plan["tenants"]["degraded"] is True
    assert plan["tenants"]["jobs"] == 0
    assert not any(key.startswith("t:") for key in _scheduled_ids(scheduler))


def test_identity_read_failure_degrades_to_primary_only(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """身份库存在但读不动（锁死/损坏）时同样降级，不能让整个调度器起不来。"""
    _seed_identity("alice")
    _seed_jobs("alice", [("盘后选股", "screen", "30 15 * * mon-fri")])

    def _boom(*args: object, **kwargs: object) -> None:
        raise sqlite3.DatabaseError("database disk image is malformed")

    monkeypatch.setattr(
        "src.identity.infrastructure.store.IdentityStore.list_users", _boom
    )
    roster = active_tenant_roster()
    assert roster["tenants"] == [PRIMARY_TENANT]
    assert roster["degraded"] is True


def test_inactive_users_and_unbuilt_tenants_are_skipped() -> None:
    """只有「活跃 ∩ 磁盘上已建库」的租户才装载。"""
    _seed_identity("active_built", "active_unbuilt")
    _seed_identity("disabled_built", status="disabled")
    _seed_jobs("active_built", [("盘后选股", "screen", "30 15 * * mon-fri")])
    _seed_jobs("disabled_built", [("盘后选股", "screen", "30 15 * * mon-fri")])
    # active_unbuilt 只有账号，没进过任何页面，磁盘上没有 ops.db。

    assert list_active_tenants() == [PRIMARY_TENANT, "active_built"]


# --------------------------------------------------------------------------
# 5. run_tenant_job 真的切了租户上下文
# --------------------------------------------------------------------------


def test_run_tenant_job_switches_current_tenant(monkeypatch: pytest.MonkeyPatch) -> None:
    """假执行器里看到的 current_tenant() 必须是目标租户。

    这是整个改造的地基：切不过去，任务就会拿主租户的库去跑别人的选股。
    """
    from src.ops.application.jobs import registry

    seen: list[str] = []

    def _fake_executor(config: dict, context: object) -> dict:
        seen.append(current_tenant())
        return {"ok": True}

    monkeypatch.setitem(registry.EXECUTORS, "notify", _fake_executor)

    _seed_identity("alice")
    alice = _seed_jobs("alice", [("推送", "notify", "0 16 * * mon-fri")])

    # 调用前后主流程仍在主租户上下文里，不能被污染。
    assert current_tenant() == PRIMARY_TENANT
    outcome = run_tenant_job("alice", alice["推送"])
    assert current_tenant() == PRIMARY_TENANT

    assert seen == ["alice"], f"执行器看到的租户是 {seen}，期望 ['alice']"
    assert outcome is not None
    assert outcome["status"] == "success"

    # run 记录必须落在 alice 自己的库里，主租户库不许有。
    with tenant_scope("alice"):
        with OpsStore(None) as store:
            assert len(store.list_runs(limit=10)) == 1
    with OpsStore(_primary_db()) as store:
        assert store.list_runs(limit=10) == []


def test_run_tenant_job_missing_job_returns_none() -> None:
    """任务已被删：安静跳过，不抛异常炸掉调度线程。"""
    _seed_identity("alice")
    _seed_jobs("alice", [("盘后选股", "screen", "30 15 * * mon-fri")])
    assert run_tenant_job("alice", "no-such-job") is None


# --------------------------------------------------------------------------
# 6. HTTP 写口：系统级 kind 与 cron 频率下限（第 3 条安全缺陷）
# --------------------------------------------------------------------------


def _jobs_client(ops_db: str):
    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    from src.ops.api.jobs import build_jobs_router

    app = FastAPI()
    app.include_router(
        build_jobs_router(write_dependency=lambda: None, ops_db=ops_db)
    )
    return TestClient(app, raise_server_exceptions=False)


def _tenant_ops_db(tenant_id: str) -> str:
    ensure_tenant_root(data_dir(), tenant_id)
    return str(tenant_paths(data_dir(), tenant_id).ops_db)


def test_sub_tenant_cannot_create_system_kind_over_http(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """子租户建 sync/prune 一律 403：调度侧那两道挡板只管定时，HTTP 建出来的
    任务照样能手动触发，``execute_sync`` 一跑就独占全局行情写锁最长 45 分钟。"""
    monkeypatch.setattr("src.shared.tenancy.is_primary_tenant", lambda *_: False)
    with _jobs_client(_tenant_ops_db("alice")) as client:
        for kind in ("sync", "prune"):
            resp = client.post(
                "/api/jobs",
                json={"name": f"偷跑{kind}", "kind": kind, "cron": "35 15 * * mon-fri"},
            )
            assert resp.status_code == 403, kind
            assert "系统级任务" in resp.json()["detail"]


def test_primary_tenant_can_still_create_system_kind() -> None:
    """主租户 = 管理员，存量行为一个字不改。"""
    with _jobs_client(_primary_db()) as client:
        resp = client.post(
            "/api/jobs",
            json={"name": "行情同步", "kind": "sync", "cron": "35 15 * * mon-fri"},
        )
    assert resp.status_code == 201
    assert resp.json()["kind"] == "sync"


def test_sub_tenant_cannot_trigger_system_kind_over_http(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """库里已经躺着一条系统级任务时，手动触发也要挡住（403，且不产生 run）。"""
    ops_db = _tenant_ops_db("alice")
    with OpsStore(ops_db) as store:
        job_id = store.create_job(name="历史遗留同步", kind="sync")
    monkeypatch.setattr("src.shared.tenancy.is_primary_tenant", lambda *_: False)
    with _jobs_client(ops_db) as client:
        resp = client.post(f"/api/jobs/{job_id}/run")
    assert resp.status_code == 403
    with OpsStore(ops_db) as store:
        assert store.list_runs(limit=10) == []


def test_sub_tenant_cannot_update_system_kind_over_http(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """改 cron / 改 enabled 同样是「让系统级任务按我的节奏跑」。"""
    ops_db = _tenant_ops_db("alice")
    with OpsStore(ops_db) as store:
        job_id = store.create_job(name="历史遗留同步", kind="sync", cron="35 15 * * *")
    monkeypatch.setattr("src.shared.tenancy.is_primary_tenant", lambda *_: False)
    with _jobs_client(ops_db) as client:
        resp = client.patch(f"/api/jobs/{job_id}", json={"cron": "*/10 * * * *"})
    assert resp.status_code == 403
    with OpsStore(ops_db) as store:
        job = store.get_job(job_id)
        assert job is not None and job["cron"] == "35 15 * * *"


def test_sub_tenant_cron_must_be_slower_than_five_minutes(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """``* * * * *`` 语法合法，但一个人就能靠它把租户线程池长期占满。"""
    monkeypatch.setattr("src.shared.tenancy.is_primary_tenant", lambda *_: False)
    with _jobs_client(_tenant_ops_db("alice")) as client:
        resp = client.post(
            "/api/jobs",
            json={"name": "每分钟选股", "kind": "screen", "cron": "* * * * *"},
        )
        assert resp.status_code == 422
        assert "定时频率过高" in resp.json()["detail"]

        # 正好 5 分钟一档（与托管的价格提醒扫描同节奏）必须放行。
        ok = client.post(
            "/api/jobs",
            json={"name": "五分钟扫描", "kind": "screen", "cron": "*/5 9-14 * * mon-fri"},
        )
        assert ok.status_code == 201


def test_primary_tenant_keeps_minute_level_cron() -> None:
    """频率下限只压非主租户；主账号的分钟级 cron 是存量行为。"""
    with _jobs_client(_primary_db()) as client:
        resp = client.post(
            "/api/jobs",
            json={"name": "每分钟盯盘", "kind": "screen", "cron": "* * * * *"},
        )
    assert resp.status_code == 201


def test_job_quota_blocks_the_sixth_self_built_job_over_http(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """配额闸门挂在 API 层；托管任务不占额度，所以只有自建的那 5 条算数。"""
    monkeypatch.setattr(
        "src.ops.application.job_quota.current_job_quota", lambda: 5
    )
    ops_db = _tenant_ops_db("alice")
    with OpsStore(ops_db) as store:
        for i in range(5):
            store.create_job(name=f"我的任务{i}", kind="screen")
        store.create_job(name="screen:managed", kind="screen")
        store.create_job(name="候选T+N跟踪", kind="outcome")
    with _jobs_client(ops_db) as client:
        resp = client.post(
            "/api/jobs", json={"name": "第六条", "kind": "screen", "cron": ""}
        )
        assert resp.status_code == 429
        assert "自建定时任务已达上限（5 / 5 条）" in resp.json()["detail"]
        status = client.get("/api/jobs/quota").json()
    assert status == {"used": 5, "limit": 5, "unlimited": False, "managed": 2}


# --------------------------------------------------------------------------
# 7. 两个 executor 池：租户任务挤不掉行情同步
# --------------------------------------------------------------------------


def test_jobs_are_loaded_into_their_own_executor_pool(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """主租户任务进 default 池，子租户任务进 tenant 池。"""
    monkeypatch.setenv("LOCI_SYSTEM_JOB_CONCURRENCY", "4")
    monkeypatch.setenv("LOCI_TENANT_JOB_CONCURRENCY", "2")
    _seed_identity("alice")
    primary = _seed_jobs(PRIMARY_TENANT, [("行情同步", "sync", "35 15 * * mon-fri")])
    alice = _seed_jobs("alice", [("盘后选股", "screen", "30 15 * * mon-fri")])

    scheduler = JobScheduler(db_path=_primary_db())
    plan = scheduler.reload()
    jobs = {job.id: job for job in scheduler._scheduler.get_jobs()}

    assert jobs[primary["行情同步"]].executor == "default"
    assert jobs[tenant_job_key("alice", alice["盘后选股"])].executor == "tenant"
    assert plan["tenants"]["executors"] == {"default": 4, "tenant": 2}
    assert plan["tenants"]["system_concurrency"] == 4


def test_two_thread_pools_are_really_separate(monkeypatch: pytest.MonkeyPatch) -> None:
    """池宽各自独立：租户池占满也动不了系统池的线程数。"""
    monkeypatch.setenv("LOCI_SYSTEM_JOB_CONCURRENCY", "3")
    monkeypatch.setenv("LOCI_TENANT_JOB_CONCURRENCY", "7")
    scheduler = JobScheduler(db_path=_primary_db())
    executors = scheduler._scheduler._executors
    assert set(executors) == {"default", "tenant"}
    assert executors["default"]._pool._max_workers == 3
    assert executors["tenant"]._pool._max_workers == 7


def test_full_tenant_gate_records_skipped_without_blocking() -> None:
    """拿不到槽位就落 skipped 留痕并**立刻**返回：旧写法 ``acquire(timeout=300)``
    会占着调度线程干等 5 分钟，而直接 return 又什么痕迹都不留。"""
    import time

    _seed_identity("alice")
    alice = _seed_jobs("alice", [("盘后选股", "screen", "30 15 * * mon-fri")])
    scheduler = JobScheduler(db_path=_primary_db())
    scheduler.reload()

    # 把槽位全占光，模拟租户池被别的任务塞满。
    assert scheduler._tenant_gate.acquire(blocking=False)
    while scheduler._tenant_gate.acquire(blocking=False):
        pass

    started = time.monotonic()
    scheduler._run_tenant("alice", alice["盘后选股"])
    assert time.monotonic() - started < 5  # 不阻塞（旧实现要等 300 秒）

    with tenant_scope("alice"), OpsStore(None) as store:
        runs = store.list_runs(limit=10)
    assert [run["status"] for run in runs] == ["skipped"]
    assert "并发槽位已满" in str(runs[0]["result"])


# --------------------------------------------------------------------------
# 8. cron 错峰：确定性、主租户不变
# --------------------------------------------------------------------------


def test_primary_tenant_keeps_the_legacy_minute() -> None:
    """存量单机用户的 15:30 / 15:40 / 15:45 一分钟都不许动。"""
    from src.ops.application.job_stagger import staggered_cron, tenant_minute_offset

    assert tenant_minute_offset(15) == 0  # 未绑定租户 = 主租户
    assert staggered_cron("30 15 * * mon-fri") == "30 15 * * mon-fri"
    with tenant_scope(PRIMARY_TENANT):
        assert staggered_cron("45 15 * * mon-fri") == "45 15 * * mon-fri"


def test_tenant_offset_is_deterministic_and_bounded() -> None:
    """同一个租户每次都落在同一分钟，且不越出 15 分钟窗口。"""
    from src.ops.application.job_stagger import staggered_cron, tenant_minute_offset

    offsets = {t: tenant_minute_offset(15, t) for t in ("alice", "bob", "carol")}
    assert all(0 <= value < 15 for value in offsets.values())
    assert offsets == {t: tenant_minute_offset(15, t) for t in offsets}

    with tenant_scope("alice"):
        cron = staggered_cron("30 15 * * mon-fri")
    minute = int(cron.split()[0])
    assert 30 <= minute <= 44
    assert cron.split()[1:] == ["15", "*", "*", "mon-fri"]


def test_interval_cron_is_left_alone() -> None:
    """``*/15`` 这种区间任务本来就摊开了，没有尖峰可削，不许改。"""
    from src.ops.application.job_stagger import staggered_cron

    with tenant_scope("alice"):
        assert staggered_cron("*/15 9-14 * * mon-fri") == "*/15 9-14 * * mon-fri"


def test_managed_outcome_job_is_staggered_only_on_first_create() -> None:
    """首次创建错峰；已存在的任务再 ensure 一次也不许动它的 cron。"""
    ensure_tenant_root(data_dir(), "alice")
    with tenant_scope("alice"), OpsStore(None) as store:
        job_id = store.ensure_managed_outcome_job()
        job = store.get_job(job_id)
        assert job is not None
        minute = int(str(job["cron"]).split()[0])
        assert 45 <= minute <= 59

        store.update_job(job_id, cron="50 15 * * mon-fri")
        store.ensure_managed_outcome_job()
        again = store.get_job(job_id)
        assert again is not None and again["cron"] == "50 15 * * mon-fri"
