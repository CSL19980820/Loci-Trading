# ledger

本限界上下文的页面：候选池与个股档案（**持仓/成交已于 2026-08 整体下线**，无账本看板、无交割单、无写入成交入口）。

- `PoolView.vue`（路由 `/pool` · 候选池）：页头用 `shared/components/layout/PageHeader.vue`（衬线标题 + 口径 note + `HeaderStat` 读数 + 主动作）：精选/观察/落选 与 新增。表格工具栏保留 `<ListToolbar :config="{ batchDelete }" />`（新增已上移页头，避免两处同名动作）；刷新仍走表右侧 `toolbarConfig.refresh`
- 页头计数为**当前已加载数据**口径（非全库统计），改动这些数字前先确认分页语义
- `PoolView.vue`：候选池完整结果走 `BasicTable` `virtualized`（内部 Element Plus `el-table-v2`；筛选后实时替换数据、选择列左固定、操作列右固定）。因表级 `fixed` 会关掉 `flexGrow`，`BasicTableVirtual` 按容器宽把余量显式加到 `minWidth` 列（如「理由」），避免大屏右侧空白死区；页面滚动仍下沉到表体；不兼容列自动回退经典表
- `ArchiveView.vue`：个股工作台（行情 / 候选）；顶栏身份行含涨跌色股价、右侧板块/行业标签；默认行情，特殊入口可带 `?view=candidates` 与 `?date=YYYY-MM-DD`（锚定日 K）；按当前 tab 按需加载面板；候选时间线为紧凑单行列表（`StockTimeline`）。后端 `/api/timeline/{code}` 已摘掉 position_events 段，只剩候选/预案，所以这里不再有「交割」tab、也不留成交图例
- **全屏蒙版**：`/archive/:code` 由 App 的 `PageHost` Teleport 盖满视口（`z-index: 8000`，盖住侧栏/底栏/FAB 与进档前残留弹层）；源页经 KeepAlive 保活。档案打开时 `el-config-provider` 将 EP 弹层起点抬到 8200，避免记一笔/分时被蒙版压住。点「返回」/「回本批」或 `Esc` 关层
- `AuthUnavailableView.vue`：认证服务探测失败时的可重试故障页，避免路由初始导航异常导致空白页面
- `PoolView` / `StockLink`：候选池进档案时带上候选日 `date`，日 K 默认落到该日
- **同批切票**：从选股结果 / 脉冲榜 / 行情台当前页 / 候选池等 ≥2 只列表进档案时，写入 `batchBrowse` 会话（内存 + `sessionStorage`）；档案顶栏 `ArchiveBatchRail`（←→ / 返回本批 / 本批列表），侧栏或窄屏抽屉 `ArchiveBatchDock`（有名称不重复展示代码；涨跌按百分数点展示，如 `-0.71%`）；键盘 ←→ 切票；孤立 `StockLink` 不带 `batch` 则无切票。来源文案拆成策略名 + **选股日**（侧栏完整展示日期，顶栏只留日期芯片，悬停看全文），避免两处同一截断串
