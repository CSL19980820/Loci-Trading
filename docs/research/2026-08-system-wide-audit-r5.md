# Loci / stock-analyzer 全系统审计 · 第五轮（R5）+ 常驻审计方案

> **本轮已被后续复核，不代表现状。** 终态见 [R6](./2026-08-system-wide-audit-r6.md)，
> 全系列导航见 [INDEX.md](./INDEX.md)。

> 执行日期：2026-08-07  
> 前提：[R4](./2026-08-system-wide-audit-r4.md) · [R3](./2026-08-system-wide-audit-r3.md) · [R2](./2026-08-system-wide-audit-r2.md) · [R1](./2026-08-system-wide-audit.md)  
> 立场：原为只读台账；**2026-08-07 用户点名后已统一修复**（见 §10）  
> 产品约束：**AI 量化全权**——不收紧 ExecutionGrant / HITL / 限制 AI `add`  
> 方法：三路并行探查 + 多 agent 分批落地 + 本地回归

---

## 0. 一句话结论

R4 主修项 **kept**；`lint-imports` **9/9**。  
原 P1 台账（时钟半回归、超 600、热库镜像、GET 写、BC/intel、交易日闸等）**已 fixed**（§10）。  
**明确未做**：AI HITL / 限制 AI `add`；部分 P2（Pulse 8s 合并、Bearer 轮换等）仍 open。P2-6 rules 退出、P2-8 前视分片已 fixed。

---

## 1. 常驻审计方案（复用 / 本轮执行版）

### 1.1 维度矩阵

| 维度 | 审什么 | 本轮入口 |
|---|---|---|
| 架构 / DDD | 跨 BC、公开 API、组合根、三库 | bounded-contexts · import 边 · CLI |
| 业务逻辑 | 纸面门闩、时钟、层数、竞价、Job、前视 | ops paper_* · nextday_plan · skill_watch |
| 性能 | KeepAlive、轮询、写放大、N+1、SSE | Pulse · Quant · board_router |
| 结构 | 600 行、神类、双真相 | 体量扫 · Store DDL |
| 功能 / UX | page-fill、榜单契约、口径标注 | Dashboard · Pulse 榜 |
| 安全 | 写鉴权、GET 写副作用、路径、Bearer | main · board · ledger API |
| 数据完整性 | 热库镜像、复权、backfill、事件投影 | ADR-007 · candidates_sql |
| 测试 / CI | 假绿、缺测、lint | lint-imports · 关键测抽查 |

### 1.2 每轮检查表

```text
[ ] 读上轮台账 fixed / open / wontfix
[ ] lint-imports（期望全 kept）
[ ] 体量：生产 >600 / 贴线 ≥580
[ ] 纸面：session_clock × scenario_gated × merge_ai_orders 三者对齐
[ ] 日终：planned_layers_max · ref_close 日 K
[ ] KeepAlive：Pulse/Dashboard/工坊 research
[ ] board live：写鉴权 · 热库镜像
[ ] 架构：BC 地图 · intel DDL · CLI 深掏
[ ] 源码核实每条 P0/P1（禁止只信代理摘要）
[ ] 落盘 docs/research/YYYY-MM-system-wide-audit-rN.md
[ ] Batch 建议（点名再改）；AI 全权项标 wontfix
```

### 1.3 严重度

| 级 | 含义 |
|---|---|
| **P0** | 未鉴权写权威库 / 可直接导致错实盘指令且无防护 |
| **P1** | 明确逻辑分裂或结构性越界，会错仓/错口径/假安全感 |
| **P2** | 债项、体验、运维可见性、贴线体量 |

### 1.4 节奏

| 轮次 | 触发 |
|---|---|
| 快速回归 | 纸面/鉴权/KeepAlive PR 合并后 |
| 主题深潜 | 单域大改 |
| 全系统轮 | 里程碑 / 用户点名（本 R5） |

---

## 2. R5 执行元数据

| 项 | 值 |
|---|---|
| lint-imports | **9 kept / 0 broken**（443 files） |
| 生产 >600 | **1**：`src/ops/application/nextday_plan.py` **611** |
| 贴线 ≥580 | `backtest_run` 600、`peek_dock`/`AssistantSenderDock` 598、`research/api/router` 597 … |
| R4 回归烟测 | `test_r3_residuals` + session_clock/scenario 共 **7 passed** |
| 并行探查 | 架构 · 业务 · 性能安全前端 |

---

## 3. R4 回归对照

