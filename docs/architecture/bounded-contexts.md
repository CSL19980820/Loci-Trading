# 限界上下文地图

```
app (组合根)
 ├── ledger ──► shared
 ├── market ──► shared
 ├── review ──► ledger, market（包根公开 API）
 ├── strategy ──► market, formula
 ├── backtest ──► strategy, market
 ├── ops ──► market, ai, intel, strategy, review（编排）, shared
 ├── ai ──► ledger, market, ops, intel, strategy, research（工具只读）, shared
 ├── intel ──► market（缓存表经 MarketStore）, ops（配额经 OpsStore）
 ├── research ──► market, strategy（验证时）, intel（可选来源）
 └── formula (纯计算)
```

产品名仍为 Loci / 潜龙记忆宫殿；代码包名 ledger 表示账本限界上下文。

## 允许的跨 BC 编排（经包根 `src.<context>`）

组合根、`application/` 用例层、Job 执行器、AI toolbus **可以**调用兄弟上下文的**公开 API**（`from src.ledger import PalaceStore` 等）。下列为当前真实编排边，**不是**越界：

| 调用方 | 被调方 | 典型用途 |
|---|---|---|
| **ai** | **ledger** | 助手/Agent 写成交、候选、预案、持仓（**产品全权**：ExecutionGrant + 写工具，by design） |
| **ai** | **market** | 行情只读、K 线、健康门禁 |
| **ai** | **ops** | LLM 供应商、技能包、Job 触发、OpsStore |
| **ai** | **intel** | MCP 工具、悟道配额、arg_clamp |
| **ai** | **strategy** | 战法目录、选股 `screen` |
| **ai** | **research** | 研究目录/剖面只读工具 |
| **ops** | **market** | 同步 Job、spot、热库镜像、纸面盯市快照 |
| **ops** | **strategy** | 定时选股、回测对比、纸面预案取战法 |
| **ops** | **intel** | `intel_fetch` 结构化采集、skill_watch 龙头/K 线 |
| **ops** | **ai** | Skill Job 跑 Agent、纸面/style memory LLM |
| **ops** | **ledger** | outcome/notify/skill 读账本事实（**不写** palace，纸面舱隔离） |
| **ops** | **review** | notify 读 alerts 常量/状态（`review.application`，待收拢为包根导出） |
| **intel** | **market** | `intel_snapshots` 缓存读写（**须**经 `MarketStore`，DDL 归属 market.db） |
| **intel** | **ops** | `mcp_quota` 计数（**须**经 `OpsStore`，DDL 归属 ops.db） |
| **research** | **market** | 输入快照、profile、回测冻结切片 |
| **research** | **strategy** | 固定因子实验引擎类型、验证时 `get` |
| **review** | **ledger**, **market** | 曲线、T+N、归因（只读） |
| **backtest** | **strategy**, **market** | 回测引擎 |

**AI 写账本**：助手 toolbus（`system_toolbus_ledger` / 潜龙工具）经 `PalaceStore` 写入 `palace.db`，与人工录入同一审计链；**禁止**收紧为只读或 HITL 拦截（产品决策）。

## 禁止深掏 infrastructure

| 规则 | 说明 |
|---|---|
| 跨 BC `*.infrastructure.*` | **禁止**（`lint-imports` 12 条契约守护 `src/` 与 `cli/`） |
| 上下文 → 组合根 `src.app` | **禁止**（契约 `contexts-must-not-import-composition-root`）。请求模型放各自 `api/schemas.py`，依赖打开器放 `src.shared.api_deps`。契约无豁免项 |
| 路由层 `CREATE TABLE` | **禁止**；DDL 只在对应 Store / `store_schema` |
| market 写 palace | **禁止** |
| AI 伪造复盘/行情权威数字 | **禁止**（写工具全权 ≠ 发明数字） |
| 恢复已删 analyze/fetcher/reporter 链 | **禁止** |

## 已知旁路与治理债（勿扩大）

| 项 | 现状 | 方向 |
|---|---|---|
| **cli/** | 已纳入 `import-linter`（`root_packages` 含 `cli`，契约 `cli-no-infra-deep`） | 新命令优先 `from src.market import …`；见 `cli/README.md` |
| **review.application** | 部分 SQL 直用 `palace.conn` / `market.conn` | 逐步收拢 Store 方法；见 `src/review/README.md` |
| **~~app.screen_skills~~** | **已解决**：整块搬入 `strategy`（application 编排 + api 契约），包存储改经 `src.ops` 包根 | Builtin slug 冲突查 `strategy.is_builtin_registered`，勿 import `_REGISTRY` |
| **research** | 2026-08 前未入 import-linter | 已补 `protect-research-infra` 合约 |
| **ops→review.application** | notify 直 import alerts 模块 | 可后续在 `src.review` 包根导出 |

## 可写库

| 上下文 | 可写库 | 禁止 |
|---|---|---|
| ledger | palace.db | 依赖行情写账本 |
| market | market.db（权威写）；market_hot.db（近 700 交易日只读镜像，可重建，见 ADR-007）；含 `intel_snapshots` 可重建缓存 | 写 palace.db |
| review | market 缓存（可选） | 伪造成交 |
| ops | ops.db（含 `mcp_quota` DDL） | 改账本事实 |
| ai / intel | 配置/对话；intel 快照经 market、配额经 ops | 产出权威数字；旁路裸连 DDL |
| research | `data/research_runs/` 中的 run card/冻结输入/阶段产物，以及追加式 PIT 事实和历史股票池 JSON 注册表；固定因子候选只在此域的私有引擎中运行 | 写行情/账本事实；把缺失资料补成完整；覆盖已归档的时点事实；绕过质量门禁；把研究候选注册为活动策略 |

## 数据源路由归属

`market` 负责 adapter 注册、同类 lane 路由与 AkShare 运行时能力目录；`ops` 只提供设置/测速 HTTP 工作台。用户的 lane 偏好写本机配置、由 market 在每次路由时读取，不能把测速结果或临时粘性写成行情/账本事实。AkShare 目录与单项试跑是按需能力检查，只有经 adapter 契约接入的字段才进入同步和 `market.db`。
