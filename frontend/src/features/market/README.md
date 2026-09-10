# market

行情数据台、Peek 与盘面首页。

- `PulseView.vue`（路由 `/` · 盘面）：**行情终端式首页**，只回答三件事——大盘怎么走 / 我的池子今天怎么样 / 系统有没有坏
  - 版面自上而下：单行页头 → `SessionRuler` 刻度尺 → 报价带 → 情报 tape（一行）→ 主区（近选跟踪 | 样本榜）→ 底区（今日选股）
  - **单行页头**：`盘面` + 交易日 + 时段 + as-of（等宽）+ 作业健康点 + 「同步现价」「刷新」。**不再有 eyebrow / 衬线大标题**
  - **异常一行制**（`PulseStatusBar`）：原来最多叠 4 条 `el-alert` 把主内容顶下去；现在正常态不占位，出错只有一行「⚠ N 项异常 · 首条标题」+「查看」（`el-popover` 里给全文）+「重试」
  - **作业健康**（`PulseHealthDot` + `usePulseOpsHealth`）：正常时只是页头一枚圆点（说明进 tooltip），有失败运行/读不到才展开成一行，仍链 `/quant?tab=jobs`。只读 `GET /jobs`、`/jobs/schedule`、`/jobs/runs?status=failed`，三请求 `allSettled`
  - **报价带**（`PulseIndexStrip`）：页面最大的字必须是数字——报价 `var(--fs-tape)` 26px 等宽 + `tabular-nums`，涨跌带符号且**只有这里用 --up/--down**；末两格是涨停/跌停（取情报缓存，读不到显示「—」）与触价提醒（>0 用 --warn，不用红绿）
  - **`SessionRuler`（本页签名元素）**：A 股交易日刻度尺，按真实时段比例分段（09:15–09:25 竞价 / 09:30–11:30 早盘 / **午休画成断口** / 13:00–14:57 午盘 / 14:57–15:00 收盘竞价）；已过去实心 `--seal`，未来 `--rule`，当前时刻是 2px `--stamp` 刻针（呼吸动画，`prefers-reduced-motion` 下静止）；右端报「早盘 · 距午休 42 分」，收盘/休市整轨降级并报「距下次开盘 x 小时」。推导是纯函数 `components/sessionRuler.ts`（`sessionRulerLogic.test.ts` 覆盖 09:14/09:20/11:31/12:59/14:58/15:01/周末），30s `setInterval` 且 `onUnmounted`/`onDeactivated` 必清
  - **情报 tape**（`PulseWatchRail`）：`GET /intel/brief` 只读缓存压成一行（晋级/炸板/涨跌家/高度/**断板率+情绪信号**/**跌停+炸板**/**竞价主线**/题材/**最近催化**），截断，全文与缓存时间进 tooltip（另含高标杀名单、两融净额、最大解禁）；无缓存则整行不渲染。后六段来自「配了悟道才采」的复盘/排雷工具，未采时该段为空、不占位
  - **近选跟踪**：近 5 个交易日精选（T～T+4），同日同代码去重，与样本榜一起吃主区剩余高度
  - **样本榜**：涨幅 / 换手 / 板块（库内排序，非全市场领涨；板块=行业成交额加权涨幅）。「非全市场」「实时降级」这类口径**只在 tooltip**，不占版面
  - **今日选股**：底区，**用 flex 分配剩余高度**（不再 `min(22vh, 11.5rem)` 写死），700px 视口下仍保证 6 行可见；开盘前若 `last_trading_day` 已切到自然日，回退 `coverage_last_date`
  - **密度纪律**（`components/pulseSkin.css`，feature 局部、`.pulse-*` 前缀）：尺度全部走令牌、本文件不复述数值——行高 `--row-h` / 表头 `--head-h` / 圆角 `--radius-lg` / hairline 1px / 卡片无阴影（阴影只留给弹层）；卡片头与全局 `.sheet-bar` 同一档（`min-height: --head-h` + `--gap-1`/`--pad-sheet-x`）。`var()` 一律不带 fallback（令牌真值只在 `style.base.css`，写 fallback 只会在改名时静默生效成错值）。数字列一律 `--mono` + `tabular-nums` + 右对齐，涨跌带符号（`signedPct`），代码列等宽次要色、名称列主色。卡片头的 tab 是文本型切换，不是控件：全局把 `.el-button--small` 的 **min-height** 钉在 `--ctl-h`，所以这里用局部契约 `--pulse-tab-h` 连 min-height 一起压
  - **空态不许说谎**（`composables/pulseEmptyState.ts`，纯函数 + 单测）：三档（历史读不到 / 一次都没跑过 / 有历史但窗口空）。表内只放 `trackEmptyShort` / `todayEmptyShort` 的 ≤14 字短句 + 一个「去选股」按钮，长解释进 tooltip
  - 首屏遮罩：会话 + 指数/榜到位后即撤；选股表后台续填，不挡已渲染内容
  - 交易时段 `useLivePolling` 约 8s：`live-tape` 每 tick；市场榜隔 tick（≈16s）；选股叠价同 tick 复用榜内行、仅对缺失 code 发 `codes` spot（`persist:false`）；KeepAlive 离页停表并 bump 世代作废 in-flight
  - 无演示掺假；逻辑在 `composables/usePulseHome.ts` / `pulseHomeLogic.ts` / `usePulseIntelBrief.ts` / `usePulseOpsHealth.ts`
  - **视觉自查**（需 `bunx playwright install chromium` + `bun run vite --port 5173`）：`node e2e/pulse-shots.mjs`（1280×800 / 1440×900 / 700 / 1200 / 880 窄屏 + 降级态截图）、`node e2e/pulse-metrics.mjs`（行高、可见行数、文档级滚动条）、`node e2e/pulse-degraded.mjs`。产物落 `frontend/artifacts/`。**用 node 跑，bun 起 playwright 在本机 launch 超时**
- `components/` 首页子块：`PulseIndexStrip` / `SessionRuler`(+`sessionRuler.ts`) / `PulseStatusBar` / `PulseHealthDot` / `PulseWatchRail` / `PulseTrackTable` / `PulsePickTable` / `PulseMarketBoard` / `pulseSkin.css`
- `PeekView.vue`（路由 `/peek`）：桌面托盘「行情」按需创建第二 WebView2 浮窗（启动期不预建，避免双 WebView2 卡死）；失败才回退系统浏览器。贴边缩成约 36–40px 探头（`peekChrome.shouldShowGhost`）；展开态禁透明白块。**只显示指数条与时钟**：原「仓 x%」徽标与「持仓·今日」列表随持仓下线一并移除，窗口标题不再带仓位涨跌
- `DataQueryView.vue`：默认实时叠价；点行进入 `/archive/:code?view=quote`；翻页/搜索时旧实时响应不会覆盖新列表；`useDataQueryMarket` KeepAlive 离页停表、回页按 `liveOn` 重启；列表 `busy` 与实时世代分离，避免首屏 `onActivated→startRefresh` 与 `loadBoard` 竞态永久转圈。**一次列表加载只探一次 `/market/session`**：`loadBoard` / `watch(liveOn)` 探到结果后用 `startRefresh(allowed)` 透传，只有 `onActivated`（离页回来）才重新探测。公开契约是导出的 `DataQueryMarket` 接口，别用 `ReturnType<typeof useDataQueryMarket>` 反推
- `components/DataQueryDetailPanel.vue`：个股 K 线详情
  - 顶栏：返回（可 embedded 隐藏）+ 周期/复权/均线
  - 现盘条为图内**左上悬浮**毛玻璃卡片；日 K **双击**打开 `MinuteSessionDialog`
- `components/MinuteSessionDialog.vue`：分时主图 + 均价线 + 量能；标注当日最高/最低/均价与现价；`GET /api/market/minute/{code}`
- `shared/lib/limitBoard.ts`：涨跌停幅度与触板判定
- K 线：ECharts；日 K 可递增 limit；默认可视 60 根

## README 维护

改首页区块、真源接口或空态语义时同步本文。
