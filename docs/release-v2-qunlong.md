# v2.0「群龙」发布说明

> 从**单机单人工作台**跃迁到**多租户 + 社区化 + 实时大屏**的量化平台。
> 设计取舍见 [ADR-015](adr/ADR-015-v2-multi-tenant-identity-and-community.md)，
> 对标依据见 [平台产品与社区化对标](research/2026-08-quant-platform-product-benchmark.md)。

## 一句话：升级要做什么

**什么都不用做。** 老的 `data/` 目录就是新的「主租户」。

- 桌面端 `python loci.py`：照旧，不需要登录。
- 服务端：首启自动创建管理员账号，登录后看到的还是原来那套账本。
  - 配了 `PALACE_AUTH_USERNAME` / `PALACE_AUTH_PASSWORD` → 用它。
  - 没配 → **`lociAdmin` / `Asdf!234`**（带强制改密提示）。
  - 已经存在的同名账号**不会被重置密码**。
- 老的 `PALACE_WRITE_TOKEN`（Agent Bearer）继续有效，CI / 脚本 / MCP 客户端零改动。

## 20 项主要改动

### 身份与租户

| # | 改动 | 落点 |
|---:|---|---|
| 1 | **用户体系**：邮箱注册 + 验证码 + 找回密码 + 服务端会话（滑动 7 天 / 绝对 30 天） | `src/identity` |
| 2 | **微信 / QQ 扫码登录**：可插拔 provider 注册表，凭据不全就不出现在登录页；`mock` provider 让资质没批下来也能跑通全链路（production 下强制不可用） | `src/identity/infrastructure/oauth_providers.py` |
| 3 | **多租户数据隔离**：换 data 根而不是给每张表加 `user_id`。账本/运维/技能/研究产物每人一份，行情全局共享一份 | `src/shared/tenancy.py` + `src/shared/paths.py` |
| 4 | **RBAC 与管理员种子**：`admin` / `member` 两级；`lociAdmin` 绑主租户 | `src/identity/application/platform.py` |
| 5 | **每用户 LLM 私密配置与配额**：供应商密钥、模型、AI 会话、月度 token 与日调用上限全部按人隔离；补上了任务侧 5 个 LLM 调用点此前**从不计费**的缺口 | `src/ai/application/quota.py` |
| 6 | **多租户定时任务**：系统级（行情同步 / 热库 / 体检 / 留存）只跑一份，用户级（选股 / 盯盘 / 提醒 / 情报）各跑各的，带并发与租户数双上限 | `src/ops/application/tenant_jobs.py` |

### 实时

| # | 改动 | 落点 |
|---:|---|---|
| 7 | **实时行情推流中枢**：一个进程一个采集线程、N 个订阅者共享快照。此前是「N 个客户端 = N 次上游取数」，而 `(spot_batch, sina)` 的在途名额只有 1，大屏一上来就会把上游打成 403 | `src/market/application/live_hub.py` |
| 8 | **实时策略信号引擎**：6 条表驱动规则（均线金叉 / MACD 金叉 / 放量突破 / 快速拉升 / 临近涨停 / 炸板），带去抖与 cooldown，**每条信号强制 `provisional: true`** | `src/market/application/realtime_signals.py` |
| 9 | **SSE 推流路由** `/api/market/stream/{quotes,signals,stats}` | `src/market/api/stream_router.py` |
| 10 | **横屏飘动实时大屏** `/live`：跑马灯（动画与数据解耦）+ 涨跌热力带 + 指数分时 + 实时信号流 + 四列滚动榜；21:9 与 1280px 双向适配 | `frontend/src/features/live/` |

### 集体化

| # | 改动 | 落点 |
|---:|---|---|
| 11 | **策略广场**：发布 / 发新版 / 克隆 / 收藏 / 下架；**上架即冻结**（DB 触发器挡住改写） | `src/community` |
| 12 | **上架检查清单**：7 条机器可校验门槛（成交 ≥30 笔、区间 ≥1 年、佣金/印花/滑点不得为 0、必须声明 `entry_timing`、禁引流……） | `src/community/domain/publish_rules.py` |
| 13 | **排行榜**：`score = 一年夏普 × min(1, 上架天数/365)`。**不用裸收益率排序**——那必然被过拟合刷榜、单押高波动、多开小号三件事吃掉 | `src/community/domain/scoring.py` |
| 14 | **跟单订阅**：只推信号、不自动下单（DDL CHECK + API schema + docstring 三处兜死，合规红线） | `src/community/application/subscribe.py` |
| 15 | **社区互动**：评论 / 收藏 / 关注 / 动态流 / 用户主页 | `src/community` + `frontend/src/features/community/` |

### 平台

