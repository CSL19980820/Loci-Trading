# 前端 UI 体检报告 · 2026-08

> 只读盘点，未修改任何业务代码。所有条目均来自 `grep` / 读文件的真实结果，标注 `文件路径:行号`。
> 判据：[`frontend/AGENTS.md`](../AGENTS.md)（§3.3.1 组件封装、§3.7 模板与 UI、§3.7.1 视口与内容高度、§4 反模式表）。
> 扫描脚本与原始输出：`.local/audit/*.ps1` / `.local/audit/*.txt`（PowerShell 7）。

---

## 1. 页面清单（`features/**/**View.vue` 路由级页面，共 23 个）

| # | 路径 | 行数 | `.page-fill` | `.page-scroll` | 顶层结构一句话 |
|---|---|---:|:---:|:---:|---|
| 1 | `frontend/src/features/ledger/LoginView.vue` | 595 | ❌ | ❌ | `main.login-shell`（`min-height:100vh`，`frontend/src/features/ledger/LoginView.vue:296`）左 hero + 右 `el-form` 登录面板；§3.7.1 明列的非壳内页例外 |
| 2 | `frontend/src/features/review/InsightsView.vue` | 563 | ✅ | ✅×2 | `div.page-fill.insights-page`（`:194`）→ `el-alert` + `PageTabs` + `page-scroll`/`page-pane` 分区 |
| 3 | `frontend/src/features/ledger/PoolView.vue` | 559 | ✅ | ❌ | `div.page-fill`（`:341`）→ `PageHeader`+`HeaderStat` + 筛选条 + `el-table`×2，滚动下沉到表体 |
| 4 | `frontend/src/features/auth/AccountView.vue` | 537 | ✅ | ✅ | `div.account-page.page-fill`（`:190`）→ `div.account-container.page-scroll`（`:191`）→ header + `el-tabs`（资料/安全/配额/API Key） |
| 5 | `frontend/src/features/community/StrategyDetailView.vue` | 530 | ✅ | ✅ | `div.page-fill`（`:213`）→ `PageHeader`+`HeaderStat` + `Sheet`×6 + `el-table`×6 |
| 6 | `frontend/src/features/strategy/ScreenHistoryView.vue` | 530 | ✅ | ❌ | `div.page-fill.screen-desk`（`:395`）→ `header.screen-desk__bar` + `.screen-desk__body`（左 rail + 右 main）；样式外置 `ScreenHistoryView.css`（`:519`） |
| 7 | `frontend/src/features/market/DataQueryView.vue` | 493 | ✅ | ❌ | `div.page-fill.data-desk`（`:291`）→ `PageHeader` + `el-alert` + `el-table`；靠 `height:100%;overflow:hidden` 自管（`:403-405`） |
| 8 | `frontend/src/features/ledger/ArchiveView.vue` | 415 | ✅ | ✅ | `div.page-fill.stock-workbench`（`:292`）→ `header.sw-top` + `Sheet`（个股档案工作台） |
| 9 | `frontend/src/features/market/PeekView.vue` | 391 | ❌ | ❌ | `main.peek`（`:172`）ghost/expanded 双态探头窗；§3.7.1 例外，但内含 `min-height:100dvh`×2（`:248`/`:343`） |
| 10 | `frontend/src/features/strategy/StrategyConverterView.vue` | 375 | ✅ | ✅ | `div.page-fill.workbench-page`（`:117`）→ `header.workbench-bar` + `PageTabs`；样式外置 `StrategyConverterView.css`（`:375`） |
| 11 | `frontend/src/features/community/MyCommunityView.vue` | 375 | ✅ | ✅ | `div.page-fill`（`:157`）→ `PageHeader` + `PageTabs` + `Sheet`×3；「我发布的」用裸 `<table>`（`:193`） |
| 12 | `frontend/src/features/ops/OpsView.vue` | 371 | ✅ | ❌ | `div.page-fill.ops-desk`（`:213`）→ `header.ops-hero` + `el-alert` + `PageTabs` + `page-pane` |
| 13 | `frontend/src/features/review/WinRateView.vue` | 355 | ✅ | ✅ | `div.page-fill`（`:208`）→ `PageHeader`+`HeaderStat` + `Sheet`×2 |
| 14 | `frontend/src/features/strategy/QuantView.vue` | 340 | ✅ | ✅ | `div.page-fill`（`:208`）→ `PageBusy` + `el-alert` + `PageTabs` + `page-pane`×8 |
| 15 | `frontend/src/features/community/LeaderboardView.vue` | 314 | ✅ | ✅ | `div.page-fill`（`:81`）→ `PageHeader`+`HeaderStat` + `.podium`（RouterLink 卡）+ `Sheet` > 裸 `<table class="board">`（`:145`） |
| 16 | `frontend/src/features/market/PulseView.vue` | 303 | ✅ | ✅×2 | `div.page-fill.pulse-home`（`:88`）→ 工具条 + `page-scroll`/`page-pane`；全站唯一使用 Tailwind 的页 |
| 17 | `frontend/src/features/review/ReviewCenterView.vue` | 269 | ✅ | ✅ | `div.page-fill`（`:137`）→ `el-alert` + `PageHeader` + `PageTabs`（`:145`，Tabs 在 scroll 外，合规）+ `.page-scroll`（`:151`）> `Sheet`×2 |
| 18 | `frontend/src/features/community/SquareView.vue` | 229 | ✅ | ✅ | `div.page-fill`（`:63`）→ `PageHeader` + `filter-bar` + `.tagline`（裸 button chips `:113`）+ `Sheet` |
| 19 | `frontend/src/features/admin/AdminView.vue` | 225 | ✅ | ❌ | `div.admin-view.page-fill`（`:26`）→ `el-empty` 权限拦截（`:29`）\| `.admin-layout` grid `13rem+1fr`（`:136-142`）：左侧裸 `<button>` rail + 右侧动态 Tab 组件 |
| 20 | `frontend/src/features/live/LiveBoardView.vue` | 222 | ✅ | ❌ | `div.page-fill.live-board-view[data-appearance=ink]`（`:47`）→ `LiveTopBar` + 三段固定高度栅格（`58%`/`120px`/`min-height:160px`，`:163-196`） |
| 21 | `frontend/src/features/review/ReviewsView.vue` | 151 | ✅ | ❌ | `div.page-fill`（`:62`）→ `PageHeader` + `PageContainer`（`:72`，`#topExpand` Sparkline + `#main` BasicTable）；滚动由 `PageContainer` 的 `overflow:hidden/auto` 兜（`shared/components/layout/PageContainer.vue:62`/`:70`） |
| 22 | `frontend/src/features/community/UserProfileView.vue` | 126 | ✅ | ✅ | `div.page-fill`（`:67`）→ `PageHeader`+`HeaderStat`×3 + `Sheet` |
| 23 | `frontend/src/features/ledger/AuthUnavailableView.vue` | 68 | ❌ | ❌ | `main.auth-unavailable`（`:19`，`min-height:100dvh` + `place-items:center`，`:32-36`）；非壳内页例外 |

### 1.1 结论

- **缺 `.page-fill` 的 3 个页面全部属于 §3.7.1 白名单例外**（`LoginView` / `PeekView` / `AuthUnavailableView`），无违规。
- **有 `.page-fill` 但无 `.page-scroll` 的 7 个页面**，逐一核对后均有替代内滚容器，无文档级滚动风险：
  - `PoolView.vue` → `el-table`×2 表体自滚；`ReviewsView.vue` → `PageContainer`（`PageContainer.vue:62`）；
  - `DataQueryView.vue:403-405` / `AdminView.vue:141` / `OpsView.vue:337-341` → 自带 `overflow:hidden` + `min-height:0`；
  - `ScreenHistoryView.vue` 样式全在 `frontend/src/features/strategy/ScreenHistoryView.css`（外置，`ScreenHistoryView.vue:519`）；
  - `LiveBoardView.vue:163-196` → 百分比/px 硬高度切分，见 §4。
- **超 600 行阈值**：无（最长 `LoginView.vue` 595 行），但 4 个页面已在 530-595 区间贴线，见 Top 20。

