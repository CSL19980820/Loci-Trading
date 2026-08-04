# 战法回测落地计划 · Horizon T+N

> 状态：P0/P2 已落地（horizon 引擎 + API + 工坊「回测」Tab）；P1 ensure_data / P3 明细待续  
> 范围：`backtest` + `market` 数据共用 + `strategy` HTTP/UI  
> 非目标：本阶段不改成交引擎止损/止盈细规则；不写 `palace.db`

---

## 1. 问题与现状

### 用户要的能力

一次指定战法 + 区间（**最长 6 个月**），跑完整选股信号回放，产出：

| 指标 | 含义 |
|------|------|
| T+1 / T+3 持股收益 | 按买卖时点对齐后的窗口收益 |
| 胜率 | 收益 > 0 的事件占比 |
| 平均 / 最高 / 最低 | 事件收益分布的 mean / max / min |

数据侧：**区间内行情尽量一次拉齐、共用面板**，不要每个信号日再打一遍单票 history。

### 现有能力（可复用，不可直接当产品）

| 模块 | 做什么 | 缺口 |
|------|--------|------|
| `backtest.application.engine` | 信号 → 成交（入场价、持有、止损止盈） | 问的是「模拟交易账本」，不是「选股日后视窗口」 |
| `review.application.outcomes` | 候选事后 T+N（收盘/收盘） | 只看已入库候选；按票拉 history；主 KPI 用收盘不是卖出日最高 |
| `POST /api/backtest` | 同步跑成交回测 | 无 6 个月硬顶；前端几乎无触发入口（仅有结果面板残骸） |
| `MarketStore.load_panel` + `runner._expand_range` | 预热 + 尾巴一次装面板 | 未与「缺段补录」绑成回测前置契约 |

结论：需要一条新的 **Horizon 回测** 路径（信号级 T+N），与现有成交回测并存；UI 重新做入口。

---

## 2. T+N 口径（权威定义）

### 2.1 符号

- **D**：选股日 / 信号日（`signal_date`），交易日历日。
- **base**：`close(D)`，**一律用选股日收盘**作分母（与用户举例一致；禁止用入场开盘偷换分母）。
- **entry_timing**：来自策略/技能声明，**禁止请求体覆盖成前视**。
- **N**：持有交易日数（本阶段固定评估 **N ∈ {1, 3}**）。

### 2.2 入场与标记日（卖出观察日）

| `entry_timing` | 入场日 E | T+N 标记日 M | 典型场景 |
|----------------|----------|--------------|----------|
| `close` | D | D + N | 尾盘买 → 次日卖 ⇒ T+1 的 M = D+1 |
| `open` | D | D + N | 当日开盘可买（竞价策略） |
| `next_open` | D+1 | D+1 + N | 盘后出票 → 次日买 → 再持 N 日卖；T+1 的 M = D+2 |

用户原话对齐：

- 尾盘买、第二天卖 → `high(D+1) / close(D)` = **T+1**
- 第二天买、第三天卖 → `high(D+2) / close(D)` = **T+1**（`next_open` + N=1）

### 2.3 单事件收益（主 KPI）

对每个有效信号事件：

```text
r_high(N) = high(M) / close(D) - 1     # 主口径：卖出日最高 / 选股日收盘
r_low(N)  = low(M)  / close(D) - 1     # 辅：同日最低（风险下沿）
r_close(N)= close(M)/ close(D) - 1     # 辅：收盘对照（与 review outcomes 可对表）
```

缺行情 / 停牌 / 一字无法成交等：计入 `skipped`，**不进胜率分母**（与成交引擎 skip 哲学一致）。

### 2.4 聚合（每个 N 各一份）

对 `{ r_high(N) }`：

- `n` / `win_rate`（>0）/ `avg` / `best`（最高）/ `worst`（最低）
- 可选：`median`、按月分桶（二期）

**禁止**前端重算胜率与收益；只展示引擎返回字段。

### 2.5 与成交回测的关系

