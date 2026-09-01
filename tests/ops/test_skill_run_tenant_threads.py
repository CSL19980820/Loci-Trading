"""对话式 Skill Run 的后台线程必须留在**发起请求那个租户**的目录里。

Skill run 的状态文件在 ``skill_runs_dir()``、技能包在 ``skill_root()``、运维库在
``ops_db()``——三者全是租户私有的。裸 ``threading.Thread`` 会让 run 建在 B 的目录、
执行与回写落在管理员目录（split-brain），而且真正被执行的是**管理员的技能包**。
"""
from __future__ import annotations

import threading
from typing import Any

from fastapi import APIRouter

from src.ops.api.schemas import SkillRunCreate
from src.ops.api.skill_runs_api import register_skill_run_routes
from src.shared.paths import ops_db, skill_root, skill_runs_dir
from src.shared.tenancy import current_tenant, tenant_scope


def _endpoint(router: APIRouter, path: str) -> Any:
    for route in router.routes:
        if getattr(route, "path", "") == path:
            return route.endpoint
    raise AssertionError(f"路由未注册：{path}")


def test_background_skill_run_thread_stays_in_the_caller_tenant(monkeypatch) -> None:
    from src.ops.application import skill_runtime, skills

    seen: dict[str, str] = {}
    done = threading.Event()

    monkeypatch.setattr(
        skills,
        "resolve_skill",
        lambda slug: {"slug": slug, "name": slug, "enabled": True},
    )

    def fake_drive(run_id: str, *, context: Any, **_kwargs: Any) -> dict[str, Any]:
        # 只抓路径：这里要验的是「线程内解析出来的库/目录归谁」。
        seen["tenant"] = current_tenant()
        seen["ops_db"] = str(ops_db())
        seen["store_db"] = str(context.ops_store.db_path)
        seen["runs_dir"] = str(skill_runs_dir())
        seen["skill_root"] = str(skill_root())
        done.set()
        return {"run": {"id": run_id}, "result": {}}

    monkeypatch.setattr(skill_runtime, "drive_skill_run", fake_drive)

    router = APIRouter()
    register_skill_run_routes(
        router,
        write_guard=None,
        ops_factory=lambda: None,
        market_db=None,
        ops_db=None,
        palace_db=None,
    )
    start = _endpoint(router, "/api/skills/{slug}/runs")

    with tenant_scope("u_a"):
        payload = SkillRunCreate(provider="demo", background=True)
        start(slug="demo-skill", payload=payload, _write=None)

    assert done.wait(30), "后台 skill run 没有跑起来"
    assert seen["tenant"] == "u_a"
    for key in ("ops_db", "store_db", "runs_dir", "skill_root"):
        assert "u_a" in seen[key], f"{key} 不属于发起租户：{seen[key]}"