---

## 2. 裸控件违规

排除 §3.3.1 允许的例外：`type="file"`、`a.skip-link`、纯路由 `RouterLink`、ECharts 容器、Monaco 编辑区。

### 2.1 裸 `<button>` — 7 处文件 / 11 个实例（**全部违规**）

| # | 位置 | 现状 | 该换成 |
|---|---|---|---|
| 1 | `frontend/src/features/admin/AdminView.vue:48` | `<button class="rail-item">` 平台总览 | 整个 `nav.rail-nav` 换 `el-menu` + `el-menu-item`（带 `el-icon`），或 `el-radio-group`+`el-radio-button` 竖排 |
| 2 | `frontend/src/features/admin/AdminView.vue:57` | `<button class="rail-item">` 用户管理 | 同上（同一 rail 的第 2 项） |
| 3 | `frontend/src/features/admin/AdminView.vue:66` | `<button class="rail-item">` 配额管理 | 同上 |
| 4 | `frontend/src/features/admin/AdminView.vue:75` | `<button class="rail-item">` 审计日志 | 同上 |
| 5 | `frontend/src/features/admin/AdminView.vue:84` | `<button class="rail-item">` 全站公告 | 同上 |
| 6 | `frontend/src/features/auth/UserAvatarMenu.vue:59` | `<button type="button" class="user-profile-btn">` 作 `el-dropdown` 触发器 | `el-button text`（或 `el-dropdown` 默认插槽内放 `el-button`），保留 `--collapsed` 变体 |
| 7 | `frontend/src/features/community/SquareView.vue:113` | `<button class="tagchip" v-for>` 标签筛选芯片 | `el-check-tag`（单选/多选语义天然匹配），或 `el-radio-group`+`el-radio-button size="small"` |
| 8 | `frontend/src/features/ops/components/JobRecentRunsPanel.vue:195` | `<button class="job-runs-panel__err">` 打开失败全文 | `el-button link size="small"`（表格单元格内的次级动作） |
| 9 | `frontend/src/features/ops/components/SettingsPanel.vue:40` | `<button class="settings-panel__pair--link">` 回执可点项 | `el-button link`（或 `el-link`），保留 `:title="pair.hint"` |
| 10 | `frontend/src/features/ops/components/SettingsRail.vue:119` | `<button class="settings-rail__anchor" v-for>` 二级锚点 | `el-button link size="small"` —— **同文件 `:79` 的一级项已经用 `el-button`**，一二级不一致 |
| 11 | `frontend/src/shared/components/layout/NotificationCenter.vue:102` | `<button class="notify-item" v-for>` 通知条目 | `el-button text` 撑满宽度，或 `el-card shadow="hover"` + `@click`；同文件 `:125` 的公告项已经用 `<article>`，两 Tab 结构不对称 |

**附带违规（EP class 冒充）**：

| 位置 | 现状 | 该换成 |
|---|---|---|
| `frontend/src/features/admin/AdminView.vue:36` | `<RouterLink to="/" class="el-button el-button--primary">返回首页</RouterLink>` | `<el-button type="primary" @click="router.push('/')">`；手抄 EP class 名会在 EP 升级时静默失效 |
| `frontend/src/shared/components/layout/AppSidebar.vue:166` | `<RouterLink class="ops-link el-button tool-row">` 设置入口 | §3.3.1 例外 2 只放行「纯路由导航项」，**工具操作仍用 `el-button`**；建议 `<el-button>` 包 `RouterLink` 或改 `@click` 路由跳转 |

### 2.2 裸 `<table>` — 2 处（**全部违规**）

| 位置 | 现状 | 该换成 |
|---|---|---|
| `frontend/src/features/community/LeaderboardView.vue:145-188` | `<table class="board">`，9 列（名次/策略/作者/score/夏普/年化/最大回撤/上架天数/样本外折扣），外层手写 `.table-scroll` | `el-table` + `el-table-column`；`.num` 列用 `align="right"`，涨跌色用现有 `tone-up/tone-down` 通过 `#default` 插槽；列定义可抽 `leaderboardColumns.ts`（§3.3.1「列过多」条） |
| `frontend/src/features/community/MyCommunityView.vue:193-223` | `<table class="rows">`，7 列（标题/状态/可见性/版本/收藏/克隆/操作），操作列**已经**是 `el-button link`（`:216`/`:219`） | `el-table` + `el-table-column`；操作列已是 EP，外壳换掉即可，改动量最小 |

> 两处都已手写 `.table-scroll` 包裹（`LeaderboardView.vue:144` / `MyCommunityView.vue:192`），换 `el-table` 后可直接删掉这层壳并由表体接管滚动。

### 2.3 裸 `<input>` / `<select>` / `<textarea>` — 0 处违规

- `<select>`、`<textarea>`：全仓 **0 处**（grep `<(select|textarea)\b` 无匹配）。
- `<input>` 共 4 处，**全部是 `type="file"`，属 §3.3.1 例外 1，且都写了 why 注释**：
  - `frontend/src/features/ai/components/AssistantSenderDock.vue:409`（图片附件）
  - `frontend/src/features/marketplace/components/MarketPublishPanel.vue:46`（注释在 `:45`）
  - `frontend/src/features/strategy/components/QuantSkillsPanel.vue:235` 与 `:242`（注释在 `:234`，zip / webkitdirectory）
  - 建议（非必须）：可用 `el-upload` + `:auto-upload="false"` 包一层，注释里已提到该优化方向。

---

## 3. 表单对齐问题

全仓 `<el-form>` 共 **49 处**（`.local/audit/forms.txt`）。其中 21 处显式写 `label-width`，23 处只写 `label-position="top"`，5 处两者都没写。

### 3.1 `label-width` 取值发散：8 种值 + rem/px 混用

| 取值 | 次数 | 代表位置 |
|---|---:|---|
| `5.5rem` | 8 | `frontend/src/features/ops/components/PackTab.vue:194`、`SysAppearanceSection.vue:45`、`SysLocationSection.vue:14`、`SysNotifySection.vue:78`、`SysSyncSection.vue:20`、`frontend/src/features/strategy/components/SkillJobConfigPanel.vue:179`、`SkillStrategyConfigPanel.vue:154`、`StrategyDetailConfigPane.vue:47` |
| `80px` | 3 | `frontend/src/features/admin/components/AnnouncementEditorDialog.vue:102`、`NotifyUserDialog.vue:59`、`ResetPasswordDialog.vue:70` |
| `6rem` | 3 | `frontend/src/features/ops/components/PaperQuantPanel.vue:333`、`:361`、`:460` |
| `6.5rem` | 2 | `frontend/src/features/community/components/NewVersionDialog.vue:87`、`PublishDialog.vue:182` |
| `5rem` | 1 | `frontend/src/features/strategy/components/ScreenSelectDialog.vue:69` |
| `7rem` | 1 | `frontend/src/features/strategy/components/SkillWatchTuningPanel.vue:150` |
| `10rem` | 1 | `frontend/src/features/strategy/components/SkillWatchTuningPanel.vue:162` |
| `130px` | 1 | `frontend/src/features/admin/components/UserQuotaDialog.vue:102` |

**问题**：`80px`/`130px`（`admin` 域）与 `5rem~10rem`（其余全域）单位不统一；`80px ≈ 5rem` 但根字号一变就错位。应收敛成 2 档 token（窄 `5.5rem` / 宽 `7rem`）。

### 3.2 同一页内 `label-width` 取值不一致（**错位可见**）

| 位置 | 问题 |
|---|---|
| `frontend/src/features/strategy/components/SkillWatchTuningPanel.vue:150` = `7rem` vs `:162` = `10rem` | 同一面板上下两段表单 label 列宽差 3rem，两组开关的输入框左边缘不对齐 |
| `frontend/src/features/ops/components/PaperQuantPanel.vue:333`/`:361`/`:460` = `6rem`，但 `:478`/`:545` = `inline` 无 `label-width` | 同一页 5 个 `el-form`，3 个块级对齐 + 2 个 inline 自适应，纵向扫视断裂 |
| `frontend/src/features/strategy/components/QuantBacktestPanel.vue:90`/`:173`/`:197` 三个 `inline` 表单 | 全部无 `label-width`，label 宽度随文案长度浮动（「口径」2 字 vs 「佣金bps」5 字符），三段控件左缘全不齐 |

