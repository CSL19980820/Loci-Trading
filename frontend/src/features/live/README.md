# 盯盘大屏（Live Board）

## 1. 职责与边界
`features/live` 是全站唯一的「一屏看盘」页面：SSE 消费 + 高密度终端排版，不做交易、不做回测、不改后端计算。

- **职责**：建立行情/信号双 SSE 长连接与退避重连；把全市场快照渲染成定高信息带（指数 / 涨跌分布 / 四榜单 / 信号流）；收盘或断连时给出**得体**的降级形态。
- **边界**：只渲染与消费，不发明数字；不引第二套 UI 库；页面根为 `.page-fill`，不产生文档级滚动条。

## 2. 版型（2026-08 重构后）

```
.page-fill.page-fill--flush.live-board   ← 逃生舱：壳给右侧容器加了内边距，大屏要满幅
├─ LiveTopBar        定高 40px   标识 / 时段 / 时钟 / 会话胶囊 / 刷新 / 全屏 / 返回
├─ IndexBar       定高 64px   5 个固定指数槽位，1px hairline 分隔，右侧 SVG 微图
├─ main      flex:1    grid 1.6fr : 1fr，gap 1px（hairline 由容器底色透出）
│   ├─ 左列
│   │   ├─ HeatStrip 定高 110px  stacked bar + 11 档刻度
│   │   └─ ranks     flex:1      2×2 榜单栅格（≥1800px 摊成 1×4）
│   └─ SignalStream  整列吃满
├─ TickerTape        定高 22px   **无数据时整条不渲染**
└─ LiveStatusBar     定高 24px   源 / 链路 / 标的 / 信号 / 快照时间 + 合规短语
```

三条硬约束（对应 `docs/ui-spec.md` D1/D2/D3）：

- **D1**：红绿只给价格。涨跌榜色条、指数涨跌、信号方向可用红绿；换手率榜用 `--info`、成交额榜用 `--warn`、连接健康用 `--info`（**绝不用绿**，绿在本仓是「跌」）。
- **D2**：最大的字是数字。指数点位与顶栏时钟用 `--fs-hero` 等宽 `tabular-nums`，中文标题一律 `--fs-aux`。
- **D3**：密度优先。全页 **零 box-shadow**，圆角不超过 `--radius`，块与块靠 1px hairline + 底色差分层。

## 3. 空态纪律（重构的首要目标）

重构前收盘态一屏里同一句会话文案出现 **7 次**。现在：

| 层级 | 谁负责 | 形态 |
|---|---|---|
| 会话级（「已收盘·展示最近快照」） | **只有** `LiveTopBar` 的胶囊 | 一行短句，全屏唯一 |
| 块级（信号流 / 四榜单） | `LiveEmptyState` 默认形态 | ≤8 字短语，`--fs-kicker`，居中，整块 ≤40px |
| 指数带 | 不出空态 | 槽位与名称保留，数值位 `—`，整条带降透明度 |
| 涨跌分布 | 不出空态 | stacked bar 压成 1px hairline，刻度值 `—` |
| 跑马灯 | 不出空态 | 整条不渲染 |

文案的唯一出处是 `lib/sessionCopy.ts`：`describeSession()`（会话级长句，只允许顶栏消费）与 `blockHint()`（块级短语）。`LiveEmptyState` 的 `verbose` 属性是逃生舱，业务子块传 `verbose` 视为 review 阻断项。
回归测试 `__tests__/liveBoardView.test.ts` 把「整屏文本里这句话只准出现一次」钉成断言。

## 4. 文件清单

