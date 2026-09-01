# src/identity/api · HTTP 契约

> 归属：本上下文自有路由，由 `src/app/main.py` 直接 `include_router` 挂载
> （不经 `legacy/quant_router.py`）。

## 分层纪律

只做三件事：解析入参 → 调 `application` → 把领域错误映射成 HTTP。
限流、账号合并、口令强度这些判断都在 `application` / `domain`，别往这里搬。

## `/api/auth/*`

### 公开（未登录可用）

| 方法 | 路径 | 入参 | 出参 |
|---|---|---|---|
| GET | `/options` | — | `{email_signup, providers:[{name,family,label,mode}]}` |
| POST | `/login` | `{username,password}` | `{authenticated,user}` + Set-Cookie `loci_session` |
| POST | `/register` | `{email,password,username?,display_name?}` | `{ok,message,mail_delivered}`；**自助注册关闭时恒 403** |
| POST | `/verify-email` | `{token?,code?,email?}` | `{authenticated,user}`（直接登录） |
| POST | `/resend-code` | `{email}` | `{ok,message}` |
| POST | `/forgot-password` | `{email}` | `{ok,message}` |
| POST | `/reset-password` | `{token?,code?,email?,new_password}` | `{ok}`（**不自动登录**） |
| POST | `/logout` | — | `{authenticated:false}` |
| GET | `/session` | — | `{authenticated,username,user}` |
| POST | `/qr/start` | `{provider,redirect_to}` | `{state,mode,redirect_url?,qr_content?,expires_in}` + Set-Cookie `loci_qr_bind` |
| GET | `/qr/{state}` | — | `{status,redirect_to,error}` |
| POST | `/qr/{state}/scanned` | — | `{ok}` |
| POST | `/qr/{state}/claim` | — | `{authenticated,user}` + Set-Cookie |
| POST | `/mock/confirm` | `{state,handle}` | `{ok}`（**production 下 provider 不可用，必然 4xx**） |
| GET | `/callback/{provider}` | `?code=&state=` | 302 → `/login?claim_state=…` 或 `/login?auth_error=…` |

`options` 的 `email_signup` 来自 `infrastructure/registry.signup_enabled()`，
也就是环境变量 `LOCI_ALLOW_SIGNUP`（`1/true/yes/on` 为开，**缺省关**），
**与 `LOCI_AUTH_PROVIDERS` 里的 `email` 无关**——后者管的是「能不能用邮箱登录」。
登录页据此决定要不要画注册入口。

**`/register` 在自助注册关闭时直接 403**（`本站不开放自助注册，请联系管理员开通账号`），
且在任何副作用之前返回：不落审计、不发信。否则一条「已关闭」的注册端点仍然是
邮箱探测器 + 免费发信器。账号的正常来源是 `POST /admin/users`。

**`register` 对已存在的邮箱也返回成功**（开着的时候）——这不是 bug，是防枚举。
真实动作是给该地址发一封「有人尝试用你的邮箱注册」提醒邮件。

### 需登录

`/me`（GET/PATCH）、`/me/password`、`/me/sessions`（DELETE）、
`/me/identities/{id}`（DELETE）、`/api-keys`（GET/POST/DELETE）、
`/notifications`（GET）、`/notifications/read`（POST）。

组合根的生产鉴权中间件把 `/api/auth/` 整个前缀放行，再用
`private_auth_prefixes` 把上面这几条重新挡上。加新的私有端点时**两处都要改**。

## `/api/admin/*`

全部要求 `role == "admin"`，否则 403。

| 方法 | 路径 | 入参 | 出参 |
|---|---|---|---|
| GET | `/overview` | — | `{users,admins,top_llm_usage,recent_audit,announcements,tenants}` |
| GET | `/users` | `?keyword=`(≤64) `&status=`(≤16) `&limit=`(1..200，默认 50) `&offset=`(≥0) | `{items:[…],total}` |
| POST | `/users` | `{username,password,display_name?,email?,role?,status?}` | **201** + 单个用户行（与 `/users` 的 `items[i]` 同形） |
| PUT | `/users/{id}/role` | `{role}` | 用户资料 |
| PUT | `/users/{id}/status` | `{status}` | 用户资料 |
| PUT | `/users/{id}/quota` | `{llm_monthly_tokens?,…}` | 配额 |
| POST | `/users/{id}/password` | `{new_password}` | `{ok}` |
| POST | `/users/{id}/notify` | `?title=&body=` | `{id}` |
| GET | `/audit` | `?actor_id=`(≤64) `&keyword=`(≤64) `&action=`(≤64) `&outcome=`(≤16) `&limit=`(1..500，默认 50) `&offset=`(≥0) | `{items:[…],total}` |
| GET | `/logins` | `?keyword=`(≤64) `&outcome=`(≤16) `&limit=`(1..500，默认 50) `&offset=`(≥0) | `{items:[…],total}` |
| GET | `/announcements` | — | `{items}` |
| POST | `/announcements` | `{id?,title,body_md,level?,published_at?,expires_at?}` | `{id}` |
| DELETE | `/announcements/{id}` | — | `{ok}` |

`POST /users` 是**账号的正常来源**（本系统不走注册制）：口令带
`must_change_password`，`tenant_id` 独立（绝不复用 `__primary__`），带邮箱时
视为已验证。登录名/邮箱撞车 → 409，口令太弱 → 422。

`GET /audit` 的 `action` 是**前缀匹配**（敲 `admin.` 捞出全部管理动作），
`keyword` 命中 `actor_id` / `actor_name` / `target`。两个端点的 `total` 都是
**过滤后的总条数**（不是当前页条数），LIKE 里的 `%` `_` 一律转义。

`GET /logins` = 审计流按 `platform.LOGIN_ACTIONS`（`account.login` +
`account.social_login`）收窄，行结构与 `/audit` 完全一致。白名单写死在服务端，
不接受调用方传参——否则它就退化成 `/audit` 的别名。

`overview` 额外返回 `tenants`（磁盘上已存在的非主租户目录），
用于盘点——**它不是权威用户名单**，权威名单在 `users` 表。

## Cookie

| 名字 | 生命周期 | 属性 |
|---|---|---|
| `loci_session` | 30 天（滑动 7 天续期，绝对上限 30 天） | HttpOnly、SameSite=Lax、生产带 Secure |
| `loci_qr_bind` | 5 分钟 | HttpOnly，兑换后立即删除 |

`Secure` 由组合根按 `is_production and not PALACE_INSECURE_HTTP` 决定。
**本地 http 调试若带 Secure，浏览器根本不会回传 Cookie**——登录后立刻掉线。

## 错误映射

| 领域错误 | HTTP |
|---|---|
| `ValidationError` | 422 |
| `AuthenticationError` | 401 |
| `AuthorizationError` | 403 |
| `ConflictError` | 409 |
| `RateLimitedError` | 429 + `Retry-After` |
| `ProviderError` | 502（`detail` 里带厂商原始错误码） |
| `ProviderNotConfigured` | 503 |

## 兼容性

`GET /api/auth/session` 的响应保留了顶层 `username` 字段，
老前端（v1 的路由守卫）不改也能跑；新前端读 `user` 对象。
**不要删这个字段**。
