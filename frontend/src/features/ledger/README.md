# ledger

本限界上下文的页面：个人账本与候选池。

- `DashboardView.vue`（路由 `/ledger` · 账本）：资产轨、持仓表、当日卖出、现金锚点、交割绩效条；面板最底为同花顺式「N月参考盈亏」卡（大数+曲线+收益率气泡）
- `components/DashboardMonthPnlCard.vue` / `DashboardHoldingsTable.vue` / `DashboardTodaySells.vue`：本月卡、持仓与当日卖出
- `composables/useDashboardLive.ts`：持仓盯市轮询
- `JournalView.vue` / `PoolView.vue`：工具栏 `<ListToolbar :config="{ create, batchDelete, import, export }" />`（按需写键；刷新仍用表右侧 `toolbarConfig.refresh`）
- `ArchiveView.vue`：个股工作台（行情 / 交割 / 候选）；顶栏身份行含涨跌色股价、右侧板块/行业标签；默认行情，特殊入口可带 `?view=trades|candidates` 与 `?date=YYYY-MM-DD`（锚定日 K）；按当前 tab 按需加载面板；交割时间线为紧凑单行列表（`StockTimeline`）
- **全屏蒙版**：`/archive/:code` 由 App 的 `PageHost` Teleport 盖满视口（`z-index: 8000`，盖住侧栏/底栏/FAB 与进档前残留弹层）；源页经 KeepAlive 保活。档案打开时 `el-config-provider` 将 EP 弹层起点抬到 8200，避免记一笔/分时被蒙版压住。点「返回」/「回本批」或 `Esc` 关层
- `AuthUnavailableView.vue`：认证服务探测失败时的可重试故障页，避免路由初始导航异常导致空白页面
- `PoolView` / `StockLink`：候选池进档案时带上候选日 `date`，日 K 默认落到该日
- **同批切票**：从选股结果 / 脉冲榜 / 行情台当前页 / 候选池等 ≥2 只列表进档案时，写入 `batchBrowse` 会话（内存 + `sessionStorage`）；档案顶栏 `ArchiveBatchRail`（←→ / 返回本批 / 本批列表），侧栏或窄屏抽屉 `ArchiveBatchDock`；键盘 ←→ 切票；孤立 `StockLink`（交割单笔等）不带 `batch` 则无切票。来源文案拆成策略名 + **选股日**（侧栏完整展示日期，顶栏只留日期芯片，悬停看全文），避免两处同一截断串