| # | 改动 | 落点 |
|---:|---|---|
| 16 | **管理后台** `/admin`：用户管理、配额、审计、公告、Top LLM 用量 | `frontend/src/features/admin/` + `/api/admin/*` |
| 17 | **审计日志**：只追加，租户改不动（在 `identity.db` 而不是各自的 `ops.db`） | `src/identity` |
| 18 | **开放 API Key**：`Authorization: Bearer loci_xxx`，明文只在创建响应里出现一次 | `/api/auth/api-keys` |
| 19 | **多通道告警**：企微 / 钉钉 / 飞书 / 通用 Webhook / 邮件 / 站内信六通道注册表，接在原有 seam 上，两处调用点零改动即获得全部通道 | `src/ops/application/notify_registry.py` |
| 20 | **登录 / 注册 / 账号中心前端**：单页四态切换 + 扫码状态机 + 会话设备管理 + 第三方绑定 | `frontend/src/features/auth/` |

## 新增环境变量

见 [`deploy/.env.example`](../deploy/.env.example)。要紧的三条：

```bash
# 邮件链接与 OAuth 回调的根地址。绝不从 Host 头推导（Host Header Injection）。
LOCI_PUBLIC_BASE_URL=https://your.domain

# 启用哪些登录方式。上线顺序是纯配置，代码零改动：
#   email → email,qq_web → email,qq_web,wechat_web
LOCI_AUTH_PROVIDERS=email

# 不配就把验证码写进日志，注册链路照样跑通（开发/内测够用）。
LOCI_SMTP_HOST=smtpdm.aliyun.com
```

## 数据布局变化

```
data/
├── identity.db          ← 新增（全局：账号、会话、配额、审计、通知）
├── community.db         ← 新增（全局：策略广场、榜单、订阅、动态）
├── market.db   ← 不变（全局共享）
├── market_hot.db        ← 不变（全局共享）
├── palace.db       ← 不变，现在归「主租户」
├── ops.db      ← 不变，现在归「主租户」
├── skills/  research_runs/  intraday/   ← 不变
└── tenants/             ← 新增
    └── u_xxxxxxxxxxxx/
     ├── palace.db
        ├── ops.db
        ├── skills/
        └── research_runs/
```

**备份优先级**：`identity.db` 与 `palace.db` 同级——它丢了所有人都登不上。
`market.db` 可重建，`community.db` 介于两者之间（发布物不可重建，榜单快照可重算）。

## 已知遗留

见 ADR-015 的「遗留项」。最要紧的一条：

> **陌生人的 Python 战法还没有沙箱。** 目前「克隆」只返回可导入的
> bundle、**不代跑**，就是在等这一层。在沙箱到位之前，不要开放
> 「一键运行别人的 Python 策略」。

## v2.1「收口」：上线后审计出来的 12 项

> v2.0 把形态换了，v2.1 补的是**换形态时被带出来、但不报错的那些洞**。
> 设计取舍见 [ADR-016](adr/ADR-016-v2-1-tenant-isolation-concurrency-retention.md)。

ADR-015 说「方案 B 的失败是打不开文件，会被立刻发现」。这句话对**落盘**成立，
对**上下文**不成立——真正的失效面搬到了「谁在读那个 ContextVar，读的时候它还在不在」。
下面 1、2 两条就是这条缝里长出来的，都是**静默串味、不报错、不刷红**。

### 隔离

| # | 改动 | 落点 |
|---:|---|---|
| 21 | **租户上下文跨线程传播**：`ContextVar` 不跨 `threading.Thread` / `ThreadPoolExecutor`，6 处从请求里裸起的后台线程全部落回主租户 = **管理员的 `data/`**。新增 `spawn_tenant_thread` / `submit_with_tenant` / `require_tenant`，默认值换成 `_UNBOUND` 哨兵让「没绑过」与「本来就是主租户」终于分得开；配一条 **AST 源码守卫**用例拦 revert | `src/shared/tenancy.py` |
| 22 | **战法目录按租户分片**：`_SCREEN_ENGINES` 是进程级 dict 且被全量 `clear()+update()`，**双向串味**——A 一保存战法，B 自己的战法当场从目录里消失，同时 B 看得见还跑得了 A 的私有战法（`install_path` 指向 A 的目录）。连同选股进度槽、实时信号去抖、悟道配额在途计数四处全局缓存一起按租户分片，各带 LRU 上限 | `src/strategy/application/catalog.py` |

### 定时任务

| # | 改动 | 落点 |
|---:|---|---|
| 23 | **两个 executor 池**：原来单池 10 线程 + `BoundedSemaphore(2)` + 300s 阻塞等待，50 租户 15:30 同时到期时**行情同步根本排不上队**。改用 APScheduler 3.x 原生多 executor，系统池 4 / 租户池 2 物理隔离；闸门改非阻塞，拿不到落 `skipped` 留痕 | `src/ops/infrastructure/scheduler.py` |
| 24 | **用户任务不抢行情写锁**：子租户选股恒不刷 spot、不做热库镜像——行情是全局共享事实，由主租户的系统任务负责，子租户只该读。当日行情没就绪就落 `skipped` 说明「等同步完成」，而不是自己去抢锁 | `src/ops/application/jobs/screen.py` |
| 25 | **系统级 kind 的第三道挡板**：调度侧两道挡板对 HTTP 手动触发完全不生效，普通 member 能手跑 `execute_sync` 独占 `market.db` 写锁 45 分钟。create / update / trigger 三个写口补齐，403（越权）/ 422（cron 快于 5 分钟）/ 429（配额）分开说话 | `src/ops/api/jobs.py` |
| 26 | **托管任务 cron 错峰**：每个租户 3 条选股原本都压在 `30 15`。按 `crc32(tenant)` 确定性散到 15:30~15:44（情报 15:40~15:54、候选跟踪 15:45~15:59），**主租户恒定不变**，存量行为零改动 | `src/ops/application/job_stagger.py` |

