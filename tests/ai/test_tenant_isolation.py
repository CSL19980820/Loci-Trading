"""两个租户的 LLM 配置 / 会话 / 用量必须互不可见。

隔离靠的**不是**给表加 user_id，而是「换一个 data 根」：``paths.ops_db()`` 随
``current_tenant()`` 变。所以真正的失效点全在「谁把路径提前算死了」——
import 期的模块常量、``build_*_router`` 装配期的 ``str(ops_db())``、构造期就
绑好库的进程内单例。这组用例盯的就是这些点，不是盯 SQL。
"""
from __future__ import annotations

import pytest

from src.ai.application.assistant_manager import AssistantManager
from src.ai.infrastructure.assistant_store import AssistantStore
from src.ai.infrastructure.providers import resolve_config, save_provider
from src.ai.infrastructure.tenant_db import ops_db_for, open_ops_store
from src.ops import OpsError, OpsStore
from src.shared.tenancy import tenant_scope


def _save(store, name: str, key: str) -> None:
    save_provider(
        store,
        name=name,
        protocol="openai_compatible",
        base_url="https://api.example.test/v1",
        api_key=key,
        model="demo-model",
        validate=False,
        discover_models=False,
        is_default=True,
    )


def test_provider_config_of_two_tenants_never_crosses() -> None:
    with tenant_scope("u_a"):
        with open_ops_store() as store:
            _save(store, "alpha", "sk-alpha-secret")
    with tenant_scope("u_b"):
        with open_ops_store() as store:
            _save(store, "beta", "sk-beta-secret")

    with tenant_scope("u_a"):
        with open_ops_store() as store:
            names = [row["name"] for row in store.list_providers()]
            assert names == ["alpha"]
            assert resolve_config(store).api_key == "sk-alpha-secret"
            with pytest.raises(OpsError):
                resolve_config(store, "beta")

    with tenant_scope("u_b"):
        with open_ops_store() as store:
            names = [row["name"] for row in store.list_providers()]
            assert names == ["beta"]
            assert resolve_config(store).api_key == "sk-beta-secret"


def test_bare_ops_store_follows_the_current_tenant() -> None:
    """``OpsStore(None)`` 必须在**构造时**解析当前租户。

    它以前用的是 import 期求值的 ``DEFAULT_DB``：第一个 import 本模块的租户
    会把全进程钉死在自己的库上，而且不报错，只是静悄悄串味。
    """
    with tenant_scope("u_a"):
        with OpsStore() as store:
            _save(store, "alpha", "sk-alpha")
            a_path = store.db_path
    with tenant_scope("u_b"):
        with OpsStore() as store:
            b_path = store.db_path
            assert [row["name"] for row in store.list_providers()] == []
    assert a_path != b_path


def test_assistant_sessions_and_usage_are_per_tenant() -> None:
    with tenant_scope("u_a"):
        with AssistantStore(ops_db_for()) as store:
            store.create_session(title="A 的对话")
            store.record_usage(provider="p", model="m", input_tokens=10, output_tokens=5)

    with tenant_scope("u_b"):
        with AssistantStore(ops_db_for()) as store:
            assert store.list_sessions() == []
            assert store.monthly_token_usage() == 0
            store.create_session(title="B 的对话")

    with tenant_scope("u_a"):
        with AssistantStore(ops_db_for()) as store:
            titles = [row["title"] for row in store.list_sessions()]
            assert titles == ["A 的对话"]
            assert store.monthly_token_usage() == 15


def test_manager_singleton_resolves_its_db_per_call_not_per_construction() -> None:
    """``AssistantManager`` 是 ``build_assistant_router`` 里 new 一次的进程内单例。

    构造期把 ops_db 解析成字符串存下来，等于让所有用户共用装配那一刻的库。
    """
    with tenant_scope("u_a"):
        manager = AssistantManager(ops_db=None)
    try:
        with tenant_scope("u_a"):
            a_path = manager.ops_db
            a_palace = manager.palace_db
        with tenant_scope("u_b"):
            b_path = manager.ops_db
            b_palace = manager.palace_db
        assert a_path != b_path
        assert a_palace != b_palace
        assert "u_a" in a_path and "u_b" in b_path
    finally:
        manager.close()


def test_manager_honours_an_explicit_db_override(tmp_path) -> None:
    """显式钉库仍然优先：单机部署与测试都靠它。"""
    pinned = str(tmp_path / "pinned-ops.db")
    manager = AssistantManager(ops_db=pinned)
    try:
        with tenant_scope("u_a"):
            assert manager.ops_db == pinned
        with tenant_scope("u_b"):
            assert manager.ops_db == pinned
    finally:
        manager.close()


def test_recover_interrupted_runs_reaches_every_tenant_it_serves() -> None:
    """原来只在构造期收口一次，别的租户的中断 run 会永远挂在 running 上。"""
    with tenant_scope("u_b"):
        with AssistantStore(ops_db_for()) as store:
            session_id = store.create_session()
            run_id = store.create_run(session_id, provider="p", model="m", user_message="打断")

    with tenant_scope("u_a"):
        manager = AssistantManager(ops_db=None)
    try:
        with tenant_scope("u_b"):
            manager._recover_interrupted_once()
            with AssistantStore(ops_db_for()) as store:
                run = store.get_run(run_id)
                assert run is not None and run["status"] == "failed"
    finally:
        manager.close()
