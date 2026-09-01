# review

本限界上下文的页面。

- `ReviewCenterView.vue`：绩效中心（侧栏「绩效」）；**无页头**（PageHeader 已下线），页面身份交给侧栏；`PageTabs` 分区，刷新 / 精选短线 T+1·T+3·T+5 行内胜率 / 口径 ⓘ 全在 tabs `trailing`，预案条数走 Tab 徽标；各分区 Colada 按当前 tab `enabled`，不预拉其它分区；候选验证表仅渲染前 40 条并在表下注明总数；预案空态可直接「写预案」（`RecordDialog kind="plan"`）
- **2026-08 实盘项下线**：「资金曲线」「持仓归因」两个 Tab 连同 `useEquityQuery` / `useRoundTripsQuery` / `RoundTripsPanel.vue` 一并删除——后端 `/api/review/equity|trips|positions|drift` 读真实成交与持仓，已随账本下线整体移除。默认 Tab 为「候选验证」
- `ReviewsView.vue`：复盘样本列表（`/reviews/records`）；无页头，「补记一笔」与口径 ⓘ 并进 `BasicTable` 自带工具行（`#toolbarButtons`），总数看分页；类型 tag 三色 plain 区分候选/预案/成交（成交仅历史存量，新写入只允许候选/预案）；**侧栏暂不挂入口**（「手记」已撤），深链/胜率「去补复盘」仍可用；后续 AI 复盘可挂靠绩效 Tab 或独立入口
- `InsightsView.vue`：管家式数据体检（hero 无标题栏，状态字并进标题行；左大体检分环 + 右主 CTA；一键扫描=仓内+本地扩展，深度扫描=另探数据源连通；一键修复 · 待检分组清单 · 自动复检）+「信号重叠」Tab（Sheet 无标题：天数、刷新、口径 ⓘ 全在分区行；战法 A/B 列落中文短名）。idle 印章环为虚线「待检」，状态文案中性灰、仅待处理用告警色。逻辑在 `composables/useHealthCheckup.ts`；后端目录见 `sentinel` + `sentinel_extended`。
- `composables/useHealthCheckup.ts`：体检状态机（只留反应式状态与编排）；分数与 `repair_plan` 以后端为准；门禁认 `blocked`。等待 `/market/health` 时有秒级心跳进度；取消扫描会 `AbortSignal` 中断请求，`scanToken`/`repairToken` 让晚到的响应自动作废——**改这里前先确认取消链路仍完整**。**自动修复**只认 `bootstrap/sync/sync_factors/repair_turnover`（判定走 `isAutoRepairAction`）：由本 composable 直接 `startMarketBootstrap`/`repairMarketTurnover`（**不**再打开不可关的 bootstrap 模态框）；修复中可「停止等待」；instruments 长时间无进展会前端超时。`job_sync_stale` 等人工项走「去处理」。线路/依赖/磁盘等只给人工跳转，不装假「修复」按钮。
- `composables/healthCheckupLogic.ts`：从 composable 提纯的无状态逻辑（对齐 `market/composables/pulseHomeLogic.ts` 的形状），单测在 `healthCheckupLogic.test.ts`。含分数/等级回退（`resolveSealScore`/`resolveSealGrade`）、落点判定（`phaseForReport`/`planIsActionable`）、目录裁剪与回放顺序（`effectiveCatalog`：空仓阻断且核心检查没往下跑时不摆核心项 / `revealSequence`）、标题与副标题文案（`checkupHeadline`/`checkupSubtitle`）、进度映射（`scanHeartbeatSnap`/`revealProgressSnap`/`softBootstrapPercent`/`bootstrapProgressDetail`/`bootstrapDoneMessage`）与 instruments 超时判定（`isInstrumentsStalled` + `INSTRUMENTS_STALL_MESSAGE`）。
- `composables/healthCheckupModel.ts`：`autoFixable` / `isAutoRepairAction`；清单行与一键计划只收真实可执行动作；`normalizeHealthReport` 始终按 AUTO 动作重建 `repair_plan`，避免旧后端把 Job 时效标成 `sync` 误触发全量 bootstrap。
- `components/HealthCheckList.vue`：idle 待检按 `group` 分组成紧凑清单（组名小标题 + check-row）；结果按阻断→提示分组；一键修复/勾选只认 `autoFixable`（人工项走「去处理」）。
- `WinRateView.vue`：胜率；顶栏为 `PageToolbar`（读数「综合胜率/样本数/T+5 均收益」由主表已加载行汇总、不另发请求；口径全文进 ⓘ）；主表所在 Sheet 无标题（下面就是胜率表）；战法列/趋势表头/check-tag 一律 `strategyShortLabel`，slug 只留在 row-key 与调试 tooltip；主表为精选候选 T+1/T+3/T+5（T+5 为主），无候选回退手工复盘；趋势区仍为复盘按月/周，粒度切换在该 Sheet actions 内
- `ReviewCenterView.vue`：候选验证列含 T+1/3/5/10/20/60；「精选短线兑现」标题与胜率卡片已删（压成 tabs 尾部行内读数），「当初否决、事后大涨」保留但压成与列表同行的 kicker