| | Horizon T+N（本计划主产品） | 成交回测（保留） |
|--|---------------------------|------------------|
| 问题 | 这套选股事后窗口有没有 alpha | 按规则买卖能赚多少（含止损） |
| 分母 | 选股日收盘 | 入场价 |
| 分子 | 标记日 high（主） | 实际 exit 价 |
| API | 新建或扩展模式 | 现有 `/api/backtest` |

同一 `signals` 面板可喂两条路径；**默认 UI 只暴露 Horizon**。

---

## 3. 数据共用策略

### 3.1 区间硬约束

- 信号窗口 `[start, end]`：**自然日跨度 ≤ 186 天**（约 6 个月）；超限 API `422`。
- 装载窗口：

```text
load_start = start - warmup(min_bars+20)
load_end   = end   + max(N) + entry_offset_tail   # next_open 再 +1
```

一次 `load_panel(fields, codes, load_start, load_end)`，信号计算与 T+N 计价**共用同一 panels**。

### 3.2 补录（ensure coverage）

回测前编排（application 层，不进路由）：

1. 解析 universe → codes  
2. 查 `market` 水位 / 交易日覆盖：是否覆盖 `[load_start, load_end]`  
3. 若缺口：对该 codes **一次** `sync_quotes`（或现有 bootstrap/增量入口），目标区间拉齐  
4. 再 `load_panel` → `engine.compute` → horizon 聚合  

原则：

- **不要**按信号日循环 `history(code)`（outcomes 路径的反例，全市场回测会炸）  
- 预热段与尾巴只服务指标与 T+N，**信号过滤仍裁到 `[start, end]`**（与现 `runner` 一致）  
- 结果携带 `data_snapshot`（revision / adjust / load 区间）便于复现  

### 3.3 性能预算（单机）

- 默认 universe ≈ 全 A 剔 ST：6 个月 × 日频面板可接受；优先复用 `LOCI_MARKET_DUCKDB` 只读加速（若已开）  
- 同步 HTTP：短区间可同步；全市场 + 首次补录 → **202 + Job**（对齐 `screen/run` / analysis）  
- 环境变量旁路：成交 fast 引擎与 Horizon **无关**；Horizon 用 numpy 向量化扫信号即可  

---

## 4. 后端设计（DDD）

### 4.1 归属

```
src/backtest/
  application/
    horizon.py      # 新增：signals + panels → T+N 事件与聚合
    runner.py       # 扩展：backtest_strategy(..., mode="horizon"|"trade")
                    # 或新增 backtest_strategy_horizon()
  domain/           # 可选：HorizonMetrics 值对象
```

- 读：`market` 公开 API、`strategy` 引擎  
- 不写 `palace`  
- `review.outcomes` **不搬来当回测**；可抽纯函数「给定 base/high 算收益」到 `backtest` 或 `shared` 极薄工具，避免 review↔backtest 环依赖  

### 4.2 API 契约（建议）

**方案 A（推荐）**：扩展现有入口，显式模式

```http
POST /api/backtest
{
  "strategy": "slug",
  "start": "YYYY-MM-DD",
  "end": "YYYY-MM-DD",
  "mode": "horizon",          # 默认可改为 horizon；trade = 旧成交
  "horizons": [1, 3],
  "mark": "high",             # high | close（主产品固定 high）
  "universe": { ... },
  "params": { ... },
  "ensure_data": true,        # 缺段先补录
  "include_events": false
}
```

响应（horizon）：

```json
{
  "strategy": "...",
  "mode": "horizon",
  "config": { "range": {}, "entry_timing": "close", "data_snapshot": {} },
  "horizons": {
    "t1": { "n": 120, "win_rate": 55.0, "avg": 2.1, "best": 18.0, "worst": -9.5 },
    "t3": { "n": 118, "win_rate": 51.2, "avg": 3.4, "best": 27.0, "worst": -12.0 }
  },
  "skipped": { "标记日无行情": 2 },
  "events": []
}
```

校验：

- `end - start ≤ 186d`  
- `horizons ⊆ {1,3}`（一期；扩展需改契约）  
- `entry_timing` 只读引擎  

