# Loci / stock-analyzer 全系统审计方案与缺陷台账

> **本轮已被后续复核，不代表现状。** 终态见 [R6](./2026-08-system-wide-audit-r6.md)，
> 全系列导航见 [INDEX.md](./INDEX.md)。文中列出的缺陷多数已在 R2–R6 修复。

> 核验日期：2026-08-07  
> 方法：并行只读扫描（架构边界 / 业务逻辑 / 性能与前端契约）+ 关键代码复核 + `lint-imports`（9/9 KEPT）  
> 范围：`src/**`、`frontend/src/**`、`cli/**`、CI；不含真实 `data/*.db` 污染写  
> 立场：找缺陷与可执行审计流程；**本文件不授权直接改生产行为**（修复另开任务）

---

## 0. 一句话结论

系统在 **DDD 导入边界与「无悟道不拖垮主体」** 上整体健康；当前最危险的不是 MCP，而是：

1. **AI 纸面单可用 `add`/`buy_dip` 绕过情景门闩**（可错误开仓）  
2. **前视审计 `guard_strategy` 未挂选股/回测热路径**（收益口径可失真）  
3. **KeepAlive 页离开后轮询不停**（性能与请求风暴）

---

## 1. 审计方案（可重复执行）

### 1.1 目标与原则

| 原则 | 说明 |
|---|---|
| 证据优先 | 每个缺陷绑定路径/符号；无证据不升 P0 |
| 真相分层 | 账本/复盘数字以后端引擎为准；AI/MCP/前端只展示或旁注 |
| 可选依赖 | 悟道/LLM/外网失败不得拖垮盘面·账本·本地选股·行情同步 |
| 最小爆炸半径 | 审计可发现巨石，但修复仍按「一刀一事」开任务 |
| 可回归 | 每项 P0/P1 必须有复现条件 + 建议测试名 |

### 1.2 审计维度矩阵

| 维度 | 检查什么 | 主工具 / 命令 | 通过标准 |
|---|---|---|---|
| A. 架构边界 | 跨域深掏 infrastructure；domain 外依；api 堆公式 | `lint-imports`；Grep `from src.*.infrastructure` | 合同全绿；新 PR 不增跨域深掏 |
| B. 体量 | 单文件 ≤600 行；巨石禁止再堆 | 行数脚本（见 §1.4） | 新增/触达文件不超限；存量有拆分债项 |
| C. 持久化 | 库归属；跨库 FK；路由 DDL；intel 旁路写 ops | Grep `CREATE TABLE`/`FOREIGN KEY`；读 store_schema | DDL 只在对应 Store；可重建表声明清楚 |
| D. 可选依赖 | 无悟道/无 LLM 硬失败路径 | 跟 `wudao_availability` / Job `skipped` / soft fail | 主体功能可启动可交易日作业 |
| E. 业务正确性 | entry_timing；门闩；竞价；前视 | 读引擎 + 纸面合并逻辑；对照测试 | 无「偷看未来」静默成功；买入动作统一过门闩 |
| F. 调度与 Job | 失败语义；重复触发；假超时成功 | `run_job` / claim_run / 各 executor | 部分失败不得假绿；skipped 状态正确 |
| G. 性能 | KeepAlive 轮询；N+1；MCP 扫池；SSE 占库 | 前端 composable + intel 配方 | 离开页停表；扇出有上限 |
| H. 前端契约 | page-fill；EP；不造复盘数字；类型对齐 | View Grep；typecheck；抽字段对拍 | 无文档级滚动；盈亏以后端为准 |
| I. 安全 | 写鉴权；Host；密钥不上库 | `main.py` write_dependency；分享包脱敏 | production 强制鉴权；分享包无密文 |
| J. 测试/CI | 盲区与假绿 | `.github/workflows/ci.yml`；关键测是否存在 | P0 有回归测；CI 含 typecheck+pytest+lint-imports |

### 1.3 节奏（建议）

| 频率 | 动作 |
|---|---|
| 每个 PR | A+B 轻扫；触及 Job/门闩/回测则补 E/F；触及 Pulse/KeepAlive 则补 G |
| 每周 | 跑 §1.4 命令包；更新本台账「未关闭」项状态 |
| 发版前 | 全维度走查 + 手工清单（§1.5） |
| 事故后 | 只扩相关维度；先复现再补测再改代码 |

### 1.4 自动化命令包（Windows / 本仓）

```powershell
# 架构
.\.venv\Scripts\lint-imports.exe

# 后端
.\.venv\Scripts\python.exe -m pytest tests/ -q --tb=line

# 前端
cd frontend; bun run typecheck; bun run test

# 体量（>600 应进债项，禁止新超限）
.\.venv\Scripts\python.exe -c "from pathlib import Path
for root in [Path('src'),Path('frontend/src')]:
  for p in root.rglob('*'):
    if p.suffix.lower() not in {'.py','.vue','.ts'}: continue
    if any(x in p.parts for x in ('node_modules','__pycache__')): continue
    n=sum(1 for _ in p.open(encoding='utf-8',errors='ignore'))
    if n>600: print(n, p)"
```

