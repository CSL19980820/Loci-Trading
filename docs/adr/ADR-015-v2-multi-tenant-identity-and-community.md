# ADR-015 · v2「群龙」：多租户身份、社区化与实时大屏

- 状态：已采纳（2026-08-27）
- 影响范围：`src/identity`（新）、`src/community`（新）、`src/shared/tenancy.py`（新）、`src/shared/paths.py`、`src/app/main.py`、`src/market`（实时推流）、`frontend/src/features/{auth,live,community}`
- 取代：无（这是对 [ADR-002] 之后单机形态的第一次形态跃迁）

## 背景

v1 的 Loci 是一台机器、一个人、一套 `data/`。

具体到代码：全仓 **0 个 users 表、0 个 `user_id` 列、0 个 `current_user` 依赖**。
鉴权只有两条路径——环境变量里的一对固定账号（`PALACE_AUTH_USERNAME` /
`PALACE_AUTH_PASSWORD`，`compare_digest` 明文比对）和一个长期静态的
`PALACE_WRITE_TOKEN`。`llm_providers.name` 上挂着全局 `UNIQUE`，
`set_default_provider` 的第一句是 `UPDATE llm_providers SET is_default = 0`
（全表清零）。这些都不是缺陷，是「单机」这个前提的自然结果。

而目标形态是：**多人同时用，各自的账本/策略/AI 配置互不可见，同时有一个
公共的策略广场和一块公共的实时大屏。**

## 决策

### 1. 多租户 = 换 data 根，不是给每张表加 `user_id`

调研过两条路：

| 方案 | 改动面 | 串户风险 | 备份/删号 |
|---|---|---|---|
| A. 33 张表加 `user_id` | 272 条 DML、49 条 DDL、17 处 PK/UNIQUE 重建（其中 5 处必须建新表搬数据） | 任何一条漏加 `WHERE user_id=?` 就串户，且**测试极难覆盖全** | 要写导出/删除脚本 |
| B. 每租户一套库文件 | **0 条 SQL 改动** | 物理不可能串户 | `rm -rf tenants/<uid>` |

选 **B**。理由不是工作量，是**失败模式**：方案 A 的失败是「静默地把别人的
持仓显示给你」，方案 B 的失败是「打不开文件」。后者会被立刻发现。

落地方式是一行都不改业务代码：

- 仓内 25+ 个 router 工厂默认收到的 `palace_db` / `ops_db` 就是 `None`，
  下游 `OpsStore(None)` / `PalaceStore(...)` 本来就会回落到
  `src/shared/paths.py` 的解析函数。
- 于是只要让 `palace_db()` / `ops_db()` / `skill_root()` /
  `research_runs_dir()` / `mcp_json_path()` 认得 ContextVar 里的当前租户，
  多租户就自动生效。见 `src/shared/tenancy.py`。

隔离边界：

| 数据 | 归属 | 理由 |
|---|---|---|
| `palace.db` 账本 | 每租户 | 成交/候选/预案/复盘是私人事实 |
| `ops.db` 运维 | 每租户 | **LLM 密钥、AI 会话、纸面舱、任务配置都是私密的** |
| `skills/` `research_runs/` | 每租户 | 用户自建战法与研究产物 |
| `market.db` `market_hot.db` | 全局共享 | 行情是公共事实，按人复制既费磁盘又费带宽 |
| `identity.db` `community.db` | 全局共享 | 身份与社区本来就是跨用户的 |

**主租户 `__primary__` 就是老的 `data/` 目录本身。** 升级到 v2 的存量单机
用户，以管理员身份登录后看到的还是自己那套账本——零迁移、零导入、零脚本。

### 2. ContextVar 必须由纯 ASGI 中间件绑定

`@app.middleware("http")`（`BaseHTTPMiddleware`）会把下游放进另一个 anyio
任务，ContextVar 的传播语义随 Starlette 版本变过。改用纯 ASGI 中间件
（`src/app/tenant_middleware.py`）在同一个任务里 `await` 下游，绑定关系确定；
同步路由走 `run_in_threadpool`，anyio 会把 context 复制进线程，同样读得到。

**它必须是最外层中间件**（`add_middleware` 后加的先跑）。踩过的坑：注册在
生产鉴权闸门内层时，登录返回 200 但下一个请求仍然 401——闸门读
`request.state.loci_auth` 时它还没被写入。

### 3. 会话用服务端 sessions 表，不用 JWT

