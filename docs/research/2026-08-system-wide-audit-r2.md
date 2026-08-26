# Loci / stock-analyzer 全系统审计 · 第二轮（复审）

> **本轮已被后续复核，不代表现状。** 终态见 [R6](./2026-08-system-wide-audit-r6.md)，
> 全系列导航见 [INDEX.md](./INDEX.md)。

> 核验日期：2026-08-07（R2，修复后复审）  
> 前提：第一轮台账见 [`2026-08-system-wide-audit.md`](./2026-08-system-wide-audit.md)；其间已落地 Batch A/B/C 主项  
> 方法：并行只读核验（已修项对照）+ 业务残余扫描 + 性能/前端/安全扫描 + `lint-imports` + 体量统计  
> 立场：验收上一轮修复、暴露漏网与新发现；**本文件不授权直接改代码**（除非用户点名）

---

## 0. 一句话结论

上一轮 **P0/P1 主修大体成立**：纸面 `add`/`buy_dip` 门闩、pending fail-closed、Pulse 批量历史、`useLivePolling` KeepAlive、intel_fetch 假绿等有代码与测试证据。

当前最危险的残余不再是「AI 用 add 绕 stance」，而是：

1. **DataQuery 自建轮询未接 KeepAlive**（离页仍 12s 打 live board）  
2. **扫描侧关 `market_gate` 仍 fail-open**，与纸面监测 fail-closed 口径分裂  
3. **AI 过门闩后层数不被情景钳制**；隔夜预案路径竞价放弃阈值可能贯通不完整  
4. **架构回归：`ops.api` 深掏 `intel.infrastructure`**（lint-imports 8/9）

---

## 1. 上一轮 fixed 项验收

| ID | R2 状态 | 说明 |
|---|---|---|
| P0-1 | **kept** | `merge_ai_orders_with_gates` 对 open/add/buy_dip 统一 `scan_auction_block_reason` + `stance!=follow` |
| P0-2 | **kept*** | screen/backtest 调 `guard_strategy`；convert / python draft 用 `audit_source`（同 block 级，非同符号）；`intraday_field=block` |
| P0-3 | **partial** | `useLivePolling` 已 deactivate；**DataQuery / 工坊技能 / 研究面板轮询未接**（见 R2-P0-1） |
| P1-1～P1-6、P1-8～P1-10 | **kept** | 与第一轮关闭证据一致（抽核通过） |
| P1-7 | **partial** | 转换/草稿有静态审计；**已注册 Python Skill 用户源码**热路径仍主要审适配器类源码 |
| P1-SEC | **wontfix** | 桌面非 production 写鉴权恒真；对网须 `PALACE_ENV=production` |
| P2-3（monitor skipped） | **kept** | registry 已含 `strategy_monitor` |

\*P0-2 验收按「fail-closed 等价」计 kept；严格「处处调用 `guard_strategy`」则标 partial。

---

## 2. 本轮新台账

### 2.1 P0 — 优先修

| ID | 标题 | 证据 | 复现要点 | 建议验收 |
|---|---|---|---|---|
| **R2-P0-1** | DataQuery KeepAlive 离页轮询不停 | `useDataQueryMarket.ts`：`setInterval` 12s/60s，仅 `onBeforeUnmount`；`PageHost` KeepAlive | 行情台→账本连切；网络面板仍见 board/session | 改用 `useLivePolling` 或补 deactivate；加单测 |

### 2.2 P1 — 应排期

| ID | 标题 | 证据摘要 | 建议 |
|---|---|---|---|
| **R2-P1-1** | AI 买入层数不被情景钳制 | `merge_ai_orders_with_gates` follow 后原样 `kept.append(order)`；对比 `scenario_gated_open_orders` 用 `decision["layers"]` | follow 后 `layers=min(AI, decision.layers)`，尊重 `layers_if_stretched` |
| **R2-P1-2** | 扫描关 `market_gate` fail-open | `leader_map`/`limit_up_momentum` `_gate_off_result` → `entry_allowed: True`；监测侧已 False | 扫描与监测对齐 fail-closed，或关闸门禁止 `paper_candidates` |
| **R2-P1-3** | 隔夜预案竞价放弃阈值未贯通监测 | 日终滚动 picks 剥 `auction_*`；`evaluate_auction_stance` 与 `auction_confirm.abandon_gap` 口径不一 | 监测重跑竞价确认或把 abandon 并入情景评估 |
| **R2-P1-4** | Python Skill 用户源码前视盲区 | create/update 无 `audit_source(code)`；`guard_strategy` 审引擎类源码；大宇宙截断审计关闭（>100 列） | 注册链审用户源码；回测抽样截断 |
| **R2-P1-5** | 工坊技能 / 研究 Job 轮询离页不停 | `useWorkbenchSkillRun`、`Research*Panel` 仅 `onUnmounted` | 同 KeepAlive 契约 |
| **R2-P1-6** | MCP clamp 缺口 | 未裁 `theme_top_n`；无逗号 codes 字符串不截；`days` 未限 | 扩键 + 规范化 codes + 补测 |
| **R2-P1-7** | lint-imports 破：ops→intel.infrastructure | `ops/api/data_sources.py:117` → `probe_mcp` | 经 `src.intel` 包根导出再调 |
| **R2-P1-8** | 悟道已装配后中途硬失败可挂 skill_watch | `McpError`/`McpQuotaError` 未统一软失败；intel_fetch 已吞、skill_watch 未 | runner 降级 skipped/空仓 |

### 2.3 P2 — 债项

