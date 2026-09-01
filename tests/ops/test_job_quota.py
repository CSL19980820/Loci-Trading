"""自建定时任务条数配额（``job_slots``）。

守的是四条会**静默**出错的线：

1. 托管任务占了额度 —— 子租户开箱 7~8 条托管任务，一登录就超额，用户连一条
   自己的任务都建不了，而且看到的报错还是「已达上限」，完全不知道为什么。
2. 额度形同虚设 —— 第 6 条自建任务必须被拒，否则一个人就能把租户线程池占满。
3. 管理员被自己的闸门锁住 —— 负数是「不限」，不是「一条都不给」。
4. 身份库缺失把任务 CRUD 整个卡死 —— 配额是治理手段，不是业务前提。
"""
from __future__ import annotations

import pytest

from src.identity import IdentityStore
from src.ops.application.job_quota import (
    DEFAULT_JOB_SLOTS,
    JobQuotaExceeded,
    check_job_quota,
    count_user_jobs,
    current_job_quota,
    is_managed_job,
    job_quota_status,
    managed_job_names,
)
from src.ops.infrastructure.store import OpsStore
from src.shared.paths import data_dir, identity_db
from src.shared.tenancy import ensure_tenant_root, tenant_scope

#: 子租户开箱即有的托管任务，抄自各 ``ensure_*`` 模块的常量。
MANAGED_SEEDS = [
    ("候选T+N跟踪", "outcome"),
    ("screen:qianlong-close-v3", "screen"),
    ("screen:yangshi-tail", "screen"),
    ("screen:tail-resonance", "screen"),
    ("情报·开盘", "intel_fetch"),
    ("情报·盘中", "intel_fetch"),
    ("情报·盘后", "intel_fetch"),
    ("价格提醒扫描", "alert_scan"),
]


def _make_user(tenant: str, **limits: int) -> str:
    """在 identity.db 里建一个挂在 ``tenant`` 上的用户，并配好额度。"""
    with IdentityStore() as store:
        user = store.create_user(
            username=f"user-{tenant}",
            email=f"{tenant}@example.test",
            password_hash=None,
            password_algo="",
            status="active",
            tenant_id=tenant,
        )
        if limits:
            store.set_quota(user.id, **limits)
        return user.id


def _seed(store: OpsStore, names: list[tuple[str, str]]) -> None:
    for name, kind in names:
        store.create_job(name=name, kind=kind, cron="30 15 * * mon-fri")


def _open(tenant: str) -> OpsStore:
    ensure_tenant_root(data_dir(), tenant)
    return OpsStore(None)


# --------------------------------------------------------------------------
# 1. 托管任务不占额度
# --------------------------------------------------------------------------


def test_managed_jobs_do_not_consume_quota() -> None:
    """开箱 8 条托管任务之后，用户仍然一条额度都没花。"""
    with tenant_scope("t_managed"):
        _make_user("t_managed")
        with _open("t_managed") as store:
            _seed(store, MANAGED_SEEDS)
            assert count_user_jobs(store) == 0
            check_job_quota(store)  # 不抛就是对的
            assert job_quota_status(store) == {
                "used": 0,
                "limit": DEFAULT_JOB_SLOTS,
                "unlimited": False,
                "managed": len(MANAGED_SEEDS),
            }


def test_screen_prefix_counts_as_managed_even_for_unknown_slug() -> None:
    """战法目录会增减，判据必须是 ``screen:`` 前缀而不是写死的名单。"""
    assert is_managed_job({"name": "screen:brand-new-strategy"}) is True
    assert is_managed_job({"name": "我的选股"}) is False
    assert is_managed_job({"name": ""}) is False
    # 名单本身要真的取到了常量，而不是空集悄悄放行/悄悄计数。
    names = managed_job_names()
    assert {"候选T+N跟踪", "情报·盘后", "价格提醒扫描", "行情盘中增量"} <= names


# --------------------------------------------------------------------------
# 2. 第 6 条自建任务被拒
# --------------------------------------------------------------------------


def test_sixth_self_built_job_is_rejected() -> None:
    with tenant_scope("t_limit"):
        _make_user("t_limit", job_slots=5)
        with _open("t_limit") as store:
            _seed(store, [(f"我的任务{i}", "screen") for i in range(1, 6)])
            # 托管任务混在同一张表里也不影响判定。
            _seed(store, MANAGED_SEEDS)
            assert count_user_jobs(store) == 5
            with pytest.raises(JobQuotaExceeded, match="自建定时任务已达上限"):
                check_job_quota(store)


def test_fifth_job_still_passes() -> None:
    """闸门判的是「建之前已经有几条」，第 5 条必须能建出来。"""
    with tenant_scope("t_edge"):
        _make_user("t_edge", job_slots=5)
        with _open("t_edge") as store:
            _seed(store, [(f"我的任务{i}", "screen") for i in range(1, 5)])
            check_job_quota(store)


# --------------------------------------------------------------------------
# 3. 管理员不限
# --------------------------------------------------------------------------


def test_negative_quota_means_unlimited() -> None:
    with tenant_scope("t_admin"):
        _make_user("t_admin", job_slots=-1)
        assert current_job_quota() == -1
        with _open("t_admin") as store:
            _seed(store, [(f"任务{i}", "screen") for i in range(1, 31)])
            check_job_quota(store)  # 不限就是不限
            assert job_quota_status(store)["unlimited"] is True


def test_zero_quota_means_system_default_not_zero_jobs() -> None:
    """identity 里的 0 是「用系统默认」。当成 0 条会把所有没配过额度的人锁死。"""
    with tenant_scope("t_zero"):
        _make_user("t_zero", job_slots=0)
        assert current_job_quota() == DEFAULT_JOB_SLOTS


# --------------------------------------------------------------------------
# 4. 身份库缺失 -> 降级为默认值
# --------------------------------------------------------------------------


def test_missing_identity_db_degrades_to_default() -> None:
    """身份库不存在时用默认额度，而且**不许**顺手把空库建出来。"""
    assert not identity_db().exists()
    with tenant_scope("t_no_identity"):
        assert current_job_quota() == DEFAULT_JOB_SLOTS
        with _open("t_no_identity") as store:
            _seed(store, [("我的任务", "screen")])
            check_job_quota(store)
    assert not identity_db().exists()


def test_identity_read_failure_degrades_to_default(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """身份库存在但读不动（锁死/损坏）时同样降级，不能把任务 CRUD 卡死。"""
    with tenant_scope("t_broken"):
        _make_user("t_broken", job_slots=1)

        def _boom(*args: object, **kwargs: object) -> None:
            raise RuntimeError("database disk image is malformed")

        monkeypatch.setattr(
            "src.identity.infrastructure.store.IdentityStore.get_quota", _boom
        )
        assert current_job_quota() == DEFAULT_JOB_SLOTS


def test_unreadable_job_table_does_not_block_crud() -> None:
    """统计读不动就按 0 计：治理失灵可以，卡死不行。"""

    class _Broken:
        def list_jobs(self):
            raise RuntimeError("ops.db is locked")

    store = _Broken()
    assert count_user_jobs(store) == 0
    check_job_quota(store)
    assert job_quota_status(store)["managed"] == 0
