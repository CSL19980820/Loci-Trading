# Loci（stock-analyzer）

A 股量化工作台：**账本 + 行情仓 + 策略/复盘/运维/AI**，v2 起支持**多用户、
策略广场与实时大屏**。数字由量化引擎产出；AI 只解释、提问、结构化录入。

> 免责声明：仅供信息整理与方法论辅助，不构成投资建议。

## 两种形态，一套代码

| 形态 | 怎么跑 | 登录 | 数据 |
|---|---|---|---|
| **桌面单机** | `python loci.py` | 不需要（自动以主租户管理员身份运行） | `data/` 就是你的 |
| **多用户服务端** | `PALACE_ENV=production` + `deploy/deploy.ps1` | 邮箱注册 / 微信 / QQ 扫码 | 每人一套私有库，行情共享一份 |

**升级零迁移**：v1 的存量 `data/` 目录就是 v2 的「主租户」。首启会创建管理员
账号（默认 `lociAdmin` / `Asdf!234`，带强制改密提示），登录后看到的还是原来
那套账本。

## 架构（DDD 模块化单体）

每个限界上下文独立目录，内部统一四层：`domain` / `application` / `infrastructure` / `api`。

| 包 | 职责 | 库 | 租户 |
|---|---|---|---|
| `src/identity` | 账号、角色、会话、配额、审计、通知 | `identity.db` | 全局 |
| `src/community` | 策略广场、排行榜、跟单订阅、评论动态 | `community.db` | 全局 |
| `src/ledger` | 成交/候选/预案/复盘记录 | `palace.db` | **每租户** |
| `src/market` | 行情同步、标的池、适配器、实时推流 | `market.db` | 全局共享 |
| `src/review` | 资金曲线、归因、候选验证 | 读 ledger+market | — |
| `src/strategy` | 战法协议与选股 | — | — |
| `src/backtest` | 信号回测 | — | — |
| `src/ops` | 任务、技能、通知、LLM 供应商 | `ops.db` | **每租户** |
| `src/ai` | LLM 客户端与 Agent | — | — |
| `src/intel` | MCP 情报 | `mcp.json` | **每租户** |
| `src/formula` | 通达信公式 / 潜龙指标 | — | — |
| `src/shared` | 路径、租户上下文等横切 | — | — |
| `src/app` | FastAPI 组合根 | — | — |

多租户模型见 [`src/shared/tenancy.py`](src/shared/tenancy.py) 与
[ADR-015](docs/adr/ADR-015-v2-multi-tenant-identity-and-community.md)：
**换 data 根，不给每张表加 `user_id`**。

约定详见 [docs/architecture/project-structure.md](docs/architecture/project-structure.md)。

**给 AI Agent：** 先读根目录 [`AGENTS.md`](AGENTS.md)（前端 [`frontend/AGENTS.md`](frontend/AGENTS.md)，后端 [`src/AGENTS.md`](src/AGENTS.md)）。

## 快速开始

```powershell
.\setup.ps1
.\.venv\Scripts\python.exe loci.py
```

仅 API（无桌面窗）：

```powershell
.\.venv\Scripts\python.exe -m cli.serve
```

前端开发：

```powershell
cd frontend
bun install
bun run dev
```

CLI 示例：

```powershell
.\.venv\Scripts\python.exe -m cli.ledger timeline 300358
.\.venv\Scripts\python.exe -m cli.market coverage
.\.venv\Scripts\python.exe -m cli.ops jobs
.\.venv\Scripts\python.exe -m cli.review candidates
```

## 版本与分享包

- 产品版本：`src/shared/version.py` 与 `frontend/src/shared/lib/release.ts`（当前 `1.0.0`）。
- 运维「设置 → 一键打包」：基于已编译的 `Loci.exe`+`_internal` 打加密 zip（可选附带账本/行情等）；详见 [docs/portable-desktop.md](docs/portable-desktop.md)。

## 测试

```powershell
.\.venv\Scripts\python.exe -m pytest tests/ -q
```

## 新增限界上下文

1. 建 `src/<name>/{domain,application,infrastructure,api}/` + `README.md`
2. 在 `src/app/main.py` 挂载路由（或写入现有聚合 router）
3. 测试放 `tests/<name>/`
4. 更新本文档与 `docs/architecture/bounded-contexts.md`
