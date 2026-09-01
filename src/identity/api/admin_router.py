"""``/api/admin/*``：平台管理后台。全部端点要求 ``role == "admin"``。

这些能力**故意不放进 ops 上下文**：ops 是「这台机器的运维」，
管理后台是「这个平台的治理」。两者的读者、权限、备份策略都不同。
"""
from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query

from src.identity.api.schemas import (
    AdminCreateUserRequest,
    AdminPasswordRequest,
    AnnouncementRequest,
    QuotaRequest,
    RoleRequest,
    StatusRequest,
    to_http,
)
from src.identity.application import platform
from src.identity.domain.models import AuthContext, IdentityError, User, utc_now
from src.identity.infrastructure.store import IdentityStore
from src.shared.tenancy import list_tenant_ids


def _user_row(store: IdentityStore, user: User) -> dict[str, Any]:
    """与 ``platform.list_users`` 的单项**同形**。

    新建用户后前端要能把返回值直接塞进列表，两处形状必须一致——抄两遍的写法
    已经在别处漂移过（列表有 quota、新建没有，表格当场空一列）。
    """
    row = user.self_dict()
    row["quota"] = store.get_quota(user.id)
    row["usage"] = store.usage_overview(user.id, period=utc_now().strftime("%Y-%m"))
    return row