| 文件 | 说明 |
|---|---|
| `LiveBoardView.vue` | 版型编排；`live-theme.css` 在**非 scoped** style 里 `@import`（子组件要吃 `.live-block` / `.live-num`） |
| `live-theme.css` | `--live-*` 全部由全局令牌派生，**出现 `#` 即 bug**；高度契约也定义在这里 |
| `components/LiveTopBar.vue` | 顶栏 + 全屏唯一的会话胶囊 |
| `components/IndexBar.vue` | 高密度指数带（固定 5 槽：上证 / 深成 / 创业板 / 科创50 / 沪深300） |
| `components/IndexSparkline.vue` | 纯 SVG 分时微图；0 点画灰 hairline，1 点画当前点位水平线 + 昨收虚线，≥2 点画折线，**不造假数据** |
| `components/HeatStrip.vue` | 涨跌分布：stacked bar + 11 档刻度 |
| `components/RankColumn.vue` | 榜单列；列头 2px 识别色条；行高 26px |
| `components/SignalStream.vue` | 信号流；不再挂红字免责声明；条数读 `SIGNAL_MAX_ITEMS` |
| `components/TickerTape.vue` | 底部跑马灯，空则不渲染 |
| `components/LiveStatusBar.vue` | 状态栏 + 收编后的合规短语（`--live-dim`，非红） |
| `components/LiveEmptyState.vue` | 极窄块级空态 |
| `lib/sessionCopy.ts` | 会话/块级文案唯一出处 |
| `composables/useLiveBoard.ts` | SSE 编排、退避重连（1s→30s）、页面隐藏挂起、世代作废；信号历史 + 7 天/80 条保留策略 |
| `composables/useBoardInk.ts` | 「暗色盯盘」开关：**默认关，大屏跟随用户外观**；开了才把 `<html>` 钉到 `ink`，偏好记 `localStorage`（`loci-live-ink`） |

## 4.1 信号只有一个来源：真规则引擎

信号流的内容 = `GET /api/market/signals/recent`（首屏历史）+ `/api/market/stream/signals`（推流追加）。
接口 404 / 报错一律空态——**不回退造数据**。`useLiveBoard` 里那段「信号流为空时用涨幅榜 / 成交额榜 /
换手榜提炼收盘复盘信号」（约 80 行）已整块删除：榜单就在同屏左边，把同一份数据换个标签叫「领涨突破」
不是策略，是在骗人。没信号就是没信号。

保留策略（用户需求 5：只看近期、超 7 天销毁、只留最新 80 条）在 `useLiveBoard.ts` 的 `addSignals()`：
先按 `triggeredAt` 丢掉超 `SIGNAL_MAX_AGE_DAYS`(7) 天的，再按时间倒序取 `SIGNAL_MAX_ITEMS`(80) 条。
服务端已经裁过同样的两刀，前端这层是给「挂机过夜、推流一直往上追加」兜底。
规则口径（开关 / 阈值）在设置页「信号规则」面板维护，见 `features/ops`。

## 5. 数据契约

`useLiveBoard()` 返回：`status / **dataStale** / **sourceError** / **staleMs** / lastAsOf / source / sessionPhase / isLive / distribution / quotesMap / indexRows / **indexTrails** / gainersRows / losersRows / turnoverRows / amountRows / signals / newSignalIds / connect / stopStream`。

### 时段与数据源现状来自 `hello` / `heartbeat`，不是等第一帧

后端连上就发 `event: hello`、无新帧时每 15s 发 `event: heartbeat`，载荷是
`{ preset, session: { phase, live }, asOf, staleMs, sourceError, rows, errors }`（见
`shared/api/marketStream.ts` 的 `StreamStatus`）。`useLiveBoard.applyStatus()` 消费它。

**为什么非有不可**：旧版 `phase` / `live` 只从行情帧里取，而后端那时根本没发这两个键，
`session?.phase ?? 'closed'` 于是把每一帧都读成「已收盘」——连续竞价里顶栏挂着
「已收盘·展示最近快照」，`dataStale` 因为 `isLive=false` 永不触发，一屏冻住的数字
没有一处交代原因（用户原话：「哪里都透着一股不像实时的感觉」）。

两条流（行情 `preset=all`、信号 `preset=signals`）各有各的上游，`sourceError` 因此
**按流分开记账**再汇总：混在一个字段里时，信号流那句「我这边没事」会立刻擦掉行情流
刚报的「东财整表挂了」。

### 顶栏时钟是本机秒针，不是快照时间

`LiveTopBar` 每秒自走一次 `clock`。它原先显示 `as_of`（最近一帧的服务端时间），
于是上游一挂或午休一到就永远停在那一秒——盯盘大屏最大的那个数字不动，比任何
错误提示都更像「这东西挂了」。**时钟回答「现在几点」，快照/延迟回答「数据多旧」**，
后者归 `LiveStatusBar`（`快照` + `延迟`，`staleMs<0` 直说「未取到实时数据」）。

### 链路状态与数据新鲜度是两件事

`status` 只描述**链路**：`streamQuotes/streamSignals` 的 `onOpen`(HTTP 200 且 event-stream)一到就是 `connected`，
不再等第一帧。`dataStale: Ref<boolean>` 单独表达「链路好但上游没喂数据」，只在**交易时段**且
超过 45s 没有新帧时为真（收盘后不发新帧是正常的，不报）。

