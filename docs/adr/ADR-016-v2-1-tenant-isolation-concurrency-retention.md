# ADR-016 · v2.1「收口」：租户隔离的失效面、任务并发与保留期

**状态**：已采纳并落地（2026-08-27）
**日期**：2026-08-27
**相关**：[ADR-015](ADR-015-v2-multi-tenant-identity-and-community.md)（v2 多租户形态）、[ADR-014](ADR-014-encrypted-intraday-tape-retention.md)（盘中留存带 60 天不可改小）

## 背景

ADR-015 选的多租户方案是 **B：每租户一套库文件**，理由是失败模式——
方案 A（给 33 张表加 `user_id`）漏一个 `WHERE` 就静默串户，方案 B 漏了就打不开文件。

上线后做了一轮专项审计，结论是：**这个论断成立，但它只覆盖了「落盘」这一层。**
方案 B 把路径解析收敛到 `src/shared/paths.py` 的一组函数，这些函数读
`ContextVar` 里的当前租户。于是真正的失效面从「SQL 写错」搬到了
**「谁在读那个 ContextVar，以及读的时候它还在不在」**。

审计确证了两类此前不报错、不刷红、只是静默串味的缺陷：

| 类别 | 实例 | 后果 |
|---|---|---|
| **上下文丢失** | 6 处从请求里裸起 `threading.Thread` / `ThreadPoolExecutor.submit` | 工作线程内 `current_tenant()` 落回 `PRIMARY_TENANT` 默认值 = **管理员的 `data/`**。B 的选股结果写进管理员账本；AI 会话的 run 行建在 B 的库、执行在主租户库，于是 `get_run()` 查不到，会话**永久卡在 running 且静默失败** |
| **进程级全局缓存** | `_SCREEN_ENGINES`、`screen_run._STATE`、`realtime_signals._fired`、`intel.quota._INFLIGHT` | 「按租户读 → 写进程级全局」把租户维度整个抹平。A 一保存战法，B 的战法从目录里消失；且 `catalog.get(slug)` 被 `screener` 与 `backtest/runner` 消费，**B 能直接跑 A 的代码**，`install_path` 指向 A 的租户目录 |

两类都不是「某人写错了一行 SQL」，是**方案 B 自带的、可预测的失效面**。
这份 ADR 的第一件事就是把它写下来，让下一个人不必再靠审计发现一次。

## 决策

### 1. 租户上下文的传播是一条纪律，不是一次修复

`ContextVar` 只跨 asyncio Task 与 anyio 的 `run_in_threadpool` 自动复制，
**不跨 `threading.Thread` 与 `ThreadPoolExecutor`**。

在 `src/shared/tenancy.py` 加三样东西：

```python
def spawn_tenant_thread(target, *, name=None, args=(), ...) -> Thread
def submit_with_tenant(executor, fn, /, *args, **kwargs) -> Future
def require_tenant() -> str      # 没显式绑过就抛 TenantError
```

配套改动：

- `_current_tenant` 的默认值从 `PRIMARY_TENANT` 换成一个 `_UNBOUND` 哨兵。
  `current_tenant()` 仍把哨兵映射回主租户（存量单机零迁移），但
  `tenant_is_bound()` 现在能区分「没绑过」与「本来就是主租户」——
  **这两件事以前长得一模一样，是所有静默降级的共同前提。**
- 6 处线程入口全部改用包装器。
- `tests/ai/test_tenant_threads.py` 里有一条 **AST 源码守卫**：扫这 7 个文件里
  的 `threading.Thread(` 与 `.submit(`，注释不计。这条用例的作用不是发现 bug，
  是拦住下一次 revert——纪律没有守卫就只是一句口号。

**为什么不改成「所有后台任务都走一个统一队列」**：那是对的方向，但它要动
6 个上下文的调用约定，而当下的缺陷是**正在生产上串味**。先用包装器把血止住，
队列化留给后面的版本。

### 2. 进程级缓存一律按租户分片，且分片表必须有上限

四处全局缓存改成 `dict[tenant, ...]`。分片带 LRU 上限（战法目录 64 个租户，
选股进度槽 64 个，去抖表 50000 条 FIFO）——**没有上限的分片是内存泄漏换了个名字**，
服务器只有 1.1 GB。

`_SCREEN_ENGINES` 有一个额外问题：进程启动时只刷过主租户，某租户首次访问时
分片是空的。用**回调注入**解决（`catalog.set_loader(fn)`，由 `screen_skills`
在 import 时注册），而不是让 `catalog` 反向 import `screen_skills` 成环。

