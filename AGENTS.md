# AGENTS.md · Loci / stock-analyzer 大模型使用手册

> 给 **AI Coding Agent** 的操作手册（[agents.md](https://agents.md/)）。人类入门见 [`README.md`](README.md)。  
> **代码规范正文在分册**：后端 [`src/AGENTS.md`](src/AGENTS.md)（DDD），前端 [`frontend/AGENTS.md`](frontend/AGENTS.md)（Vue3）。  
> 借鉴：`zhanymkanov/fastapi-best-practices`、`miguelgrubin/fastapi-boilerplate`（六边形/DDD）、Vue Composition / Pinia 社区惯例。

> ## ⛔ 动手前先认环境（最常被违反的一条）
>
> **只管线上。`E:\entertainment_software\Loci`（开发机桌面便携版）已搁置——不要碰。**
>
> | | 地址 | 怎么办 |
> |---|---|---|
> | ✅ 线上 | `ssh my-debian` → `/srv/qianlong-loci` → <http://qianlong.chenkit.cloud/> | 改这里、部署这里、验证这里 |
> | ⛔ E 盘便携版 | `E:\entertainment_software\Loci` | **搁置**。不部署、不重建、不重启、不读它的库、不拿它下结论 |
>
> 部署只有一条命令：`pwsh .\deploy\deploy.ps1`（纯后端改动加 `-SkipFrontendBuild`）。
> **`scripts\build-loci.ps1` 是给便携版打包用的，现在不要跑。**
>
> 细则与取证姿势见 [§3.5](#35-运行环境线上为准)。

## 0. 阅读顺序

1. 本文（全局硬约束 + 命令 + DoD）
2. 分册就近覆盖：`frontend/AGENTS.md` 或 `src/AGENTS.md`
3. 改某上下文前读 `src/<context>/README.md`
4. **用户当轮指令 > 任何 AGENTS.md**

## 1. 项目速览（Agent）

- **v2「群龙」形态**：多租户量化平台 = 私人工作台（账本 / 行情 / 策略 / 复盘 / 运维 / AI）
  + 公共策略广场 + 实时大屏。v1 的单机单人形态仍然完整保留（桌面端零登录）。
- **DDD 模块化单体**；数字由量化引擎产出，AI 不发明数字
- 旧报告链（analyze/fetcher/reporter）已删除，**禁止恢复**

### 多租户的一句话模型（改任何存储前先读）

**多租户 = 换 data 根，不是给每张表加 `user_id`。** 见
[`src/shared/tenancy.py`](src/shared/tenancy.py) 与
[ADR-015](docs/adr/ADR-015-v2-multi-tenant-identity-and-community.md)。

| 数据 | 归属 | 说明 |
|---|---|---|
| `palace.db` / `ops.db` / `skills/` / `research_runs/` | **每租户** | 路径由 `src/shared/paths.py` 按 ContextVar 里的当前租户解析 |
| `market.db` / `market_hot.db` | **全局共享** | 行情是公共事实 |
| `identity.db` / `community.db` | **全局共享** | 身份与社区本来就跨用户 |

主租户 `__primary__` **就是老的 `data/` 目录本身**——存量单机用户升级后零迁移。

**写新代码时**：`OpsStore(None)` / `PalaceStore(palace_db())` 这类惰性解析会自动
落到当前租户；**任何把库路径在 import 时或进程启动时固化下来的写法都会让所有
用户共用一个库**，是本轮最需要警惕的反模式。

## 2. 命令

```powershell
.\setup.ps1
.\.venv\Scripts\python.exe -m pytest tests/ -q --tb=line
.\.venv\Scripts\lint-imports.exe
# 导入冒烟：逐个 import src/** 与 cli/**。比 compileall 严格，能抓出「语法对但
# 缩进错位」的代码（AI 批量生成的真实失败模式）。
.\.venv\Scripts\python.exe tools\import_smoke.py
cd frontend; bun install; bun run typecheck; bun run test; bun run build
# 可选：bun run test:e2e（需 bunx playwright install chromium）；bun run build:rolldown
.\.venv\Scripts\python.exe loci.py
.\.venv\Scripts\python.exe -m cli.serve
# 缩进被写歪时的急救（只改前导空白，改完必须再跑 import_smoke.py 复核语义）
python tools\reindent.py <file> [<file> ...]
# 写大段 Python 时的防走样写法见 tools\README.md（缩进编码 + enc2py.py）
```

CI（`.github/workflows/ci.yml`）共 7 个 job：`python`（`pytest` + `lint-imports`）、`frontend`（`bun install` + `typecheck` + `test` + `build`）、`e2e`（ubuntu + Chromium 真跑）、`performance-baseline`（**硬门禁**，`tests/benchmarks/baseline_benchmark.py` 失败即红）、`uv-validation`（**硬门禁**，无 `continue-on-error` 且脚本 `set -euo pipefail`）、`python-quality`（ruff，`continue-on-error`，不阻断）、`security-reports`（pip-audit + gitleaks + zizmor，三步全 `continue-on-error` 且只上传 artifact，无人读取）。

即：**5 个硬门禁**（python / frontend / e2e / performance-baseline / uv-validation）+ 2 个 report-only。

可选加速：`$env:LOCI_MARKET_DUCKDB='1'`（[ADR-002](docs/adr/ADR-002-duckdb-readonly-panel.md)）；`$env:LOCI_BACKTEST_FAST='1'`（回测旁路，失败/有细规则止损回退经典引擎）。行情详情为 ECharts 通达信式三窗（K/量/副图常驻）；日 K 约拉 320 根供 MA250，默认可视最近 60 根。

前端 **bun**；后端仓库 `.venv`。不要编造另一套工具链。

## 3. 全仓硬规则（语言无关）

### 3.1 体量

- **单文件 ≤ 600 行**（含 Vue SFC / Python 模块）。逼近即拆：页面按区块、后端按用例。
- 禁止在已超限的存量巨石上「再加一点」；贴线簇（≥580 行）仅允许拆出，禁止继续堆功能。

### 3.2 耦合与分支

- 跨限界上下文：**禁止**深路径掏对方 `infrastructure`；只经包公开 API。
- 同一决策点 **≥3 种可变策略** → 注册表 / Strategy / Protocol / 表驱动，禁止 if 丛林。
- 后端依赖：`api → application → domain`；`market` 不写 `palace.db`。

### 3.3 命名与注释（通用）

| 类别 | 约定 |
|---|---|
| 文件/目录 | 小写 snake 或已有项目风格（前端组件 PascalCase） |
| 标识符 | 与周边文件一致；不要混用无意义缩写 |
| 注释 | 只写非显而易见的「为什么」；禁止大段复述代码 |
| 提交 | 未经用户要求不 commit / push |

### 3.4 工程卫生

| 规则 | 说明 |
|---|---|
| 最小改动 | 不做范围外重构 |
| 不编造 API | URL/字段以代码与 `types` 为准 |
| 秘密不上库 | `.env`、密钥、真实 `data/*.db` |
| Agent Bearer | `PALACE_WRITE_TOKEN` 长期静态；生产若配置须 ≥32 字符；优先会话；`PALACE_WRITE_TOKEN_ISSUED_AT` 触发轮换告警 |
| 测试隔离+清理 | 见 `tests/conftest.py`；跑完不留垃圾 |
| README 同步 | 改模块公开行为 → **同批**更新该模块 README |
| 中文沟通 | 对用户简洁中文；代码标识符保持英文 |
| 租户安全 | 新表/新缓存/新全局字典：先问「两个用户会不会串味」。库路径一律惰性解析，进程级缓存 key 必须含 `current_tenant()` |
| 身份唯一入口 | 「当前用户」只从组合根注入的 `auth_dependency` / `request.state.loci_auth` 取；禁止在业务里自己开 `identity.db` 查 users |
| Python 缩进 | AI 生成的 `.py` 极易写歪前导空格。**关卡是 `python -c "import <module>"`，不是 `compileall`**——`tools/reindent.py` 能修出语法正确但语义错位的代码（实测：一整个 `with` 块掉出方法体落进类体，compileall 全绿而 import 当场炸）。批量修完必须逐文件 import 一遍 |
| 测试不许出网 | 外部 HTTP 必须 mock。**朴素守卫无效**：很多通道/适配器按契约吞异常，守卫在 `urlopen` 里抛错会被它自己接住，用例照样绿。要用「记账 + teardown 断言」，并注入一次真泄漏验证守卫确实会红（实测抓到过一个真打 `open.feishu.cn` 的用例） |

### 3.5 运行环境：**线上为准**

| 环境 | 地位 | 怎么用 |
|---|---|---|
| **线上** `ssh my-debian` → `/srv/qianlong-loci`，<http://qianlong.chenkit.cloud/> | **唯一权威运行环境** | 排查、取证、验证、修复、部署**一律以它为准** |
| 开发机桌面便携版 `E:\entertainment_software\Loci` | **已搁置** | **不要碰。** 不部署、不重建、不重启、不恢复、不读它的库、不拿它下结论 |

**「搁置」是字面意思**：不是「优先级低」，也不是「用户没说就别动」，是**这一整个目录不在工作范围内**。
需要一个能登录的界面来验收时，用**刚部署的那个镜像**在服务器起一次性容器
（见 `frontend/e2e/verify-live-ui.mjs` 文件头的完整步骤），验完删掉——
那验的是同一份产物，且不碰生产数据，比拿便携版试跑靠谱得多。

> **真实事故（2026-08-29）**：用户说了「只管线上」，agent 仍然跑
> `scripts\build-loci.ps1 -DeployDir "E:\entertainment_software\Loci"` 部署了两次、
> 起停便携版 exe、还照着它的 CSP 表现改了后端。用户原话：「怎么还是老是在操作E盘的」。
> 当时 §3.5 已经写着这条规则——**它被违反不是因为没写，是因为写得太软**（「用户当轮
> 明确要求才动」被读成了「验证一下不算动」）。所以现在的措辞是：**不要碰**。
>
> 同一轮还有个副作用值得记住：便携版是 WebView2 + PyInstaller，线上是 Docker + nginx，
> **两者的表现不可互相推断**。拿便携版观察到的现象去改线上代码，等于照着一个不存在的
> 环境排查。

- **取证姿势**：`ssh my-debian` + `docker exec qianlong-loci …` /
  `sqlite3 -readonly /srv/qianlong-loci/data/{market,ops,palace}.db`。**只读**打开线上库。
- **部署即重启**：后端改动 `pwsh .\deploy\deploy.ps1 -SkipFrontendBuild`（详见
  [`deploy/README.md`](deploy/README.md)）。容器 Recreate 就是那次「重启」。
- **部署成功 ≠ 修复生效**。必须在线上真跑一次相关任务并对比前后事实，例如
  `docker exec qianlong-loci python -m cli.ops job run "行情日终重刷"` 之后确认当日
  `quotes_daily.source` 从 `tdx_spot` 翻成 `tdx`，再跑「行情库体检」确认判据转绿。
- **别把开发机的数字写成「生产实测」**。两台机同一天可以一好一坏：开发机通达信自
  2026-07-28 起被限流，当日 4396/5542 行成交额是 `close×volume` 合成的假值；同日生产
  逐日 99.9%~100% tdx。混淆会让后来人照着一个不存在的故障排查（`market/application/
  data_quality.py` 里为此专门留了取证归属的注释）。

### 3.6 Definition of Done

- [ ] 相关测试绿；无真实 `data/` 污染
- [ ] 前端改动：`bun run typecheck`（及触及逻辑时 `bun run test`）通过
- [ ] 触及跨上下文导入时：`lint-imports` 通过
- [ ] 无新超 600 行文件（或已拆分）
- [ ] 触及的模块 `README.md` / `api/README.md` 已更新
- [ ] 涉及运行时行为：**已在线上真跑验证**（见 §3.5），不以「部署成功」代替「修复生效」
- [ ] 无跨上下文违规依赖；未改用户未要求范围
- [ ] 涉及存储/缓存：**两个租户互不可见**（有测试，参考 `tests/identity/test_identity.py`）
- [ ] 新增 Python 文件：`python -m compileall -q` 通过

## 4. 分册索引

| 领域 | 文件 | 内容重点 |
|---|---|---|
| 后端代码规范 | [`src/AGENTS.md`](src/AGENTS.md) | DDD、**是否入库**、**表设计**、FastAPI Do&Don't |
| 前端代码规范 | [`frontend/AGENTS.md`](frontend/AGENTS.md) | Vue3、**组件封装落点/契约**、Pinia、features |
| 架构 | [`docs/architecture/`](docs/architecture/) | 上下文地图 |
| 单模块 | `src/<context>/README.md` | Agent 用法 + 维护义务 |
| **v2 形态决策** | [`docs/adr/ADR-015-...md`](docs/adr/ADR-015-v2-multi-tenant-identity-and-community.md) | 多租户 / 身份 / 社区 / 实时大屏的取舍与遗留项 |
| 身份与治理 | [`src/identity/README.md`](src/identity/README.md) | 账号、角色、配额、审计、第三方登录如何扩展 |
| 社区 | [`src/community/README.md`](src/community/README.md) | 策略广场、榜单口径、上架规则、跟单红线 |

根文件保持短；**细则以下方分册为准**。
