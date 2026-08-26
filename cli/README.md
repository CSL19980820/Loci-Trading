# CLI

## 职责
薄命令行入口，转发到各限界上下文。

## 边界
无业务逻辑。**禁止** `from src.<context>.infrastructure.*` 深掏；只经 `src.<context>` 包根公开 API（`DEFAULT_DB`、`save_provider`、`format_tray_title` 等）。

import-linter 合约 `cli-no-infra-deep` 覆盖 `cli/` 包。桌面入口 `loci.py` 不在该 root package 内，同样遵守包根导入，**勿扩大**深掏。

### 勿扩大（已知例外 / 边界）

| 路径 | 说明 |
|---|---|
| `loci.py` | 非 `cli` 包，不进 import-linter；仅允许 `from src.<context> import …` / `src.shared` / `src.app` |
| 历史深掏 | 已清零；新代码禁止再引入 `*.infrastructure` |

## 关键入口
`python -m cli.ledger|market|ops|review|serve`；桌面：`python loci.py`

子命令范围（实盘账本下线后）：

- `cli.ledger`：`init` / `stock` / `candidate` / `plan` / `review` / `timeline`。**已删** `buy`/`sell`/`cashflow`/`snapshot`/`dashboard`/`scorecard`/`import-skill-memory`——持仓、成交、现金、账户快照与潜龙起始快照导入随 `src/ledger` 一起下线。
- `cli.review`：`candidates` / `plans`。**已删** `equity`/`trips`/`positions`——资金曲线与持仓归因依赖真实成交，现已无数据源。

## 如何扩展
新命令：加 `cli/<name>.py`，内部调 `src.<context>` 公开符号。缺导出时先补包根 `__init__.py`，再改 CLI。

## 给 Agent 的用法
- 运维：`from src.ops import OpsStore, discover_skills, DEFAULT_SKILL_ROOT, …`
- 行情：`from src.market import MarketStore, format_tray_title, …`
- 禁止：`from src.*.infrastructure…`

## README 维护
公开入口、import-linter 覆盖范围或例外清单变更时必须更新本文。

## 相关测试
手工 / 对应上下文单测；`lint-imports`（含 `cli-no-infra-deep`）
