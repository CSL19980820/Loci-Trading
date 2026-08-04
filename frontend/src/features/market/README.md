# market

行情数据台、Peek 与盘面首页。

- `PulseView.vue`（路由 `/` · 盘面）：紧凑首页
  - 顶栏：交易日 / 时钟 / 会话 + 刷新（与下方卡片同水平边距）
  - 指数条：`live-tape` 指数 + 仓市值加权涨跌 / 持仓数 / 触价→账本
  - **近选跟踪**：近 5 个交易日精选（`/review/candidates?window_days=5&selected_only=true`）；**同日同代码去重**（优先现行战法 slug，其次更高 score）；列=名称/选股日/策略/选入/最新/涨跌幅/T+1/T+3；选入价=选股日收盘，T+N 以后端为准
  - **市场榜**：涨幅 / 换手 / 跌幅（`/market/board` live）；窄列只显示名称不跟代码
  - **今日选股**：按 `last_trading_day` 取已落库真选（休市不误用自然日）；未跑则空态；调度器启动会补跑错过的盘后选股；同日同代码按 score 去重
  - 交易时段 `useLivePolling` 约 8s 轻刷指数 / 市场榜 / 选股叠价；收盘后不自动 tick
  - 无演示掺假；逻辑在 `composables/usePulseHome.ts` / `pulseHomeLogic.ts`
- `components/PulseIndexStrip.vue` / `PulseTrackTable.vue` / `PulsePickTable.vue` / `PulseMarketBoard.vue`：首页子块；近选跟踪用宽表
- `PeekView.vue`（路由 `/peek`）：桌面托盘「行情」按需创建第二 WebView2 浮窗（启动期不预建，避免双 WebView2 卡死）；失败才回退系统浏览器。贴边缩成约 36–40px 探头（`peekChrome.shouldShowGhost`）；展开态禁透明白块
- `DataQueryView.vue`：默认实时叠价；点行进入 `/archive/:code?view=quote`；翻页/搜索时旧实时响应不会覆盖新列表，避免展示回退到上一页
- `components/DataQueryDetailPanel.vue`：个股 K 线详情
  - 顶栏：返回（可 embedded 隐藏）+ 周期/复权/均线
  - 读盘条为图内**左上悬浮**毛玻璃卡片；日 K **双击**打开 `MinuteSessionDialog`
- `components/MinuteSessionDialog.vue`：分时主图 + 均价线 + 量能；标注当日最高/最低/均价与现价；`GET /api/market/minute/{code}`
- `shared/lib/limitBoard.ts`：涨跌停幅度与触板判定
- K 线：ECharts；日 K 可递增 limit；默认可视 60 根

## README 维护

改首页区块、真源接口或空态语义时同步本文。