### 配额与垃圾

| # | 改动 | 落点 |
|---:|---|---|
| 27 | **`job_slots` 配额**：非管理员自建定时任务默认 ≤5 条。**系统托管的 7~8 条不占额度**——算进去的话新用户一登录就超额 | `src/ops/application/job_quota.py` |
| 28 | **`prune_tenant` 每租户清理**：`prune` 在 `SYSTEM_JOB_KINDS` 里，子租户 `ops.db` 此前**一条都不清**（`job_runs` 粗算 580 MB/年/人）。拆成主租户段（全局唯一的三样）与租户段（各跑一份，挂在 `ensure_tenant_jobs` 上零额外装载） | `src/ops/application/jobs/prune_tenant.py` |
| 29 | **保留期分三类**：纯时间 15 天 / 纯条数（`ai_sessions` 留 500 个，对话是用户资产）/ 时间+条数双闸门（`job_runs` 原来单一 `keep_per_job=200` 对 `*/5` 任务是 2.8 天、对日更任务是 10 个月）。时间比较一律 `julianday()`，删除分批 5000 行让出写锁 | `src/shared/sqlite_retention.py` |
| 30 | **`storage_mb` 软上限**：默认 2048 MB。超了只让清理进激进模式（保留期减半），**不拒绝写入**——把人锁在门外比留点垃圾更糟。AI 助手 8 张表、community 三表、identity 的会话/票据/通知/日用量此前**全部零清理**（`purge_expired()` 是死代码），一并接上 | `src/ops/application/tenant_storage.py` |

### 通知与前端

| # | 改动 | 落点 |
|---:|---|---|
| 31 | **通知渠道按租户隔离 + 企微限流**：`PALACE_OPS_DB` 一旦配置会让**全部租户共用一份通知配置（含企微 webhook）**。另外企微旧腿从不过限流，失败分支还没有按日去重——一个 `*/5` 的告警任务持续失败 = 全天 60+ 条推送。补上 20 条/分钟令牌桶（官方限额）与 45009 不可重试判定，并修掉 `run_serialized` 无超时的真实挂死 | `src/ops/application/notify_*.py` |
| 32 | **刷新即失忆**：`main.ts` 从不调 `userStore.load()`，守卫走的是另一套窄契约。F5 之后头像变「未登录」、`isAdmin=false` 让管理后台入口整个消失、强制改密条永不出现、未读角标恒为 0。守卫改为单一真相源，并把「没登录」与「后端挂了」分开 | `frontend/src/shared/router/index.ts` |

### 顺带修掉的死路

- **克隆策略无处可导**：`clone()` 把 bundle 复制到剪贴板并提示「去工坊粘贴导入」，
  而**工坊没有任何粘贴入口**——全站唯一的「导入」收的是通达信源码与 `.zip`。
  现在克隆直接进确认对话框 → 一键落进工坊（≤4 步），工坊也补了粘贴入口。
- **通知与公告没有读端**：`getNotifications` / `markNotificationsRead` / `AnnouncementItem`
  三样在 api 层齐了、管理后台写端也做完了，但**前端没有任何组件读它们**——
  管理员发的公告用户永远看不到。补 `NotificationCenter` 抽屉。
- **选股不可取消**：现在有 `POST /api/screen/run/cancel`，但**取消是协作式的**
  （选股主体是同步面板计算，线程杀不得），当前交易日会先跑完并入库。
  界面在检查点到达前只写「正在停止」，**禁止写「已取消」**。
- **窄屏无法退出登录**：≤980px 侧栏整体 `display:none`，连头像菜单一起消失，
  手机上没有任何办法打开账号页或退出。底栏抽屉补齐。
- 导航孤岛（`/my/community`、`/reviews/records`）、`/live` 有入口无出口、
  admin 断点 768 与全站 980 错位、9 处空 `catch` 让 401/403/500 显示同一句话。

## v2.1 验证口径

```powershell
.\.venv\Scripts\python.exe -m pytest tests/ -q     # 2462 passed, 464 subtests
.\.venv\Scripts\lint-imports.exe      # 14 contracts kept, 0 broken
.\.venv\Scripts\python.exe tools\import_smoke.py# 554 modules, 0 failed
cd frontend; bun run typecheck; bun run test; bun run build   # 597 tests
```

## 验证口径

```powershell
.\.venv\Scripts\python.exe -m pytest tests/ -q    # 2300+ 用例
.\.venv\Scripts\lint-imports.exe            # 14 contracts
.\.venv\Scripts\python.exe tools\import_smoke.py        # 545 个模块逐个 import
cd frontend; bun run typecheck; bun run test; bun run build
```