### 3.3 既无 `label-width` 也无 `label-position` 的表单（5 处）

- `frontend/src/features/ops/components/PaperQuantPanel.vue:478`（`<el-form inline class="mt">`）
- `frontend/src/features/ops/components/PaperQuantPanel.vue:545`（`<el-form inline>`）
- `frontend/src/features/strategy/components/QuantBacktestPanel.vue:90`（`<el-form class="bt-rail__form" inline>`）
- `frontend/src/features/strategy/components/QuantBacktestPanel.vue:173`（`<el-form inline>`）
- `frontend/src/features/strategy/components/QuantBacktestPanel.vue:197`（`<el-form v-if="showCost" inline class="bt-cost">`）

### 3.4 `label-position` 缺省导致的右对齐孤岛（8 处）

以下表单写了 `label-width` 但**没写 `label-position`**，EP 默认 `right`；而全仓主流是 `top`（23 处）或 `left`（11 处），这 8 处成了右对齐孤岛：

`AnnouncementEditorDialog.vue:102`、`NotifyUserDialog.vue:59`、`ResetPasswordDialog.vue:70`、`UserQuotaDialog.vue:102`、`ScreenSelectDialog.vue:69`、`PaperQuantPanel.vue:333`、`:361`、`:460`

### 3.5 `el-form-item` 混排裸 `div` 导致错位

| 位置 | 现状 | 影响 |
|---|---|---|
| `frontend/src/features/ops/components/JobEditorDialog.vue:281` | `<el-form>` 内直接塞 `<div class="form-grid">` 再包 `el-form-item` | 栅格由全局 `.form-grid`（`style.content.css:2-6`）接管，EP 的 `label-width` 计算被绕过 |
| `frontend/src/features/ops/components/McpTab.vue:296` | 同上 `<div class="form-grid">` | 同上 |
| `frontend/src/shared/components/dialogs/RecordDialog.vue:233` | 同上 `<div class="form-grid">`；且 `:231` 的 `<p class="form-hint">` 在 `el-form` **外** | hint 与首个 field 不共用 label 缩进 |
| `frontend/src/features/ops/components/LlmProviderDialog.vue:151-153` | `<el-form>` → `<div class="dlg-layout">` → `<div class="dlg-main">` → `<section class="sec">` 三层裸壳 | form-item 深埋，`:237`/`:262`/`:271` 的 `.field-hint` 各自缩进不同 |
| `frontend/src/features/ops/components/SysNotifySection.vue:80` | `el-form-item` 内 `<div class="wecom-row">` 手拼输入+按钮行 | 该行控件基线与相邻 form-item 不齐 |
| `frontend/src/features/admin/components/UserQuotaDialog.vue:104` | `el-form-item` 内 `<div class="quota-input-row">`，配 `:166`/`:181` 的 `<span class="quota-hint">` | hint 不是 EP 的原生位置，换行时会顶开行高 |
| `frontend/src/features/research/components/ResearchBacktestPanel.vue:544` | 用 CSS grid 直接改写 `el-form` 布局（`repeat(4,...)`），并在 `:545` 重置 `.el-form-item{margin-bottom:0}` | 绕过 EP 表单布局；`:573`/`:574` 还要两级断点补救 |
| `frontend/src/features/research/components/ResearchHypothesisPanel.vue:233` | 同上 `repeat(3,...)` + `margin-bottom:0` 重置 | 同上；`:220-222` 还把多个 `el-form-item` 挤在同一行源码里，可读性差 |
| `frontend/src/features/datasource/components/AkshareToolTable.vue:404` | `.params-form` grid `repeat(2,...)` 覆盖 `el-form` | 同上 |

### 3.6 完全自绘的表单行（未用 `el-form` / `el-form-item`）

| 位置 | 自绘结构 | 说明 |
|---|---|---|
| `frontend/src/features/admin/components/QuotaTab.vue:161` | `.batch-fields-grid` > `.field-item` > `.field-header` + `.field-controls` + `.field-hint` | **全文件零 `el-form`**。6 组字段行：`:163`/`:185`/`:207`/`:229`/`:251`/`:274`；header 行 `:164`/`:186`/`:208`/`:230`/`:252`/`:275`；控件行 `:167`/`:189`/`:211`/`:233`/`:255`/`:278`；hint `:270`/`:293`。且源码缩进已散架（`:253`/`:257`/`:270`/`:274`/`:279`/`:294`） |
| `frontend/src/features/auth/AccountView.vue:273` | `.quota-grid` > `.quota-card` > `.quota-label`/`.quota-val`/`.quota-desc` | 6 张自绘 label/value 卡：`:277`/`:283`/`:289`/`:295`/`:301`/`:309`；应为 `el-descriptions` 或 `StatCard` |
| `frontend/src/features/admin/components/OverviewTab.vue:51` | `.metrics-grid` > `.metric-card` > `.metric-label`/`.metric-value`/`.metric-hint` | 4 张自绘指标卡：`:55`/`:60`/`:65`/`:70`；`shared/components/ui/StatCard.vue:25-28` 已有同形组件 |
| `frontend/src/features/auth/AccountSecurityPane.vue:187` | `<div class="empty-hint">` | 自绘空态行，见 §4 |
| `frontend/src/features/ops/components/LlmProviderDialog.vue:237`/`:262`/`:271` | `<p class="field-hint">` | 三处 hint 三种缩进上下文 |
| `frontend/src/features/admin/components/QuotaTab.vue:270`/`:293` | `<p class="field-hint">` | 同名 class 与 `LlmProviderDialog` 的 `.field-hint` 语义冲突（两处均 `scoped`，只是命名重复） |

---

## 4. 空置留白

### 4.1 `.stat-strip` —— 不是「只有 1~2 个卡片」，而是**全站零使用的死 CSS**

| 位置 | 内容 |
|---|---|
| `frontend/src/style.layout.css:178-183` | `.stat-strip` 基准：`grid-template-columns: repeat(4, minmax(0,1fr))` + `margin-bottom: 0.9rem` |
| `frontend/src/style.layout.css:185` / `:189` / `:193` / `:197` | `.cols-3` / `.cols-4` / `.cols-5` / `.mini` 四个变体 |
| `frontend/src/style.layout.css:137` | `.page-pane .stat-strip` 间距特例 |
| `frontend/src/style.tail.css:33-37` / `:71-75` | 两级断点覆盖 |
| **`.vue` 中的使用** | **0 处**（`grep stat-strip frontend/src/**/*.vue` 无匹配） |

实际在用的统计条是 `frontend/src/features/review/ReviewCenterView.vue:157` 的 `.stat-row`，只放 3 张 `StatCard`（`:158-164`，`v-for="h in [1,3,5]"`），样式是 `flex-wrap`（`:257-260`），不会硬留空格 —— 说明全局 4 列 `.stat-strip` 已与实现完全脱节。

**同批死 CSS**（同样 0 处 `.vue` 引用）：`.pool-layout`（`style.content.css:221`）、`.pool-aside`（`:228`）、`.day-list`（`:236`）、`.day-item`（`:242`/`:256`/`:262`）、`.memory-head`（`:430`）、`.grid-2`（`style.layout.css:201`）、`.hold-plan`（`style.layout.css:208`），及其在 `style.tail.css:39-59`/`:77-79` 的断点覆盖。

### 4.2 硬编码 `min-height` 撑空（46 个文件命中，高风险 20 条）

