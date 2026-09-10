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
- `WinRateView.vue`：胜率，**两层**。顶栏 `PageToolbar` 给全局读数（综合胜率/样本数/T+5 均收益，由已加载行汇总、不另发请求），口径全文进 ⓘ；`PageTabs` = 「综合对比 + 每个战法」（badge 是 T+5 样本数），分周期粒度选择器放 tabs `trailing`，两层共用。
  - **综合层**（默认）：`components/WinRateCompareTable.vue` 横向比各战法——胜率单元格采用现代化双层量化指示（大号数值 + 进度条 + 样本分子分母刻度），最佳持有期采用精美决策胶囊（`T+N` 药丸 + 胜率 + 均收益），行尾配下钻指引动效（`→`），整行可点进详情。下方是 `components/WinRatePeriodTable.vue` 的 `matrix` 形态（周期 × 战法），以结构化微单元格呈现胜率与盈亏热力。
  - **单战法层**：`components/WinRateStrategyPanel.vue`——顶部**一行结论**（T+N 胜率大数字 + 置信度徽章 + 四项口径注脚 + 推导公式）；三张洞察卡（最佳样本 / 最差样本 / 最佳持有期）；左侧各持有期表现（最佳档行底微染）与右侧样本明细（状态 Tag、等宽涨跌染色）；下方为 `WinRatePeriodTable` 的 `single` 形态。样本按 tag 懒加载并缓存，「刷新」清缓存。
  - 战法名一律 `strategyShortLabel`，slug 只留在 row-key、tab name 与调试 tooltip；分周期与主表**同源**（精选候选 T+5 按选出日聚合），旧版读手工 `reviews`、线上 0 行，那张表永远空着
- `ReviewCenterView.vue`：候选验证列含 T+1/3/5/10/20/60；「精选短线兑现」标题与胜率卡片已删（压成 tabs 尾部行内读数），「当初否决、事后大涨」保留但压成与列表同行的 kicker

### 胜率屏的装饰禁令（2026-09 重做，用户反馈「浓浓 AI 味各种线条」）

重做前这一屏有 **7 条纯装饰线**与 3 个 emoji，垂直空间被它们吃掉，两张真正要读的表被挤出视口（用户原话「无法全部展示」）。逐条清掉了：

| 删掉的东西 | 位置 | 为什么它是装饰 |
|---|---|---|
| 3px 渐变顶条 ×2 | `.wr-hero::before`、`.period-studio::before` | 不承载任何状态，纯色块 |
| 卡片顶部色条 ×3 | `.wr-card--best/worst/horizon::before` | 卡内数字已经是涨跌色，色条是第二遍说同一件事 |
| 胜率进度条 | `.wr-hero__meter-*` | 数字已经写了 50.0%，条形不增加信息 |
| 表格内每行进度条 | `.wr-mini-meter` | 同上 ×6 行 |
| 最佳行左侧色条 | `:deep(.is-best-horizon td:first-child)::before` | 行内已有「最佳」文字标签，改成行底 5% 微染 |
| 公式条的灰底 + 蓝左边框 | `.wr-formula-bar` | 给一句说明文字配了两条装饰线 |
| emoji 图标 | `🚀` `🛡️` `⭐` `📈` | 金融工作台不用 emoji；标签文字已经说清是什么 |
| 柱子渐变 + 彩色投影 | `.chart-bar--up/down` | 柱子表达「涨跌 + 幅度」，渐变与投影都不承载信息 |
| 卡片 hover 抬起 | `.wr-card:hover { transform }` | 卡片不可点，抬起是假的可交互暗示 |
| 四处 `box-shadow` | hero / card / block / studio | 违反 D3：业务卡片不挂阴影 |
| 三处 `rgba(0,0,0,.0x)` 阴影 | `.filter-pill.is-active` 等 | 写死的黑在 night/ink 两档完全不可见，选中态在深色下等于没反馈；改用边框 |

同时把两处「KPI 卡片」压成注脚行（`.wr-summary__facts`、`.period-studio__kpi-bar`）：计算口径 / 结算进分母 / 盈利样本 / 窗口观察中这四项是**胜率的注脚**，不是四个独立 KPI，各带一圈边框只会吃掉一整行高度。参见 business-ui 的那条：不要加只重复表格计数的 KPI 卡。

**改这一屏之前先问一遍**：要加的这条线/色块/图标，能不能被「它旁边的数字」替代？能的话就不要加。层次交给排版（字号、字重、颜色、留白），不交给边框与色条。

验证口径：真机 Chromium 1568×900 + 代表性 fixture（含长中文名、观察中样本、负均收益 + 正胜率），明暗两档取 computed 值核对——全部走令牌，零硬编码色值，所以两档同时成立。