| ID | 标题 | 备注 |
|---|---|---|
| **R2-P2-1** | 人工纸面单绕门闩 | `POST .../paper-cabins/{slug}/orders` 直 `execute_orders` |
| **R2-P2-2** | `sync` 部分失败仍 success | registry 只对 intel_fetch 看 stats.failed |
| **R2-P2-3** | `layers_if_stretched` 仅文案 | ADR-008 减层未进 `evaluate_auction_stance` |
| **R2-P2-4** | 10 个文件 >600 行 | 见 §5；禁止再堆 `skills.py` / `AssistantHost.vue` |
| **R2-P2-5** | CI 无 `bun run build`；KeepAlive/鉴权烟测窄 | 发版盲区 |
| **R2-P2-6** | Pulse 盘中 tick 仍偏宽 | 非 N+1；8s tape+board+≤80 叠价 |

---

## 3. 本轮确认相对健康

| 项 | 证据 |
|---|---|
| 纸面 AI open/add/buy_dip 情景门闩 | `merge_ai_orders_*` + 回归测 |
| pending / abandon / abandoned 不可开仓 | `paper_eligibility` |
| Pulse 选股历史批量 | `GET /api/screen/history/batch` + `usePulseHome` |
| `useLivePolling` KeepAlive（Pulse/Dashboard/Peek） | onDeactivated/onActivated |
| 助手 SSE 短开短关 | `assistant.stream_events` |
| 主路由 page-fill + html/body 禁滚 | 壳层在位 |
| 复盘胜率/总资产以后端为准；Dashboard 盯市标估算 | 未发现自造胜率 |
| domain 不依赖 FastAPI；market/ledger 等 infrastructure 合同 | lint 其余 8 合同 KEPT |

---

## 4. 修复路线图（建议批次）

### Batch E — KeepAlive 收口（R2-P0-1, R2-P1-5）

1. DataQuery → `useLivePolling` 或 deactivate 停表  
2. 工坊技能 / 研究面板同契约  

**验收：** KeepAlive 离页网络面板静默；单测。

### Batch F — 纸面口径对齐（R2-P1-1～3, R2-P2-3）

1. AI 层数钳制 + stretched 减层  
2. 扫描 `_gate_off_result` fail-closed  
3. 监测/滚动预案贯通竞价放弃  

**验收：** pytest + 纸面 auto 人工场景。

### Batch G — 架构与前视（R2-P1-4, R2-P1-7, R2-P1-6, R2-P1-8）

1. `probe_mcp` 包根导出，修 lint-imports  
2. Python Skill 注册审用户源码；回测抽样截断  
3. MCP clamp 补洞；skill_watch MCP 软失败  

**验收：** `lint-imports` 9/9；相关测绿。

### Batch H — 债项（R2-P2-*）

人工单门闩提示；sync 假绿；CI build；巨石触达再拆。

---

## 5. 元数据（R2）

| 项 | 值 |
|---|---|
| lint-imports | **8 kept / 1 broken**（`ops.api.data_sources` → `intel.infrastructure.registry`） |
| >600 行文件（src+frontend/src） | **10**（较 R1 的 17 下降，主因统计口径/已拆；头部仍是 skills 719 / AssistantHost 652） |
| 并行代理 | 已修项核验 / 业务残余 / 性能前端安全 |
| 上一轮文档 | `2026-08-system-wide-audit.md` |

### >600 行 Top

| 行数 | 路径 |
|---:|---|
| 719 | `src/ops/application/skills.py` |
| 708 | `frontend/src/features/ai/AssistantHost.test.ts` |
| 652 | `src/ops/api/skills.py` |
| 652 | `frontend/src/features/ai/AssistantHost.vue` |
| 651 | `src/review/application/outcomes.py` |
| 626 | `src/strategy/application/screen_python.py` |
| 625 | `frontend/.../StrategyDetailDialog.vue` |
| 624 | `src/market/infrastructure/akshare_catalog.py` |
| 617 | `src/market/api/router.py` |
| 613 | `src/ledger/infrastructure/candidates.py` |

---

## 6. 缺陷状态跟踪（R2）

| ID | 状态 | 关闭证据 |
|---|---|---|
| R2-P0-1 | fixed | `useDataQueryMarket` onDeactivated/onActivated |
| R2-P1-1 | fixed | `merge_ai_orders` 层数钳制；`tests/ops/test_r2_paper_gates.py` |
| R2-P1-2 | fixed | 扫描 `_gate_off_result` fail-closed |
| R2-P1-3 | fixed | `abandon_gap_pct` 并入情景评估；日终滚动保留竞价字段 |
| R2-P1-4 | fixed | `_validate_engine` 审 Python 用户源码；回测大宇宙抽样截断 |
| R2-P1-5 | fixed | 工坊技能 / 研究面板 deactivate 停轮询 |
| R2-P1-6 | fixed | clamp 扩 theme/days/空格 codes |
| R2-P1-7 | fixed | `probe_mcp` 等经 `src.intel` 导出；lint 9/9 |
| R2-P1-8 | fixed | `call_mcp_tool` / `skill_watch_mcp_call` 中途软失败 |
| R2-P2-1 | fixed | 人工单默认过门闩，`bypass_gates` 显式绕过 |
| R2-P2-2 | fixed | sync `failed>0` → Job failed |
| R2-P2-3 | fixed | `layers_if_stretched` 生效 |
| R2-P2-4～6 | open | 巨石/CI/Pulse 频宽债项 |
| 上一轮 P0-1～P1-10 | kept / wontfix 见 §1 |

---

## 7. 下一步

**Batch E/F/G 与明确 bug 型 P2（R2-P2-1～3）已于同日落地。** 剩余债项：巨石拆分、CI 加 build、Pulse 盘中降频（R2-P2-4～6），触达再做。

**复审：** [`2026-08-system-wide-audit-r3.md`](./2026-08-system-wide-audit-r3.md)（R2 fixed 全 kept；新残余以昨收错写、竞价降级未贯通、企微先绿后红为主）。
