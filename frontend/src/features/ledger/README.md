# ledger

## 展示约定

候选池使用全站冷色令牌；评分右对齐并使用等宽数字，标的列为名称与代码预留宽度。精选、观察和落选属于裁决状态，使用蓝色或中性徽章；红绿只表示价格涨跌。筛选读数在窄屏独立换行，仍表示当前已加载记录。

候选详情在窄屏切成单列，证据数据可展开查看，保留原文及删除、看档案动作。档案通过 `style scoped src="./ArchiveView.css"` 引用样式，内嵌行情面板使用局部 `:deep()`；同批列表在 EP 默认插槽内容层排成序号、名称、涨跌三列，窄屏抽屉保留视口边距。切票按钮配有图标与键盘说明。

## 页面与行为

本限界上下文的页面：候选池与个股档案（**持仓/成交已于 2026-08 整体下线**，无账本看板、无交割单、无写入成交入口）。

- `PoolView.vue`（路由 `/pool` · 候选池）：**表格上方只有一条横栏**（原来是页头 / 筛选 / 表格工具栏三条）。PageHeader 已删；筛选行右侧依次是「查询 · 重置 · 共/精选/观察/落选 `HeaderStat` 读数 · `<ListToolbar :config="{ batchDelete }" />` · 记一条候选 · 口径 ⓘ」。表格不再开 `toolbarConfig`（刷新由「查询」代劳，列设置随之下线——为省掉那条几乎空白的横栏）
- 筛选行读数为**当前已加载数据**口径（非全库统计），改动这些数字前先确认分页语义；详情抽屉的「池 / 来源」走 `poolLabel` / `sourceLabel`，界面不露 `sanyuan-tail-v1@2026-08-20` 这类内部编码
- `PoolView.vue`：候选池走 `BasicTable` 经典表 + **前端分页**（后端一次返回筛选全量 `limit 1000`，
  本地每页 20 切片；`layout 'total, prev, pager, next'`）；**虚拟滚动已下线**（`el-table-v2` 无分页槽，
  全量渲染千行才需要它）。翻页清空勾选（与管理后台一致：已选只表示当前页，避免跨页批量删错范围）；
  页面滚动仍下沉到表体；空态走 `#empty`（列头始终露出，「记一条候选」在表内）
- **`PoolView.vue` 已拆**（613 → 444 行，仓库 600 行硬规则）：详情抽屉抽成
  `components/PoolCandidateDialog.vue`，筛选/分页状态抽成 `composables/usePoolFilters.ts`，
  「池 / 来源 / 战法」的中文化文案抽成 `composables/poolLabels.ts`。中文化那份**只做映射不取数**——
  界面不露 `sanyuan-tail-v1@2026-08-20` 这类内部编码这条约定就落在它一处，改文案只改它。
  拆出的三个文件都没有自己的单测，渲染契约由
  `features/ops/components/splitRenderContracts.test.ts` 真挂载兜住（script setup 漏一个
  destructure 不会被 vue-tsc 抓到，只在 render 时抛 ReferenceError）。
- `ArchiveView.vue`：个股工作台（行情）；顶栏身份行含涨跌色股价、右侧板块/行业标签；支持 `?date=YYYY-MM-DD`（锚定日 K 到指定交易日）。
- **全屏蒙版**：`/archive/:code` 由 App 的 `PageHost` Teleport 盖满视口（`z-index: 8000`，盖住侧栏/底栏/FAB 与进档前残留弹层）；源页经 KeepAlive 保活。档案打开时 `el-config-provider` 将 EP 弹层起点抬到 8200，避免记一笔/分时被蒙版压住。点「返回」/「回本批」或 `Esc` 关层
- `AuthUnavailableView.vue`：认证服务探测失败时的可重试故障页，避免路由初始导航异常导致空白页面
- `PoolView` / `StockLink`：候选池进档案时带上候选日 `date`，日 K 默认落到该日
- **同批切票**：从选股结果 / 脉冲榜 / 行情台当前页 / 候选池等 ≥2 只列表进档案时，写入 `batchBrowse` 会话（内存 + `sessionStorage`）；档案顶栏 `ArchiveBatchRail`（←→ / 返回本批 / 本批列表），侧栏或窄屏抽屉 `ArchiveBatchDock`（有名称不重复展示代码；涨跌按百分数点展示，如 `-0.71%`）；键盘 ←→ 切票；孤立 `StockLink` 不带 `batch` 则无切票。来源文案拆成策略名 + **选股日**（侧栏完整展示日期，顶栏只留日期芯片，悬停看全文），避免两处同一截断串