JWT 做不到三件事，而这三件事我们都要：改密后踢掉所有旧会话、管理员远程下线、
封号即刻断开。`sessions` 表存 `sha256(token)`，明文只在 Cookie 里；
滑动过期 7 天 + 绝对上限 30 天双闸门。

### 4. 第三方登录：先有可插拔契约，再有实现

微信/QQ 开放平台都要主体资质 + 应用审核才能拿到 appid/secret。等审核过了
才发现状态机有 bug，代价高得多。所以：

- 契约在 `src/identity/domain/providers.py`（`OAuthProvider` Protocol），不依赖 httpx；
- 真实现（`wechat_web` / `qq_web`）与 `mock` 实现同构，都在 infrastructure；
- 启用哪些由 `LOCI_AUTH_PROVIDERS` 环境变量决定，**上线顺序是纯配置**：
  `email,mock` → `email,qq_web` → `email,qq_web,wechat_web`，代码零改动；
- `mock` provider 在 `PALACE_ENV=production` 下 `is_configured()` 恒为 False，
  **刻意不提供 override 开关**——一个能凭空造账号的 provider 只要留一个开关，
  就一定有一天被打开。

调研得到的两条硬事实写进了代码注释：微信的 `unionid`「当且仅当已获得
userinfo 授权时才出现」（必须容忍缺失）；QQ 的 token 与 me 两个接口
**默认不返回 JSON**（必须显式 `fmt=json`）。

### 5. 口令哈希：Argon2id 优先，标准库 scrypt 兜底

不硬依赖 `argon2-cffi`：本仓有 PyInstaller 桌面分发形态，多一个 C 扩展就多
一份打包风险。`hashlib.scrypt` 是 CPython 自带、RFC 7914、内存硬，参数
`n=2^15, r=8, p=1`（约 32 MiB / 60–120 ms）落在 OWASP 建议区间内。
产出是 PHC 风格自描述串，装了 argon2 就自动升档，登录时 `needs_rehash` 在线迁移。

`passlib` 明确不用：最后一版 1.7.4 发布于 2020-10，官方 issue「Maintenance
status?」至今无人回应，且 Python 3.13 起不可用。

### 6. 实时大屏走 SSE，且必须「单采集器 + N 订阅者」

选 SSE 不选 WebSocket 的三条硬理由：语义就是单向广播；本仓唯一被实测验证过
的流式范式就是 SSE（`src/ai/api/assistant_stream.py`，连踩坑记录都在注释里）；
鉴权与断线重连零改造。

**比传输选型更要紧的是采集架构**：`(spot_batch, sina/tencent)` 的在途名额
默认只有 **1**（`router_live.py` 的 `DEFAULT_ADAPTER_CONCURRENCY`）。
今天是「N 个客户端 = N 次上游取数」，只靠 3s/5s TTL 挡。大屏一上来会把这个
门闩打满，触发降级、403 与截断。所以 `src/market/application/live_hub.py`
是一个进程一个采集线程、N 个订阅者共享同一份快照；订阅者归零自动停表。

刷新频率预算（有依据，不是拍脑袋）：指数/自选 ≤400 只 → 3s（`live_tape`
的 TTL 就是 3s，更快只会拿到同一份 payload）；全市场东财整表 → 6s
（`_SPOT_RAW_TTL_SEC = 4.0`）；非交易时段 → 60s。

盘中信号一律带 `provisional: true`：盘中 `close` 会变，`CROSS` 类信号会反复
真假切换；而且引擎声明的 `entry_timing` 是**日线口径**，盘中命中不等于可成交。

### 7. 排行榜按「样本外折扣后的夏普」排，不按裸收益率

`score = sharpe_1y × min(1, live_days / 365)`（抄 QuantConnect）。

对标了 18 个平台后的结论：**排行榜是国内外差距最大的一格**。国内基本是裸
收益率排序，而裸收益率榜的三种必然结局是过拟合刷榜、单押高波动、多开小号。
QuantConnect 用样本外折扣、Collective2 把订阅费与佣金算进净收益、Numerai 按
质押加权——三家都在给「可信度」而不是「收益率」定价。

配套的两条：**上架即冻结**（`published_versions` 挂 BEFORE UPDATE/DELETE
触发器，改内容只能发新版，抄果仁网）；**上架检查清单** 7 条机器可校验门槛
（成交笔数 ≥30、回测区间 ≥1 年、佣金/印花/滑点不得为 0、必须声明
`entry_timing`……，抄 TradingView 与 QuantConnect 的发布规范）。

