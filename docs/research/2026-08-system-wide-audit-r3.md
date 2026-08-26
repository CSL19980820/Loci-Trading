# Loci / stock-analyzer 全系统审计 · 第三轮（复审）

> **本轮已被后续复核，不代表现状。** 终态见 [R6](./2026-08-system-wide-audit-r6.md)，
> 全系列导航见 [INDEX.md](./INDEX.md)。

> 核验日期：2026-08-07（R3，R2 修复后再审）  
> 前提：[`2026-08-system-wide-audit.md`](./2026-08-system-wide-audit.md) · [`2026-08-system-wide-audit-r2.md`](./2026-08-system-wide-audit-r2.md)  
> 方法：并行只读核验（R2 fixed 对照）+ 业务残余 + 性能/前端/安全 + `lint-imports` + 体量  
> 立场：验收 R2、暴露新残余；**本文件不授权直接改代码**（除非用户点名）  
> **续轮**：[R4](./2026-08-system-wide-audit-r4.md) · [R5](./2026-08-system-wide-audit-r5.md)

---

## 0. 一句话结论

R2 台账中标 **fixed 的 13 项全部 kept**；`lint-imports` **9/9**。旧 P0（AI 绕门闩、pending 静默开仓、DataQuery KeepAlive 风暴）未复发。

当前最高危残余转为：

1. **日终滚动把持仓 `mark_cost` 写成 `ref_close`** → 次日情景按成本价判高开/低开，可错跟 AI 加仓  
2. **扫描竞价「降级带 / 调参放弃线」未贯通监测预案** → 扫描已降级/放弃，监测仍可能 follow  
3. **Job 先按 success 推企微再改 failed** → 库内红、企微绿  
4. **MCP clamp 只挂助手 invoke 路径**；看板「总资产」盯市合成可写回快照

无新证据升 P0。

---

## 1. R2 fixed 验收

| ID | R3 | 说明 |
|---|---|---|
| R2-P0-1 … R2-P1-8 | **kept** | DataQuery/工坊/研究 KeepAlive；门闩/层数/关闸门/abandon；前视/clamp/lint/软失败 |
| R2-P2-1 … R2-P2-3 | **kept** | 人工单默认过门闩；sync 假绿；`layers_if_stretched` |
| R2-P2-4～6 | open | 巨石 / CI build / Pulse 频宽（债项） |

---

## 2. 本轮新台账

### 2.1 P0

无。

### 2.2 P1 — 应排期

| ID | 标题 | 证据摘要 | 建议 |
|---|---|---|---|
| **R3-P1-1** | 日终滚动 `mark_cost`→`ref_close` | `paper_quant_eod._nextday_picks_after_eod` 持仓项写 `ref_close=mark_cost`；监测优先用 item `ref_close`，不再回退 `quote.prev_close` | 写昨收/日 K 收；缺省 `None` |
| **R3-P1-2** | 扫描 downgrade 未进监测 | `auction_confirm` 有 `downgrade_gap_pct`；`evaluate_auction_stance` 仅 `abandon_gap` | 监测复用降级阈值，强制半层 |
| **R3-P1-3** | 调参 `abandon_gap` 未写入预案项 | tuning 可 −6/−4；`build_plan_item` 默认 −5；`_paper_pick` 未带 auction 段 | 种子时写入 `section(tuning,"auction")` |
| **R3-P1-4** | `limit_up_momentum` 无竞价确认 | 无 `confirm_leaders`；候选无 `auction_stance` | 对齐 leader_map 或禁种子纸面 |
| **R3-P1-5** | 前视：`next_open` 静态空转 + 大宇宙只抽前 40 列 | `audit_source` 非 open 即 return；截断 `columns[:40]` | 分层/随机抽样；可疑模式 warn |
| **R3-P1-6** | Job 先 success 推企微再改 failed | `registry`：`_maybe_push_wecom(status="success")` 在 status 判定之前 | 先定最终 status 再推 |
| **R3-P1-7** | MCP clamp 未挂统一边界 | 仅 `invoke_mcp_tool`；`call_mcp_tool`/`guarded_client_call`/Skill 旁路无语义裁 | 下沉到 `call_mcp_tool` 或 `McpClient` |
| **R3-P1-8** | 看板总资产盯市合成可写回 | `DashboardView` `cash+liveMv` 标「总资产」并 `createSnapshot` | 标估算；写回只交现金或后端算 |

### 2.3 P2 — 债项 / 体验

| ID | 标题 | 备注 |
|---|---|---|
| **R3-P2-1** | skill_watch 中途 MCP 软失败仍常记 success | 交易安全（空仓），运维可见性假绿 |
| **R3-P2-2** | `bypass_gates=true` 仍可绕 | 设计如此；生产可禁或审计 |
| **R3-P2-3** | `_next_trade_date` 只跳周末 | 长假错位（旧债） |
| **R3-P2-4** | KeepAlive in-flight 世代：Dashboard/Pulse 仅 unmount bump | 定时器已停；离页仍可能写 state |
| **R3-P2-5** | 工坊技能离页停、回页不续轮询 | 进度可能僵死 |
| **R3-P2-6** | KeepAlive 单测未真挂 KeepAlive | 名不副实 |
| **R3-P2-7** | CI 无 `bun run build` | 发版盲区 |
| **R3-P2-8** | page-fill 依赖 `> .page-fill` 直接子 | 包一层会破契约 |
| **R3-P2-9** | >600 行仍约 10 文件 | 头：`skills.py` 719、`AssistantHost*` 等 |
| **P1-SEC** | 非 production 写鉴权恒真 | 桌面威胁模型；对网须 production |

---

## 3. 本轮确认相对健康

