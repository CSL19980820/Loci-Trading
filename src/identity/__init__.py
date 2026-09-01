"""identity 限界上下文：账号、身份、会话、配额、审计、通知、公告。

职责
----
回答三个问题：**你是谁**（认证）、**你能做什么**（角色/配额）、
**你的数据在哪**（tenant_id → 私有库目录）。

边界
----
- 只写 ``identity.db``（全局唯一，不分租户）。
- 不认识行情、账本、策略。别的上下文要「当前用户」，经组合根注入的
  ``auth_dependency`` 拿，不要 import 本包的 infrastructure。
- 租户 → 物理路径的换算在 ``src/shared/tenancy.py``，不在这里。

关键入口
--------
- ``IdentityStore``：唯一读写口。
- ``build_auth_dependency(identity_db)``：给组合根用，产出 ``AuthContext`` 依赖。
- ``build_auth_router`` / ``build_admin_router``：HTTP 适配器。
- ``seed_default_admin(store)``：首启种子（lociAdmin / Asdf!234，主租户）。
- ``resolve_session`` / ``resolve_api_key``：凭证 → ``AuthContext``。

如何扩展
--------
- **加一种登录方式**：在 ``infrastructure/oauth_providers.py`` 写一个类，
  满足 ``OAuthProvider`` Protocol，注册进 ``infrastructure/registry.py``
  的 ``_REGISTRY``，然后把名字加进 ``LOCI_AUTH_PROVIDERS``。不用改路由。
- **加一项配额**：``store_platform.DEFAULT_QUOTAS`` 加键 + schema 加列，
  两处都要动（列是显式的，不用 JSON 大字段，便于管理员排序筛选）。
- **加一张表**：只准往 ``infrastructure/schema.py`` 的 ``_MIGRATIONS`` 尾部追加。

给 Agent 的用法
---------------
```python
from src.identity import IdentityStore, seed_default_admin

with IdentityStore() as store:
    admin = seed_default_admin(store)
    users = store.list_users(limit=20)
```

README 维护
-----------
改公开行为（新端点、新表、新 provider、鉴权语义）必须同批更新本文与
``api/README.md``，否则 DoD 失败。

相关测试
--------
``tests/identity/``
"""
from __future__ import annotations

from src.identity.api.admin_router import build_admin_router
from src.identity.api.router import build_auth_router
from src.identity.api.schemas import (
    BINDING_COOKIE,
    SESSION_COOKIE,
    build_auth_dependency,
)
from src.identity.application.accounts import (
    change_password,
    login_with_password,
    logout,
    register_with_email,
    resolve_api_key,
    resolve_session,
    verify_email,
)
from src.identity.application.platform import seed_default_admin
from src.identity.domain.models import (
    AuthContext,
    AuthenticationError,
    AuthorizationError,
    ConflictError,
    Identity,
    IdentityError,
    Role,
    SessionInfo,
    User,
    UserStatus,
    ValidationError,
)
from src.identity.domain.providers import (
    AuthzChallenge,
    ExternalIdentity,
    OAuthProvider,
    ProviderError,
)
from src.identity.infrastructure.registry import (
    enabled_providers,
    login_options,
    public_base_url,
)
from src.identity.infrastructure.store import IdentityStore

__all__ = [
    "BINDING_COOKIE",
    "SESSION_COOKIE",
    "AuthContext",
    "AuthenticationError",
    "AuthorizationError",
    "AuthzChallenge",
    "ConflictError",
    "ExternalIdentity",
    "Identity",
    "IdentityError",
    "IdentityStore",
    "OAuthProvider",
    "ProviderError",
    "Role",
    "SessionInfo",
    "User",
    "UserStatus",
    "ValidationError",
    "build_admin_router",
    "build_auth_dependency",
    "build_auth_router",
    "change_password",
    "enabled_providers",
    "login_options",
    "login_with_password",
    "logout",
    "public_base_url",
    "register_with_email",
    "resolve_api_key",
    "resolve_session",
    "seed_default_admin",
    "verify_email",
]