### 8. 跟单只推信号，不自动下单

国内九家平台的「跟单」列全是 ❌/⚠️，不是技术原因，是牌照原因——A 股自动跟单
等于代客理财。果仁网的做法最直白：订阅者拿到调仓指令，**拿不到策略定义**，
执行靠自己。我们照此办理：`subscriptions.mode` 只有 `signal_only`，
DDL CHECK + API schema + domain docstring 三处兜死。

## 后果

**好的：**

- 存量单机用户零感知升级；桌面模式仍然不需要登录（非 production 自动以主租户
  管理员身份运行）。
- LLM 密钥、AI 对话、纸面舱天然每人一份，不需要给任何一张表加列。
- 行情只存一份，多租户不放大磁盘与带宽。
- 新增登录方式 = 写一个类 + 改一个环境变量。
- 定时任务已按租户分流：系统级（行情同步 / 热库 / 体检 / 留存）只跑一份，
  用户级（选股 / 盯盘 / 提醒 / 情报）各跑各的，带并发与租户数双上限。

**代价与风险：**

- 每个租户一套 SQLite 意味着**连接数与文件句柄随用户数线性增长**。当前形态
  （单容器、预期几十个用户）没问题；上到几百人要么加连接复用，要么换 PG。
- 调度器把 N 个租户的任务装进**同一个进程内 APScheduler**。
  `LOCI_TENANT_JOB_CONCURRENCY`（默认 2）与 `LOCI_MAX_SCHEDULED_TENANTS`
  （默认 50）是两道闸；超过 50 个活跃租户会被截断并告警，而不是静默漏跑。
- **最危险的一类缺陷是「库路径在 import 期就定下来」**——它不报错，只是让所有
  用户共用一个文件。本轮修掉 6 处（`store_helpers.DEFAULT_DB`、
  `AssistantManager` 构造期字段、`api_deps.DEFAULT_PALACE_DB`、
  `jobs/context.DEFAULT_PALACE_DB`、`converter.DEFAULT_OPS_DB`、
  组合根传给助手 router 的 `PALACE_OPS_DB`）。新代码务必惰性解析。
- `identity.db` 是新的单点：它丢了所有人都登不上。备份优先级与 `palace.db` 同级。
- 分享包脱敏清单（`share_pack_sanitize.PERSONAL_TABLES`）此前漏掉全部 8 张
  AI 助手表，会把对话原文外发。这是 v1 就存在的缺口，本轮一并补上。

## 遗留项（明确不在本轮）

1. **陌生人 Python 策略的沙箱**：`screen_python_load.py` 用
   `importlib.exec_module` 在 API 进程内直接执行，无 restricted builtins、
   无 rlimit、无网络隔离。**在开放「克隆并运行别人的 Python 战法」之前，
   这一层必须先换掉**——目前克隆只返回 bundle、不代跑，就是在等这件事。
2. **`prune` 任务的租户分段**：它同时删全局的盘中留存带目录与**租户私有**的
 `job_runs` / `leader_roles`。当前整体归为系统级（只在主租户跑），取的是
   「不重复删全局目录」这一头，代价是**子租户的 `job_runs` 没人清**。
   每租户任务量小、`keep_per_job` 默认 200，量级可控；等子租户任务多起来，
   正确做法是拆成 system 段与 tenant 段，而不是简单挪出 `SYSTEM_JOB_KINDS`。
3. **系统级任务的通知只到主租户**。要让子租户也收到应在 notify 层扇出，
 **不要给每个子租户各建一个 sync 任务**（会把上游打成 403）。
4. **`dispatch_subscription_signal` 还没有生产调用方**：函数与测试都在，
   但接进 community 的发布流程需要组合根注入（community 不得 import ops）。
5. **每日重跑全部已上架战法**（QuantConnect 式样本外积累）还没接进调度。
6. **边际贡献分**（Numerai MMC 的零成本退化版：新战法对现有战法池的增量 IR）。
7. **付费订阅与创作者分成**：涉及支付通道、发票、资质、退款纠纷。
8. **Level-2 逐笔与盘口五档**：sina/tencent 的报文里其实有五档，是 parser
   主动丢弃的；要做改两个 `_parse_*` 即可，但那是另一个话题。

## 参考

- 平台对标：`docs/research/2026-08-quant-platform-product-benchmark.md`
- 身份与 OAuth 调研：`docs/research/2026-08-oauth-identity-research.md`
- 模块文档：`src/identity/README.md`、`src/community/README.md`、`src/market/README.md`
