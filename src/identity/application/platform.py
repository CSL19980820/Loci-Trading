"""平台引导与管理员用例。

**首启种子**：库里没有任何管理员时，创建默认管理员
``lociAdmin / Asdf!234``，租户绑到 ``__primary__``——也就是**存量单机用户
原来的那套 data/ 目录**。升级到 v2 的人登录后看到的还是自己的账本，
零迁移、零导入。

默认口令写死在代码里是有意的（用户明确要求了这一对），但：

1. 种子只在「一个管理员都没有」时发生，不会覆盖已有账号；
2. 种子账号带 ``must_change_password``，前端会一直提示改密；
3. 环境变量 ``LOCI_ADMIN_USERNAME`` / ``LOCI_ADMIN_PASSWORD`` 可覆盖；
4. 历史遗留的 ``PALACE_AUTH_USERNAME`` / ``PALACE_AUTH_PASSWORD`` 也认，
   让老部署平滑过渡。
"""
from __future__ import annotations

from typing import Any
import logging
import os

from src.identity.domain import password as pw
from src.identity.domain.models import (
    AuthorizationError,
    ConflictError,
    User,
    ValidationError,
    check_password_strength,
    iso,
    normalize_email,
    normalize_username,
    utc_now,
)
from src.identity.infrastructure.store import IdentityStore
from src.identity.infrastructure.store_platform import ADMIN_QUOTAS
from src.shared.tenancy import PRIMARY_TENANT

logger = logging.getLogger(__name__)

DEFAULT_ADMIN_USERNAME = "lociAdmin"
DEFAULT_ADMIN_PASSWORD = "Asdf!234"


def seed_default_admin(
    store: IdentityStore,
    *,
    username: str | None = None,
    password: str | None = None,
    email: str | None = None,
) -> User | None:
    """确保平台有管理员账号；已就绪则返回 None（不改任何东西）。

        两种调用姿势：

        - **显式**（组合根传入 ``PALACE_AUTH_USERNAME`` / ``PASSWORD``）：
          「这套部署声明的管理员就是他」。即便库里已有别的管理员也照建，
          否则升级后老部署的凭据会突然失效。
        - **隐式**（不传参）：只在一个管理员都没有时种默认账号 lociAdmin。

        **已存在同名账号一律不改口令**——那是用户自己改过的密码，
        每次启动重置回环境变量会让「改密」这个动作失去意义。
        """
    explicit = bool(username and password)
    resolved_username = (
        username
        or os.environ.get("LOCI_ADMIN_USERNAME")
        or os.environ.get("PALACE_AUTH_USERNAME")
        or DEFAULT_ADMIN_USERNAME
).strip()
    resolved_password = (
        password
        or os.environ.get("LOCI_ADMIN_PASSWORD")
        or os.environ.get("PALACE_AUTH_PASSWORD")
        or DEFAULT_ADMIN_PASSWORD
)
    resolved_email = (email or os.environ.get("LOCI_ADMIN_EMAIL", "")).strip().lower()
    try:
        resolved_username = normalize_username(resolved_username)
    except ValidationError:
        resolved_username = DEFAULT_ADMIN_USERNAME
    existing = store.get_user_by_login(resolved_username)
    if existing is not None:
        if existing.role == "admin" and existing.status == "active":
            return None
        # 同名普通用户先于种子存在：提权而不是新建，避免撞登录名唯一索引。
        store.update_user(existing.id, role="admin", status="active")
        store.set_quota(existing.id, **ADMIN_QUOTAS)
        return store.get_user(existing.id)
    if not explicit and store.admin_exists():
        # 已经有别的管理员，说明平台早就初始化过，不再塞默认账号。
        return None
    # 主租户只能有一个（tenant_id UNIQUE）。第一个管理员接管老的 data/ 目录，
    # 后续管理员各自独立租户——他们是「平台管理员」，不是「同一个人的第二个号」。
    tenant = PRIMARY_TENANT if not store.count_users() else None
    user = store.create_user(
        username=resolved_username,
        email=resolved_email,
        password_hash=pw.hash_password(resolved_password),
        password_algo=pw.preferred_algo(),
        display_name="平台管理员",
        role="admin",
        status="active",
        tenant_id=tenant,
        must_change_password=resolved_password == DEFAULT_ADMIN_PASSWORD,
)
    if resolved_email:
        store.update_user(user.id, email_verified_at=iso(utc_now()))
        store.upsert_identity(
            user_id=user.id,
            provider="email",
            family="local",
            subject=normalize_email(resolved_email),
            display_name=user.display_name,
)
    store.set_quota(user.id, **ADMIN_QUOTAS)
    store.write_audit(action="platform.seed_admin", actor_id=user.id, actor_name=user.username)
    logger.warning(
        "已创建管理员 %s（租户 %s）；首次登录后请立即修改密码（设置 → 账号安全）",
        resolved_username,
        user.tenant_id,
)
    return user


