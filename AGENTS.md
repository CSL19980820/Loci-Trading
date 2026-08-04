# AGENTS.md · Loci / stock-analyzer 大模型使用手册

> 给 **AI Coding Agent** 的操作手册（[agents.md](https://agents.md/)）。人类入门见 [`README.md`](README.md)。  
> **代码规范正文在分册**：后端 [`src/AGENTS.md`](src/AGENTS.md)（DDD），前端 [`frontend/AGENTS.md`](frontend/AGENTS.md)（Vue3）。  
> 借鉴：`zhanymkanov/fastapi-best-practices`、`miguelgrubin/fastapi-boilerplate`（六边形/DDD）、Vue Composition / Pinia 社区惯例。

## 0. 阅读顺序

1. 本文（全局硬约束 + 命令 + DoD）
2. 分册就近覆盖：`frontend/AGENTS.md` 或 `src/AGENTS.md`
3. 改某上下文前读 `src/<context>/README.md`
4. **用户当轮指令 > 任何 AGENTS.md**

## 1. 项目速览（Agent）

- 单机工作台：账本 / 行情 / 策略 / 复盘 / 运维 / AI
- **DDD 模块化单体**；数字由量化引擎产出，AI 不发明数字
- 旧报告链（analyze/fetcher/reporter）已删除，**禁止恢复**

## 2. 命令

```powershell
.\setup.ps1
.\.venv\Scripts\python.exe -m pytest tests/ -q --tb=line
.\.venv\Scripts\lint-imports.exe
cd frontend; bun install; bun run typecheck; bun run test; bun run build
# 可选：bun run test:e2e（需 bunx playwright install chromium）；bun run build:rolldown
.\.venv\Scripts\python.exe loci.py
.\.venv\Scripts\python.exe -m cli.serve
```

CI（`.github/workflows/ci.yml`）：Python `pytest` + `lint-imports`；前端 `bun install` + `typecheck` + `test`；另跑 Playwright e2e（ubuntu + Chromium）。

可选加速：`$env:LOCI_MARKET_DUCKDB='1'`（[ADR-002](docs/adr/ADR-002-duckdb-readonly-panel.md)）；`$env:LOCI_BACKTEST_FAST='1'`（回测旁路，失败/有细规则止损回退经典引擎）。行情详情为 ECharts 通达信式三窗（K/量/副图常驻）；日 K 约拉 320 根供 MA250，默认可视最近 60 根。

前端 **bun**；后端仓库 `.venv`。不要编造另一套工具链。

## 3. 全仓硬规则（语言无关）

### 3.1 体量

- **单文件 ≤ 600 行**（含 Vue SFC / Python 模块）。逼近即拆：页面按区块、后端按用例。
- 禁止在已超限的存量巨石上「再加一点」。

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
| 测试隔离+清理 | 见 `tests/conftest.py`；跑完不留垃圾 |
| README 同步 | 改模块公开行为 → **同批**更新该模块 README |
| 中文沟通 | 对用户简洁中文；代码标识符保持英文 |

### 3.5 Definition of Done

- [ ] 相关测试绿；无真实 `data/` 污染
- [ ] 前端改动：`bun run typecheck`（及触及逻辑时 `bun run test`）通过
- [ ] 触及跨上下文导入时：`lint-imports` 通过
- [ ] 无新超 600 行文件（或已拆分）
- [ ] 触及的模块 `README.md` / `api/README.md` 已更新
- [ ] 无跨上下文违规依赖；未改用户未要求范围

## 4. 分册索引

| 领域 | 文件 | 内容重点 |
|---|---|---|
| 后端代码规范 | [`src/AGENTS.md`](src/AGENTS.md) | DDD、**是否入库**、**表设计**、FastAPI Do&Don't |
| 前端代码规范 | [`frontend/AGENTS.md`](frontend/AGENTS.md) | Vue3、**组件封装落点/契约**、Pinia、features |
| 架构 | [`docs/architecture/`](docs/architecture/) | 上下文地图 |
| 单模块 | `src/<context>/README.md` | Agent 用法 + 维护义务 |

根文件保持短；**细则以下方分册为准**。