| 位置 | 值 | 问题 |
|---|---|---|
| `frontend/src/features/market/components/MinuteSessionDialog.vue:254` | `420px` | 弹窗外层硬撑；`:283` 内层再 `360px`，双层叠加，无数据时近 800px 空白 |
| `frontend/src/features/datasource/components/AkshareBatchProbeDialog.vue:99` | `360px` | `.batch-table` 空表也占 360px |
| `frontend/src/features/admin/components/TopLlmChart.vue:130` | `260px` | 配 `align-items:center;justify-content:center`（`:131-133`），零数据时 260px 纯空白居中 |
| `frontend/src/features/live/LiveBoardView.vue:164` | `260px` | 配 `height:58%`（`:163`），双重定高 |
| `frontend/src/features/admin/components/AnnouncementEditorDialog.vue:174` | `180px` | 预览框空内容仍 180px（`:175` 有 `max-height:320px` 但无下限收缩） |
| `frontend/src/features/ops/components/JobRunsDialog.vue:190` | `16rem` | 外层已有 `height: min(68vh,36rem)`（`:189`），下限冗余 |
| `frontend/src/features/ai/components/AssistantSettingsDialog.vue:283` | `16rem` | 设置项少时空半屏 |
| `frontend/src/features/ops/components/PaperRoleTimelineChart.vue:198` | `14rem` | 同时 `height:16rem`（`:199`），`:204` 再写一次 `14rem`，三重定高 |
| `frontend/src/features/ai/components/AssistantKlineCard.vue:66` | `14rem` | 同行还有 `height:16rem`；`:72` 重复 `14rem` |
| `frontend/src/features/ops/components/JobRecentRunsPanel.vue:216` | `14rem` | 无执行历史时 14rem 空表 |
| `frontend/src/features/strategy/components/QuantBacktestPanel.vue:274` | `14rem` | 未跑回测时空 14rem（`:230-232` 已有 EmptyState，两者叠加） |
| `frontend/src/features/review/InsightsView.vue:402` | `12rem` | |
| `frontend/src/features/ops/OpsView.vue:338` | `12rem` | |
| `frontend/src/features/datasource/components/AkshareToolTable.vue:390` | `12rem` | |
| `frontend/src/features/marketplace/components/MarketPanel.vue:334` | `12rem` | |
| `frontend/src/features/ops/components/LlmProviderCard.vue:153` | `10.5rem` | 卡片定高；只配 1 家供应商时配合 `LlmTab.vue:228` 的 3 列栅格 = 2 个 10.5rem 空位 |
| `frontend/src/features/ops/components/McpTab.vue:341` | `8rem` | `.mcp-loading` 加载态定高 |
| `frontend/src/features/strategy/components/ScreenWorkbenchDock.vue:177` | `8rem` | 同时 `height:100%`（`:178`），两者互相打架 |
| `frontend/src/features/strategy/components/SkillDetailDialog.vue:362` | `8rem` | |
| `frontend/src/features/market/PeekView.vue:248` / `:343` | `100dvh` ×2 | 探头窗两态各写一次满屏下限 |

### 4.3 `padding` 超过 2rem

| 位置 | 值 | 问题 |
|---|---|---|
| `frontend/src/features/admin/AdminView.vue:121` | `3rem 1rem` | `.admin-forbidden` 同时 `height:100%`（`:120`），非管理员进来 = 整屏只有一个居中 `el-empty` + 3rem 内边距 |
| `frontend/src/features/ledger/LoginView.vue:463` | `3rem 2.5rem` | `.login-hero`；非壳内页，可接受但偏大 |
| `frontend/src/features/ledger/LoginView.vue:502` | `2.5rem` | `.login-panel` |
| `frontend/src/features/auth/AccountView.vue:395` | `2rem 1.5rem` | `.account-container` 同时 `max-width:900px`（`:392`），宽屏下两侧大片纸色空白 + 顶部 2rem，首屏可见内容被压到很低 |
| `frontend/src/features/ledger/LoginView.vue:586` / `:592` | `2rem 1.5rem` | 窄屏断点 |

### 4.4 `height: 100%` 空容器 / 冗余定高

| 位置 | 问题 |
|---|---|
| `frontend/src/features/admin/AdminView.vue:120` | `.admin-forbidden{height:100%}` 内只有一个 `el-empty`（`:29-37`） |
| `frontend/src/features/datasource/components/AkshareToolTable.vue:365` / `:378` / `:399` | 三层 `height:100%` 嵌套叠加 |
| `frontend/src/features/datasource/DataSourcePanel.vue:297` | `flex:1 1 auto`（`:296`）与 `height:100%` 同时写，后者冗余 |
| `frontend/src/features/strategy/components/ScreenWorkbenchDock.vue:178` | `height:100%` + `min-height:8rem`（`:177`）冲突 |
| `frontend/src/features/live/components/RankColumn.vue:201` | `height:100%` + `min-height:80px`（`:202`）；`SignalStream.vue:258`+`:259`、`HeatStrip.vue:80`/`:119`、`IndexMiniChart.vue:150` 同型 |
| `frontend/src/features/ai/components/AssistantKlineCard.vue:71` | `height:100%` + `min-height:14rem` |

### 4.5 grid 列数写死但内容不足

| 位置 | 列数 | 问题 |
|---|---|---|
| `frontend/src/features/live/LiveBoardView.vue:181` | `repeat(3,1fr)` | 配 `height:120px`（`:183`），指数不足 3 个时留固定空格 |
| `frontend/src/features/live/LiveBoardView.vue:193` | `repeat(4,1fr)` | 配 `min-height:160px`（`:196`），榜单不足 4 列时留 160px 空块 |
| `frontend/src/features/community/components/StrategyCard.vue:200` | `repeat(4,minmax(0,1fr))` | 绩效四格；`:98` 明写「暂无净值切片（未进榜：成交笔数或上架天数没到门槛）」，未进榜时四格全空 |
| `frontend/src/features/ops/components/LlmTab.vue:228` | `repeat(3,minmax(0,1fr))` | `.prov-grid`；只配 1 家供应商 = 2 个 10.5rem 空位（见 §4.2） |
| `frontend/src/features/research/components/ResearchBacktestPanel.vue:544` | `repeat(4,...)` | `.backtest-form`；`:560` `.detail-grid` 再 `repeat(3,...)` |
| `frontend/src/features/research/components/ResearchEvidencePanel.vue:81` | `repeat(4,...)` | `.risk-grid`，字段缺失时按设计「保持空缺不补零」（`ResearchFactorPanel.vue:239`），空格必然出现 |
| `frontend/src/features/research/components/ResearchDimensionDetail.vue:200` | `repeat(3,...)` | `.value-grid` |
| `frontend/src/features/research/components/ResearchHypothesisPanel.vue:233` | `repeat(3,...)` | |
| `frontend/src/features/strategy/components/QuantBacktestTradeResult.vue:299` | `repeat(3,...)` | |
| `frontend/src/features/ops/components/SysNotifySection.vue:302` | `repeat(2,...)` | |

**反例（应推广的写法）**：`frontend/src/features/auth/AccountView.vue:457`、`frontend/src/features/admin/components/OverviewTab.vue:141`、`frontend/src/features/admin/components/QuotaTab.vue:441` 用 `repeat(auto-fill|auto-fit, minmax(200~220px,1fr))`，内容不足时不留硬空格。

### 4.6 `el-empty` / `EmptyState` 之外的自绘空态

