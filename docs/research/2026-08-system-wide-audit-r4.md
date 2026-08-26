# Loci / stock-analyzer 全系统审计 · 第四轮（R4）+ 常驻审计方案

> **本轮已被后续复核，不代表现状。** 终态见 [R6](./2026-08-system-wide-audit-r6.md)，
> 全系列导航见 [INDEX.md](./INDEX.md)。R4 里「体量已无 >600 行」的结论现已不成立。

> 执行日期：2026-08-07  
> 前提：R1–R3 台账（[`2026-08-system-wide-audit.md`](./2026-08-system-wide-audit.md) · [r2](./2026-08-system-wide-audit-r2.md) · [r3](./2026-08-system-wide-audit-r3.md)）  
> 立场：**只读核验 + 出方案**；本文不授权直接改代码（除非用户点名修）  
> 方法：四路并行探查（架构 / 纸面业务 / 性能前端 / 安全数据）+ 本地 `lint-imports` + 体量清单 + 关键符号对照源码  
> **续轮**：[R5](./2026-08-system-wide-audit-r5.md)（2026-08-07）— R4-P1-2 在 AI merge 路径半回归；`nextday_plan.py` 再破 600 行

---

## 0. 一句话结论

R3 主债抽查 **仍 kept**；R4 落盘时生产代码 **无 >600 行**；`lint-imports` **9/9**。  
**无新 P0**。本轮最高危新发现（**2026-08-07 已修一批，见 §10**）曾为：

1. **日终滚动读 `planned_layers`，预案写的是 `planned_layers_max`** → **fixed**  
2. **竞价窗 09:25–09:30 监测可开仓** → **fixed（rules）**；R5 发现 AI merge **未统一吃 `allow_open_fill`**  
3. **未成交滚动 `ref_close` 未用日 K 校正** → **fixed**  
4. **AI ExecutionGrant 写账本** → **wontfix / by design**（产品定位 AI 量化全权，不收紧）  
5. **Pulse 离页世代 / 工坊研究轮询** → **fixed**

架构层无跨域掏 `infrastructure`，但 **BC 地图失真**、**CLI 深路径**、**intel 在 market/ops 旁路 DDL** 构成结构性债。

---

## 1. 常驻审计方案（可复用流程）

### 1.1 目标与范围

| 维度 | 审什么 | 不做 |
|---|---|---|
| 架构 / DDD | 分层、跨 BC、三库写隔离、公开 API、组合根 | 大重构实施 |
| 业务逻辑 | 纸面门闩、层数、竞价、前视、Job 状态、复盘口径 | 代用户下买卖决策 |
| 性能 | KeepAlive/轮询、写放大、N+1、阻塞 IO、SSE | 未部署环境压测 |
| 结构 | 600 行、神类、重复真相 | 无关美化 |
| 功能 / UX | page-fill、空态、EP 控件、口径标注 | 视觉 redesign |
| 安全 | 写鉴权、Bearer、路径穿越、密钥、probe | 渗透打真实外网 |
| 数据完整性 | 事件可回放、热库/全量、复权、backfill、PIT | 用户真实 data/ 读写 |
| 测试 / CI | 假绿、缺测、lint-imports、体量 | 全量无差别重跑 |

**权威库红线**：ledger=`palace.db`；market=`market.db`（热库可重建）；ops=`ops.db`；AI 不产出权威行情/盈亏数字。

### 1.2 节奏

| 轮次 | 触发 | 深度 |
|---|---|---|
| **快速回归** | 每合并纸面/鉴权/KeepAlive PR | 对照上轮 fixed 台账 + `lint-imports` + 相关 pytest |
| **主题深潜** | 功能大改后 | 单维度 very thorough（如只审纸面） |
| **全系统轮（本 R4）** | 里程碑 / 用户点名 | 四维并行 + 体量 + 安全 + 出台账 |

### 1.3 执行检查表（每轮必做）