异步：`ensure_data` 且预计耗时长 → `202` + ops Job `kind=backtest`（config 带 mode）。

### 4.3 测试（DoD）

| 用例 | 断言 |
|------|------|
| `close` + T+1 | `high[D+1]/close[D]-1` |
| `next_open` + T+1 | `high[D+2]/close[D]-1` |
| 区间 > 6 月 | 422 |
| 面板一次装载 | mock store：`load_panel` 调用次数 = 1 |
| 跳过缺 M 日 | 不进 n |
| 不前视 | 信号仅用 ≤D 数据（沿用策略测试） |

目录：`tests/backtest/test_horizon.py`

---

## 5. 前端设计（产品壳）

### 5.1 入口

挂在**选股台**（`ScreenHistoryView`）比工坊更合适：同一战法目录，动作从「选股」旁加「回测」。

结构（拆分，单文件 ≤600 行）：

```
features/strategy/
  components/
    ScreenBacktestPanel.vue      # 区间 / 跑 / 进度
    ScreenBacktestHorizonCards.vue  # T+1 T+3 四格：胜率·均·高·低
    ScreenBacktestEventsTable.vue    # 可选明细
  composables/
    useScreenBacktest.ts         # 调 API / 轮询 Job；不重算数字
```

Element Plus：日期范围、按钮、表格、空态；根 `.page-fill`，表体自滚。

### 5.2 交互要点

1. 选战法 → 选 ≤6 个月区间（控件硬顶）  
2. 展示 `entry_timing` 只读说明（「尾盘买 / 次日开」）  
3. 主按钮「跑回测」→ loading / Job 进度  
4. 结果区：**T+1 | T+3** 双列；每列 胜率 / 平均 / 最高 / 最低 / n  
5. 口径脚注一行：`标记日最高 ÷ 选股日收盘 − 1`  
6. 数据提示：缺段时文案「先补齐 load 区间再算」，成功后带 snapshot 水位  

视觉方向见同目录设计方案 canvas（签名件：选股日→入场→标记日时间轴）。

### 5.3 类型

`shared/types` 增加 `HorizonBacktestResult`；`quant_strategy.ts` 增加 `runHorizonBacktest`（或 `runBacktest` 带 mode）。  
废弃路径：无入口的旧 `QuantResultsPanel` 成交摘要可并入「高级 / 成交模式」折叠，默认不抢主路径。

---

## 6. 分期落地

| 阶段 | 交付 | 验收 |
|------|------|------|
| **P0** | `horizon.py` + 单测口径 + API `mode=horizon` + 6 月校验 | pytest 绿；手工 curl 一例 |
| **P1** | `ensure_data` 一次补录 + `data_snapshot` | 缺口仓补后可跑；面板单次 load |
| **P2** | 选股台 UI + Job 异步 | typecheck/test；无文档级滚动 |
| **P3** | 事件明细表、按月分桶、与目录胜率对表 | README / api README 同步 |

本 goal 当前检查点只交付：**本计划 + canvas 设计方案**；实现从 P0 起另开回合。

---

## 7. 边界与红线

- AI / 前端 **不发明**收益数字  
- **禁止前视**：信号只用 ≤D；分母用 `close(D)` 不偷看 M  
- market 只缓存可重建行情；回测结果默认不落权威表（Job run 可留摘要）  
- 跨上下文：只经 `src.market` / `src.strategy` 包根  
- 与 `review` 目录胜率：口径不同（候选事后 close vs 全信号 high）；UI 文案必须区分「目录跟踪」vs「战法回测」

---

## 8. 相关入口索引

- 成交引擎：`src/backtest/application/engine.py`  
- Runner：`src/backtest/application/runner.py`  
- HTTP：`src/strategy/api/router.py` → `POST /api/backtest`  
- 请求模型：`src/app/legacy/quant_common.py` → `BacktestRequest`  
- 候选 T+N（对照）：`src/review/application/outcomes.py`  
- 前端 API：`frontend/src/shared/api/quant_strategy.ts` → `runBacktest`  
- 选股台：`frontend/src/features/strategy/ScreenHistoryView.vue`