| 位置 | 现状 | 该换成 |
|---|---|---|
| `frontend/src/features/auth/AccountSecurityPane.vue:187` | `<div class="empty-hint">暂未绑定任何第三方登录方式</div>` | `EmptyState`（`shared/components/ui/EmptyState.vue`）或 `el-empty :image-size="48"` |
| `frontend/src/features/ops/components/LlmProviderDialog.vue:262` | `<p class="field-hint">目录为空。</p>` | `el-empty` 小尺寸 |
| `frontend/src/features/ops/components/LlmProviderDialog.vue:271` | `<p class="field-hint side-empty">保存并校验后可拉取模型目录。</p>` | 同上（这是「原因+下一步」，正好是 `EmptyState` 的 `reason` 语义） |
| `frontend/src/features/ops/components/LlmModelCatalogDrawer.vue:267` | `<span class="op-placeholder">—</span>` | 单元格占位可保留，但应统一走 `format` 的空值口径 |
| `frontend/src/features/community/components/StrategyCard.vue:98` | 纯文字「暂无净值切片 …」 | `el-empty` 或 `EmptyState`（`image-size` 调小） |
| `frontend/src/features/community/MyCommunityView.vue:235` | `<p class="pad notice">{{ signalNotice }}</p>` | `el-alert type="info" :closable="false"` |
| `frontend/src/features/admin/AdminView.vue:31-34` | 用了 `el-empty` 但把 `#description` 换成自绘 `<h3>+<p>` | 用 `EmptyState` 的 `description`/`reason` 双槽 |
| `frontend/src/features/research/components/ResearchDimensionDetail.vue:118` | `<div class="gap-empty">` 外包一层再放 `el-empty`（`:119`） | 去掉无行为的包壳（§3.3.1 封装契约 5） |
| `frontend/src/shared/components/ui/BasicTableVirtual.vue:296` | `<span class="basic-table__virtual-empty">` | `el-table-v2` 的 `#empty` 里放 `EmptyState` |
| `frontend/src/style.content.css:22-27` | 全局仍留 `.empty` / `.empty-inline` 旧空态皮肤 | `EmptyState` 已统一，这套可删（见 §7） |

---

## 5. 解释性文案过多

扫描口径：`.local/audit/copy.ps1` 只扫 `<template>` 区间，提取 `description` / `title` / `note` / `reason` / `placeholder` / `empty-text` 等静态属性文案与纯文本节点，统计汉字数 ≥ 20 的条目。**命中 132 条**（`.local/audit/copy.txt`）。

> 已剔除 HTML 注释误命中（如 `frontend/src/shared/components/ui/EmptyState.vue:20-21`、`frontend/src/features/ops/components/SettingsRail.vue:110-111`、`frontend/src/features/live/components/LiveTopBar.vue:101-102`、`frontend/src/features/ops/components/McpTab.vue:281-282`）——那些是给维护者看的 why 注释，应保留。下表 38 条均为真实渲染给用户的文案。

| 页面（文件:行号） | 文案原文 | 建议精简为 |
|---|---|---|
| `features/strategy/components/ScreenSkillReferencesPanel.vue:38` | 资料为可选项，不填也能试跑与保存。只有动手填写某条资料时，才需要补齐编号、标题，以及链接 / 路径 / 章节 / 引文之一；逻辑里写了引用编号时也要能对应到这里。AI 生成草稿时才强制要求资料。 | 资料选填。填了就要补齐编号、标题、来源三选一；AI 生成草稿时必填 |
| `features/community/SquareView.vue:67` | 只展示公开且在架的发布；卡片绩效取自当期榜单快照，未进榜的策略留白不补零。涨红跌绿，最大回撤恒为负。 | 仅公开在架。绩效取当期榜单快照，未进榜留白 |
| `features/research/components/ResearchBacktestPanel.vue:357` | 提交后仍由后端逐日复核可见日、真实成员、行情来源回执和 OHLC 覆盖；任一证据缺失都会保留失败原因。 | 后端逐日复核可见日 / 成员 / 来源 / OHLC，缺证据即失败 |
| `features/research/components/ResearchBacktestPanel.vue:366` | 未开启严格 PIT 时，后端会保留警告和证据缺口；结果不能作为严格证据、假设通过或生产默认的依据。 | 非严格 PIT：结果仅供探索，不能作为证据 |
| `features/research/components/ResearchHypothesisPanel.vue:218` | 通过审核必须关联证据文件指纹，并按预注册指标填写真实观测值；缺字段请保留空白，不要估算。 | 通过需附证据指纹与真实观测值；缺项留空，勿估算 |
| `features/community/LeaderboardView.vue:85` | 榜单是当期快照，不现算：同一天刷新名次不会跳。门槛不满足的策略直接不出现，而不是排在后面。 | 当期快照，不现算；未达门槛不入榜 |
| `features/admin/components/ResetPasswordDialog.vue:64` | 管理员代重置将注销该用户所有活跃登录会话，并标记该账号在下次登录时必须修改密码。 | 将注销该用户全部会话，并强制下次登录改密 |
| `features/community/MyCommunityView.vue:160` | 发布 / 订阅 / 收藏三本账。订阅只推信号，不自动下单——是否成交由你自己决定并记进自己的账本。 | 发布 / 订阅 / 收藏三本账。订阅只推信号，不自动下单 |
| `features/ops/components/PackTab.vue:166` | 运维库与 MCP 只带骨架：任务定义、战法档案、推送模板、调参档位；API Key、Webhook、纸面舱与教训留痕都不会进包。 | 只带骨架（任务 / 战法 / 模板 / 档位）；密钥与纸面记录不进包 |
| `features/auth/AccountView.vue:310` | 账本、运维库与技能运行记录的软上限；超了只会更激进地清理临时数据，不会拒绝写入 | 软上限。超限只加速清理临时数据，不拒写入 |
| `features/auth/AccountView.vue:302` | 自己新建的定时任务条数上限；系统托管的选股 / 情报任务不占额度 | 自建任务上限，托管任务不占额度 |
| `features/community/components/OosCompare.vue:99` | 两栏差得越远，越说明上架时那条曲线是拟合出来的。样本内数字冻在版本里改不了， | 两栏差距越大，上架曲线越可能是拟合 |
| `features/community/components/PublishDialog.vue:245` | 回测证据：上架必须附，三项成本都不能为 0（零成本是最常见的注水手法）， 成交笔数 ≥ 30，区间 ≥ 1 年。 | 上架必附回测：三项成本 > 0、成交 ≥ 30 笔、区间 ≥ 1 年 |
| `features/auth/AccountView.vue:358` | 请立即复制并妥善保管此 Key！为了您的安全，明文仅展示这一次，关闭后将无法再次查看。 | 明文仅展示这一次，请立即复制保存 |
| `features/review/InsightsView.vue:324` | 策略是否失效请看选股目录「近期胜率」。前视偏差由测试与生成链自动拦，不在本页。 | 策略失效看选股目录「近期胜率」；前视偏差不在本页 |
| `features/ops/components/McpToolsDialog.vue:212` | 为已在数据源「按接口」上桌的接口。测连通只验证服务握手和工具发现，不执行工具。 | 测连通只验握手与工具发现，不执行工具 |
| `features/community/StrategyDetailView.vue:286` | 可能已被作者设为私有 / 下架，或链接里的 id 不存在（后端对看不见的东西一律回 404） | 已设私有 / 下架，或链接 id 不存在 |
| `features/strategy/components/SkillStrategyConfigPanel.vue:151` | 盘后走 AI 全量选股，盘中走 MCP + 本地量化信号监测。战法本身不带时间，全在这里配。 | 盘后走 AI 全量选股，盘中走 MCP 监测；时点在此配 |
| `src/App.vue:147` | 安全提醒：您的账号当前为初始密码或已被重置，请点击此处尽快修改密码！ | 账号仍是初始密码，点此修改 |
| `features/auth/AccountView.vue:216` | 安全提醒：您的账号当前为初始密码或已被重置，请尽快修改新密码！ | 账号仍是初始密码，请尽快修改（与 `App.vue:147` **重复**，二选一） |
| `features/strategy/components/ScreenRunPanel.vue:337` | 在左侧选中战法后，点右上角「选股」开跑；工作日 15:30 也会自动跑一遍盘后选股。 | 选中左侧战法后点右上角「选股」；15:30 自动跑一遍 |
| `features/community/SquareView.vue:151` | 没有人发布过，或当前筛选条件太窄；后端未启用社区时这里也会是空的 | 无人发布，或筛选过窄 |
| `features/research/components/ResearchBacktestPanel.vue:356` | 严格 PIT 模式：必须完整填写训练/OOS 区间和历史股票池标识；缺一项将拒绝提交。 | 严格 PIT：训练 / OOS 区间与股票池标识必填 |
| `features/research/components/ResearchFactorPanel.vue:239` | Top 10% 仅保留可成交标的；数据缺失或不可成交的位置保持空缺，不以弱票替补。 | Top 10% 只保留可成交标的，缺失处留空不替补 |
| `features/review/WinRateView.vue:211` | 胜率 = 精选候选 T+5 口径（另列 T+1/T+3），无候选样本时回退手工复盘；样本少于 5 仅供参考 | 胜率 = 精选候选 T+5；样本 < 5 仅供参考 |
| `features/review/ReviewsView.vue:66` | 手工补记的买卖样本与教训；无候选样本时，胜率统计回退到这批复盘 | 手工补记的样本与教训 |
| `shared/components/layout/NotificationCenter.vue:100` | 别人克隆、收藏你的战法，或订阅的策略发出信号时，消息会出现在这里。 | 克隆 / 收藏 / 订阅信号会出现在这里 |
| `features/ops/components/JobEditorDialog.vue:328` | 这条 cron 约每 N 分钟触发一次，快于 5 分钟下限；非主账号提交会被后端拒绝（422）。 | 约每 N 分钟一次，快于 5 分钟下限（非主账号会被拒） |
| `features/ops/components/JobScheduleInline.vue:202` | 这个时点约每 N 分钟触发一次，快于 5 分钟下限，非主账号会被后端拒绝（422）。 | 同上（与 `JobEditorDialog.vue:328` **近乎逐字重复**，应抽同一 composable/常量） |
| `features/ops/components/PackTab.vue:157` | 要发给别人的话，取消这些勾选；其余项默认已抹掉 API Key、Webhook 与纸面交易记录。 | 要外发就取消这些勾选；密钥与交易记录已默认抹掉 |
| `features/research/components/ResearchHypothesisPanel.vue:208` | 还没有登记假设。先写清楚要验证什么、以及判定通过的指标和门槛 | 还没有假设。先写清验证目标与通过门槛 |
| `features/research/components/ResearchTemporalDataPanel.vue:242` | 这个条件下没有快照。换个股票池标识或日期，或点「导入快照」补一批 | 无快照。换条件，或点「导入快照」 |
| `features/research/components/ResearchTemporalDataPanel.vue:282` | 这个条件下没有事实。换个实体或日期，或点「导入事实」补一批 | 无事实。换条件，或点「导入事实」 |
| `features/ledger/PoolView.vue:345` | 选股产出与手动记录的候选；裁决与理由为当时快照，不随行情变动 | 候选为当时快照，不随行情变动 |
| `features/community/MyCommunityView.vue:264` | 在策略详情页点「订阅信号」；订阅只会收到作者发布的当日信号快照 | 在策略详情页点「订阅信号」 |
| `features/strategy/components/QuantBacktestPanel.vue:231` | 选口径与战法，用近一月 / 三月 / 六月再跑。预计耗时写在「跑回测」旁边。 | 选好口径与战法后点「跑回测」 |
| `features/ops/components/JobDetailPane.vue:117` | 技能绑定：时点与启停可以在这里改；股票池 / 提示词等技能专属配置在技能详情。 | 时点与启停在此改，其余配置在技能详情 |
| `features/ops/components/JobDetailPane.vue:118` | 战法绑定：时点与启停可以在这里改；股票池 / top_n / AI 精选等战法专属配置在工坊。 | 时点与启停在此改，其余配置在工坊 |
| `features/admin/AdminView.vue:33` | 该管理后台仅对系统管理员开放。当前登录账号无权访问。 | 仅管理员可访问 |