```text
[ ] 读 AGENTS.md + bounded-contexts.md + 上轮台账 fixed 表
[ ] lint-imports（期望 9 kept）
[ ] 体量：src+frontend/src 生产文件 >600 / 贴线 ≥560
[ ] 架构：跨域 infrastructure / domain 染框架 / CLI 深路径
[ ] 纸面：ref_close、层数键、竞价窗、bypass、Job→企微、MCP clamp、pending
[ ] 性能：Pulse/Dashboard/工坊/Research KeepAlive 世代；board spot 闸
[ ] 前端：盯市写回、胜率来源、page-fill
[ ] 安全：require_write_auth、AI 写账本、路径/probe
[ ] 对照源码核实每条 P0/P1（禁止只信代理摘要）
[ ] 落盘 docs/research/YYYY-MM-system-wide-audit-rN.md
[ ] 给出 Batch 修复建议（不擅自改代码，除非用户点名）
```

### 1.4 严重度

| 级 | 含义 |
|---|---|
| **P0** | 可导致错误实盘/账本污染/未鉴权写；须立即停损 |
| **P1** | 明确逻辑洞或结构性越界，会错仓/错口径/假安全感 |
| **P2** | 债项、体验、运维可见性、贴线体量 |

### 1.5 验收 DoD（审计本身）

- [ ] 每条 Finding 有路径/符号证据  
- [ ] R(n-1) fixed 标明 kept / regress  
- [ ] 健康项与盲区分开写  
- [ ] 给出可执行 Batch（谁先修）  
- [ ] 未污染真实 `data/`  

### 1.6 工具与入口

| 用途 | 命令 / 入口 |
|---|---|
| 导入契约 | `.\.venv\Scripts\lint-imports.exe` |
| 后端测 | `.\.venv\Scripts\python.exe -m pytest tests/ -q --tb=line` |
| 前端 | `cd frontend; bun run typecheck; bun run test` |
| 体量 | 扫 `src`/`frontend/src` 行数（排除 test/spec） |
| 图谱 | codegraph（若有 `.codegraph/`） |
| 地图 | `docs/architecture/bounded-contexts.md` |

---

## 2. R4 执行元数据

| 项 | 值 |
|---|---|
| lint-imports | **9 kept / 0 broken**（442 files） |
| 生产 >600 | **0** |
| 贴线（560–600） | ~23 文件（头：`backtest_run` 600、`nextday_plan` 599、`peek_dock`/`AssistantSenderDock` 598） |
| 并行探查 | 架构 · 纸面 · 性能前端 · 安全数据 |
| R3 fixed | 抽查 **kept**（见 §3） |

---

## 3. R3 fixed 回归对照

| ID | R4 | 证据摘要 |
|---|---|---|
| R3-P1-1 ref_close≠mark_cost | **kept** | `paper_quant_eod` 日 K 收盘 + 禁成本注释 |
| R3-P1-2/3 downgrade/abandon | **kept** | `evaluate_auction_stance` / tuning auction 段 |
| R3-P1-4 limit_up 竞价 | **kept** | `confirm_leaders` |
| R3-P1-5 前视 | **kept（未闭合）** | hash 抽 40 列仍在 → 见 R4-P2 |
| R3-P1-6 Job→企微 | **kept** | 先 status 再推 |
| R3-P1-7 MCP clamp | **kept** | `call_mcp_tool` / guarded |
| R3-P1-8 盯市写回 | **kept** | 现金+持仓成本；展示标估 |
| R3-P2-* / P1-SEC | **kept** | bypass 生产闸、日历、KeepAlive 部分、page-fill、巨石生产侧 |
| R2 P0 门闩/pending | **kept** | 未复发静默开仓 |

---

## 4. R4 新台账

### 4.1 P0

**无**（默认桌面 loopback 威胁模型）。

**条件性 P0**：对网/`0.0.0.0` 暴露且未 `PALACE_ENV=production` 与 `PALACE_REQUIRE_WRITE_AUTH=1` → 写鉴权恒真。