可选加深：`bun run build`；`bun run test:e2e`（需 Chromium）。

### 1.5 发版前人工清单（15 分钟）

- [ ] 未配悟道 Key：启动 → 盘面刷新 → 选股历史 → 账本写入，无红屏/无 Job 连环 failed  
- [ ] 配悟道后：`intel_fetch` 成功一次；盘面短线情报非空或诚实空态  
- [ ] 龙回头纸面：竞价 `abandon`/`pending` 时不应静默开仓  
- [ ] AI 纸面 auto：输出 `add`/`buy_dip` 时须被情景门闩同等拦截  
- [ ] 离开盘面页后，网络面板不再每 8s 打 `live-tape`/`board`  
- [ ] production 配置下无 Cookie 写接口 → 401  

---

## 2. 本轮发现台账

### 2.1 P0 — 必须优先修

| ID | 标题 | 证据 | 复现要点 | 建议验收 |
|---|---|---|---|---|
| **P0-1** | AI 纸面 `add`/`buy_dip` 绕过情景门闩 | `nextday_plan.merge_ai_orders_with_gates`：`scan_auction_block_reason` 与 `stance!="follow"` **仅当 `action=="open"`** 才 reject | `ai_mode=auto` + 预案内代码 + LLM 出 `add`/`buy_dip` + stance 非 follow；非龙回头或闸门关 | 所有买入动作统一过 stance/竞价拦截；补单测 |
| **P0-2** | `guard_strategy` 未挂热路径 | 全仓仅定义于 `strategy/application/audit.py`；`screener`/`backtest`/`screen_skill_generation`/`convert` 无调用 | 生成/注册可偷看未来的策略后直接回测 | screen/backtest/生成链 fail-closed；有回归测 |
| **P0-3** | KeepAlive 离开后轮询不停 | `PageHost` KeepAlive；`useLivePolling` 仅 onMounted/onUnmounted，无 onDeactivated | 盘面→账本→数据连切；观察后台仍 8s tick | deactivate 停表 / activate 重启；补测 |

> **鉴权说明（原候选 P0，本轮定为 P1-SEC）**：`has_browser_session` 在非 `production` 恒真——桌面默认可接受，但对网暴露时危险；见 P1-SEC。

### 2.2 P1 — 应排期

| ID | 标题 | 证据摘要 | 建议 |
|---|---|---|---|
| **P1-1** | `skill_watch` 强制 LLM，与「可确定性监测」配置不一致 | `jobs/skill_watch.py` 无 provider 即 JobError；runner 仅 `watch_use_ai` 才需 AI | 对齐配置：无 AI 时 MCP-only |
| **P1-2** | 竞价 `pending` 不阻断纸面候选 | `auction_confirm`→`pending`；`is_auction_abandoned` 不认 pending | 竞价窗 pending fail-closed |
| **P1-3** | `intel_fetch` 部分失败仍 `success` | `_run_call_list` 累计 failed；`run_job` 不看 stats.failed | failed>0 → failed/degraded |
| **P1-4** | Pulse 按策略 N+1 `getScreenHistory` | `usePulseHome.loadScreenTables` | 聚合 API 或限流扇出 |
| **P1-5** | 助手 MCP 扫池参数无上限 | `system_toolbus_mcp` 透传 schema；对比 builtin 有 limit | 对 screener/ladder 等裁 limit/codes |
| **P1-6** | 关 `market_gate` 段 = 双路径 fail-open | `_resolve_market_gate` 返回 None → `_apply_market_gate` 放行 | UI 强提示；默认勿静默关 |
| **P1-7** | Python/转换策略缺少公式级 entry_timing 硬拦 | formula 有 `_audit_entry_timing`；python/convert 仅枚举 | 对齐审计或生成链强制 guard |
| **P1-8** | intel 旁路在 ops.db 建 `mcp_quota` | `intel/infrastructure/quota.py` | DDL 收归 OpsStore |
| **P1-9** | SSE 长持 SQLite 连接 | `ai/api/assistant.py` stream_events | 短查+释放或改推送模型 |
| **P1-SEC** | 非 production 写鉴权恒真 | `main.has_browser_session` | 对网绑定强制 auth；文档标明威胁模型 |
| **P1-10** | Dashboard 前端自算浮盈/市值 | `useDashboardLive` | 优先后端字段；标注「展示估算」 |

### 2.3 P2 — 债项 / 契约脆弱点

| ID | 标题 | 备注 |
|---|---|---|
| **P2-1** | 17 个文件 >600 行 | 优先 `skills.py`(719)、`AssistantHost.vue`(652)、market/strategy API router |
| **P2-2** | api/application 直掏本域 infrastructure | intel/ai router 偏厚 |
| **P2-3** | `strategy_monitor` 的 skipped 记 success | 仅 notify/intel_fetch/skill_watch 升格 skipped |
| **P2-4** | `_next_trade_date` 只跳周末 | 长假预案错位 |
| **P2-5** | 竞价词 `abandon` vs `abandoned` 双套 | 漏滤风险 |
| **P2-6** | role_history 写失败静默 | 演进统计缺口 |
| **P2-7** | CI 无 `bun run build`；e2e 窄且多 mock | 发版盲区 |
| **P2-8** | 助手靠 prompt 禁造数，无服务端硬拦口播数字 | 策略层空洞 |
| **P2-9** | 部分列表页无 `page-scroll`、靠表体内滚 | 空态时易文档滚动 |