### 5.1 文案层面的系统性问题

1. **重复文案**：`App.vue:147` 与 `AccountView.vue:216` 是同一条初始密码警告的两个手抄版本；`JobEditorDialog.vue:328` 与 `JobScheduleInline.vue:202` 是同一条 cron 频率警告的两个手抄版本 —— 应提到 `shared/lib` 常量。
2. **`note` 属性被当长文段用**：`PageHeader` 的 `note` 出现 40 字以上的整句（`SquareView.vue:67`、`LeaderboardView.vue:85`、`MyCommunityView.vue:160`、`WinRateView.vue:211`），页头被文案顶高，挤压首屏内容高度 —— 与 §4 的留白问题互为因果。
3. **口径说明该沉到 `el-tooltip`**：`InsightsView.vue:324`、`WinRateView.vue:211`、`ReviewCenterView.vue:142` 这类「统计口径」文本适合放 `el-tooltip` 或 `el-popover`，而不是常驻页头。

---

## 6. 样式碎片统计

扫描口径：`.local/audit/style.ps1` 逐文件截取 `<style ...>` … `</style>` 区间（跳过整行 `/*` 注释），匹配 `#xxxxxx|#xxx|rgb(|rgba(` 与 `font-size: …NNpx`。

### 6.1 总数

| 指标 | 数量 | 来源 |
|---|---:|---|
| 含硬编码的 `.vue` 文件数 | **37** | `.local/audit/style.txt:1` |
| `.vue` `<style>` 内硬编码颜色 | **104** | `.local/audit/style.txt:2` |
| `.vue` `<style>` 内 px 字号 | **37** | `.local/audit/style.txt:3` |
| 同级 `.css` 分片内硬编码颜色 | **20** | `.local/audit/style2.txt`（`frontend/src/features/live/live-theme.css` 19 + `frontend/src/features/ledger/ArchiveView.css` 1） |
| 同级 `.css` 分片内 px 字号 | **0** | 同上 |
| **合计** | **颜色 124 / px 字号 37** | |

### 6.2 Top 20 文件排行（按 颜色+px字号 合计）

| # | 文件 | 颜色 | px 字号 | 合计 |
|---:|---|---:|---:|---:|
| 1 | `frontend/src/features/ledger/LoginView.vue` | 15 | 0 | 15 |
| 2 | `frontend/src/features/live/components/SignalStream.vue` | 5 | 8 | 13 |
| 3 | `frontend/src/features/ai/components/AssistantPanel.vue` | 8 | 0 | 8 |
| 4 | `frontend/src/features/live/components/LiveTopBar.vue` | 1 | 7 | 8 |
| 5 | `frontend/src/features/ai/components/AssistantFloatBall.vue` | 7 | 0 | 7 |
| 6 | `frontend/src/features/market/components/PulseTrackTable.vue` | 6 | 0 | 6 |
| 7 | `frontend/src/features/review/InsightsView.vue` | 6 | 0 | 6 |
| 8 | `frontend/src/features/live/components/RankColumn.vue` | 0 | 6 | 6 |
| 9 | `frontend/src/features/market/components/MinuteSessionDialog.vue` | 5 | 0 | 5 |
| 10 | `frontend/src/features/auth/VerifyEmailForm.vue` | 4 | 0 | 4 |
| 11 | `frontend/src/features/auth/QrLoginPanel.vue` | 4 | 0 | 4 |
| 12 | `frontend/src/features/ledger/components/ArchiveBatchDock.vue` | 4 | 0 | 4 |
| 13 | `frontend/src/features/live/components/HeatStrip.vue` | 0 | 4 | 4 |
| 14 | `frontend/src/features/live/components/IndexMiniChart.vue` | 0 | 4 | 4 |
| 15 | `frontend/src/features/market/PeekView.vue` | 4 | 0 | 4 |
| 16 | `frontend/src/features/review/components/HealthCheckList.vue` | 4 | 0 | 4 |
| 17 | `frontend/src/features/market/components/KlineReadout.vue` | 3 | 0 | 3 |
| 18 | `frontend/src/features/live/components/TickerTape.vue` | 0 | 3 | 3 |
| 19 | `frontend/src/features/live/components/LiveEmptyState.vue` | 0 | 3 | 3 |
| 20 | `frontend/src/features/ledger/components/StockTimeline.vue` | 3 | 0 | 3 |

### 6.3 结论

