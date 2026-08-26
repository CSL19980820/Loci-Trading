"""阻塞文件/压缩包工作不得运行在 FastAPI 事件循环中。"""
from __future__ import annotations

import inspect

from src.strategy.api.screen_skills_router import build_screen_skills_router
from src.ops.api.skills import build_skills_router


def _endpoint(router, path: str):
    return next(route.endpoint for route in router.routes if getattr(route, "path", "") == path)


def test_skill_archive_upload_endpoints_are_sync_threadpool_handlers() -> None:
    write_dependency = lambda: None

    skill_router = build_skills_router(write_dependency=write_dependency)
    screen_router = build_screen_skills_router(write_dependency=write_dependency)

    assert not inspect.iscoroutinefunction(_endpoint(skill_router, "/api/skills"))
    assert not inspect.iscoroutinefunction(_endpoint(screen_router, "/api/screen-skills/import"))