def list_users(store: IdentityStore, **filters: Any) -> list[dict[str, Any]]:
    users = store.list_users(**filters)
    out: list[dict[str, Any]] = []
    for user in users:
        row = user.self_dict()
        row["quota"] = store.get_quota(user.id)
        row["usage"] = store.usage_overview(user.id, period=utc_now().strftime("%Y-%m"))
        out.append(row)
    return out


def set_role(store: IdentityStore, *, operator: User, user_id: str, role: str) -> User:
    if role not in ("admin", "visitor"):
        raise ValidationError("角色只能是 admin 或 visitor")
    target = store.get_user(user_id)
    if target is None:
        raise ValidationError("用户不存在")
    if target.id == operator.id and role != "admin":
        # 自己把自己降级 = 可能把最后一个管理员降掉，直接锁死平台。
        raise AuthorizationError("不能取消自己的管理员身份")
    if not operator.is_admin:
        raise AuthorizationError("需要管理员权限")
    updated = store.update_user(user_id, role=role,
                                view_tenant_id=(target.view_tenant_id or target.tenant_id) if role == "visitor" else "",
                                must_change_password=0 if role == "visitor" else target.must_change_password)
    if target.role != role:
        store.revoke_user_sessions(user_id)
    store.write_audit(
    action="admin.set_role",
    actor_id=operator.id,
    actor_name=operator.username,
    target=user_id,
    detail={"role": role},
    )
    if updated is None:
        raise ValidationError("用户不存在")
    return updated


def set_status(store: IdentityStore, *, operator: User, user_id: str, status: str) -> User:
    if status not in ("active", "pending", "disabled"):
        raise ValidationError("状态只能是 active / pending / disabled")
    target = store.get_user(user_id)
    if target is None:
        raise ValidationError("用户不存在")
    if target.id == operator.id and status != "active":
        raise AuthorizationError("不能停用自己")
    updated = store.update_user(user_id, status=status)
    if status == "disabled":
        # 封号必须立刻断开在线会话，否则「封了还能用到下次过期」。
        store.revoke_user_sessions(user_id)
    store.write_audit(
    action="admin.set_status",
    actor_id=operator.id,
    actor_name=operator.username,
    target=user_id,
    detail={"status": status},
    )
    if updated is None:
        raise ValidationError("用户不存在")
    return updated


def set_quota(
    store: IdentityStore, *, operator: User, user_id: str, limits: dict[str, int]
) -> dict[str, int]:
    if store.get_user(user_id) is None:
        raise ValidationError("用户不存在")
    result = store.set_quota(user_id, **limits)
    store.write_audit(
    action="admin.set_quota",
    actor_id=operator.id,
    actor_name=operator.username,
    target=user_id,
    detail=limits,
    )
    return result


