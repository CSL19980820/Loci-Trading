# market

行情数据台、Peek 与盘面首页。

- `PulseView.vue`（路由 `/` · 盘面）：紧凑首页
  - 顶栏：交易日 / 时钟 / 会话 + **同步现价**（`POST /api/market/board/spot` 显式落盘，与轮询解耦）+ 刷新
  - 指数条：`live-tape` 指数 + 触价提醒计数（`GET /api/alerts/today`，plan 口径）。**持仓下线后不再显示「我的仓」市值加权涨跌与持仓只数**，`live-tape` 的 positions 已不消费
  - **盘面监控带**（`PulseWatchRail`）：**二波监测** + 短线情报
    - 二波：`GET /api/skills/dragon-second-wave/second-wave` 读上一轮扫描快照并叠当日现价；盘中约 30s 轮询；任务本身每 5 分钟用全市场现价重跑
    - 情报：`GET /api/intel/brief` 只读缓存；有数据时展示涨停/跌停/晋级等；无悟道时只留标题、不堆空态说明
  - **近选跟踪**：近 5 个交易日精选；同日同代码去重；与库内样本榜一起吃主区剩余高度；列均 min-width（名称 120 / 选股日·选入·最新·涨跌幅·低→高·T+1·T+3 各 80 / 策略 120 置最右），表头与内容居中
  - **库内样本榜**：涨幅 / 换手 / 板块（库内排序，非全市场领涨；板块=行业成交额加权涨幅，可叠实时价）；序号 60，名称·涨幅/换手·板块 min-width 120，列头居中；换手优先用成交额/(价×流通股本) 校正单位错位
  - **今日选股**：高度压低；列 序号 60 / 标的 200 / 策略 min 240 / 今涨 160 / 评分 160（表头与内容居中）；开盘前若 `last_trading_day` 已切到自然日，回退 `coverage_last_date` 取最近落库真选；盘中/盘后仍跟 `last_trading_day`；未跑则空态；同日同代码按 score 去重；历史经 `GET /api/screen/history/batch` 一次拉取
  - 首屏遮罩：会话 + 指数/榜到位后即撤；选股表后台续填，不挡已渲染内容
  - 交易时段 `useLivePolling` 约 8s：`live-tape` 每 tick；市场榜隔 tick（≈16s）；选股叠价同 tick 复用榜内行、仅对缺失 code 发 `codes` spot（`persist:false`，避免写鉴权 401）；**KeepAlive 离页停表并 bump 世代作废 in-flight、回页重启**；收盘后不自动 tick；情报条仅随整页刷新/交易日变化重读缓存
  - 无演示掺假；逻辑在 `composables/usePulseHome.ts` / `pulseHomeLogic.ts` / `usePulseIntelBrief.ts` / `usePulseSecondWave.ts`
- `components/PulseIndexStrip.vue` / `PulseIntelStrip.vue` / `PulseSecondWaveStrip.vue` / `PulseWatchRail.vue` / `PulseTrackTable.vue` / `PulsePickTable.vue` / `PulseMarketBoard.vue`：首页子块
- `PeekView.vue`（路由 `/peek`）：桌面托盘「行情」按需创建第二 WebView2 浮窗（启动期不预建，避免双 WebView2 卡死）；失败才回退系统浏览器。贴边缩成约 36–40px 探头（`peekChrome.shouldShowGhost`）；展开态禁透明白块。**只显示指数条与时钟**：原「仓 x%」徽标与「持仓·今日」列表随持仓下线一并移除，窗口标题不再带仓位涨跌
- `DataQueryView.vue`：默认实时叠价；点行进入 `/archive/:code?view=quote`；翻页/搜索时旧实时响应不会覆盖新列表；`useDataQueryMarket` KeepAlive 离页停表、回页按 `liveOn` 重启；列表 `busy` 与实时世代分离，避免首屏 `onActivated→startRefresh` 与 `loadBoard` 竞态永久转圈
- `components/DataQueryDetailPanel.vue`：个股 K 线详情
  - 顶栏：返回（可 embedded 隐藏）+ 周期/复权/均线
  - 现盘条为图内**左上悬浮**毛玻璃卡片；日 K **双击**打开 `MinuteSessionDialog`
- `components/MinuteSessionDialog.vue`：分时主图 + 均价线 + 量能；标注当日最高/最低/均价与现价；`GET /api/market/minute/{code}`
- `shared/lib/limitBoard.ts`：涨跌停幅度与触板判定
- K 线：ECharts；日 K 可递增 limit；默认可视 60 根

## README 维护

改首页区块、真源接口或空态语义时同步本文。