| ID | R5 | 说明 |
|---|---|---|
| R4-P1-1 planned_layers_max | **kept** | `_planned_layers_from_item` 优先 max |
| R4-P1-2 session_clock 禁 09:25–09:30 | **部分 kept** | clock 字段正确；**AI merge 未吃 allow_open_fill** → R5-P1-1 |
| R4-P1-3 滚动 ref_close 日 K | **kept** | `closes.get(code, item.get(...))` |
| R4-P1-8 Pulse deactivate bump | **kept** | `onDeactivated(bumpDataGeneration)` |
| R4-P1-9 research v-if | **kept** | QuantView |
| R4-P1-4/5 AI 全权 | **wontfix** | 产品决策，本轮不建议改 |
| R4-P1-6/7 地图·intel DDL | **仍 open** | → R5-P1-3/4 |
| R3/R2 主债抽查 | **kept** | 门闩 pending、Job→企微、bypass 生产闸、盯市写回 |

---

## 4. R5 新台账

### 4.1 P0

**无**（默认桌面 loopback）。

**条件性 P0**：对网暴露且未 `PALACE_ENV=production` / `PALACE_REQUIRE_WRITE_AUTH=1`；叠加 GET board live 无写鉴权可写 `market.db`。

### 4.2 P1

| ID | 维度 | 标题 | 证据 | 影响 | 建议 |
|---|---|---|---|---|---|
| **R5-P1-1** | 业务 | AI/手工买入未统一 `allow_open_fill` | → **fixed**（`scenario_gates.merge_ai_orders_with_gates`） |
| **R5-P1-2** | 业务 | 监测时钟无交易日历 | → **fixed**（`resolve_trading_day_gate` + monitor/eod） |
| **R5-P1-3** | 架构 | BC 地图失真 | → **fixed**（`bounded-contexts.md`） |
| **R5-P1-4** | 架构 | intel DDL/配额旁路 | → **fixed**（MarketStore / OpsStore） |
| **R5-P1-5** | 结构 | `nextday_plan.py` 611 行 | → **fixed**（拆 session_clock / plan_build / scenario_gates） |
| **R5-P1-6** | 数据 | board live 写全量不镜像热库 | → **fixed**（`mirror_recent_to_hot`） |
| **R5-P1-7** | 安全 | GET board live 写副作用无 write_guard | → **fixed**（`persist` 默认 false + 写鉴权） |
| **R5-P1-8** | 业务 | enrich 层数键序与 EOD 相反 | → **fixed**（`planned_layers_from_pick`） |
| **R5-P1-9** | 功能 | Pulse「涨幅榜」样本口径 | → **fixed**（文案「库内样本榜」） |

### 4.3 P2

| ID | 标题 | 备注 |
|---|---|---|
| R5-P2-1 | CLI/`loci` 深掏 infra | → **fixed**（见 [R6](./2026-08-system-wide-audit-r6.md)） |
| R5-P2-2 | `screen_skills` + `_REGISTRY` | → **fixed** |
| R5-P2-3 | review `.conn` 直捅 | → **partial**（alerts 已收拢） |
| R5-P2-4 | import-linter 无 research/cli | → **fixed**（11 合约） |
| R5-P2-5 | strategy_monitor 固定 success | → **fixed**（LLM 失败记 failed） |
| R5-P2-6 | rules 几乎无退出 | → **fixed**（`rules_exit_orders` + monitor rules 路径） |
| R5-P2-7 | abandon/downgrade 可配反 | → **fixed**（`normalize_tuning` 序关系） |
| R5-P2-8 | 前视仍抽 40 列 | → **fixed**（`iter_guard_panel_shards` 分片全覆盖） |
| R5-P2-9 | Pulse 8s 三路 HTTP | → **fixed**（错峰 + `persist:false`） |
| R5-P2-10 | skills Tab 仍 v-show | → **fixed**（`v-if`） |
| R5-P2-11 | Dashboard 本月% 盯市分母 | → **fixed** |
| R5-P2-12 | Bearer 长期静态 | → **fixed**（≥32 + 轮换） |
| R5-P2-13 | 潜龙 preview 无 WriteAccess | → **fixed** |
| R5-P2-14 | market_gate 文案 vs fail-closed | → **fixed**（STAGE_META） |
| R5-P2-15 | apply_downgrade 忽略 planned_layers_max | → **fixed**（同 P1-8） |
| R5-P2-16 | 贴线簇 ~10+ 文件 ≥580 | open（禁止再堆，非功能） |

---

## 5. 健康项