> **修订（2026-08，战法级多槽）**：选股进度槽从「每租户一个」细化成
> `_STATES[tenant][strategy_slug]`——本决策只解决了跨租户串味，却把「同一个人
> 跑潜龙时点不动三源」当成了既定事实；底层 `market_gate` 早就是「sync 独占写 /
> screen 共享读」，那个限制纯粹来自这张表的形状。上限随之变成三道：外层 64 个
> 租户、内层 `MAX_RUNS_PER_TENANT = 6`、**再加一道全进程总闸
> `MAX_TOTAL_RUN_SLOTS = 96`**。本节那句「没有上限的分片是内存泄漏换了个名字」
> 在两层分片下要读作：**两个上限相乘不等于有界**（64 × 6 = 384 份
> `result.picks`），所以总槽数必须单独封顶，量级与改造前持平。同时在跑的选股另有
> `MAX_CONCURRENT_RUNS = 3`（`LOCI_SCREEN_MAX_CONCURRENT_RUNS` 可覆盖）——那是 CPU
> 闸，不是内存闸。详见 `src/strategy/application/screen_run_state.py`。

### 3. 定时任务：两个 executor 池，而不是一个信号量

原实现是单池（APScheduler 默认 `max_workers=10`，本仓从未覆盖）+
`BoundedSemaphore(2)` + `acquire(timeout=300)`。代码注释自己写了
「全被堵住等于整个调度器停摆」，然后用了 300 秒阻塞等待。

50 个租户在 15:30 同时到期时，10 条线程全被租户任务堵死 300 秒，
**行情同步根本排不上队**。

改用 APScheduler 3.x 原生的多 executor：

```python
BackgroundScheduler(executors={
    "default": APThreadPool(max_workers=4),# 系统级任务专用
    "tenant":  APThreadPool(max_workers=2),   # 租户任务
})
```

池宽即并发上限，两池物理隔离，**租户任务再多也挤不掉行情同步**。
`_tenant_gate` 保留但改成 `acquire(blocking=False)`，拿不到就落 `skipped` 留痕
——留着它不是为了限流（那是池宽的事），是为了让「被挤掉了」这件事可观测。

### 4. 用户任务只读行情，不抢写锁

链路：`execute_screen` → `ensure_today_quotes_for_screen` → `apply_today_spot`
→ **全局 `market_write_lock`**，`refresh_spot` 默认 `True`。

**子租户的选股任务恒不刷 spot。** 行情是全局共享事实，由主租户的系统级同步
任务负责；子租户只该读。当日行情不就绪就落 `skipped` 并说明「等行情同步完成」，
而不是自己去抢锁。同理，`mirror_recent_to_hot` 从选股任务里摘掉——镜像是
sync 的写职责。

### 5. 三道挡板守系统级 kind，写口都要拦

调度侧原有两道挡板（装载层、执行层）对 **HTTP 手动触发完全不生效**：
`POST /api/jobs/{id}/run` 没有守卫，普通 member 能手跑 `execute_sync`
独占全局 `market.db` 写锁最长 45 分钟。

补第三道，挂在 create / update / trigger 三个写口上，按状态码分说：

| 码 | 含义 |
|---|---|
| 403 | 非主租户碰系统级 kind（`sync` / `prune`） |
| 422 | 非主租户 cron 快于 5 分钟下限 |
| 429 | `job_slots` 配额超限 |

`JobCreate.kind` 的 Literal **保持不变**（主租户仍需能建 `sync`/`prune`），
越权由守卫按租户拦，不靠收窄类型——收窄了主租户就也建不了。

### 6. 配额的语义只有一套：0 = 系统默认，负数 = 不限

`user_quotas` 加两列：`job_slots`（默认 5）与 `storage_mb`（默认 2048）。

两个刻意的取舍：

- **系统托管任务不占 `job_slots`。** 子租户开箱就有 7~8 条托管任务
  （候选跟踪 / 3 条选股 / 3 条情报），算进去的话新用户一登录就超额。
  额度只管**用户自己建的**。
- **`storage_mb` 超限不拒绝写入。** 超了只是让清理任务进入激进模式
  （保留期减半再清一轮）并在账号页红字提示。**把人锁在门外比留点垃圾更糟。**

配额闸门只放 API 层，**绝不放 `OpsStore.create_job` / `ensure_job`**——
`_ensure_step` 只打 warning，闸门放进去会让启动时的托管确保**静默卡死**。

### 7. 保留期分三类，时间比较必须用 `julianday`

全仓 40 类持续增长的数据，此前只有 5 类真的有人清。三个最严重的盲区：
`prune` 在 `SYSTEM_JOB_KINDS` 里 → 子租户 `ops.db` 一条不清（`job_runs` 粗算
580 MB/年/人）；AI 助手 8 张表全部无清理；`IdentityStore.purge_expired()`
是**全仓零调用点的死代码**。

