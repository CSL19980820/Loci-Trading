# market

行情数据台、Peek 与盘面首页。

页面沿用全站冷色终端令牌：标题与操作使用图标建立层级，数字使用等宽字和涨跌符号，裁决或运行状态不占用红绿。盘面布局样式通过 `style scoped src="./PulseView.css"` 引用；桌面分配主区与底区高度，窄屏将面板依次排列并在页面内部滚动。行情台名称、行业左对齐，报价、涨跌、换手和成交额右对齐。Peek 的指数随窗口宽度重排，缺报价时展示真实空态，关闭、拖动与贴边协议保留。

- `PulseView.vue`（路由 `/` · 盘面）：**行情终端式首页**，只回答三件事——大盘怎么走 / 我的池子今天怎么样 / 系统有没有坏
  - 版面自上而下：单行页头 → `SessionRuler` 刻度尺 → 报价带 → 情报 tape（一行）→ 主区（近选跟踪 | 样本榜）→ 底区（今日选股）
  - **单行页头**：`盘面` + 交易日 + 时段 + as-of（等宽）+ 作业健康点 + 「同步现价」「刷新」。**不再有 eyebrow / 衬线大标题**
  - **异常一行制**（`PulseStatusBar`）：原来最多叠 4 条 `el-alert` 把主内容顶下去；现在正常态不占位，出错只有一行「⚠ N 项异常 · 首条标题」+「查看」（`el-popover` 里给全文）+「重试」
  - **作业健康**（`PulseHealthDot` + `usePulseOpsHealth`）：正常时只是页头一枚圆点（说明进 tooltip），有失败运行/读不到才展开成一行，仍链 `/quant?tab=jobs`。只读 `GET /jobs`、`/jobs/schedule`、`/jobs/runs?status=failed`，三请求 `allSettled`
  - **报价带**（`PulseIndexStrip`）：报价使用 `--fs-tape`、等宽字与 `tabular-nums`，涨跌带符号；槽位固定五个（上证/深成/创业/科创50/沪深300），缺报价显示「—」并保留名称与文字对比度。窄屏可横向浏览；末两格是涨停/跌停（取情报缓存，读不到显示「—」）与触价提醒（>0 用 `--warn`）
  - **`SessionRuler`**：A 股交易日刻度尺按真实时段比例分段（09:15–09:25 竞价 / 09:30–11:30 早盘 / 午休断口 / 13:00–14:57 午盘 / 14:57–15:00 收盘竞价）。已过去与当前刻针使用 `--seal`，未来使用 `--rule`；`prefers-reduced-motion` 下刻针动画静止。右侧显示真实时段与倒计时，窄屏可换行。推导在 `components/sessionRuler.ts`，30s 定时器由 `onUnmounted` / `onDeactivated` 清理
  - **情报 tape**（`PulseWatchRail`）：`GET /intel/brief` 只读缓存压成一行（晋级/炸板/涨跌家/高度/**断板率+情绪信号**/**跌停+炸板**/**竞价主线**/题材/**最近催化**），截断，全文与缓存时间进 tooltip（另含高标杀名单、两融净额、最大解禁）；无缓存则整行不渲染。后六段来自「配了悟道才采」的复盘/排雷工具，未采时该段为空、不占位
  - **近选跟踪**：近 5 个交易日精选（T～T+4），同日同代码去重，与样本榜一起吃主区剩余高度
  - **样本榜**：涨幅 / 换手 / 板块（库内排序，非全市场领涨；板块=行业成交额加权涨幅）。「非全市场」「实时降级」这类口径**只在 tooltip**，不占版面
  - **今日选股**：桌面用 flex 分配剩余高度，内容在表体内滚；窄屏面板保留最小高度。开盘前若 `last_trading_day` 已切到自然日，回退 `coverage_last_date`
  - **密度纪律**（`components/pulseSkin.css`，`.pulse-*` 前缀）：行高、表头、圆角、间距统一使用令牌，面板无阴影；表头用紧凑图标与正文级标题。数字列使用 `--mono`、`tabular-nums` 与右对齐，名称与代码保留足够列宽。表头切换按钮的 `--pulse-tab-h` 引用 `--ctl-h`，与主工作台保持一致的点击面积
  - **空态不许说谎，也不许卸骨架**（`composables/pulseEmptyState.ts` + 三张密度表）：三档（历史读不到 / 一次都没跑过 / 有历史但窗口空）。表内只放 `trackEmptyShort` / `todayEmptyShort` 的 ≤14 字短句 + 一个「去选股」按钮，长解释进 tooltip。**无数据仍渲染 `el-table` 列头**，短句走 `#empty`，不把主区塌成白板
  - 首屏遮罩：会话 + 指数/榜到位后即撤；选股表后台续填，不挡已渲染内容
  - 交易时段 `useLivePolling` 约 8s：`live-tape` 每 tick；市场榜隔 tick（≈16s）；选股叠价同 tick 复用榜内行、仅对缺失 code 发 `codes` spot（`persist:false`）；KeepAlive 离页停表并 bump 世代作废 in-flight
  - 无演示掺假；逻辑在 `composables/usePulseHome.ts` / `pulseHomeLogic.ts` / `usePulseIntelBrief.ts` / `usePulseOpsHealth.ts`
  - **视觉自查**（需 `bunx playwright install chromium` + `bun run vite --port 5173`）：`node e2e/pulse-shots.mjs`（1280×800 / 1440×900 / 700 / 1200 / 880 窄屏 + 降级态截图）、`node e2e/pulse-metrics.mjs`（行高、可见行数、文档级滚动条）、`node e2e/pulse-degraded.mjs`。产物落 `frontend/artifacts/`。**用 node 跑，bun 起 playwright 在本机 launch 超时**
- `components/` 首页子块：`PulseIndexStrip` / `SessionRuler`(+`sessionRuler.ts`) / `PulseStatusBar` / `PulseHealthDot` / `PulseWatchRail` / `PulseTrackTable` / `PulsePickTable` / `PulseMarketBoard` / `pulseSkin.css`
- `PeekView.vue`（路由 `/peek`）：桌面托盘「行情」按需创建第二 WebView2 浮窗（启动期不预建，避免双 WebView2 卡死）；失败才回退系统浏览器。贴边缩成约 36–40px 探头（`peekChrome.shouldShowGhost`）；展开态禁透明白块。**只显示指数条与时钟**：原「仓 x%」徽标与「持仓·今日」列表随持仓下线一并移除，窗口标题不再带仓位涨跌
- `DataQueryView.vue`：默认实时叠价；点行进入 `/archive/:code?view=quote`；翻页/搜索时旧实时响应不会覆盖新列表；`useDataQueryMarket` KeepAlive 离页停表、回页按 `liveOn` 重启；列表 `busy` 与实时世代分离，避免首屏 `onActivated→startRefresh` 与 `loadBoard` 竞态永久转圈。**一次列表加载只探一次 `/market/session`**：`loadBoard` / `watch(liveOn)` 探到结果后用 `startRefresh(allowed)` 透传，只有 `onActivated`（离页回来）才重新探测。公开契约是导出的 `DataQueryMarket` 接口，别用 `ReturnType<typeof useDataQueryMarket>` 反推
- `components/DataQueryDetailPanel.vue`：个股 K 线详情
  - 顶栏：返回（可 embedded 隐藏）+ 周期/复权/均线
  - 周期、复权、均线设置沿用统一控件高度，图标与可访问名称齐全；均线最多八行，到达上限时禁用添加。图中读数保留文本访问，不对每次十字光标移动发出播报
  - 现盘条为图内**左上悬浮**毛玻璃卡片；日 K **双击**打开 `MinuteSessionDialog`
- `components/MinuteSessionDialog.vue`：分时主图 + 均价线 + 量能；日期与来源按返回内容展示，历史分时不标成「实时」。高低价与昨收比较后使用涨跌色，未知基准保持中性；读取接口仍为 `GET /api/market/minute/{code}`
- `shared/lib/limitBoard.ts`：涨跌停幅度与触板判定
- K 线：ECharts；日 K 可递增 limit；默认可视 60 根

## README 维护

改首页区块、真源接口或空态语义时同步本文。
