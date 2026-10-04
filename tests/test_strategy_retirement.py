"""退役战法不能被启动对齐恢复，旧任务在隔离库中清理。"""
from __future__ import annotations

from types import SimpleNamespace

import pytest

from src.ops import OpsStore
from src.ops.application.retired_slugs import is_retired_strategy_slug
from src.shared.tenancy import tenant_scope

RETIRED_SLUGS = ("chinext-gap-repair-v1", "tail-micro-right-v1")


@pytest.mark.parametrize("slug", RETIRED_SLUGS)
def test_retired_strategy_matches_existing_identifier_forms(slug):
    for value in (slug, f"screen:{slug}", f"skill:{slug}", f" {slug.upper()} "):
        assert is_retired_strategy_slug(value)


@pytest.mark.parametrize("enabled", [True, False])
@pytest.mark.parametrize("retired_slug", RETIRED_SLUGS)
def test_startup_removes_retired_jobs_and_never_recreates_them(tmp_path, monkeypatch, enabled, retired_slug):
    import src.strategy

    # 模拟旧的注册或技能发现残留：即使目录仍暴露 slug，也不能恢复其任务。
    monkeypatch.setattr(src.strategy, "all_strategies", lambda: [SimpleNamespace(slug=retired_slug)])
    path = tmp_path / "ops.db"
    with tenant_scope("__primary__"), OpsStore(path) as store:
        old_id = store.create_job(name=f"screen:{retired_slug}", kind="screen",
                                  cron="30 15 * * mon-fri",
                                  config={"strategy": retired_slug}, enabled=enabled)
        custom_id = store.create_job(name="旧选股自定义任务", kind="screen",
                                     config={"strategy": f"skill:{retired_slug}"})
        unrelated_id = store.create_job(name="自定义有效选股", kind="screen",
                                        config={"strategy": "yangshi-tail-v1"})
        other_kind_id = store.create_job(name="无关任务", kind="notify",
                                         config={"strategy": retired_slug})
        first = store.ensure_managed_screen_jobs()
        assert first["created"] == 0
        assert first["removed"] == 2
        assert set(first["removed_slugs"]) == {retired_slug}
        assert store.get_job(old_id) is None
        assert store.get_job(custom_id) is None
        assert store.get_job(unrelated_id) is not None
        assert store.get_job(other_kind_id) is not None
        second = store.ensure_managed_screen_jobs()
        assert second["created"] == second["removed"] == 0
        assert store.get_job_by_name(f"screen:{retired_slug}") is None
    with tenant_scope("__primary__"), OpsStore(path) as reopened:
        result = reopened.ensure_managed_screen_jobs()
        assert result["created"] == result["removed"] == 0
        assert reopened.get_job_by_name(f"screen:{retired_slug}") is None


def test_retired_tail_is_absent_from_builtin_catalog_and_implementation():
    from importlib.util import find_spec
    from src.strategy import StrategyError, all_strategies, describe_all, get

    assert {engine.slug for engine in all_strategies()} >= {
        "qianlong-close-v3", "sanyuan-tail-v1", "yangshi-tail-v1",
    }
    assert all(engine.slug != "tail-micro-right-v1" for engine in all_strategies())
    assert all(item["slug"] != "tail-micro-right-v1" for item in describe_all())
    assert find_spec("src.strategy.application.tail_micro_right") is None
    with pytest.raises(StrategyError, match="未注册"):
        get("tail-micro-right-v1")


def test_manual_job_routes_reject_retired_strategy_but_allow_disable_and_retarget(tmp_path):
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from src.ops.api.jobs import build_jobs_router

    path = tmp_path / "ops.db"
    with OpsStore(path) as store:
        old_id = store.create_job(name="screen:tail-micro-right-v1", kind="screen",
                                  config={"strategy": "tail-micro-right-v1"})
    app = FastAPI()
    app.include_router(build_jobs_router(write_dependency=lambda: None, ops_db=str(path)))
    with tenant_scope("__primary__"), TestClient(app) as client:
        for slug in ("tail-micro-right-v1", "skill:tail-micro-right-v1", "screen:tail-micro-right-v1"):
            for enabled in (True, False):
                response = client.post("/api/jobs", json={
                    "name": "旧战法", "kind": "screen", "enabled": enabled,
                    "config": {"strategy": slug},
                })
                assert response.status_code == 422 and "已退役" in response.json()["detail"]
        assert client.post("/api/jobs", json={
            "name": "screen:tail-micro-right-v1", "kind": "screen",
        }).status_code == 422
        assert client.patch(f"/api/jobs/{old_id}", json={"enabled": True}).status_code == 422
        assert client.post(f"/api/jobs/{old_id}/run").status_code == 422
        assert client.patch(f"/api/jobs/{old_id}", json={"enabled": False}).status_code == 200
        response = client.patch(f"/api/jobs/{old_id}", json={
            "config": {"strategy": "yangshi-tail-v1"}, "enabled": True,
        })
        assert response.status_code == 200
        assert response.json()["config"]["strategy"] == "yangshi-tail-v1"
    with OpsStore(path) as store:
        assert len(store.list_jobs()) == 1