拆成 `prune`（主租户一份：`data/intraday/` + identity.db + community.db，
这三样全局唯一）与 **`prune_tenant`**（每租户各跑一份，挂在 `ensure_tenant_jobs`
上，零额外装载代码）。保留期按数据性质分三类：

| 类 | 判据 | 例子 |
|---|---|---|
| 纯时间（15 天） | 只有时间意义 | `ai_agent_events`、`monitor_runs`、`alert_hits` |
| 纯条数 | 是用户资产，砍时间会腰斩 | `ai_sessions` 留最近 500 个会话 |
| 时间 + 条数双闸门 | 频率差异巨大 | `job_runs`：`keep_min=5` / `keep_max=200` / `keep_days=15` |

`job_runs` 必须双闸门：原来单一的 `keep_per_job=200` 对 `*/5` 的任务是 2.8 天，
对日更任务是 10 个月——**同一个参数给出了从 2.8 天到 10 个月的保留期**。

**时间比较一律 `julianday()`。** `job_runs` 里新旧两种时间戳并存（历史行是
UTC 裸串 `"YYYY-MM-DD HH:MM:SS"`，新行是本地带偏移 `"...T...+08:00"`），
字符串比会差 8 小时，且 `'T' > ' '` 让排序也一起错。
唯一的例外是纯 `YYYY-MM-DD` 列——但那要写成 `length(period) = 10` 这样的
**显式判断**，而不是靠「`julianday('2026-08')` 恰好返回 NULL」这种巧合。

删除必须分批：SQLite 的 `DELETE ... LIMIT` 需要编译选项，CPython 自带的没开，
所以走 `WHERE rowid IN (SELECT ... LIMIT 5000)` 循环，批间让出写锁。
首次开 15 天会一次删掉几十万行，不分批就是 WAL 暴涨 + 长时间持写锁。

**明确不砍的四类**：`audit_log`（180 天，合规）、`ai_sessions`/`ai_messages`
（用户资产，按条数）、`data/intraday/`（**60 天，ADR-014，上游取不到历史，
删早了永久没有**）、`palace.db` 全部（账本）。

### 8. 取消是协作式的，界面不许说「已取消」

选股主体是一段同步的 pandas 面板计算：没有可打断的 IO 等待点，线程也不能在
持有 SQLite 连接与 `ExitStack` 的中途被强杀。所以
`POST /api/screen/run/cancel` **只立一面旗**，真正的退出发生在交易日循环头的
检查点上。

由此产生三条硬约束：

1. 旗按租户——A 点停止不能停掉 B 的选股。
2. 新一轮开跑前旗必须落下，否则「取消过一次之后」再开就会刚进循环即自尽。
3. **已经跑完的交易日不回滚。** 取消是「不再往下跑」，不是「撤销做过的事」；
   已入库的候选是真实发生过的选股结果。

界面在检查点到达之前只能写「正在停止」。技能运行仍然没有中止端点，
所以它的文案与选股**不共用**——把「停得掉」和「停不掉」写成同一句话就是骗人。

## 后果

**好的：**

- 两个高危串味缺陷（`_SCREEN_ENGINES` 双向串味、上下文不跨线程）有了确证的
  修复与双租户回归；后者还有 AST 守卫拦 revert。
- 行情同步不再可能被租户任务饿死（物理隔离，不是靠调参）。
- 每租户垃圾有上限，且上限超了不会把人锁在门外。
- 不引入任何新依赖：多 executor 是 APScheduler 3.x 原生能力，分批删除、令牌桶、
  租户传播全是 stdlib。明确否决了 redis / celery / rq / dramatiq（违反单副本
  部署约定）与 apscheduler 4.x（至今只有 4.0.0a6 alpha，官方明写 do NOT use
  in production——同时给 `apscheduler>=3.11,<4` 钉上上界，否则 4.0 出 stable
  当天 pip 就会解析到 4.x 直接 ImportError）。

**代价与遗留：**

- 分片缓存的 LRU 上限是拍的（64）。租户数超过它会有目录反复重载的抖动，
  届时应当改成按内存占用而不是按个数淘汰。
- 取消最坏要等一个交易日的选股耗时。要更快只能在选股主循环内部再加检查点，
  那要动 `screen` 的签名，本轮没做。
- `prune_tenant` 与 `prune` 各自有一份 cron 错峰逻辑的调用（共用
  `job_stagger.tenant_minute_offset`，但小时进位各算各的），因为
  `staggered_cron` 刻意拒绝跨整点。两处不一致时以 `job_stagger` 为准。
- 前端 `cronPreview.ts` 复刻了后端的 5 分钟下限与星期归一化。**权威值在后端**
  （`MIN_TENANT_CRON_INTERVAL_SECONDS` / `cron_interval_seconds()`），
  前端那份只做提交前的就地提示，两处不一致以后端为准。