### 4.2 P1 — 应排期

| ID | 维度 | 标题 | 证据 | 影响 | 建议 |
|---|---|---|---|---|---|
| **R4-P1-1** | 业务 | 日终滚动层数字段错位 | **fixed**（读 `planned_layers_max`） | — | — |
| **R4-P1-2** | 业务 | 09:25–09:30 开仓边界分裂 | **fixed**（仅 `regular` 默认可开仓） | — | — |
| **R4-P1-3** | 业务 | 未成交滚动 `ref_close` 脏种子 | **fixed**（日终用日 K 覆盖） | — | — |
| **R4-P1-4** | 业务 | 持仓滚动 AI `add` | **wontfix** | AI 量化全权，不收紧加仓 | — |
| **R4-P1-5** | 安全 | AI ExecutionGrant 写账本 | **wontfix / by design** | 产品即 AI 量化系统，助手保持写账本全权 | — |
| **R4-P1-6** | 架构 | BC 地图与代码严重偏离 | open | Agent 按地图纠偏会误伤 | 地图改为「允许编排边 / 禁止深掏与写穿」两层 |
| **R4-P1-7** | 架构 | intel 旁路 DDL/配额 | open | schema 双源；锁/迁移不一致 | DDL 收 market/ops Store；配额走 OpsStore |
| **R4-P1-8** | 性能 | Pulse 离页世代未 bump | **fixed**（`onDeactivated` bump） | — | — |
| **R4-P1-9** | 性能 | 工坊研究台轮询不停 | **fixed**（research Tab `v-if`） | — | — |

### 4.3 P2 — 债项

| ID | 标题 | 备注 |
|---|---|---|
| **R4-P2-1** | 前视仍只抽 40 列 | R3-P1-5 未闭合；hash 抽样优于字典序但仍假阴性 |
| **R4-P2-2** | CLI/`loci.py` 深掏 infrastructure | import-linter 不覆盖 cli；违反「只经包根」 |
| **R4-P2-3** | import-linter 无 research / sqlite3 / cli | 治理假安全感 |
| **R4-P2-4** | `app/screen_skills` 触达 `_REGISTRY` | 组合根堆业务 + 私有符号 |
| **R4-P2-5** | review application 直捅 `.conn` | 绕过 Store 封装 |
| **R4-P2-6** | strategy_monitor 固定 success | 运维假绿（成交安全尚可） |
| **R4-P2-7** | rules 模式几乎无退出 | 纸面可拿到日终 |
| **R4-P2-8** | market_gate 文案「关掉自负」vs 实际 fail-closed | 文档误导（偏安全） |
| **R4-P2-9** | abandon/downgrade 可配反 | 缺 `|downgrade|<|abandon|` 校验 |
| **R4-P2-10** | Pulse 8s 三路 HTTP | 读放大；与 board spot 闸交错 |
| **R4-P2-11** | Dashboard 本月% 可用盯市分母重算 | 不写库；口径漂移 |
| **R4-P2-12** | Bearer 长期静态无作用域 | 泄露=全写面 |
| **R4-P2-13** | holdings 无事件回放重建入口 | 投影损坏难自愈 |
| **R4-P2-14** | 贴线巨石 ~23 文件 | 禁止再堆；触达再拆 |
| **R4-P2-15** | 测试巨石 | `tests/**` 多文件 >600，未纳入生产债但拖慢维护 |

---

## 5. 健康项（本轮既证）

| 域 | 状态 |
|---|---|
| `src/` 跨 BC 深掏 infrastructure | **0** |
| domain ← FastAPI/httpx | **未发现** |
| market 写 palace | **未发现** |
| paper 声明不写 palace | **kept** |
| quant_router 薄聚合 | **健康** |
| 写依赖覆盖主要写 API | **健康** |
| Zip Slip / entrypoint `..` | **健康** |
| AkShare probe 非任意表达式 | **健康** |
| 候选默认排除 backfill | **健康** |
| 盯市快照写回主洞 | **kept** |
| page-fill / 禁文档滚 | **kept** |
| SSE→poll 串行非双开 | **健康** |
| 生产体量 >600 | **0** |