def reset_user_password(
    store: IdentityStore, *, operator: User, user_id: str, new_password: str
) -> None:
    """管理员代重置。会踢掉该用户全部会话并要求下次登录改密。"""
    from src.identity.domain.models import check_password_strength

    check_password_strength(new_password)
    if store.get_user(user_id) is None:
        raise ValidationError("用户不存在")
    store.set_password(
    user_id, password_hash=pw.hash_password(new_password), algo=pw.preferred_algo()
    )
    target = store.get_user(user_id)
    store.update_user(user_id, must_change_password=bool(target and target.is_admin))
    store.revoke_user_sessions(user_id)
    store.write_audit(
    action="admin.reset_password",
    actor_id=operator.id,
    actor_name=operator.username,
    target=user_id,
    )


#: 「登录记录」页认这两类事件。口令登录与扫码/第三方登录是同一件事的两条路，
#: 分开看等于把一半的登录记录藏起来；而 ``account.register`` 之类不是登录。
LOGIN_ACTIONS = ("account.login", "account.social_login")


def create_user(
    store: IdentityStore,
    *,
    operator: User,
    username: str,
    password: str,
    display_name: str = "",
    email: str = "",
    role: str = "visitor",
    status: str = "active",
) -> User:
    """管理员在后台开号。

    本系统**不支持注册制**（``LOCI_ALLOW_SIGNUP`` 默认关闭），所以这里是账号的
    唯一正常来源，首启种子只负责第一个管理员。
    """
    if not operator.is_admin:
        raise AuthorizationError("需要管理员权限")
    if role not in ("admin", "visitor"):
        raise ValidationError("角色只能是 admin 或 visitor")
    if status not in ("active", "disabled"):
        raise ValidationError("状态只能是 active 或 disabled")
    login = normalize_username(username)
    if not login:
        raise ValidationError("登录名不能为空")
    check_password_strength(password)
    address = normalize_email(email) if email else ""
    # 先预检，撞名时给一句人话；``store.create_user`` 的 IntegrityError 仍是兜底
    # ——预检与插入之间有并发窗口，唯一索引才是最终裁判。
    if store.get_user_by_login(login) is not None:
        raise ConflictError("登录名已被占用")
    if address and store.get_user_by_login(address) is not None:
        raise ConflictError("邮箱已被占用")
    user = store.create_user(
        username=login,
        email=address,
        password_hash=pw.hash_password(password),
        password_algo=pw.preferred_algo(),
        display_name=display_name or login,
        role=role,
        status=status,
        # Identity remains private. Only visitors receive an explicit, read-only
        # delegation to the creating administrator's workspace. Promotion to admin
        # clears that delegation, so it can never become write access to this data.
        tenant_id=None,
        view_tenant_id=operator.tenant_id if role == "visitor" else "",
        must_change_password=role == "admin",
    )
    if address:
        # 管理员代开的号视为**邮箱已验证**：这条路径上邮箱是管理员录入的事实，
        # 再让用户走一遍收信验证只会把人卡在门外（多半还收不到那封信）。
        store.upsert_identity(
            user_id=user.id,
            provider="email",
            family="local",
            subject=address,
            display_name=user.display_name,
        )
        store.update_user(user.id, email_verified_at=iso(utc_now()))
    if role == "admin":
        store.set_quota(user.id, **ADMIN_QUOTAS)
    # 访客不运行计算或写入作品，不需要资源配额。
    store.write_audit(
        action="admin.create_user",
        actor_id=operator.id,
        actor_name=operator.username,
        target=user.id,
        detail={"role": role, "status": status},
    )
    refreshed = store.get_user(user.id)
    return refreshed or user


def platform_overview(store: IdentityStore) -> dict[str, Any]:
    period = utc_now().strftime("%Y-%m")
    return {
    "users": store.count_users(),
    "admins": len([u for u in store.list_users(limit=500) if u.is_admin]),
    "top_llm_usage": store.top_usage(period=period, metric="llm_tokens", limit=10),
    "recent_audit": store.list_audit(limit=20),
    "visitors": len([u for u in store.list_users(limit=500) if not u.is_admin]),
}