| 域 | 状态 |
|---|---|
| 跨 BC `*.infrastructure` | **0** |
| domain ← FastAPI/httpx | **未发现** |
| market 写 palace | **未发现** |
| paper 不写 palace | **kept** |
| R4 层数/ref_close/Pulse/research | **kept**（时钟 AI 路径除外） |
| Job 先 status 再企微 | **kept** |
| pending/abandon fail-closed（扫描） | **kept** |
| 盯市快照=现金+成本 | **kept** |
| page-fill 主壳 | **kept** |
| 候选默认排除 backfill | **kept** |
| Zip Slip / entrypoint | **kept** |
| AI 写账本全权 | **by design** |

---

## 6. 修复路线图（须点名再改）

### Batch Q — 纸面时钟对齐（优先，不收 AI 权）

1. **R5-P1-1**：`merge_ai_orders_with_gates` 买入统一 `not allow_open_fill` → reject（与 rules 同语义；**仍允许 AI 在 regular 全权买卖**）  
2. 补测：09:28 / 12:00 / `auction_allow_open=True`  
3. **R5-P1-8/P2-15**：层数键序统一 max 优先  

### Batch R — 热库与 GET 写

1. **R5-P1-6**：spot 后镜像或读契约  
2. **R5-P1-7**：对网策略 / POST+write_guard  
3. **R5-P1-9**：榜单文案或策略  

### Batch S — 结构与日历

1. **R5-P1-5**：拆 `nextday_plan.py`  
2. **R5-P1-2**：监测入口交易日闸  
3. **R5-P1-3/4**：BC 地图 + intel DDL  

### 明确不做

- AI ExecutionGrant HITL  
- 限制 AI `add` / 写账本  

---

## 7. 盲区

1. 未跑全量 pytest / bun e2e / 浏览器量流  
2. 多 worker 下 spot 闸/登录限流未验  
3. DuckDB / 夜间全市场 Job 未压测  
4. 未打开真实 `data/`  
5. 财务因子 PIT 接入回测前语义未审  
6. Archive Teleport 下 KeepAlive deactivate 未运行时确认  

---

## 8. 给 Agent 的用法

1. 修纸面优先 Batch Q（对齐时钟，**不**收 AI 权）。  
2. 用户说「再审」→ 对照 §3 + 重跑 §1.2 → R6。  
3. 更新 BC 地图前先列「允许编排边」清单，避免误删 ai→ledger。  
4. 禁止恢复已删报告链；禁止 AI 造复盘权威数字（写工具全权 ≠ 伪造行情）。

---

## 9. 证据索引

| 主题 | 锚点 |
|---|---|
| AI 时钟 | `scenario_gates.merge_ai_orders_with_gates`（统一 `allow_open_fill`） |
| session_clock | `session_clock.py` |
| 层数 | `paper_eligibility.planned_layers_from_pick` |
| 体量 | `nextday_plan` 门面 + 三子模块均 ≤600 |
| board live | `board_router` `persist` + `mirror_recent_to_hot` |
| Pulse / research | `PulseMarketBoard` 样本榜；`QuantView` skills/research `v-if` |
| intel DDL | `MarketStore.ensure_intel_snapshots_schema`；`OpsStore` quota mixin |

---

## 10. 修复落地（2026-08-07）

### Batch Q / S — 纸面

- `merge_ai_orders_with_gates` 买入统一 `not allow_open_fill`
- `nextday_plan` 拆分为 `session_clock` / `plan_build` / `scenario_gates`
- `resolve_trading_day_gate` 接入 `strategy_monitor` / `paper_eod`
- 层数键 `planned_layers_max` 优先；降级写回 max
- `monitor_runs` LLM 失败 → `failed`；`dispatch_text` 导入修复

### Batch R — 行情 board

- `persist` 默认 false；true 需写鉴权；落盘后镜像热库
- 前端 live 轮询显式传 `persist`；Pulse「库内样本榜」

### Batch P2 / 架构

- BC 地图重写；intel DDL/配额收拢 Store
- QuantView skills `v-if`；`normalize_tuning` 放弃/降级序；market_gate 文案

### 回归（摘录）

```
tests/ops/{test_paper_quant,test_r3_residuals,test_r5_batch_s,test_role_stats,...}
+ tests/market/test_board_live_persist + tests/intel
→ 127 passed；lint-imports 9/9；bun typecheck；Pulse/QuantView 前端测 6 passed
```

**未做（产品/债）**：AI HITL；限制 AI add；Pulse 读合并；Bearer 轮换。
