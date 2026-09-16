# AGENTS.md · Loci / stock-analyzer

> 给 AI Coding Agent 的项目导览（[agents.md](https://agents.md/)）。人类入门见 [`README.md`](README.md)。
>
> **这份文件是导览，不是法规。** 它交代项目形态、命令、环境归属和几个当初踩过坑才定下来的
> 约定。怎么做按当轮任务判断；**用户的当轮指令优先于本文件**。
>
> 代码规范正文在分册：后端 [`src/AGENTS.md`](src/AGENTS.md)（DDD），
> 前端 [`frontend/AGENTS.md`](frontend/AGENTS.md)（Vue 3 + shadcn-vue）。

## 1. 项目形态

**v2「群龙」**：多租户量化平台 = 私人工作台（账本 / 行情 / 策略 / 复盘 / 运维 / AI）
+ 公共策略广场 + 实时大屏。v1 的单机单人形态仍然完整保留（桌面端零登录）。

- DDD 模块化单体，按限界上下文分包
- **数字由量化引擎产出，AI 不发明数字**
- 旧报告链（analyze / fetcher / reporter）已删除，不再恢复

### 多租户的一句话模型（改任何存储前值得先读）

**多租户 = 换 data 根，不是给每张表加 `user_id`。** 见
[`src/shared/tenancy.py`](src/shared/tenancy.py) 与
[ADR-015](docs/adr/ADR-015-v2-multi-tenant-identity-and-community.md)。

| 数据 | 归属 | 说明 |
|---|---|---|
| `palace.db` / `ops.db` / `skills/` / `research_runs/` | **每租户** | 路径由 `src/shared/paths.py` 按 ContextVar 里的当前租户解析 |
| `market.db` / `market_hot.db` | 全局共享 | 行情是公共事实 |
| `identity.db` / `community.db` | 全局共享 | 身份与社区本来就跨用户 |

主租户 `__primary__` **就是老的 `data/` 目录本身**，所以存量单机用户升级后零迁移。

写新代码时：`OpsStore(None)` / `PalaceStore(palace_db())` 这类惰性解析会自动落到当前租户。
**在 import 时或进程启动时把库路径固化下来的写法，会让所有用户共用一个库**——这是这一块
最容易出的事故。

## 2. 命令

```powershell
.\setup.ps1
.\.venv\Scripts\python.exe -m pytest tests/ -q --tb=line
.\.venv\Scripts\lint-imports.exe
# 导入冒烟：逐个 import src/** 与 cli/**。比 compileall 严格，能抓出「语法对但缩进错位」的代码
.\.venv\Scripts\python.exe tools\import_smoke.py
# ruff F 类门禁：不用真 import 就能全仓扫一遍，抓 SyntaxError 与未定义名字
.\.venv\Scripts\python.exe -m ruff check --select F src cli tests

cd frontend; bun install; bun run typecheck; bun run test; bun run build
# 可选：bun run test:e2e（需 bunx playwright install chromium）；bun run build:rolldown

.\.venv\Scripts\python.exe loci.py
.\.venv\Scripts\python.exe -m cli.serve

# 缩进被写歪时的急救（只改前导空白，改完必须再跑 import_smoke.py 复核语义）
python tools\reindent.py <file> [<file> ...]
```

前端用 **bun**，后端用仓库内 `.venv`。

### CI（`.github/workflows/ci.yml`）

7 个 job：`python`（pytest + lint-imports）、`frontend`（install + typecheck + test + build）、
`e2e`（ubuntu + Chromium 真跑）、`performance-baseline`、`uv-validation`、`python-quality`
（ruff F 类门禁）、`security-reports`（gitleaks 密钥扫描门禁）。
其中 secret scan 的假阳性登记在根目录 `.gitleaks.toml`，按假凭据字面量放行而不是按路径豁免。

F 类是「真错」——未使用 / 重复导入、未定义名、被遮蔽的导入、写了没用的局部变量。
全量风格检查（E501/E402 等）目前 report-only，不阻断。

可选加速：`$env:LOCI_MARKET_DUCKDB='1'`（[ADR-002](docs/adr/ADR-002-duckdb-readonly-panel.md)）。
行情详情是 ECharts 通达信式三窗（K / 量 / 副图常驻）；日 K 约拉 320 根供 MA250，默认可视最近 60 根。

## 3. 运行环境（这条是操作约定，值得先确认）

| 环境 | 地位 | 怎么用 |
|---|---|---|
| **线上** `ssh my-debian` → `/srv/qianlong-loci` → <http://qianlong.chenkit.cloud/> | 权威运行环境 | 排查、取证、验证、部署以它为准 |
| 开发机桌面便携版 `E:\entertainment_software\Loci` | 已搁置 | 用户已明确不再维护，不部署 / 不重建 / 不读它的库 / 不拿它下结论 |

需要一个能登录的界面来验收时，用**刚部署的那个镜像**在服务器起一次性容器
（步骤写在 `frontend/e2e/verify-live-ui.mjs` 文件头），验完删掉——验的是同一份产物，
且不碰生产数据。

> 背景：便携版是 WebView2 + PyInstaller，线上是 Docker + nginx，**两者表现不可互相推断**。
> 拿便携版的现象去改线上代码，等于照着一个不存在的环境排查。

- 部署：`pwsh .\deploy\deploy.ps1`（纯后端改动加 `-SkipFrontendBuild`，详见
  [`deploy/README.md`](deploy/README.md)）。容器 Recreate 就是那次「重启」。
  `scripts\build-loci.ps1` 是给便携版打包用的，现在不用跑。
- 取证：`ssh my-debian` + `docker exec qianlong-loci …`，或
  `sqlite3 -readonly /srv/qianlong-loci/data/{market,ops,palace}.db`（**只读**打开线上库）。
- **部署成功 ≠ 修复生效。** 值得在线上真跑一次相关任务再对比前后事实，例如
  `docker exec qianlong-loci python -m cli.ops job run "行情日终重刷"` 之后确认当日
  `quotes_daily.source` 变化，再跑「行情库体检」。
- **别把开发机的数字写成「生产实测」。** 两台机同一天可以一好一坏：开发机通达信自
  2026-07-28 起被限流，当日 4396/5542 行成交额是 `close × volume` 合成的假值；同日生产
  逐日 99.9%~100% tdx。混淆会让后来人照着一个不存在的故障排查。

## 4. 几个当初踩过坑才定下来的约定

这些不是凭空定的偏好，每条背后都有一次真实的返工：

- **文件名 / 目录**：小写 snake，前端组件 PascalCase。标识符跟周边文件保持一致。
- **注释**：只写非显而易见的「为什么」。复述代码的注释会在下次重构时变成谎言。
- **抽 SFC 样式到单独 CSS 文件**：用 `<style scoped src="./x.css">`，别用 `@import`——
  `@import` 进来的规则拿不到 scope id，选择器会漏到全站。
- **AI 写的 Python 极易写歪前导空格**：关卡是 `python -c "import <module>"`，不是 `compileall`
  ——`tools/reindent.py` 能修出语法正确但语义错位的代码（实测：一整个 `with` 块掉出方法体
  落进类体，compileall 全绿而 import 当场炸）。
- **测试不许出网**：外部 HTTP 要 mock。朴素守卫往往无效（通道按契约吞异常），
  可靠做法见 `src/AGENTS.md` §7。
- **秘密不上库**：`.env`、密钥、真实 `data/*.db`。
- **「当前用户」只有一个入口**：组合根注入的 `auth_dependency` / `request.state.loci_auth`。
  业务里自己开 `identity.db` 查 users 会绕开租户与配额。
- **单文件体量**：经验上 600 行左右就该考虑拆（页面按区块、后端按用例）。
  贴线的大文件只拆不涨。
- **提交**：未经用户要求不要 commit / push。
- **沟通**：对用户说简洁中文；代码标识符保持英文。

## 5. 分册索引

| 领域 | 文件 | 内容 |
|---|---|---|
| 后端规范 | [`src/AGENTS.md`](src/AGENTS.md) | DDD 分层、是否入库、表设计、FastAPI |
| 前端规范 | [`frontend/AGENTS.md`](frontend/AGENTS.md) | Vue 3、shadcn-vue、组件落点、Pinia |
| 前端视觉 | [`frontend/docs/ui-spec.md`](frontend/docs/ui-spec.md) | 令牌、密度、排版、文案 |
| 架构 | [`docs/architecture/`](docs/architecture/) | 上下文地图 |
| 单模块 | `src/<context>/README.md` | 用法、边界、扩展点 |
| v2 形态决策 | [`ADR-015`](docs/adr/ADR-015-v2-multi-tenant-identity-and-community.md) | 多租户 / 身份 / 社区 / 大屏的取舍 |
| 身份与治理 | [`src/identity/README.md`](src/identity/README.md) | 账号、角色、配额、审计 |
| 社区 | [`src/community/README.md`](src/community/README.md) | 策略广场、榜单口径、上架规则 |
| shadcn-vue 细则 | [`.cursor/skills/shadcn-vue/SKILL.md`](.cursor/skills/shadcn-vue/SKILL.md) | 组件落点、令牌桥、迁移对照 |
