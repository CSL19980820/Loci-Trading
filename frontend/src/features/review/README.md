# review

本限界上下文的页面。

- `ReviewCenterView.vue`：绩效中心（侧栏「绩效」）；`PageHeader` + `PageTabs` 分区（刷新在 tabs `trailing`，两区通用）；各分区 Colada 按当前 tab `enabled`，不预拉其它分区；候选验证表仅渲染前 40 条并在表下注明总数；预案空态可直接「写预案」（`RecordDialog kind="plan"`）
- **2026-08 实盘项下线**：「资金曲线」「持仓归因」两个 Tab 连同 `useEquityQuery` / `useRoundTripsQuery` / `RoundTripsPanel.vue` 一并删除——后端 `/api/review/equity|trips|positions|drift` 读真实成交与持仓，已随账本下线整体移除。默认 Tab 为「候选验证」
- `ReviewsView.vue`：复盘样本列表（`/reviews/records`）；`PageHeader` 计数 + 新增出口；类型 tag 三色 plain 区分候选/预案/成交（成交仅历史存量，新写入只允许候选/预案）；**侧栏暂不挂入口**（「手记」已撤），深链/胜率「去补复盘」仍可用；后续 AI 复盘可挂靠绩效 Tab 或独立入口
- `InsightsView.vue`：管家式数据体检（左大体检分环 + 右主 CTA；一键扫描=仓内+本地扩展，深度扫描=另探数据源连通；一键修复 · 待检分组清单 · 自动复检）+「信号重叠」Tab。idle 印章环为虚线「待检」，状态文案中性灰、仅待处理用告警色。逻辑在 `composables/useHealthCheckup.ts`；后端目录见 `sentinel` + `sentinel_extended`。
- `composables/useHealthCheckup.ts`：体检状态机；分数与 `repair_plan` 以后端为准；门禁认 `blocked`。等待 `/market/health` 时有秒级心跳进度；取消扫描会 `AbortSignal` 中断请求。**自动修复**只认 `bootstrap/sync/sync_factors/repair_turnover`：由本 composable 直接 `startMarketBootstrap`/`repairMarketTurnover`（**不**再打开不可关的 bootstrap 模态框）；修复中可「停止等待」；instruments 长时间无进展会前端超时。`job_sync_stale` 等人工项走「去处理」。线路/依赖/磁盘等只给人工跳转，不装假「修复」按钮。
- `composables/healthCheckupModel.ts`：`autoFixable` / `isAutoRepairAction`；清单行与一键计划只收真实可执行动作；`normalizeHealthReport` 始终按 AUTO 动作重建 `repair_plan`，避免旧后端把 Job 时效标成 `sync` 误触发全量 bootstrap。
- `components/HealthCheckList.vue`：idle 待检按 `group` 分组成紧凑清单（组名小标题 + check-row）；结果按阻断→提示分组；一键修复/勾选只认 `autoFixable`（人工项走「去处理」）。
- `WinRateView.vue`：胜率；`PageHeader` 读数（综合胜率/样本数/T+5 均收益）由主表已加载行汇总、不另发请求；主表为精选候选 T+1/T+3/T+5（T+5 为主），无候选回退手工复盘；趋势区仍为复盘按月/周，粒度切换在该 Sheet actions 内
- `ReviewCenterView.vue`：候选验证列含 T+1/3/5/10/20/60，并展示精选短线胜率卡片
