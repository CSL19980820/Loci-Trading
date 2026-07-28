# Loci（stock-analyzer）

单机 A 股工作台：**账本 + 行情仓 + 策略/复盘/运维/AI**。数字由量化引擎产出；AI 只解释、提问、结构化录入。

> 免责声明：仅供信息整理与方法论辅助，不构成投资建议。

## 架构（DDD 模块化单体）

每个限界上下文独立目录，内部统一四层：`domain` / `application` / `infrastructure` / `api`。

| 包 | 职责 | 库 |
|---|---|---|
| `src/ledger` | 成交/候选/预案/复盘记录 | `palace.db` |
| `src/market` | 行情同步、标的池、适配器 | `market.db` |
| `src/review` | 资金曲线、归因、候选验证 | 读 ledger+market |
| `src/strategy` | 战法协议与选股 | — |
| `src/backtest` | 信号回测 | — |
| `src/ops` | 任务、技能、通知 | `ops.db` |
| `src/ai` | LLM 客户端与 Agent | — |
| `src/intel` | MCP 情报 | `mcp.json` |
| `src/formula` | 通达信公式 / 潜龙指标 | — |
| `src/shared` | 路径等横切 | — |
| `src/app` | FastAPI 组合根 | — |

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
.\.venv\Scripts\python.exe -m cli.ledger dashboard
.\.venv\Scripts\python.exe -m cli.market coverage
.\.venv\Scripts\python.exe -m cli.ops jobs
.\.venv\Scripts\python.exe -m cli.review equity
```

## 测试

```powershell
.\.venv\Scripts\python.exe -m pytest tests/ -q
```

## 新增限界上下文

1. 建 `src/<name>/{domain,application,infrastructure,api}/` + `README.md`
2. 在 `src/app/main.py` 挂载路由（或写入现有聚合 router）
3. 测试放 `tests/<name>/`
4. 更新本文档与 `docs/architecture/bounded-contexts.md`