def build_admin_router(*, auth_dependency: Any, identity_db: str | None = None) -> APIRouter:
    router = APIRouter(prefix="/api/admin", tags=["admin"])
    Auth = Depends(auth_dependency)

    def _store() -> IdentityStore:
        return IdentityStore(identity_db)

    def _admin(context: AuthContext) -> Any:
        try:
            return context.require_admin()
        except IdentityError as exc:
            raise to_http(exc) from exc

    @router.get("/overview")
    def overview(context: AuthContext = Auth) -> dict[str, Any]:
        _admin(context)
        from src.shared.paths import data_dir

        with _store() as store:
            data = platform.platform_overview(store)
        data["tenants"] = list_tenant_ids(data_dir())
        return data

    @router.get("/users")
    def list_users(
        keyword: str = Query(default="", max_length=64),
        status: str = Query(default="", max_length=16),
        limit: int = Query(default=50, ge=1, le=200),
        offset: int = Query(default=0, ge=0),
        context: AuthContext = Auth,
    ) -> dict[str, Any]:
        _admin(context)
        with _store() as store:
            items = platform.list_users(
                store, keyword=keyword, status=status, limit=limit, offset=offset
            )
            # total 必须跟着同一套过滤条件走，否则筛出 3 条却显示「共 128 条」，
            # 分页器会画出 7 个翻不动的空页。
            return {"items": items, "total": store.count_users(keyword=keyword, status=status)}

    @router.post("/users", status_code=201)
    def create_user(
        payload: AdminCreateUserRequest, context: AuthContext = Auth
    ) -> dict[str, Any]:
        """管理员开号。自助注册默认关闭，这是账号的正常来源。"""
        operator = _admin(context)
        try:
            with _store() as store:
                user = platform.create_user(
                    store,
                    operator=operator,
                    username=payload.username,
                    password=payload.password,
                    display_name=payload.display_name,
                    email=payload.email,
                    role=payload.role,
                    status=payload.status,
                )
                return _user_row(store, user)
        except IdentityError as exc:
            raise to_http(exc) from exc

    @router.put("/users/{user_id}/role")
    def set_role(user_id: str, payload: RoleRequest, context: AuthContext = Auth) -> dict[str, Any]:
        operator = _admin(context)
        try:
            with _store() as store:
                return platform.set_role(
                    store, operator=operator, user_id=user_id, role=payload.role
                ).self_dict()
        except IdentityError as exc:
            raise to_http(exc) from exc

    @router.put("/users/{user_id}/status")
    def set_status(
        user_id: str, payload: StatusRequest, context: AuthContext = Auth
    ) -> dict[str, Any]:
        operator = _admin(context)
        try:
            with _store() as store:
                return platform.set_status(
                    store, operator=operator, user_id=user_id, status=payload.status
                ).self_dict()
        except IdentityError as exc:
            raise to_http(exc) from exc

    @router.put("/users/{user_id}/quota")
    def set_quota(
        user_id: str, payload: QuotaRequest, context: AuthContext = Auth
    ) -> dict[str, int]:
        operator = _admin(context)
        limits = {key: value for key, value in payload.model_dump().items() if value is not None}
        if not limits:
            raise HTTPException(status_code=422, detail="至少要给一个配额项")
        try:
            with _store() as store:
                return platform.set_quota(
                    store, operator=operator, user_id=user_id, limits=limits
                )
        except IdentityError as exc:
            raise to_http(exc) from exc

    @router.post("/users/{user_id}/password")
    def reset_password(
        user_id: str, payload: AdminPasswordRequest, context: AuthContext = Auth
    ) -> dict[str, bool]:
        operator = _admin(context)
        try:
            with _store() as store:
                platform.reset_user_password(
                    store, operator=operator, user_id=user_id, new_password=payload.new_password
                )
        except IdentityError as exc:
            raise to_http(exc) from exc
        return {"ok": True}

    @router.post("/users/{user_id}/notify")
    def notify(
        user_id: str,
        title: str = Query(min_length=1, max_length=120),
        body: str = Query(default="", max_length=2000),
        context: AuthContext = Auth,
    ) -> dict[str, str]:
        _admin(context)
        with _store() as store:
            return {"id": store.push_notification(user_id=user_id, title=title, body=body)}

    @router.get("/audit")
    def audit(
        actor_id: str = Query(default="", max_length=64),
        keyword: str = Query(default="", max_length=64),
        action: str = Query(default="", max_length=64),
        outcome: str = Query(default="", max_length=16),
        limit: int = Query(default=50, ge=1, le=500),
        offset: int = Query(default=0, ge=0),
        context: AuthContext = Auth,
    ) -> dict[str, Any]:
        """审计流水。``action`` 前缀匹配，``keyword`` 命中操作者或对象。"""
        _admin(context)
        with _store() as store:
            return {
                "items": store.list_audit(
                    actor_id=actor_id,
                    keyword=keyword,
                    action=action,
                    outcome=outcome,
                    limit=limit,
                    offset=offset,
                ),
                "total": store.count_audit(
                    actor_id=actor_id, keyword=keyword, action=action, outcome=outcome
                ),
            }

    @router.get("/logins")
    def logins(
        keyword: str = Query(default="", max_length=64),
        outcome: str = Query(default="", max_length=16),
        limit: int = Query(default=50, ge=1, le=500),
        offset: int = Query(default=0, ge=0),
        context: AuthContext = Auth,
    ) -> dict[str, Any]:
        """登录记录。口令登录与第三方/扫码登录是同一件事的两条路，一起看。

        动作白名单写死在服务端（``platform.LOGIN_ACTIONS``），不让调用方传：
        否则这条端点就退化成 ``/audit`` 的别名，「登录记录」的语义随手就被改掉。
        """
        _admin(context)
        with _store() as store:
            return {
                "items": store.list_audit(
                    keyword=keyword,
                    outcome=outcome,
                    limit=limit,
                    offset=offset,
                    actions=platform.LOGIN_ACTIONS,
                ),
                "total": store.count_audit(
                    keyword=keyword, outcome=outcome, actions=platform.LOGIN_ACTIONS
                ),
            }

    @router.get("/announcements")
    def list_announcements(context: AuthContext = Auth) -> dict[str, Any]:
        _admin(context)
        with _store() as store:
            return {"items": store.list_announcements(only_live=False)}

    @router.post("/announcements")
    def upsert_announcement(
        payload: AnnouncementRequest, context: AuthContext = Auth
    ) -> dict[str, str]:
        operator = _admin(context)
        data = payload.model_dump()
        data["created_by"] = operator.username
        with _store() as store:
            announcement_id = store.upsert_announcement(data)
            store.write_audit(
                action="admin.announcement",
                actor_id=operator.id,
                actor_name=operator.username,
                target=announcement_id,
            )
            return {"id": announcement_id}

    @router.delete("/announcements/{announcement_id}")
    def delete_announcement(
        announcement_id: str, context: AuthContext = Auth
    ) -> dict[str, bool]:
        _admin(context)
        with _store() as store:
            return {"ok": store.delete_announcement(announcement_id)}

    return router