| 项 | 证据 |
|---|---|
| R2 纸面 AI 门闩 / 层数钳制 / pending | 代码 + 既有测 |
| 扫描/监测关闸门 fail-closed 对齐 | `_gate_off_result` / `_resolve_market_gate` |
| KeepAlive 主轮询停表 | Pulse / DataQuery / Research / 工坊 |
| lint-imports | **9 kept / 0 broken** |
| sync / intel_fetch 入库假绿主路径 | registry 看 `failed` |
| 复盘胜率走后端；持仓浮盈有估算标注 | 总资产写回见 R3-P1-8 |
| 舱内 `max_layers` 执行校验 | `paper_exec` |

---

## 4. 修复路线图（建议，须点名再改）

### Batch I — 纸面昨收与竞价贯通（R3-P1-1～4）

1. 日终 `ref_close` 用昨收，禁止 `mark_cost`  
2. 监测纳入 downgrade + 调参 abandon 写入预案  
3. `limit_up_momentum` 竞价确认或禁种子  

### Batch J — Job 与 MCP 边界（R3-P1-6～7）

1. 先定 status 再推企微  
2. `call_mcp_tool` 统一 clamp  

### Batch K — 前端契约（R3-P1-8 + P2-4～6）

1. 总资产标估算 / 写回收口  
2. deactivate bump generation；工坊回页续轮询；真 KeepAlive 测  

### Batch L — 债项

前视抽样、交易日历、CI build、巨石触达再拆。

---

## 5. 元数据（R3）

| 项 | 值 |
|---|---|
| lint-imports | **9 kept / 0 broken** |
| >600 行（src+frontend/src） | **10** |
| Top | `skills.py` 719 · `AssistantHost.test.ts` 708 · `ops/api/skills.py` 652 · `AssistantHost.vue` 652 · `outcomes.py` 651 |
| 并行代理 | R2 核验 / 业务残余 / 性能前端安全 |
| 上一轮 | R2 文档 |

### 缺陷状态（R3）

| ID | 状态 |
|---|---|
| R3-P1-1 … R3-P1-8 | **fixed**（2026-08-07 落地） |
| R3-P2-1 skill_watch 假绿 | **fixed**（degraded→skipped） |
| R3-P2-2 bypass 生产闸 | **fixed**（production 403 + 环境开闸） |
| R3-P2-3 交易日历次日 | **fixed**（`trading_calendar` / 周末退路） |
| R3-P2-4/5 KeepAlive 世代/续轮询 | **fixed**（Dashboard + 工坊） |
| R3-P2-6 真 KeepAlive 单测 | **fixed**（`useLivePolling` KeepAlive 挂载） |
| R3-P2-7 CI build | **fixed** |
| R3-P2-8 page-fill 契约 | **fixed**（`:has(.page-fill)`） |
| R3-P2-9 巨石 | **fixed**（见 §7 拆分清单；生产代码已无 >600） |
| P1-SEC 写鉴权 | **fixed**（启动 warning + `PALACE_REQUIRE_WRITE_AUTH`） |
| R2 fixed 全集 | kept |

---

## 6. 下一步（已执行一轮）

见 §7。R3 台账主债已清。全系统再审见 **[R4 审计方案+台账](./2026-08-system-wide-audit-r4.md)**。

---

## 7. R3.1 续拆 / 再审（2026-08-07）

### 7.1 本轮拆分（生产代码）

| 原文件 | 拆后 | 行数 |
|---|---|---|
| `review/application/outcomes.py` | + `outcomes_plans.py` | 522 / 139 |
| `strategy/application/screen_python.py` | + `screen_python_load.py` | 396 / 252 |
| `market/api/router.py` | + `board_router.py` | 386 / 256 |
| `market/infrastructure/akshare_catalog.py` | + `akshare_catalog_limits.py` | 344 / 314 |
| `ledger/infrastructure/candidates.py` | + `candidates_query.py` / `candidates_sql.py` | 220 / 408 / 18 |
| `app/main.py` | + `login_throttle.py` | 551 / ~57 |

另：上一轮已拆 `ops/api/skills*`、`AssistantHost*`、`StrategyDetail*`。

### 7.2 拆分中发现并修的缺陷

| 严重度 | 项 | 处理 |
|---|---|---|
| **P1** | `evaluate_plans` 多预案循环复用末项 `stop`/`target`，止盈止损可串票 | 按 `record` 取价；`PlanOutcomeTests` 加双预案断言 |
| P2 | board live 测只种全量库、pytest 热库为空 → 假失败 | 热库+全量双写；patch 路径改 `board_router` / `application.live`；`wait` 放进 patch 块 |

### 7.3 再探结论（R3.1）

| 项 | 状态 |
|---|---|
| lint-imports | **9/9 kept** |
| 生产 `src`+`frontend/src` **>600** | **0**（贴线：`backtest_run` 600、`nextday_plan` 599、`peek_dock`/`AssistantSenderDock` 598） |
| R3-P1/P2 主债 | **kept fixed**（抽查：`bypass_gates` 生产闸、`paper_quant_eod` 禁 mark_cost→ref_close 注释仍在） |
| 新 P0 | **无** |
| 残余债 | 测试巨石（`tests/**` 多文件 >600）；贴线生产文件触达再拆；`paper_exec` 仍合法使用持仓 `mark_cost`（成本字段，非 ref_close 冒充） |

### 7.4 建议下一刀（非阻塞）

1. 贴线：`research/backtest_run.py` / `ops/nextday_plan.py` / `AssistantSenderDock.vue`  
2. 测试：`tests/strategy/test_strategies.py`、`tests/intel/test_intel.py` 等 >600 按场景拆  
3. 可选：board live 单测改为注入假热库，避免依赖真实/环境热库路径