- **px 字号 100% 集中在 `features/live/components/**`**：37 处全部在大屏组件，取值 `10px/11px/12px/13px/14px/16px` 六档（如 `SignalStream.vue:118`/`:124`/`:129`/`:149`/`:167`/`:173`/`:198`/`:226`，`LiveTopBar.vue:129`/`:135`/`:142`/`:164`/`:186`/`:201`/`:235`，`RankColumn.vue:123`/`:129`/`:146`/`:154`/`:187`/`:194`，`HeatStrip.vue:91`/`:99`/`:124`/`:160`，`IndexMiniChart.vue:167`/`:173`/`:185`/`:189`，`LiveEmptyState.vue:166`/`:181`/`:201`，`LiveStatusBar.vue:53`/`:84`，`TickerTape.vue:123`/`:146`/`:151`）。**修一个 feature 就能清掉全部 px 字号债**。
- **颜色债最重的是 `LoginView.vue`（15 处）**，其次 `AssistantPanel.vue`（8）与 `AssistantFloatBall.vue`（7）；`live-theme.css`（19 处）是大屏自建的一套色板，与全局 token 平行。
- **样式碎片的第三个来源**：8 个 SFC 同级 `.css` 分片（`ScreenHistoryView.css` 88 行、`StrategyConverterView.css` 144、`ScreenRunPanel.css` 249、`ArchiveView.css` 216、`AssistantSenderDock.css` 207、`DataQueryDetailPanel.css` 241、`ResearchPanel.responsive.css` 56、`live-theme.css` 90），共 1191 行样式游离在 `<style scoped>` 之外，普通 grep 扫不到。
- **12 处非 `scoped` 的 `<style>`**（`AssistantAgentThread.vue:331`、`AssistantPanel.vue:378`、`AssistantSettingsDialog.vue:417`、`PoolView.vue:554`、`PeekView.vue:377`、`JobRunsDialog.vue:220`、`McpToolsDialog.vue:378`、`ScreenHistoryView.vue:521`、`ScreenCatalogDialog.vue:67`、`ScreenHistoryPanel.vue:395`、`MarketBootstrapDialog.vue:546`、`MobileBottomNav.vue:286`）—— 绝大多数是 `el-dialog` teleport 到 body 的合法场景且已写 why 注释（如 `PoolView.vue:555`、`McpToolsDialog.vue:379`、`ScreenCatalogDialog.vue:68`），**保留**。

---

## 7. 全局 CSS 现状

### 7.1 各文件职责与体量

| 文件 | 行数 | 职责一句话 |
|---|---:|---|
| `frontend/src/style.css` | 8 | 唯一入口，只做 `@import` 排序：tailwind → base → layout → components → content → tail → **theme 最后**（`:7` 注释说明主题必须覆盖前面各层 token） |
| `frontend/src/style.base.css` | 308 | `:root` 设计 token（`:2-33`：墨/纸/印色、涨跌语义色、圆角阴影）+ 元素级 reset（`body:121`、`button:138`/`:151`）+ 少量壳件（`.app-shell:174`、`.record-fab:207`、`.seal-meter__fill:282`） |
| `frontend/src/style.layout.css` | 210 | 壳与页面骨架：`.main-content:1`、`.page-host:16`、`.page-host:has(.page-fill):29`、`.page-scroll`/`.page-pane`、`.filter-bar:165`、`.mb:174`、`.stat-strip:178`、`.grid-2:201` |
| `frontend/src/style.components.css` | 256 | 面板皮肤：`.sheet`/`.panel:2`、`.sheet.sheet-plain:11`、`.sheet-bar`/`.panel-bar:17`、`.text-link:179` 等通用组件外观 |
| `frontend/src/style.content.css` | 525 | **最杂的一层**：对话框表单栅格（`.form-grid:2`）、旧空态皮肤（`.empty`/`.empty-inline:22`）、以及一批已死的页面级布局（`.pool-layout:221`、`.day-list:236`、`.memory-head:430`、`.bar-value:358`） |
| `frontend/src/style.tail.css` | 96 | 收尾层：EP `el-card` 覆盖（`:2-17`）+ **全部响应式断点**（`980px:24`/`:31`、`640px:62`）+ `prefers-reduced-motion:82` + 链接下划线重置（`:91-96`，带 `!important`） |
| `frontend/src/style.theme.css` | 153 | `data-appearance`（paper/night/ink）× `data-primary` 主题的**唯一定义处**；`:1-7` 注释记录了「此前 components.css 与 tail.css 各存一份逐字副本、改前者被后者静默覆盖」的历史故障 |

### 7.2 同一选择器在两个文件里都出现（12 条）

| 选择器 | 出现位置 | 判定 |
|---|---|---|
| `:root` | `style.base.css:2`，`style.theme.css:113` | ⚠️ **可疑**：token 默认值被拆成两处，`theme.css:113` 的 `:root` 与 `base.css:2` 谁定义了哪些变量不可见，只能靠 import 顺序保证 |
| `body` | `style.base.css:121`，`style.tail.css:63` | ✅ 合理：tail 是 `@media (max-width:640px)` 内的字号覆盖 |
| `.main-content` | `style.layout.css:1`，`style.tail.css:67` | ✅ 合理：tail 内为 640px 断点 padding 收窄 |
| `.app-shell` | `style.base.css:174`，`style.tail.css:25` | ⚠️ **可疑**：骨架定义在 base 而非 layout，断点在 tail —— 一个组件的三处定义横跨两层且都不在 `layout.css` |
| `.text-link` | `style.components.css:179`，`style.tail.css:94` | ⚠️ **可疑**：tail 的 `text-decoration: none !important`（`:95`）会盖掉 components 里任何下划线设定，且 `!important` 无法在 SFC 里局部覆盖 |
| `.stat-strip.cols-3` | `style.layout.css:185`，`style.tail.css:73` | ❌ **死代码**：`.stat-strip` 全站 0 使用（见 §4.1） |
| `.stat-strip.cols-5` | `style.layout.css:193`，`style.tail.css:35` | ❌ 死代码 |
| `.pool-layout` | `style.content.css:221`，`style.tail.css:41` | ❌ 死代码 |
| `.pool-aside` | `style.content.css:228`，`style.tail.css:45` | ❌ 死代码 |
| `.day-list` | `style.content.css:236`，`style.tail.css:50` | ❌ 死代码 |
| `.day-item` | `style.content.css:242`，`style.tail.css:55` | ❌ 死代码 |
| `.memory-head` | `style.content.css:430`，`style.tail.css:77` | ❌ 死代码 |

### 7.3 同一文件内重复定义（7 条）

| 选择器 | 位置 | 说明 |
|---|---|---|
| `button` | `style.base.css:138`，`:151` | 元素级 reset 拆成两块，第二块可能是后补的 hover/focus，建议合并 |
| `.form-grid` | `style.content.css:2`，`:17` | `:17` 在 `@media (max-width:480px)` 内，合理 |
| `.bar-value` | `style.content.css:358`，`:363` | 相邻 5 行内两次定义同一类，**应合并** |
| `.record-fab` | `style.base.css:207`，`:212` | 相邻定义，**应合并** |
| `.seal-meter__fill` | `style.base.css:282`，`:305` | 相隔 23 行两次定义，需人工确认后者是否为无意覆盖 |
| `html[data-appearance='ink']` | `style.theme.css:22`，`:51`，`:120`，`:148` | 4 段（底色 / 细节 / 主色联动 / 收尾），有注释分区，可接受 |
| `html[data-primary]` | `style.theme.css:103`，`:134` | 2 段，可接受 |

### 7.4 分层边界失守的证据

- **`style.content.css` 已经不是「内容层」**：525 行里至少 `:221-265`（pool 布局）、`:430-434`（memory-head）是特定页面的骨架，且这些页面已不存在。该文件应拆散：表单栅格归 `components`，死代码删除。
- **`style.tail.css` 承担了两件不相干的事**：EP 组件覆盖（`:2-17`）与全站响应式断点（`:24-80`）。断点应回到各自所属层（`.stat-strip` 断点→layout、`.day-item` 断点→随死代码一起删）。
- **`.app-shell` 定义在 `base` 而非 `layout`**（`style.base.css:174` vs `style.tail.css:25` 的断点），是分层错位的直接样例。

---

## 按修复收益排序的 Top 20 问题