---

## 6. 修复路线图（须点名再改）

### Batch M — 纸面口径（优先）

1. **R4-P1-1** 日终读 `planned_layers_max` + 回归测  
2. **R4-P1-3** 统一 ref_close 真相源（计划日前收）  
3. **R4-P1-2** 统一 09:25/09:30 开仓边界  
4. **R4-P1-4** 持仓滚动收紧 AI add  

### Batch N — 前端运行时

1. **R4-P1-8** Pulse `onDeactivated` bump  
2. **R4-P1-9** 工坊 Tab 停轮询  
3. P2-10/11 频宽与本月% 口径  

### Batch O — 安全与账本

1. **R4-P1-5** AI 写账本 HITL  
2. 对网强制写鉴权文档/启动硬拒绝非 loopback（可选）  
3. P2-12 Bearer 轮换；P2-13 holdings 对账命令  

### Batch P — 架构治理

1. **R4-P1-6** 重写 BC 地图  
2. **R4-P1-7** intel DDL/配额收拢  
3. P2-2/3 CLI 包根 + import-linter 补 research/cli  
4. P2-4 Screen Skill 迁出 app  

---

## 7. 盲区（本轮未覆盖）

1. 未跑全量 pytest / bun e2e / 浏览器量流  
2. 未动态追踪全部 SQL 写路径（偏静态 import/DDL）  
3. DuckDB 旁路、全市场 Job 夜间负载未压测  
4. 财务因子 PIT 接入回测前的语义审计未做  
5. 多 worker Uvicorn 下 probe 并发/登录限流未验证  
6. 真实用户 `data/` 库未打开（刻意）  

---

## 8. 给 Agent 的用法

1. 先读本文 §1 检查表与 §4 台账，再读 R3 §7。  
2. 用户说「修 R4」时按 Batch M→N→O→P，**最小改动**，每项补测。  
3. 用户说「再审」时：对照 §3 fixed + 重跑 §1.3，增量编号 R5。  
4. **禁止**把 AI 生成数字当复盘权威；**禁止**恢复已删报告链。

---

## 10. 修复落地（2026-08-07，不收紧 AI）

| 项 | 状态 | 说明 |
|---|---|---|
| R4-P1-1/2/3 | **fixed** | `paper_quant_eod` / `session_clock` / 日 K 覆盖 ref_close |
| R4-P1-8/9 | **fixed** | Pulse `onDeactivated`；`QuantView` research `v-if` |
| R4-P1-4/5 | **wontfix** | 用户明确：AI 量化全权，不收 HITL、不限制 add |
| R4-P1-6/7 及多数 P2 | open | 架构债，未本轮改 |

---

## 9. 证据索引（关键锚点）

| 主题 | 锚点 |
|---|---|
| 层数字段 | `src/ops/application/nextday_plan.py`（`planned_layers_max`）；`jobs/paper_quant_eod.py` L95 |
| 竞价时钟 | `nextday_plan.session_clock`；`skill_watch/auction_confirm.in_auction_window` |
| ref_close 种子 | `skill_watch/dragon_return.py`；`limit_up_momentum.py` |
| Pulse 世代 | `frontend/.../usePulseHome.ts`；对比 `useDashboardLive.ts` |
| 工坊 Tab | `frontend/.../QuantView.vue` `v-show` |
| 写鉴权 | `src/app/main.py` `require_write_auth` |
| AI 写账本 | `src/ai/application/assistant_manager.py`；`system_toolbus_ledger.py` |
| intel DDL | `src/intel/infrastructure/intel_cache.py`；`quota.py` |
| 体量 / lint | 本轮 shell 实测（见 §2） |
