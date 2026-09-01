"""每用户 LLM 配额：命中、未命中、身份库缺失时降级。

配额是治理手段，不是业务前提：身份库读不出来时必须退回旧的环境变量行为，
**不能把 AI 功能整个卡死**。这一条比「配额算得准」更重要，所以单独一条用例。
"""
from __future__ import annotations

from pathlib import Path

import pytest

from src.ai.application import quota
from src.ai.application.quota import (
    QuotaExceeded,
    check_llm_quota,
    current_llm_quota,
    record_llm_usage,
)
from src.ai.infrastructure.assistant_store import AssistantStore
from src.identity import IdentityStore
from src.shared.paths import ops_db
from src.shared.tenancy import current_tenant, tenant_scope


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


def _burn(tokens: int) -> None:
    with AssistantStore(str(ops_db())) as store:
        store.record_usage(provider="p", model="m", input_tokens=tokens, output_tokens=0)


def test_quota_comes_from_identity_and_blocks_when_used_up() -> None:
    with tenant_scope("u_quota"):
        _make_user("u_quota", llm_monthly_tokens=100)
        assert current_llm_quota()["llm_monthly_tokens"] == 100

        _burn(99)
        check_llm_quota()  # 99 < 100：还能发

        _burn(1)
        with pytest.raises(QuotaExceeded, match="本月 Token 预算已用尽"):
            check_llm_quota()


def test_quota_counts_the_tokens_this_call_is_about_to_spend() -> None:
    with tenant_scope("u_estimate"):
        _make_user("u_estimate", llm_monthly_tokens=100)
        _burn(40)
        check_llm_quota(tokens_needed=30)
        with pytest.raises(QuotaExceeded):
            check_llm_quota(tokens_needed=60)


def test_daily_call_quota_counts_calls_not_tokens() -> None:
    with tenant_scope("u_calls"):
        _make_user("u_calls", llm_monthly_tokens=1_000_000, llm_daily_calls=2)
        record_llm_usage(provider="p", model="m", input_tokens=1, output_tokens=1)
        check_llm_quota()
        record_llm_usage(provider="p", model="m", input_tokens=1, output_tokens=1)
        with pytest.raises(QuotaExceeded, match="今日 LLM 调用次数"):
            check_llm_quota()


def test_negative_quota_means_unlimited() -> None:
    with tenant_scope("u_unlimited"):
        _make_user("u_unlimited", llm_monthly_tokens=-1, llm_daily_calls=-1)
        _burn(10_000_000)
        check_llm_quota()  # 不限就是不限，烧再多也不拦


def test_missing_identity_store_degrades_to_env_budget(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """身份库炸了不能连累 AI：退回环境变量那套单值行为。"""
    import src.identity as identity_pkg

    def _boom(*_args, **_kwargs):
        raise RuntimeError("identity.db 打不开")

    monkeypatch.setattr(identity_pkg, "IdentityStore", _boom)
    monkeypatch.setenv("LOCI_AI_MONTHLY_TOKEN_BUDGET", "50")

    with tenant_scope("u_degraded"):
        assert quota.current_user_id() == ""
        assert current_llm_quota()["llm_monthly_tokens"] == 50

        _burn(10)
        check_llm_quota()  # 降级路径照样能判，不是无脑放行

        _burn(40)
        with pytest.raises(QuotaExceeded):
            check_llm_quota()

        # 计费同样不能抛：identity 写不进去顶多少一条后台统计
        record_llm_usage(provider="p", model="m", input_tokens=1, output_tokens=1)


def test_no_user_for_this_tenant_falls_back_instead_of_locking_out() -> None:
    """identity.db 在、但这个租户还没建账号：退回默认额度，而不是判 0。"""
    with tenant_scope("u_nobody"):
        assert quota.current_user_id() == ""
        assert current_llm_quota()["llm_monthly_tokens"] == quota.DEFAULT_MONTHLY_TOKEN_BUDGET
        check_llm_quota()


def test_zero_in_identity_means_use_system_default_not_zero_budget() -> None:
    """``user_quotas`` 缺行/填 0 的语义是「用系统默认」，不能读成「一点都不给」。"""
    with tenant_scope("u_zero"):
        user_id = _make_user("u_zero")
        with IdentityStore() as store:
            store.set_quota(user_id, llm_monthly_tokens=0, llm_daily_calls=0)
        resolved = current_llm_quota()
        assert resolved["llm_monthly_tokens"] == quota.DEFAULT_MONTHLY_TOKEN_BUDGET
        assert resolved["llm_daily_calls"] < 0  # 0 = 不限日调用，保持存量行为
        check_llm_quota()


def test_usage_lands_in_the_callers_tenant_db_and_identity_counters() -> None:
    with tenant_scope("u_meter"):
        user_id = _make_user("u_meter")
        record_llm_usage(provider="deepseek", model="v3", input_tokens=7, output_tokens=5)

        with AssistantStore(str(ops_db())) as store:
            assert store.monthly_token_usage() == 12

        with IdentityStore() as store:
            from datetime import date

            period = date.today().strftime("%Y-%m")
            assert store.get_usage(user_id, period=period, metric="llm_tokens") == 12


def test_usage_of_one_tenant_is_invisible_to_another(tmp_path: Path) -> None:
    with tenant_scope("u_left"):
        record_llm_usage(provider="p", model="m", input_tokens=1_000, output_tokens=0)
        left_db = ops_db()
    with tenant_scope("u_right"):
        right_db = ops_db()
        with AssistantStore(str(right_db)) as store:
            assert store.monthly_token_usage() == 0
    assert left_db != right_db


def test_record_llm_usage_never_raises_even_with_a_broken_store(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """计费坏了顶多丢一条账，不能把这一轮盯盘/选股带崩。"""
    import src.ai.infrastructure.assistant_store as store_mod

    class _Broken:
        def __init__(self, *_a, **_k) -> None:
            raise OSError("disk full")

    monkeypatch.setattr(store_mod, "AssistantStore", _Broken)
    record_llm_usage(provider="p", model="m", input_tokens=1, output_tokens=1)


def test_current_tenant_is_the_key_not_a_process_global() -> None:
    assert current_tenant() == "__primary__"
    with tenant_scope("u_scoped"):
        assert current_tenant() == "u_scoped"
    assert current_tenant() == "__primary__"
