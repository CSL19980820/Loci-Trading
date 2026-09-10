"""技能包装 / 卸的管理员边界。

2026-09 安全审查 RCE-SKILL-CLI-001（critical）的授权侧修复。技能包 frontmatter
的 `agents[]` 会在调用 LLM **之前**无条件跑完它声明的 CLI 子任务，而包内允许落
`.py`——所以「能上传技能包」等价于「能在服务器上执行任意代码」。旧实现三个装/卸
端点只挂 write guard，任何已登录租户（含最低权限 member）都能调。

这个文件钉住两件事：非管理员被拒、组合根真的把 auth_dependency 接上了。
后者是最容易静默退化的一环——`build_skills_router` 的 `auth_dependency` 有默认
None（桌面单机不注入），忘了传就退回旧行为且不报错。
"""
from __future__ import annotations

from typing import Any

import pytest
from fastapi import APIRouter, FastAPI
from fastapi.testclient import TestClient

from src.ops.api.skills import build_skills_router


class _Ctx:
    """最小 AuthContext 替身：只需要 require_admin 的两种结果。"""

    def __init__(self, *, admin: bool) -> None:
        self._admin = admin

    def require_admin(self) -> Any:
        if self._admin:
            return object()
        from src.identity.domain.models import AuthorizationError

        raise AuthorizationError("需要管理员权限")


def _client(*, admin: bool | None) -> TestClient:
    app = FastAPI()
    auth = None if admin is None else (lambda: _Ctx(admin=admin))
    app.include_router(
      build_skills_router(write_dependency=lambda: None, auth_dependency=auth)
    )
    return TestClient(app, raise_server_exceptions=False)


ZIP = {"file": ("x.zip", b"not-a-real-zip", "application/zip")}


@pytest.mark.parametrize(
    "method,path,kwargs",
    [
        ("post", "/api/skills", {"files": ZIP}),
        ("post", "/api/skills/sync-templates", {}),
 ("delete", "/api/skills/demo", {}),
],
)
def test_member_cannot_install_or_uninstall_skills(method, path, kwargs) -> None:
    """装 / 卸技能包 = 装 / 卸代码。member 拿到 403，不是 422/201。"""
    response = getattr(_client(admin=False), method)(path, **kwargs)
    assert response.status_code == 403, response.text


def test_admin_passes_the_authorization_gate() -> None:
    """管理员过授权闸门。

    断言的是「**不是** 403」而不是 201：这个 zip 是故意坏的，后面会被
    `install_skill` 拒成 422。授权与包校验是两道闸门，这里只测第一道。
    """
    response = _client(admin=True).post("/api/skills", files=ZIP)
    assert response.status_code != 403, response.text


def test_desktop_single_user_without_identity_is_not_blocked() -> None:
    """桌面单机不注入 auth_dependency：本机单用户，不该被管理员闸门挡死。"""
    response = _client(admin=None).post("/api/skills", files=ZIP)
    assert response.status_code != 403, response.text


def test_composition_root_actually_wires_the_identity_dependency() -> None:
    """组合根必须把 auth_dependency 接上——忘了传会静默退回旧行为。

  不去起整个 app（太重），直接查 `build_quant_router` 的转发链：它必须把
    `auth_dependency` 透给 `build_skills_router`。用 monkeypatch 截获实参。
    """
    import src.app.legacy.quant_router as qr

    seen: dict[str, Any] = {}
    real = None

    def spy(**kwargs: Any) -> APIRouter:
        seen.update(kwargs)
        return real(**kwargs)

    from src.ops.api import skills as skills_mod

    real = skills_mod.build_skills_router
    original = qr.build_quant_router
    assert original is not None

    import unittest.mock as mock

    with mock.patch.object(skills_mod, "build_skills_router", spy):
        qr.build_quant_router(
     write_dependency=lambda: None,
            auth_dependency=lambda: _Ctx(admin=True),
        )

    assert "auth_dependency" in seen, "组合根没把身份依赖传给 skills router"
    assert seen["auth_dependency"] is not None
