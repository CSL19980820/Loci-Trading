# src/identity · 身份与平台治理

## 职责

回答三个问题：

1. **你是谁** —— 账号、口令、第三方身份、会话。
2. **你能做什么** —— 角色（`admin` / `member`）、配额、API Key、封禁。
3. **你的数据在哪** —— `tenant_id`，由 `src/shared/tenancy.py` 换算成私有库目录。

外加平台治理的三张附属表：审计日志、站内通知、全站公告。

## 边界

- **只写 `identity.db`**。这个库是**全局唯一、不分租户**的——身份本身就是跨租户的东西。
- **不可重建**。这里丢一行 = 一个用户永久失联。备份优先级与 `palace.db` 同级。
- 不认识行情、账本、策略。别的上下文要「当前用户」，从组合根注入的
  `auth_dependency` 拿，**不要 import 本包的 `infrastructure`**（`.importlinter`
  有 `protect-identity-infra` 契约挡着）。
- 租户 id → 物理路径的换算在 `src/shared/tenancy.py`，不在这里。这一层只产出
  `tenant_id` 这个字符串。

## 关键入口

| 符号 | 位置 | 用途 |
|---|---|---|
| `IdentityStore` | `infrastructure/store.py` | 唯一读写口。上下文管理器 |
| `build_auth_dependency(db, *, auto_login_primary)` | `api/schemas.py` | 给组合根用，产出 `AuthContext` 依赖 |
| `build_auth_router` / `build_admin_router` | `api/` | HTTP 适配器（`/api/auth/*`、`/api/admin/*`） |
| `seed_default_admin(store, *, username, password)` | `application/platform.py` | 首启种子 |
| `create_user(store, *, operator, username, password, …)` | `application/platform.py` | 管理员开号（账号的正常来源） |
| `signup_enabled()` | `infrastructure/registry.py` | 自助注册开关（`LOCI_ALLOW_SIGNUP`，默认关） |
| `resolve_session` / `resolve_api_key` | `application/accounts.py` | 凭证 → `AuthContext` |
| `login_with_password` / `register_with_email` | `application/accounts.py` | 本地账号 |
| `start_login` / `poll_state` / `complete_callback` / `claim_session` | `application/social_login.py` | 扫码/跳转登录状态机 |
| `enabled_providers()` / `login_options()` | `infrastructure/registry.py` | 当前可用的第三方登录 |

### 账号从哪来

**自助注册默认关闭，账号由管理员新增**（`LOCI_ALLOW_SIGNUP`：`1/true/yes/on`
才开，缺省关）。关闭时 `POST /api/auth/register` 直接 403，且不落审计不发信；
正常开号走 `POST /api/admin/users` → `platform.create_user`，初始口令带
`must_change_password`，新号拿**自己**的 `tenant_id`（绝不复用 `__primary__`），
管理员录入的邮箱视为已验证。

`LOCI_ALLOW_SIGNUP` 与 `LOCI_AUTH_PROVIDERS` 里的 `email` 刻意解耦：后者决定
「能不能用邮箱+口令**登录**」，前者决定「陌生人能不能自己开号」。

### 默认管理员

首启时若库里一个管理员都没有，创建 **`lociAdmin` / `Asdf!234`**，
`tenant_id = __primary__`（也就是老的 `data/` 目录本身，存量数据零迁移），
并打上 `must_change_password`。

`PALACE_AUTH_USERNAME` / `PALACE_AUTH_PASSWORD`（或 `LOCI_ADMIN_USERNAME` /
`LOCI_ADMIN_PASSWORD`）会覆盖它。**已存在的同名账号一律不改口令**——那是用户
自己改过的密码，每次启动重置回环境变量会让「改密」这个动作失去意义。

## 如何扩展

### 加一种登录方式

1. 在 `infrastructure/oauth_providers.py` 写一个类，满足
   `domain/providers.py` 的 `OAuthProvider` Protocol（`is_configured` /
   `start` / `exchange` 三个方法）。
2. 注册进 `infrastructure/registry.py` 的 `_REGISTRY`。
3. 把名字加进 `LOCI_AUTH_PROVIDERS` 环境变量。

**不用改路由、不用改前端**：登录页从 `GET /api/auth/options` 拿名片自己画按钮。
凭据不全的 provider 不会出现在名片里，所以「资质还没批下来」也能安全上线。

### 加一项配额

`infrastructure/store_platform.py` 的 `DEFAULT_QUOTAS` 加键 + `schema.py` 加列。
两处都要动：配额用**显式列**而不是 JSON 大字段，管理员后台要能排序和筛选。

### 加一张表

只准往 `infrastructure/schema.py` 的 `_MIGRATIONS` **尾部追加**，且每条语句
必须可重复执行（每次连接都会无条件重跑一遍）。

## 给 Agent 的用法

```python
from src.identity import IdentityStore, seed_default_admin

with IdentityStore() as store:
    admin = seed_default_admin(store)
    users = store.list_users(limit=20)
    store.write_audit(action="ops.something", actor_id=admin.id if admin else "")
```

跨上下文只从包根导入（`from src.identity import ...`）。深路径掏
`src.identity.infrastructure.*` 会被 `lint-imports` 拦下。

需要「当前请求的用户」时，**不要自己开库查**——组合根已经在
`TenantResolverMiddleware` 里解析过一次并缓存在 `request.state.loci_auth`，
再查一次是白白多开一条 SQLite 连接。

## 安全约定（改代码前先读）

| 约定 | 为什么 |
|---|---|
| 登录失败、找回密码、注册已存在邮箱，对外**同一种响应** | 任何差异都是邮箱枚举器 |
| 账号不存在时也跑一次 `verify_dummy` | 否则拿秒表就能枚举出注册过的邮箱 |
| 会话库里只存 `sha256(token)` | 库泄漏不等于会话泄漏 |
| 改密 / 封号 **立刻** `revoke_user_sessions` | 这是服务端会话相对 JWT 的全部价值 |
| 扫码 `confirmed → consumed` 用条件 UPDATE（CAS） | 同一个 state 只能兑出一个会话 |
| 扫码兑换要校验 `binding` Cookie | 挡住「A 发起、B 抢兑」 |
| 邮件里的链接从 `LOCI_PUBLIC_BASE_URL` 取，**绝不读 Host 头** | OWASP 点名的 Host Header Injection |
| 找回密码**不触发**账号锁定 | 否则任何人都能用「一直点找回」把别人锁死 |
| `mock` provider 在 production 下恒不可用，**无 override 开关** | 一个能凭空造账号的 provider，只要留一个开关就一定有一天被打开 |
| 合并账号只认 `(provider, subject)` 与 `(family, union_key)` | 昵称可改、可重名，拿它合并等于把账号送人 |

## README 维护

改公开行为（新端点、新表、新 provider、鉴权语义、默认管理员口径）
必须**同批**更新本文与 `api/README.md`，否则 DoD 失败。

## 相关测试

`tests/identity/test_identity.py` —— 口令策略、防枚举、限流锁定、改密踢会话、
封号断连、扫码状态机与重放保护、租户隔离、配额、审计。

`tests/identity/test_admin_users.py` —— 管理员开号（登录、改密标记、租户隔离、
重名 409、弱口令、按角色发配额）、过滤计数与 `list_*`/`count_*` 一致性、
LIKE 通配符转义、`LOGIN_ACTIONS` 白名单、`signup_enabled()` 的取值表。

`tests/identity/test_tenant_e2e.py` —— 真实 ASGI：多租户隔离、关闭注册后 403
且零痕迹、管理员开号后新人能登录。