### 2.4 本轮确认相对健康

| 项 | 证据 |
|---|---|
| 跨域深掏兄弟 infrastructure | 未命中；lint-imports 9/9 |
| domain 依赖 FastAPI | 合同 KEPT |
| market 写 palace / 跨库 FK / 路由 CREATE TABLE | 未命中 |
| 无悟道：intel_fetch / skill_watch MCP / call_mcp_tool / 纸面闸门 / brief | 软跳过或空态（另见 P1-1 LLM） |
| 回测引擎 entry_timing 成交偏移 | next_open/next_dip 大体正确 |
| 前端复盘页未发现自造胜率 | 展示后端字段 |
| `quant_router` 薄聚合 | ~141 行，未堆业务公式 |

---

## 3. 修复路线图（建议批次，仍须用户点名再改代码）

### Batch A — 正确性闸门（P0-1, P0-2, P1-2）

1. `merge_ai_orders_with_gates`：所有买入动作统一 stance + 竞价拦截  
2. screen/backtest/生成链挂 `guard_strategy`（至少 error 级 fail-closed）  
3. 竞价 `pending` → 不可进 openable picks  

**验收：** 新增/更新 pytest；手动纸面 auto 场景。

### Batch B — 性能与体验（P0-3, P1-4, P1-5）

1. `useLivePolling` / DataQuery 定时器对接 KeepAlive  
2. Pulse 选股历史聚合  
3. 助手 MCP 扫池参数裁剪  

**验收：** 前端测 + 网络面板目视。

### Batch C — 运维语义（P1-1, P1-3, P2-3, P1-8）

1. skill_watch LLM 可选  
2. intel_fetch / monitor skipped·partial 状态  
3. mcp_quota 收归 ops  

**验收：** Job 列表状态与企微/告警预期一致。

### Batch D — 债项收敛（P2-1 等）

按触达拆巨石；禁止在 719 行 `skills.py` / 652 行 `AssistantHost.vue` 上继续堆功能。

---

## 4. 缺陷状态跟踪模板

| ID | 状态 | 负责人 | PR | 关闭证据 |
|---|---|---|---|---|
| P0-1 | fixed | | | `tests/ops/test_merge_ai_gates_add_buy_dip.py` |
| P0-2 | fixed | | | `tests/strategy/test_guard_hot_path.py`；screen/backtest/convert 挂 guard |
| P0-3 | fixed* | | | `useLivePolling` 已修；DataQuery 等漏网见 [R2](./2026-08-system-wide-audit-r2.md) |
| P1-1 | fixed | | | `tests/ops/test_skill_watch_provider_optional.py` |
| P1-2 | fixed | | | `test_paper_eligibility` pending/abandon |
| P1-3 | fixed | | | `tests/ops/test_intel_fetch_partial_failed.py` |
| P1-4 | fixed | | | `GET /api/screen/history/batch` + Pulse 消费 |
| P1-5 | fixed | | | `tests/ai/test_clamp_mcp_arguments.py` |
| P1-6 | fixed | | | `tests/ops/test_market_gate_disabled_fail_closed.py` |
| P1-7 | fixed | | | 同 P0-2：转换/Python Skill 草稿审计 |
| P1-8 | fixed | | | `mcp_quota` DDL 写入 ops `store_schema` |
| P1-9 | fixed | | | SSE `stream_events` 短开短关 |
| P1-10 | fixed | | | Dashboard 列标注展示估算 |
| P1-SEC | wontfix | | | 桌面非 production 写鉴权恒真属威胁模型；对网须 `production` |
| P2-* | open | | | 债项，本轮未拆巨石 |

状态枚举：`open` / `in_progress` / `fixed` / `wontfix`（须写威胁模型理由）。

---

## 5. 审计元数据

| 项 | 值 |
|---|---|
| lint-imports | R1：9/9；**R2 复审：8/9**（见 R2） |
| >600 行文件（src+frontend/src+部分 tests） | R1 记 17；R2 复计 **10** |
| 并行审计代理 | 架构 / 业务 / 性能前端 |
| 相关既有笔记 | `docs/research/2026-08-wudao-mcp-utilization-assessment.md` |
| **复审** | [R2](./2026-08-system-wide-audit-r2.md) · [R3](./2026-08-system-wide-audit-r3.md)（2026-08-07） |

---

## 6. 下一步（默认不自动开工；复审后见 R2 Batch E/F/G）

用户指定批次后按 Batch 实施；未指定时本文件仅作台账与方案。  
若只修一件：**优先 P0-1（纸面门闩）**，因其可直接导致错误开仓。