为什么拆开：上游东财全市场截面是大屏与信号预设的唯一数据源，它一挂后端仍会照常保持 SSE 并每 15s 发心跳——
链路完好、只是没数据。旧版把「收到第一帧」当连接判据，于是数据源故障一律显示成
「连接中断 / 重连中」，用户原话「动不动就是连接中断」，照着链路方向排查永远查不到。
文案分流在 `lib/sessionCopy.ts:describeSession(status, isLive, phase, dataStale, sourceError)`。
`PHASE_LABELS` 的键**必须**与后端 `market/application/session.py` 的相位常量逐字对齐
（唯一词表在后端）。午休单独出文案「午间休市·13:00 恢复」——12:00 顶着「已收盘」
正是那张截图里最不像实时的地方。

### 生命周期必须走 activated / deactivated

`PageHost.vue` 用 `<KeepAlive :max="12">` 包住所有非档案路由，**离开大屏不触发 `onUnmounted`**。
`useLiveBoard` 与 `useBoardInk` 都成对注册 `onMounted/onActivated` 与 `onDeactivated/onUnmounted`，
且 `start()/stop()` 幂等——首次挂载在 KeepAlive 里时 `onMounted` 与 `onActivated` **会双双触发**，
不挡就会建两条重复的流。漏掉这一对钩子的后果：SSE 在后台常驻不断累积（且再进来不重连），
外观被墨黑永久钉住（表现为「大屏改了全站主题色」）。

**大屏不替用户决定外观**（2026-08-29）。旧版进大屏就强制墨黑，用户原话「这个大屏还是会改我颜色啊」——
日间档的人点一下「大屏」，整个 App（含侧栏与 EP 弹层）当场变黑。`live-theme.css` 的 `--live-*` 全部派生自
全局令牌，明暗两档本来就都成立，强制墨黑纯粹是主动放弃了这个能力。现在默认跟随外观，想要盯盘墙按顶栏
那颗「暗色」。另外，**恢复靠重放主题 store 而不是 DOM 快照**：快照法在「用户于大屏上改了外观」时会把新
选择原样回滚掉，等于大屏又偷偷改了一次色。

`indexTrails: ShallowRef<Map<string, number[]>>` 是 2026-08 新增的**向后兼容**字段：code → 最近 240 个真实点位，只由推流帧与首屏快照累加。**不要**用 `/market/minute/{code}` 给指数补点：那个端点按 `instrument_type=STOCK` 归一化，`000001` 会返回平安银行的分钟线。

## 6. 相关测试

- `__tests__/liveBoardView.test.ts`：整屏回归（会话文案唯一、指数槽位与 `—`、`page-fill--flush`、四榜色条、空态无跑马灯）。
- `__tests__/components.test.ts`：IndexBar / HeatStrip / RankColumn / SignalStream / TickerTape / LiveEmptyState 的空态与语义色。
- `__tests__/liveBoard.test.ts`：SSE 帧解析与 `shared/lib/tape.ts` 纯函数。
- `__tests__/boardInk.test.ts`：默认不改外观、开关与 `localStorage` 记忆、**KeepAlive 切走即还原/切回再钉**、
  以及「在大屏上改外观时暗色覆盖自动让位，且离开不回滚用户的新选择」。
- `__tests__/useLiveBoard.lifecycle.test.ts`：KeepAlive 下 deactivated 真停流、activated 重建链、历史只回填一次；`onOpen` 即判已连接；交易时段 45s 无帧 → `dataStale` 而 `status` 仍为 connected。
- `__tests__/sessionCopy.test.ts`：链路与数据源分开报，真断线仍照实说。
- `__tests__/liveTopBar.test.ts`：顶栏时段小字与会话胶囊不重复同一个词。
- `__tests__/useLiveBoard.signals.test.ts`：**喂满榜单 + 空信号流断言 signals 为空**（不许再造信号）、超 7 天丢弃、超 80 条只留最新、历史接口 404 不崩、推流追加。
- `__tests__/useLiveBoard.session.test.ts`：没有任何行情帧时相位/live 从 `hello` 就位；
  开着盘却一帧没来立刻判 `dataStale` 并透出 `sourceError`；帧一到就清告警、延迟归零。
- `__tests__/components.test.ts` 另钉：顶栏时钟每秒自走（不显示会冻住的 `as_of`）、
  延迟 chip、午休文案不说「已收盘」、相位标签不漏机器码。
- 命令：`cd frontend && bun run test -- src/features/live`；类型：`bun run typecheck`。