| # | 问题 | 位置 | 影响 | 难度 |
|---:|---|---|---|:---:|
| 1 | 全局 `.stat-strip`（5 变体 + 2 断点）及 `.pool-layout`/`.pool-aside`/`.day-list`/`.day-item`/`.memory-head`/`.grid-2`/`.hold-plan` 全部零引用的死 CSS | `style.layout.css:137`/`:178-199`/`:201`/`:208`，`style.content.css:221-265`/`:430-434`，`style.tail.css:33-59`/`:71-79` | 约 90 行死代码 + §7.2 中 7 条「跨文件覆盖」全是幽灵，误导后续所有布局改动 | S |
| 2 | `AdminView` 左侧导航 5 个裸 `<button class="rail-item">` | `features/admin/AdminView.vue:48`/`:57`/`:66`/`:75`/`:84` | 全站最大的一处 EP 违规；键盘导航/焦点环/禁用态全靠手写 CSS，主题切换时不跟随 | M |
| 3 | `LeaderboardView` 9 列裸 `<table class="board">` | `features/community/LeaderboardView.vue:145-188`（外壳 `:144`） | 无排序/无固定表头/无虚拟滚动；`.table-scroll` 自造滚动与 §3.7.1 内滚约定平行 | M |
| 4 | `QuotaTab` 整个批量配额表单零 `el-form`，全自绘 `.field-item/.field-header/.field-controls` | `features/admin/components/QuotaTab.vue:161`，字段行 `:163`/`:185`/`:207`/`:229`/`:251`/`:274` | 6 组字段无 label 对齐、无校验、无 `required` 语义；源码缩进已散架（`:253`/`:270`/`:279`/`:294`） | L |
| 5 | `label-width` 发散成 8 种取值且 rem/px 混用 | 见 §3.1 表（`80px`/`130px` 在 admin 域，`5rem~10rem` 在其余全域） | 跨页表单左缘不齐；根字号一变 px 组全错位 | M |
| 6 | 同页 `label-width` 不一致造成可见错位 | `SkillWatchTuningPanel.vue:150`(7rem) vs `:162`(10rem)；`PaperQuantPanel.vue:333`/`:361`/`:460`(6rem) vs `:478`/`:545`(inline) | 同一屏内两段表单输入框左缘错开，是肉眼可见的「歪」 | S |
| 7 | `MyCommunityView` 裸 `<table class="rows">`（操作列已是 `el-button`） | `features/community/MyCommunityView.vue:193-223`（外壳 `:192`） | 与 #3 同类，但改动量最小（列内容已 EP 化），性价比最高 | S |
| 8 | `features/live/components/**` 37 处 px 硬编码字号，6 档取值 | `SignalStream.vue:118`…`:226`、`LiveTopBar.vue:129`…`:235`、`RankColumn.vue:123`…`:194`、`HeatStrip.vue:91`…`:160`、`IndexMiniChart.vue:167`…`:189`、`LiveEmptyState.vue:166`/`:181`/`:201`、`LiveStatusBar.vue:53`/`:84`、`TickerTape.vue:123`/`:146`/`:151` | **全站 px 字号债 100% 集中在这一个 feature**，改一处即清零；当前不跟随 `style.tail.css:63-65` 的 640px 字号收缩 | M |
| 9 | `AdminView` 非管理员空态占满整屏 | `features/admin/AdminView.vue:120`（`height:100%`）+ `:121`（`padding:3rem 1rem`）+ 自绘 `#description`（`:31-34`） | 最典型的「大片空白」：整屏只有一个居中 `el-empty` | S |
| 10 | `min-height` 硬编码撑空（46 文件，高风险 20 条） | `MinuteSessionDialog.vue:254`+`:283`（420+360px）、`AkshareBatchProbeDialog.vue:99`（360px）、`TopLlmChart.vue:130`（260px）、`AssistantSettingsDialog.vue:283`（16rem）… 见 §4.2 | 空数据时成片死白；多处与 `height`/`height:100%` 三重定高互相打架 | M |
| 11 | 页头 `note` 被当长文段用，顶高页头压缩首屏 | `SquareView.vue:67`(45字)、`LeaderboardView.vue:85`(40)、`MyCommunityView.vue:160`(38)、`WinRateView.vue:211`(30) | 文案与留白互为因果：note 越长，可视内容区越矮 | S |
| 12 | 重复手抄的文案（同一句话两个版本） | `App.vue:147` ↔ `AccountView.vue:216`；`JobEditorDialog.vue:328` ↔ `JobScheduleInline.vue:202` | 改一处漏一处，口径分叉（与 §3.7「fmtPct 被手抄 9 份」同型） | S |
| 13 | `el-form` 内混排裸 `div` 绕过 EP 布局 | `JobEditorDialog.vue:281`、`McpTab.vue:296`、`RecordDialog.vue:233`、`LlmProviderDialog.vue:151-153`、`ResearchBacktestPanel.vue:544-545`、`ResearchHypothesisPanel.vue:233`、`AkshareToolTable.vue:404` | `label-width` 计算被 CSS grid 接管，还要靠 `margin-bottom:0` 重置和两级断点补救（`ResearchBacktestPanel.vue:573-574`） | M |
| 14 | `.vue` 内 104 处硬编码颜色 | `LoginView.vue`(15)、`AssistantPanel.vue`(8)、`AssistantFloatBall.vue`(7)、`PulseTrackTable.vue`(6)、`InsightsView.vue`(6)… 见 §6.2 | 三套主题（paper/night/ink）切换时这些色值不跟随，暗色下出现亮块 | M |
| 15 | 5 处 `el-form` 既无 `label-width` 也无 `label-position` | `PaperQuantPanel.vue:478`/`:545`，`QuantBacktestPanel.vue:90`/`:173`/`:197` | inline 表单 label 宽度随文案浮动，三段控件全不齐 | S |
| 16 | 8 处写了 `label-width` 却漏 `label-position`，落到 EP 默认 `right` | `AnnouncementEditorDialog.vue:102`、`NotifyUserDialog.vue:59`、`ResetPasswordDialog.vue:70`、`UserQuotaDialog.vue:102`、`ScreenSelectDialog.vue:69`、`PaperQuantPanel.vue:333`/`:361`/`:460` | 全仓主流是 `top`(23)/`left`(11)，这 8 处成右对齐孤岛 | S |
| 17 | grid 列数写死、内容不足留硬空格 | `LiveBoardView.vue:181`(3列)/`:193`(4列)、`StrategyCard.vue:200`(4列，配 `:98` 的空态文案)、`LlmTab.vue:228`(3列，配 `LlmProviderCard.vue:153` 的 10.5rem 定高) | 只配 1 家供应商 = 2 个 10.5rem 空位；未进榜策略卡 4 格全空 | S |
| 18 | `el-empty`/`EmptyState` 之外的自绘空态 10 处 | `AccountSecurityPane.vue:187`、`LlmProviderDialog.vue:262`/`:271`、`StrategyCard.vue:98`、`MyCommunityView.vue:235`、`AdminView.vue:31-34`、`ResearchDimensionDetail.vue:118`、`BasicTableVirtual.vue:296`、`LlmModelCatalogDrawer.vue:267`，及全局旧皮肤 `style.content.css:22-27` | 违反 §3.7「空态 = EmptyState（原因 + 下一步）」；样式与 `EmptyState.vue` 不一致 | M |
| 19 | `RouterLink` 手抄 EP class 冒充按钮 | `AdminView.vue:36`（`class="el-button el-button--primary"`）、`AppSidebar.vue:166`（`class="ops-link el-button tool-row"`） | EP 升级改 class 名即静默失效；§3.3.1 例外 2 只放行纯导航项，工具操作须用 `el-button` | S |
| 20 | 全局 CSS 分层边界失守 | `:root` 拆在 `style.base.css:2` + `style.theme.css:113`；`.app-shell` 在 `base:174` 而非 layout；`.text-link` 被 `style.tail.css:94-95` 的 `!important` 锁死；`style.content.css` 525 行里混着页面骨架 | 后续任何 token / 布局改动都要跨 3 个文件试错；`!important` 让 SFC 无法局部覆盖 | L |
