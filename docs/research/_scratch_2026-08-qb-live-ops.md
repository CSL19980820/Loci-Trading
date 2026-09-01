# 信号之后：实盘骨架、风控前置、实验可复现与静默失败（scratch）

> **日期**：2026-08-25 ｜ **检索日期**：2026-08-25
> **用途**：供上层综述引用。回答「信号产生之后主流量化系统还有什么」，以及「实验管理 / 可复现该抄哪一段、不该抄哪一段」。**本文是台账与方案，不是改动**。
> **范围**：只读。除本文件外未改任何仓库文件，未 commit / push，未写任何库，未安装任何依赖。
> **证据分级**：`P1` 上游源码原文本轮逐行读完（GitHub raw）；`P2` 上游官方文档正文本轮读完、实现未读；`L` 本仓源码 / README 原文（带路径）；`M` **主 agent dbstat 实测 2026-08-25**（只读 `E:\entertainment_software\Loci\data`，不是仓库里那个空 `data/`）；`X` 本轮实测的 PyPI 元数据与 wheel 体积。
> **⚠ 任务书有两处前提已过期**，见 §0.2。**本文按代码现状写，不按任务书前提写**——否则会产出一份「建议你做已经做完的事」的方案。

---

## 0. 方法、边界与两处前提修正

### 0.1 本轮实际读到的一手来源

| # | 来源 | 级 | 取到了什么 |
|---|---|---|---|
| 1 | `vnpy/vnpy_riskmanager` · `vnpy_riskmanager/engine.py`（main） | P1 | `RiskEngine.patch_functions()` 用**猴补** `main_engine.send_order` 的方式插进下单路径；`check_allowed()` 遍历规则，任一 False 即 `return ""`（空委托号＝拦截）；拦截走 `EVENT_LOG` + `EVENT_RISK_NOTIFY` + `winsound` |
| 2 | 同上 · `rules/{order_size,order_validity,active_order,duplicate_order,daily_limit}_rule.py` | P1 | 五条内置规则的**默认阈值原文**，见 §2.1 |
| 3 | `vnpy/vnpy` · `vnpy/trader/engine.py`（master） | P1 | `MainEngine` 持有 `gateways`/`engines`/`apps`/`exchanges` 四张表；`BaseEngine` 抽象基类只吃 `(main_engine, event_engine, engine_name)`；事件常量 `EVENT_TICK/ORDER/TRADE/POSITION/ACCOUNT/CONTRACT/LOG/QUOTE` |
| 4 | NautilusTrader 官方文档 `concepts/live` | P2 | `LiveNode::run()` 生命周期：**先备好 cache 与 venue 状态、再启动 trader 组件**；连接/对账/启动任一失败即 abort；`QueueMonitorConfig` 对五条 runner 通道（`time_events`/`exec_events`/`exec_commands`/`data_events`/`data_commands`）做 trigger+clear **双阈值**；100 ms 维护 tick |
| 5 | NautilusTrader 官方文档 `concepts/reconciliation` | P2 | **只有 `LiveExecutionEngine` 做对账**；三段式 `generate_order_status_reports` → `generate_fill_reports` → `generate_position_status_reports`；**启动对账失败就不启动系统**；运行期持续检查 in-flight 订单 / open orders / positions / own books |
| 6 | `QuantConnect/Lean` · `Engine/RealTime/LiveTradingRealTimeHandler.cs`（master） | P1 | 独立线程 `Run()` **每秒**唤醒遍历 `ScheduledEvents`，按 id 排序保证确定性；`GetTimeMonitorTimeout()=500`；`Setup()` 挂一条周期任务**定时重刷 MarketHoursDatabase / SymbolPropertiesDatabase** |
| 7 | Lean `Algorithm.Framework/Risk/` 目录 + 两个模型全文 | P1 | 内置只有五个模型（§2.2）；`MaximumDrawdownPercentPortfolio` 触发后**先 `insights.cancel` 再把 target 全置 0**；`MaximumSectorExposure` 用 `ratio>1` **等比缩仓**而非清仓 |
| 8 | PyPI `mlflow`/`mlflow-skinny`/`pandera`/`great_expectations`/`dvc`/`wandb` JSON | X | `requires_dist` 基础依赖数与 cp312-manylinux wheel 体积，见 §3.1 |
| 9 | 本仓 `src/market`、`src/ops`、`src/research`、`src/review`、`src/ai` 源码与 README | L | 见正文逐条引用 |
| 10 | 主 agent dbstat 实测 | M | `market.db` 5,740.2 MB、溯源审计占 44.8%；`strategy_backtests`/`strategy_versions` **0 行**；`instruments.delist_date` 填充数 **0** |

**没取到 / 已降级的**：`nautilus_trader` 的 `live/execution_engine` 源码本轮 raw 与目录 API 均 404/403（该包已大幅 Rust 化、Python 侧路径变动），所以 nautilus 部分**只用官方文档正文**（P2），不冒充读过实现；web_search 六家 provider 全被 bot 墙拦截，本轮**未使用搜索**，所有外部结论都来自直接 URL 读取。

### 0.2 ⚠ 任务书两处前提已过期（先读这条，否则整篇方案都会跑偏）

| 任务书原话 | 代码现状 | 证据 |
|---|---|---|
| Loci「**没有订单对象、没有风控前置**」 | **两样都有。** `PaperOrder` 是完整的订单意图对象（`code/action/layers/mark_price/reason/decided_by`，9 种 action、买卖两族常量）；`validate_and_normalize_order()` 就是 pre-trade gate，返回 `(规范化订单, 拒单原因)`；拒单落 `paper_rejects` 表 | `src/ops/application/paper_exec.py`：`PaperOrder` / `BUY_ACTIONS` / `SELL_ACTIONS` / `validate_and_normalize_order` / `execute_orders` → `store.insert_paper_reject` |
| 二波「**还没接 `skill_watch`、没建 Job**」 | **都接了。** 引擎 `second_wave` 已在 `skill_watch/` 注册；`ensure_second_wave_watch_job()` 启动时幂等挂 `监测·dragon-second-wave`，cron `*/5 9-14 * * mon-fri`；每轮快照写 `meta.second_wave_latest`；触发留痕表 `second_wave_signals`（只追加，**未达 45 分线 / 未过宽度闸的也写**——观察期要留反例） | `src/ops/application/ensure_second_wave_job.py`；`src/ops/README.md`「二波监测」段 |

那篇观察期规格（`2026-08-dragon-second-wave-live-alert-spec.md` §6「生产接入的前置条件」）列的五项前置——引擎注册、`tuning.FIELD_META` 登记、ops.db 只追加留痕表、单独开舱、企微降噪——**逐条都已落地**。该文档头部的「未接入」状态标记本身已经过期，属于文档债，不是工程缺口。

**所以本文的落点必须改**：不是「教 Loci 抄一套订单/风控」，而是回答三个真问题——(a) 已有的那套 pre-trade gate **漏了哪几项**（§2.4）；(b) 「不自动下单」的系统里，风控该换成什么形态（§2.3 判定列）；(c) **真正零覆盖的两块**是「实验可复现」（§3，`strategy_backtests` 0 行实锤）与「回测-实盘偏离」（§4，该能力 2026-08 被**主动删除**）。

---

## 1. 实盘/模拟盘的架构模式：抽出最小骨架

### 1.1 三家怎么分层（一手对照）

| 维度 | vn.py | NautilusTrader | Lean |
|---|---|---|---|
| 总线 | `EventEngine`（进程内队列 + 定时器事件 `EVENT_TIMER`），`MainEngine` 持 `gateways`/`engines`/`apps`/`exchanges` 四表 | Rust `LiveNode` 拥有事件循环，五条 runner 通道分离（time/exec_events/exec_commands/data_events/data_commands） | `IAlgorithm` + 独立 `LiveTradingRealTimeHandler` 线程 |
| 行情入口 | `BaseGateway` 推 `EVENT_TICK` | `LiveDataEngine`（data_events / data_commands 两条通道） | DataFeed → `Slice` |
| 策略回调 | App 引擎注册事件回调 | actors / strategies（**与回测同一套对象**） | `OnData` / `ScheduledEvent` |
| 订单意图 | `OrderRequest` 值对象 | `SubmitOrder` 命令 | `PortfolioTarget` |
| 风控前置 | `RiskEngine.patch_functions()` **猴补** `MainEngine.send_order`，拦截即 `return ""` | 引擎级 command 校验 + 队列压力监控 | `RiskManagementModel.manage_risk(algorithm, targets)` **改写 targets** 而非拒单 |
| 网关 | `BaseGateway.send_order` → 柜台 | `ExecutionClient`（有 write-once 的 execution-client origin 绑定） | `IBrokerage` |
| 回报 | `EVENT_ORDER` / `EVENT_TRADE` | 订单事件流（event-sourced） | `OrderEvent` |
| 持仓/资金同步 | `OmsEngine` 缓存 + `OffsetConverter`；`EVENT_POSITION`/`EVENT_ACCOUNT` | **`LiveExecutionEngine` 三段式对账**（order status → fill → position），启动失败即不启动 | `SecurityPortfolioManager` + brokerage 同步 |
| 落库 | 各 App 自理（`load_json`/`save_json` 存配置） | cache database（**建议持久化全部执行事件**，减少对交易所历史的依赖） | `IResultHandler` |
| 时钟/日历 | `EVENT_TIMER` | 100 ms 维护 tick | 每秒扫 `ScheduledEvents`，并**周期重刷交易时段库与合约属性库** |

**三家的共同点不是「有订单对象」，而是三条不变量**：

1. **风控在网关之前，而且是不可绕过的同一个入口。** vn.py 干脆猴补掉 `send_order`——不是让策略「记得调用检查」，是让策略**没法不调用**。
2. **持仓真相来自对账，不来自自己的累加。** Nautilus 把这条推到极致：启动对账失败就不启动；跑起来还要持续比 in-flight / open / position / own-book 四类。
3. **时钟与静态数据会漂，必须定期重取。** Lean 专门挂一条定时任务重刷 `MarketHoursDatabase` / `SymbolPropertiesDatabase`——交易日历不是常量。

### 1.2 最小骨架的九段与 Loci 逐段对照

| # | 骨架段 | 主流做法 | Loci 现状（`L`） | 判定 |
|---|---|---|---|---|
| 1 | 行情订阅 | Gateway 推 tick / LiveDataEngine | 无订阅，**拉模式**：`fetch_live_quotes_routed` + `live_cache` 进程内 TTL（quote 5s）。`M`：分钟线**不落库**，live 只有 3–5 秒进程内 TTL → **实时数据留存能力为零** | 差异是范式，不是缺陷；但见 §4 的后果 |
| 2 | 策略回调 | on_tick / OnData | `skill_watch` 引擎注册表 `engine_registry.EngineSpec`（`needs_market_store`/`uses_market_gate`/`emits_observe`/`eod_rescan`），APScheduler cron 驱动 | ✅ 表驱动，等价物到位 |
| 3 | 订单意图 | `OrderRequest` / `SubmitOrder` / `PortfolioTarget` | `PaperOrder`（9 action） | ✅ 有 |
| 4 | 风控前置 | RiskEngine / RiskManagementModel | `validate_and_normalize_order()`（8 类检查，见 §2.4） | ⚠ 有但不全 |
| 5 | 网关 | Gateway / ExecutionClient / Brokerage | `execute_orders()` 写 `paper_fills`（**纸面**，不接柜台） | ✅ 边界明确 |
| 6 | 回报 | EVENT_ORDER / OrderEvent | `paper_fills` + `paper_rejects` 落库 | ✅ 有 |
| 7 | 持仓/资金同步 | OmsEngine / 对账 | `apply_paper_fill` **成交流水与仓位快照同事务**；`paper_capital` 明确标注是**名义值**、不计佣金滑点 | ✅ 无外部真相可对，语义已诚实 |
| 8 | 落库 | cache DB / ResultHandler | `ai_decisions`（prompt + 报价数值 + 原始回复 + 解析 orders，**失语轮次同样留痕**）、`second_wave_signals`、`leader_role_snapshots` | ✅ **这块比多数 OSS 做得细** |
| 9 | 时钟/日历重刷 | Lean 定时重刷两个 DB | `resolve_trading_day_gate` 读热库/注入日历；**日历缺失时 weekday 粗判，但买入 fail-closed** | ✅ 语义正确 |

### 1.3 【清单】不接实盘也应该抄过来的 12 条

盘中信号监控与提醒这条链上，主流骨架里**与「是否真下单」无关**的部分。逐条给判定与落点：

| # | 检查项 | 抄自 | Loci 状态 | 落点 |
|---|---|---|---|---|
| L-1 | **提醒/信号也要有唯一 ID 与幂等键**，同一 `(信号定义, 标的, 交易日, 时间桶)` 只出一次 | vn.py `duplicate_order_rule.format_req()` 把请求序列化成字符串做去重键 | ⚠ `insert_alert_hit` 已有 `(rule_id, trigger_bucket)` 幂等；但二波提醒**没有**同类去重（规格 §4.2 自己列为待观察项） | `second_wave_signals` 加 `(code, trade_date, bucket)` 唯一键 |
| L-2 | **拒发/未发也要留痕**，且要能回答「为什么今天没提醒」 | vn.py 拦截走 `EVENT_RISK_NOTIFY`；Nautilus 未成交命令有明确 outcome 分类 | ✅ 已做且做对：`second_wave_signals` 用 `alerted` 标记当时是否真推送，未达线的也写 | 保持 |
| L-3 | **信号 → 提醒之间要有一层「可执行性」判定**，不可执行就不出声 | Lean `manage_risk` 返回空列表表示无需干预 | ✅ `EngineSpec.push_only_when_actionable`，仅观察 = 无信号 | 保持；但见 §4 的 L-14 |
| L-4 | **静态数据定期重刷**（交易日历、涨跌停板幅、合约状态） | Lean `RefreshMarketHoursAndSymbolProperties` 周期任务 | ⚠ 交易日历随同步刷新；**涨跌停板幅是本地判定**（`_PRICE_EPSILON=0.005`），无独立重刷任务 | 并入 `data_quality`（16:30）加一条日历尖端检查 |
| L-5 | **扫描轮次要有心跳与队列深度**，不能只有「跑没跑」 | Nautilus `metrics_snapshot()`：queue_depth / mean_dispatch_ns / dispatch_utilization | ⚠ `job_runs` 有 `heartbeat_at`/`owner_pid`，但**无单轮耗时分布**；`M`：`job_runs` 11.36 MB / 706 行 ≈ 16 KB/行，装的是结果不是指标 | 在 run result 里加 `scan_ms` / `pool_size` / `evaluable` 三个标量 |
| L-6 | **双阈值滞回**（trigger 与 clear 分开），避免告警抖动 | Nautilus `queue_depth_trigger` / `queue_depth_clear`，且**校验 clear < trigger** | ❌ 本仓所有阈值都是单阈值（`DEFAULT_THRESHOLDS` 六项、`EVIDENCE_THRESHOLDS` 四项全是单边） | 至少给 `staleness` / `coverage` 两项加 clear 阈 |
| L-7 | **启动时先对账再放行业务**，对不上就别开工 | Nautilus：cache/venue 状态先备好；对账失败**不启动** | ⚠ 有 `guard_market_health` 但只在选股路径；`eod_catchup` 是启动后**补跑**，不是启动**前置闸** | 启动补跑前先跑一次 `check_market_health`，`blocked` 时只补跑不推送 |
| L-8 | **一个进程只跑一个节点** | Nautilus 明文：`run_async()` 拒绝同 loop 第二个节点 | ✅ 已知且写进文档：APScheduler 进程内单例，多 worker 会重复触发 | 保持 |
| L-9 | **命令结果三分类**：本地失败 / 确定结果 / 未知结果 | Nautilus `Command outcomes` | ⚠ Job 终态有 `success/failed/skipped/cancelled/timed_out`；但 MCP 软失败被压成 `skipped`/`degraded`，**「未知」与「确认没有」区分度不足** | `skipped` 拆出 `unknown`（源没答）与 `not_applicable`（确实没有） |
| L-10 | **推送出站串行化 + 有限重试** | vn.py 拦截即发单条通知；不并发打 | ✅ `notify_send_queue` FIFO，同刻一条，失败最多 3 次间隔 1s | 保持 |
| L-11 | **同一轮只能有一个出声者** | — | ✅ `emit_follow = not push_wecom`，扫描摘要与纸面跟随二选一 | 保持 |
| L-12 | **提醒里必须带可自证的原始数字** | — | ✅ 二波模板「低40.00收复MA10」= 触发的全部定义，看到两个数就能自己复核 | **这条应推广到所有引擎**，目前只有二波做到 |

**结论**：九段骨架 Loci 缺的不是段，是**每段的可观测性**。真正该抄的是 L-5 / L-6 / L-7 / L-9 四条，都属于「让轮次自己说清楚这轮干了什么」，与是否下单无关。

---

## 2. 风控前置（pre-trade risk）具体检查哪些项

### 2.1 vn.py `RiskManager` 的五条规则（默认值为源码原文，`P1`）

| 规则类 | 检查项 | 默认阈值 |
|---|---|---|
| `OrderValidityRule`「委托指令检查」 | ① 合约存在；② 价格是 `pricetick` 整数倍（容差 1e-6）；③ ≤ `contract.max_volume`；④ ≥ `contract.min_volume` | 无，全取合约属性 |
| `OrderSizeRule`「委托规模检查」 | ⑤ 单笔数量上限；⑥ 单笔**价值**上限（`volume×price×size`，**仅限价单**） | `order_volume_limit=500`；`order_value_limit=1_000_000` |
| `ActiveOrderRule`「活动委托检查」 | ⑦ 未成交挂单数上限 | `active_order_limit=50` |
| `DuplicateOrderRule`「重复报单检查」 | ⑧ 同一 `symbol｜type｜direction｜offset｜volume@price` 字符串的重复次数 | `duplicate_order_limit=10` |
| `DailyLimitRule`「每日上限检查」 | ⑨–⑭ **六个计数器**：合约级 / 汇总级 × 委托笔数 / **撤单笔数** / 成交笔数 | 汇总 20000/10000/10000；合约 2000/1000/1000 |

两个实现细节值得记：
- **拦截不抛异常**，`send_order` 返回空字符串；调用方拿到空委托号就知道被拦。但同时发 `EVENT_LOG`（level=ERROR）+ `EVENT_RISK_NOTIFY` + Windows 提示音——**拦截必须可听可见**，不能静默。
- `DuplicateOrderRule` 是**先计数再判断**（`+= 1` 在 `>=` 之前），所以 limit=10 实际放行 9 笔。这类「先加后判」的偏移一定要写进阈值注释，否则调参的人会算错一个。

### 2.2 Lean `RiskManagementModel` 的五个内置模型（`P1`）

完整目录只有五个：`MaximumDrawdownPercentPerSecurity`、`MaximumDrawdownPercentPortfolio`、`MaximumSectorExposureRiskManagementModel`、`MaximumUnrealizedProfitPercentPerSecurity`、`TrailingStopRiskManagementModel`。

**与 vn.py 的根本差异**：Lean 的风控**不拒单，改目标仓位**。`manage_risk(algorithm, targets)` 返回一批新 `PortfolioTarget`：
- 组合回撤超限：**先 `algorithm.insights.cancel([symbol])` 再把 target 置 0**——只平仓不撤 insight 会被下一轮再建仓，这行是必须的；且重置 `initialised=False` 以便下一个调仓周期重启。
- 行业集中度超限：算 `ratio = 行业绝对持仓市值 / (总市值 × 20%)`，`ratio>1` 时把该行业**每只票除以 ratio 等比缩**，不清仓。且计算时**已有 target 优先于当前持仓**（用 target 的 quantity 重算）——风控箱看的是「执行完会成什么样」而不是「现在是什么样」。
- 行业模型在 `on_securities_changed` 里发现无基本面数据就**直接抛异常**（fail-closed），不静默降级成「不限制」。

### 2.3 【清单】pre-trade 检查项全集 + 对「不自动下单、只给人看」系统的适用判定

判定列：**★ 依然有意义（只是语义要换）** / **○ 退化为提示** / **✗ 无意义（依赖真下单）**。

| # | 检查项 | 上游出处 | 对 Loci | 在 Loci 里应该变成什么 |
|---|---|---|---|---|
| R-1 | 单笔数量上限 | vn.py `order_volume_limit` | ✗ | —（纸面按层不按股） |
| R-2 | 单笔**价值**上限 | vn.py `order_value_limit` | ★ | 已有等价物：`max_layers_per_name` + 剩余层钳制（「梭哈剩余」逐步向下取整） |
| R-3 | 价格是最小变动价位整数倍 | vn.py `pricetick` | ○ | 提醒买价应对齐 0.01（科创/创业 0.01，但**挂单数量 200 股起**），现在一律不检 |
| R-4 | 标的存在且可交易 | vn.py `get_contract` | ★ | **当前最弱一环**：`M` 实测 `instruments.status` 里 `delisted=1 / normal=5546`、`delist_date` 填充数 **0** → 退市、长期停牌、退市整理期的票**在系统里全部叫 normal** |
| R-5 | 活动委托数上限 | vn.py `active_order_limit=50` | ○ | 改成「同时处于观察态的候选数」上限（目前二波池子实测均 48 只，无上限） |
| R-6 | 重复报单 | vn.py `duplicate_order_limit=10` | ★ | 变成**重复提醒**：同一 code 当日反复触发只提醒一次（规格 §4.2 已列为待观察，未实现） |
| R-7 | 日内累计下单量 | vn.py 汇总 20000 / 合约 2000 | ★ | 变成**日内累计信号数上限**——这就是任务书说的「信号泛滥应当降级」，见 R-14 |
| R-8 | 撤单率 | vn.py `total_cancel_limit=10000` | ★ | 变成**提醒撤回率**：当日先推后又从池里移出 / 角色降为 failed 的比例。高撤回率 = 信号不稳，应降级 |
| R-9 | 单票持仓集中度 | Lean per-security | ★ | 已有：`max_layers_per_name`、`max_positions` |
| R-10 | **行业/题材集中度** | Lean `MaximumSectorExposure`，默认 20% | ★ | **完全缺失。** 本仓有 `instruments.industry` 与开盘啦主类题材（`primaryThemeStats`），却没任何一处在候选出口处算集中度。见 R-15 |
| R-11 | 总仓位 | — | ★ | 已有：`max_layers` + 剩余层钳制 |
| R-12 | 亏损熔断 | Lean `MaximumDrawdownPercentPortfolio`（默认 5%，可 trailing） | ★ | **部分有但层级错位**：`stop_cut` 是**单票**止损（默认 -6%），`decay.py` 是**胜率**衰减——**没有组合级回撤熔断**。`paper_capital` 又明确声明不计已实现盈亏，所以目前**算不出**组合回撤 |
| R-13 | 黑名单 | —（三家都靠 universe 而非独立黑名单） | ★ | 现状是反的：`stock_screener` 默认 `excludeST=true`，但二波规格实测**排除 ST 是自伤**（那 203 只每笔 +4.39%）。真正该拉黑的是退市整理期 / 长停 / 待解禁已公告，而这三类目前都识别不了（见 R-4） |

### 2.4 【清单】Loci 现有 gate 盘点 + 九条可立即落地的「看板层风控」

**先盘清已有的八类**（`validate_and_normalize_order`，`L`）：① code 非空；② action 在白名单（`allow_actions`）；③ 卖出类必须有仓且不超持仓；④ 层数是 `min_step`（默认 0.5）整数倍；⑤ `max_positions` 持股只数上限；⑥ `max_layers` 舱内剩余层（不足则拒，超出则**限到剩余**并向下取整）；⑦ `max_layers_per_name` 单票层上限；⑧ 高抛/低吸门闩（`trim_high_min_pnl_pct` / `buy_dip_drawdown_pct`）；另加一条硬条件：**无有效标记价就拒单**。外层还有交易日闸（`resolve_trading_day_gate`，买入 fail-closed）、情景/竞价闸（`allow_open_fill`）、市场闸（`market_gate` 段关闭 = fail-closed）、人工单门闩（`PALACE_ENV=production` 拒 `bypass_gates`）。

**这套已经比大多数 OSS 个人项目严。缺的是下面九条、且全部与「不自动下单」不矛盾。**

| # | 检查项 | 判据（可直接写成代码） | 触发后的动作 | 建议落点 |
|---|---|---|---|---|
| R-14 | **信号泛滥降级** | 当日单一引擎产出 `picks + watch_picks > N`（建议 N = 该引擎历史日均的 P95，二波实测 22 日均 2.32 只/日、实际提醒 1.18 只/日 → N≈10） | **不拒发，降级发**：只推前 N 名 + 一行「今日信号 M 只，超历史 P95，已降级展示」 | `EngineSpec` 加 `daily_signal_p95`；runner 写 `degraded_reason=signal_flood` |
| R-15 | **组合层集中度提示** | 同一 `primaryTheme` 或 `instruments.industry` 占当日候选总数 > 40%（Lean 默认 20% 是市值口径，这里是计数口径，阈值要放宽） | 在推送首行加一句「本日 N 只中 M 只属【题材】，同注意单一主线风险」 | 直接用 `limit_up_ladder.primaryThemeStats` 同一口径 |
| R-16 | **退市/长停牌黑名单** | 最近 20 个交易日无行情，或 `instruments.status != normal`，或名称含「退」 | 从候选中剔除并**写入拒因**（不是静默丢） | `M`：目前 `delist_date` 0 行、`status` 只有 1 只 delisted，所以**只能用行情缺口判**，不能信任 `status` |
| R-17 | **待解禁提示** | `stock_event_calendar(eventTypes=unlock)` 与候选交集，T+0…T+5 内有解禁 | 提醒行末尾加标记，不剔除 | 直接调惟道 MCP，归 skill 池配额 |
| R-18 | **语义阈值双边化** | 现有 `min_strength=45` 是单边；加一条上边告警：当日**全部**信号强度 ≥ 90 | 强度分失去区分度 = 打分器坏了或行情异常，应标 `suspect_scorer` | `second_wave_signals` 已存全部触发，直接在日终算 |
| R-19 | **候选与行情快照同源校验** | 候选落库时记录 `market_revision`；推送前重读一次，不一致则标注 | 避免「选股用的是 A 快照、推送价是 B 快照」 | `store.market_revision()` 单行 meta 查询，成本可忽 |
| R-20 | **下单层补：最小下单单位** | 买价 × 100 股 > 该层名义金额 → 该层实际买不了一手 | 提醒里直接不给这只票分层建议 | 高价股（>200 元）在小额舱位下是硬不可行 |
| R-21 | **涨停不可买提示** | 现价 ≥ 涨停价 − `_PRICE_EPSILON` 且封单 > 0 | 标「今日买不到」，不计入可执行信号 | 与回测 `allow_limit_up_entry=False` 口径**对齐**；不对齐就是回测-实盘偏离的来源 |
| R-22 | **拒因可聚合** | `paper_rejects` 现在存中文句子（`舱内剩余层不足`…），无枚举码 | 加 `reject_code` 枚举列，中文句子降为 `reason_text` | 不加码就无法回答「本周拒单 Top3 原因」，而这正是风控调参的唯一依据 |

**一句话总结 §2**：不自动下单使 R-1/R-3（交易所微观约束）失效，但**使 R-7/R-8/R-10/R-12 更重要**——机器不下单时，唯一能挡住「信号泛滥 → 人手动满仓单一主线」的就是提醒本身的自制。

---

## 3. 实验管理与可复现

### 3.1 四类方案的**实测**重量对照（`X`，2026-08-25 PyPI）

| 方案 | 版本 | 基础依赖数 | 主 wheel | 会拉进来的重包 | 对本仓的增量 |
|---|---|---:|---:|---|---|
| **MLflow（完整）** | 3.15.1 | — | 10.7 MB | `scikit-learn<2`、8.7 MB；`scipy<2`、33.7 MB；`matplotlib<4`、9.6 MB；`pyarrow>=4`、47.8 MB；另 Flask / Flask-CORS / SQLAlchemy 3.2 MB / alembic / graphene / docker / huey / aiohttp / cryptography / waitress | **≈117 MB wheel，其中 99.8 MB 是本仓现在一个都没有的包**（`M`：依赖清单无 scipy / sklearn / statsmodels / vectorbt） |
| MLflow-skinny | 3.15.1 | 20 | 3.4 MB | fastapi/starlette/uvicorn（已有）、**databricks-sdk**、otel-api/proto/sdk 三件、gitpython、cloudpickle、protobuf | 轻，但 skinny **不带 UI 与服务端**，而 UI 正是想要 MLflow 的唯一理由 |
| Weights & Biases | 0.28.2 | 10 | — | sentry-sdk、protobuf、otel-api | 轻，但**默认 SaaS**：与本仓「单机离线、分享包默认脱敏、`.palace_ai_master_key` 禁止出境」直接冲突，self-host 又是另一套服务 |
| DVC | 3.67.1 | **42** | 0.4 MB | **celery + kombu**（broker！）、networkx、hydra-core、omegaconf、psutil、pydot、grandalf、rich、scmrepo、dvc-data/objects/render/task/http/studio-client 六个子包 | 它把 Celery 拉进来。而 Celery 在本仓技术雷达里是**明确 Reject** |
| **纯文件 + manifest.json** | — | **0** | 0 | 无 | 0（`hashlib`/`json`/`subprocess` 均标准库；`ArtifactManifestEntry` 已存在） |

### 3.2 判定：不引入 MLflow——三条实证理由（不是“感觉重”）

1. **内存**。服务器 4 核 / 3786 MB、当前可用 **1150 MB**（`docs/master-plan-2026-07.md`）。MLflow 完整包意味着在**同一个 venv** 里多一个 Flask/waitress 常驻服务 + SQLAlchemy/alembic 元数据库层，并把 scipy/sklearn/pyarrow 拉进 `import` 图。本仓已有**实测先例**：全市场回测把预热从 260 根降到 170 根就是因为 **260 根会 `MemoryError`**；PTH252 完整宽面板冻结运行「本机需约 4 GB 内存且未在合理窗口内完成」。给一个已经在 OOM 边缘做回测的进程旁边再放一个 tracking server，换来的只是一个网页。
2. **功能重叠**。MLflow 的四件套（run / params / metrics / artifacts）本仓**已经有同构实现且更严**：`ResearchRunCard`（`run_id` / `params` / `metrics` / `artifact_manifest` / `input_sha256` / `market_revision` / `status`）+ `ArtifactManifestEntry`（内容寻址 + 目录穿越校验）+ `manifest_sha256()` 规范化摘要 + `replay_research_backtest()` 逐项比对 + **人工签署状态机**（`running` 不能直达 `completed`，否决不可翻案）。MLflow **没有**后两项。
3. **该解决的问题它解决不了**。真正的缺口不是「没有 recorder」，而是 **`scripts/*.py` 这条路不走 recorder**。`M` 实测：`ops.db` 里 `strategy_backtests` **0 行**、`strategy_versions` **0 行**，而前者的 DDL 注释写的就是「回测结果按策略版本存储，**避免新代码覆盖旧版本的可复现实验结论**」——**设计了、建表了、一行没写**。同时 `output/` 下散落 22 个目录/文件，`scripts/` 下 62 个脚本（含 7 个 `_tmp_*`）。装 MLflow 也不会让这 62 个脚本自己开始 `mlflow.log_param`。

**反方意见已考虑并驳回**：“用 `mlflow-skinny` + `file://` backend 就不重了”。skinny 不带 UI，而数据模型（run/experiment/tag/metric-step）会把本仓已有的 run card 变成第二套真相——而本仓硬规则就是「零双真相」。它还会拉 `databricks-sdk` 与三个 otel 包进一个明确「OTel 默认关闭」的仓。

### 3.3 【清单】一次量化实验的最小可复现清单（12 项）

判判据：**缺一项就不能叫可复现，只能叫可重跑**（同一命令再跑一次 ≠ 能重放同一份输入）。

| # | 项 | 为什么不能省 | 本仓现成件 |
|---|---|---|---|
| E-1 | 代码 commit + **工作区是否脏** | 脏工作区下的 commit 号是谎话 | `git rev-parse HEAD` / `git status --porcelain` |
| E-2 | 入口脚本路径 + **它自己的 sha256** | 同一 commit 下脚本可能没入库（`_tmp_*.py` 就是） | `hashlib` |
| E-3 | **完整 argv** | 默认值会变；二波规格已踩过「`Thresholds.max_alerts` 改了但 argparse 默认值没改」 | `sys.argv` |
| E-4 | **`market_revision`** | 行情库内容版本号；没它就无法判定「这份结果是不是在当前快照上算的」 | `store.market_revision()`（**单行 meta 查询**，不要为此调 `data_snapshot()`） |
| E-5 | `as_of` 请求值 **与** 解析值 | 传 2026-08-24（周日）实际落在 08-22；不分开记事后对不上 | `capture_research_input` 已有 `requested_as_of` / `as_of` 双字段 |
| E-6 | 股票池定义 + **是否 PIT** | 存活偏差。`M`：`delist_date` **0 行**、`normal=5546` → 本机**根本无法** PIT，必须显式标 `survivorship=unmeasurable` | `MembershipSnapshot` / `historical_universe_id`（现存但无数据） |
| E-7 | 参数字典（含默认值展开后） | 只记显式传入的参数，默认值一改历史就不可复现 | 已有 `ResearchRunCard.params` |
| E-8 | **随机种子 + 随机使用点清单** | 写个 `seed=42` 但不写「哪里用了随机」等于没写；PTH252 用了 `random_repeats=200` / `bootstrap_iterations=200` | `frozen_input.json` 已存「随机配置」 |
| E-9 | 环境：Python 版本 + **实际 import 到的包版本** | 全量 `pip freeze` 噪声太大；pandas 2.x 小版本差异能改变 `groupby` 行为 | `sys.modules` 过滤 + `importlib.metadata.version` |
| E-10 | **`LOCI_*` 环境开关** | `LOCI_MARKET_DUCKDB` / `LOCI_RESEARCH_POLARS` / `LOCI_BACKTEST_FAST` / `LOCI_CROSS_CHECK_EVERY` 都能换掉计算路径 | `os.environ` 前缀扫描 |
| E-11 | 结果指纹 | 光存指标不够；要有**逐字节可重现的序列化** hash（`sort_keys` + 紧凑分隔符 + `allow_nan=False`） | `_manifest_sha256()` 已是这个写法；`tests/research/test_frozen_artifact.py` 钉了逐字节可重现 |
| E-12 | **行情健康快照**（当时的 blocked / findings） | 不记就无法事后区分「策略不行」与「那天库坏了」 | `check_market_health(...).to_dict()`，`capture_research_input` 已内置 |

### 3.4 `manifest.json` 字段设计（JSON Schema 级）

**设计约束**：字段名一律向 `ResearchRunCard` / `ArtifactManifestEntry` 看齐，以便日后 `scripts/` 路与 `src/research/` 路**合并而不是再造一套**；全部字段只靠标准库可填；不可填的字段**写 `not_observed` 而不是缺省**（与 `source_route_receipts` 同口径）。

落盘位置：`output/<experiment_id>/manifest.json`，与现有 `output/*/` 产物同目录。

```json
{
  "$schema": "https://json-schema.org/draft/2020-12/schema",
  "$id": "loci-experiment-manifest-v1",
  "title": "Loci 量化实验可复现清单",
  "type": "object",
  "additionalProperties": false,
  "required": [
    "contract_version", "experiment_id", "created_at", "status",
    "code", "data", "params", "seed", "env", "results",
    "reproducibility", "input_sha256"
  ],
  "properties": {
 "contract_version": { "const": "loci-experiment-manifest-v1" },
    "experiment_id":    { "type": "string", "pattern": "^[a-z0-9][a-z0-9-]{2,63}$",
    "description": "与 output/ 子目录同名，如 dragon-pool-trigger-2024-01-02_2026-07-31" },
    "created_at":    { "type": "string", "format": "date-time" },
    "finished_at":      { "type": ["string", "null"], "format": "date-time" },
    "status":           { "enum": ["running", "completed", "failed", "stale", "superseded"],
          "description": "stale = market_revision 已变，结论仍有效但不能逐值重放" },

    "code": {
   "type": "object", "additionalProperties": false,
      "required": ["commit", "dirty", "entrypoint", "entrypoint_sha256", "argv"],
      "properties": {
 "commit":       { "type": "string", "pattern": "^[0-9a-f]{40}$" },
        "dirty":             { "type": "boolean", "description": "git status --porcelain 非空" },
        "dirty_paths":       { "type": "array", "items": { "type": "string" }, "maxItems": 50 },
        "branch":            { "type": "string" },
        "entrypoint":        { "type": "string", "description": "仓内相对路径，如 scripts/xxx_research.py" },
   "entrypoint_sha256": { "type": "string", "pattern": "^[0-9a-f]{64}$" },
        "argv":          { "type": "array", "items": { "type": "string" } }
      }
    },

    "data": {
    "type": "object", "additionalProperties": false,
      "required": ["market_revision", "market_schema_version", "as_of_requested", "as_of_resolved", "adjust", "universe", "health"],
      "properties": {
        "market_revision":       { "type": "string", "pattern": "^[0-9a-f]{64}$" },
 "market_schema_version": { "type": "integer" },
        "market_db_bytes":       { "type": "integer", "description": "诊断用；实测 2026-08-25 为 6019770368" },
        "as_of_requested":     { "type": "string", "pattern": "^(\\d{4}-\\d{2}-\\d{2})?$" },
        "as_of_resolved":        { "type": "string", "pattern": "^\\d{4}-\\d{2}-\\d{2}$" },
        "window_start":    { "type": "string", "pattern": "^\\d{4}-\\d{2}-\\d{2}$" },
        "trading_days":          { "type": "integer", "minimum": 1 },
        "adjust":                { "enum": ["none", "qfq", "hfq"] },
        "universe": {
    "type": "object", "additionalProperties": false,
          "required": ["spec", "code_count", "codes_sha256", "pit"],
          "properties": {
   "spec":    { "type": "object", "description": "UniverseSpec 展开后的完整参数" },
   "code_count":   { "type": "integer" },
            "codes_sha256": { "type": "string", "pattern": "^[0-9a-f]{64}$",
             "description": "排序后换行拼接的 sha256；不存全量名单" },
            "pit":{ "enum": ["strict", "degraded", "unmeasurable"] },
     "historical_universe_id": { "type": ["string", "null"] },
            "survivorship_note":    { "type": "string",
           "description": "unmeasurable 时必填。实测：delist_date 填充 0 行、status 只 1 只 delisted" }
     }
},
        "health": {
    "type": "object", "additionalProperties": false,
    "required": ["blocked", "findings_sha256"],
  "properties": {
            "blocked":   { "type": "boolean" },
 "grade":      { "type": "string" },
            "findings_sha256":  { "type": "string", "pattern": "^[0-9a-f]{64}$" },
          "blocking_checks":  { "type": "array", "items": { "type": "string" } }
  }
        },
        "source_evidence": {
     "type": "object", "additionalProperties": false,
   "properties": {
        "receipts_total":        { "type": "integer" },
   "receipts_failed":       { "type": "integer" },
        "attempts_not_observed": { "type": "integer" },
   "rejected_ohlc_rows":    { "type": "integer" },
            "publication_status":    { "enum": ["observed", "not_observed", "mixed"] }
          }
   }
    }
    },

  "params": {
      "type": "object", "additionalProperties": false,
      "required": ["resolved", "resolved_sha256"],
   "properties": {
   "resolved":   { "type": "object", "description": "默认值展开后的全集，不只记显式传入的" },
        "explicit_keys":   { "type": "array", "items": { "type": "string" } },
      "resolved_sha256": { "type": "string", "pattern": "^[0-9a-f]{64}$" },
        "cost_model": {
   "type": "object",
     "properties": {
        "commission_bps": { "type": "number" },
     "stamp_duty_bps": { "type": "number" },
            "slippage_bps":   { "type": "number" },
            "entry_timing": { "enum": ["open", "close", "next_open", "next_dip"] },
            "allow_limit_up_entry": { "type": "boolean" }
          }
 }
      }
    },

    "seed": {
      "type": "object", "additionalProperties": false,
      "required": ["value", "consumers"],
    "properties": {
        "value":  { "type": ["integer", "null"] },
        "consumers": { "type": "array", "items": { "enum": ["python_random", "numpy", "bootstrap", "shuffle_control", "none"] },
        "description": "空数组不合法；确实无随机则填 [\"none\"]" },
        "repeats":   { "type": "integer", "minimum": 0 }
      }
    },

    "env": {
      "type": "object", "additionalProperties": false,
      "required": ["python", "platform", "packages"],
      "properties": {
      "python":    { "type": "string" },
        "platform":  { "type": "string" },
        "packages":  { "type": "object", "additionalProperties": { "type": "string" },
            "description": "只记本次真正 import 到的（sys.modules ∩ 可查版本），不是 pip freeze" },
     "loci_env":  { "type": "object", "additionalProperties": { "type": "string" },
        "description": "所有 LOCI_* / PALACE_* 开关实际生效值" }
      }
    },

    "results": {
      "type": "object", "additionalProperties": false,
      "required": ["metrics", "primary_metric", "artifacts"],
      "properties": {
        "metrics":        { "type": "object", "additionalProperties": { "type": ["number", "null"] } },
    "primary_metric": { "type": "string" },
        "sample_size":    { "type": "integer" },
        "artifacts": {
    "type": "array",
          "items": {
"type": "object", "additionalProperties": false,
       "required": ["path", "sha256", "size_bytes", "artifact_type"],
            "properties": {
        "path":  { "type": "string", "description": "相对 manifest 所在目录；拒绝绝对路径与 .." },
   "sha256": { "type": "string", "pattern": "^[0-9a-f]{64}$" },
         "size_bytes":    { "type": "integer", "minimum": 0 },
       "artifact_type": { "enum": ["grid", "trades", "yearly", "portfolio", "diagnostic", "report_markdown", "frozen_input"] },
       "rows":          { "type": ["integer", "null"] },
              "created_at":    { "type": "string", "format": "date-time" }
        }
          }
     }
      }
    },

    "reproducibility": {
      "type": "object", "additionalProperties": false,
    "required": ["level", "gaps"],
   "properties": {
        "level": { "enum": ["strict", "degraded", "exploratory"],
        "description": "strict 要求 dirty=false 且 pit=strict 且 health.blocked=false" },
        "gaps":  { "type": "array", "items": { "enum": [
             "dirty_worktree", "survivorship_unmeasurable", "no_minute_bars",
            "health_blocked", "missing_receipts", "seed_unrecorded", "third_party_source"
        ] } }
      }
    },

    "provenance": {
      "type": "object", "additionalProperties": false,
  "properties": {
     "doc_path":     { "type": "string", "description": "引用本次结果的 docs/research/*.md" },
        "supersedes":   { "type": "array", "items": { "type": "string" } },
        "derived_from": { "type": "array", "items": { "type": "string" } }
      }
    },

    "input_sha256":    { "type": "string", "pattern": "^[0-9a-f]{64}$",
 "description": "code+data+params+seed+env 四段的规范化 JSON 摘要；results 不入入参" },
    "manifest_sha256": { "type": "string", "pattern": "^[0-9a-f]{64}$",
          "description": "全文去掉本字段后的规范化摘要，供外部引用锁定" }
  }
}
```

**四个关键设计决定（都有本仓先例）**：
1. `input_sha256` **不含 `results`**——与 `ResearchRunCard.input_payload()`「返回参与输入指纹的字段；结果字段不在其中」同口径。同一输入两次跑出不同结果是 **bug 信号**，得能看得出来。
2. `codes_sha256` 而非全量名单——全市场 5,547 只，存名单会把 manifest 撞成几百 KB。与 `frozen_input` 从 376 MB 降到 71 MB 的那次优化同一思路。
3. `reproducibility.gaps` 是**枚举而非自由文本**，否则无法聚合「有多少份历史实验因存活偏差不可信」。`no_minute_bars` 单列一项：`M` 实测分钟线不落库，所有声称盘中时点的结论都带这个 gap。
4. `status=stale` 与 `ResearchRunCard` 的 `mark_run_card_stale` 对齐：**行情版本变了只标 stale，不覆盖旧输入**。

### 3.5 用现有件拼出来：三步，零新依赖

| 步 | 做什么 | 成本 | 验收 |
|---|---|---|---|
| 1 | 写一个 `scripts/_manifest.py`（≤120 行，只用 `hashlib`/`json`/`subprocess`/`importlib.metadata`），导出 `open_experiment(experiment_id, entrypoint) -> Manifest` 与 `Manifest.finish(metrics, artifacts)` | 单文件 | 同一输入跑两次，`input_sha256` 相等 |
| 2 | 把 **6 个已被结论引用**的脚本（`dragon_return_pool_trigger` / `tail_1450_next_day_touch` / `tail_close_entry_baseline` / `tail_material_rules_backtest` / `yangshi_tail_rank_portfolio` / `heat_tail_attention_proxy`）接上。其余 56 个**不动** | 每个 3–5 行 | `output/*/manifest.json` 存在且 `git` 不脏时 `level=strict` |
| 3 | 把 manifest 的 `metrics` + `manifest_sha256` 写进已存在但**空了一年**的 `ops.db.strategy_backtests`（`slug`/`version`/`metrics_json`） | 一条 upsert | 运维页能答「这个战法当前参数的回测结论是哪一次跑的」 |

**不做的**：不把 `output/` 里几百 MB 的 CSV/JSON 入 git（这正是 DVC 要解决的问题，而本仓的答案是「产物不入库，但 hash 入库」）；不建 web UI；不动 `src/research` 那套已有的严格链。

---

## 4. 监控与告警：无人值守下的静默失败

### 4.1 主流四类做法与 Loci 对应物

| 类 | 主流做法 | Loci 现状 |
|---|---|---|
| **数据新鲜度 SLA** | 定义「应该有的最新时点」而非「最后一次写入时间」 | ✅ **做得很对**。`_wall_clock_data_lag()` 比的是库内最新日对**墓钟应覆盖交易日**，而不是「基准日距日历末日」——后者会误拦历史复盘。15:00 前 `expected_last_date` 不含今日 |
| **行情源健康探测** | 主动 probe，与业务路径分开 | ✅ `include_network=True` 时探 hist/spot/factor/instruments 四条 lane；**默认关**（选股门禁不打第三方）。另有 `check_lane_readiness.py` 兵棋盘 |
| **策略信号数异常** | 今天 0 只或 500 只都是异常 | ❌ **零覆盖，且现有机制把它变得更隐蔽**——见 §4.3 M-9 |
| **回测-实盘偏离** | live vs backtest slippage tracking | ❌ **能力曾经有，2026-08 被主动删除**：`src/review/__init__.py` 写明「回测-实盘偏离已整体删除」，`/api/review/equity｜trips｜positions｜drift` 四个端点一并拆掉，`position_tracking` 降为「**纯写入孤儿**」。剩下的只有 `review/application/decay.py`（胜率衰减） |

**关于回测-实盘偏离，先说一句实话**：删得有道理——实盘账本下线后，那些端点读的真成交已不存在。但**不能就此丢掉这个问题**：现在的替代品是「候选池 + 行情」的纸上收益（`outcome` 任务，工作日 15:45，`benchmark=000300`，`max_age_trading_days=5`）。纸上收益**与回测口径可以对齐**——那就应该真的对一下，而不是各算各的。见 M-12/M-13。

### 4.2 本仓现有阈值全景（写新检查前先看这张表，避免重复造）

| 来源 | 检查项与默认阈值 |
|---|---|
| `sentinel.DEFAULT_THRESHOLDS` | `min_coverage_ratio=0.90`、`max_stale_days=3`、`max_turnover_missing_ratio=0.05`、`max_factor_age_days=30.0`、`max_failed_codes=50`、`max_zero_amount_ratio=0.10` |
| `sentinel_evidence.EVIDENCE_THRESHOLDS` | `max_ohlc_reject_ratio=0.05`、`max_evidence_gap_ratio=0.50`、`max_fallback_ratio=0.60`、`max_sync_job_age_hours=36.0` |
| `sentinel_extended.EXTENDED_THRESHOLDS` | `max_db_bytes=8 GiB`；另有四条 lane 连通、`session_backfill`、`capabilities_runtime`、`schema_version`、`factor_coverage` |
| `market.application.data_quality.QualityThresholds` | `min_authoritative_ratio=0.95`、`max_fabricated_rows=2000`、`max_missing_receipts=200`、`lookback_days=90`、`min_last_day_rows=5000`、`min_index_close=1000.0` |
| `review/application/decay.py` | 滞后胜率 <30% → critical；相对基线降 ≥20pp → critical；≥10pp → warning（基线 = 前 100 笔，近期 = 后 20 笔） |

⚠ **一条已经靠很近的阈值**：`M` 实测 `market.db` = **5,740.2 MB**，而 `max_db_bytes` = 8 GiB = 8,192 MiB → **已用 70.1%**。且其中 **44.8%（2,569 MB）是溯源审计**（receipts 450.9 + attempts 724.7 + 它们的索引 344.4 + `idx_quotes_receipt` 1,049.0）。它会先于行情本体撞线：行情体按 160 B/行 × 2025 年 1,307,392 行 ≈ **209 MB/年**，而回执跟的是同步次数不是交易日数。当前体检只会在撞线那天 warn 一声，**不报增速、不拆构成**。

### 4.3 【清单】静默失败检查项（带判据、阈值、落点）

分三类：**✅ 已有**（只列供对照）/ **⚠ 有但会漏**（需改）/ **❌ 缺**。

| # | 检查 | 判据 | 阈值建议 | 状态 / 落点 |
|---|---|---|---|---|
| M-1 | 行情库尖端落后 | 库内最新日 vs 墓钟应覆盖交易日 | >3 个交易日 = block | ✅ `_check_staleness` |
| M-2 | 当日覆盖率 | `当日有行情的票 / status=normal` | <90% = block | ✅ `_check_coverage`（且会区分「盘中 spot 未写完」） |
| M-3 | 换手率缺失 | 筹码类战法完全依赖 | >5% = warn | ✅ `_check_turnover` |
| M-4 | 复权因子偏科 | `MAX(fetched_at)` 会被一只票骗过 → 另按标的统计 | 按标的 >30 天未刷 = warn | ✅ `factor_age` + `factor_coverage` 双项 |
| M-5 | 源切换静默降级 | 权威源（tdx）占比 | <95% = alert | ✅ `data_quality` 任务（16:30，**只报不改**） |
| M-6 | 合成成交额回流 | `|amount − close×volume| < ε` 且源在 `FABRICATING_SOURCES` | >2000 行 = alert | ✅（**判据只在会合成的源上算**——这个限定是对的，1990s 单一价格成交日真值也相等） |
| M-7 | 同步 Job 时效 | 最近成功同步距今 | >36h = warn | ✅ `job_sync_stale` |
| M-8 | **库体积增速与构成** | 现只有总量单阈 | 新增：① 溯源占比 >40% → 提示可剪；② 周环比增量 >200 MB → warn | ⚠ `db_size_warn` 只在 8 GiB 撞线才叫；`M` 已 70.1%。另：`market_hot.db` 1,022.1 MB 里 `idx_quotes_receipt` 占 **238.3 MB（23%）**，而热库是只读选股库、**不走 receipt 查询** → 这个索引在热库里可能是白占（需 EQP 验证后再动） |
| M-9 | **信号数异常（下界）** | 某引擎连续 N 轮 / N 个交易日 `picks==0 且 watch_picks==0` | 连续 **3 个交易日**全空 → warn；**5 个** → critical | ❌ **缺，且现机制会掩盖它**。`push_only_when_actionable=True` 使「零信号」不推送（这对，防刷屏），但 Job 仍记 `success`——于是**引擎坏掉与市场真没信号在运维页上长得一模一样**。参考先例：龙池退役前就是「2026 年 3/6/7 月整月零信号」而无人发现。**落点**：`skill_runs` 聚合出 `consecutive_empty_days`，进 `data_quality` 同一条告警链 |
| M-10 | **信号数异常（上界）** | 当日信号数 > 该引擎历史 P95 | 二波实测日均触发 2.32 / 实际提醒 1.18 → P95 约 8–10 | ❌ 缺（= §2.4 R-14） |
| M-11 | **扫描内部健康** | 池子规模、可判定数、单轮耗时 | 池子 >60 只 = 规格 §4.4 自定告警线；单轮 >120s = warn（已有先例：`load_panel` 不传 `start` 时实测 230s） | ⚠ 数字在日志里，**未成阈值** |
| M-12 | **候选实现值 vs 回测预期值** | `outcome` 任务已算 T+1/3/5 纸上收益；把它与 `strategy_backtests.metrics_json` 里同参数的回测均净比 | 滞后 20 笔均净 − 回测均净 < −1.0pp → warn | ❌ **缺且现在不可能**：`strategy_backtests` **0 行**（`M`）。§3.5 第 3 步就是这条的前置 |
| M-13 | **成交口径偏离（纸面版 slippage）** | 提醒时的 `mark_price` vs 当日收盘 / 次日开盘（按回测 `entry_timing`） | 均值偏离 >0.3%（回测滑点假设是单边 5 bps）→ 回测成本模型低估 | ❌ 缺。`paper_fills.mark_price` 已存，`quotes_daily` 已存，**差一个日终对账任务** |
| M-14 | **推送链本身活着** | 已连续 N 日无任何出站 | ≥五个交易日零推送 → 发一条心跳 | ❌ 缺。降噪做得越好，「推送坏了」越像「今天没信号」 |
| M-15 | **配额扁平** | 惟道 structured/skill 池日耗 | 已有 `estimate_daily_calls` 自检，**只报警不静默截断** | ✅ **这是全仓最好的一段告警设计**，应当做模板：告警要说清楚「超了多少 / 该拧哪个旋钮」 |
| M-16 | **任务假绿** | 缓存 TTL ≥ 采集间隔 → 整轮命中缓存、一次真调用都没发、Job 却记绿 | 已钳：盘中 TTL 默认 12 分钟 < cron `*/15` | ✅ 已修。**同类 bug 应写成通用断言**：任何带 TTL 的周期任务，启动时断言 `ttl < interval` |
| M-17 | **部分失败不假绿** | `intel_fetch.stats.failed>0` → Job 记 failed | — | ✅ 已有 |
| M-18 | **尽力而为项的失败要看得见** | 复权因子刷新 / 换手率回填 / 热库镜像失败 | 不改任务状态，但写 `factors_error` / `turnover_repair.error` / `hot_mirror.error` | ✅ **已有且思路正确**（避免「除权后 qfq 长期失真却一直绿灯」） |

**两条横向原则**（从上表提炼，建议写进 `src/ops/README.md`）：
1. **降噪必须配心跳。** 每当你加一条「没事就不出声」（`push_only_when_actionable`、`quiet_hours`、`wecom_push_marks`、hold 节流），就必须同时加一条「长期不出声就报警」。否则降噪会把静默失败变成默认态。
2. **告警要带旋钮。** `intel_fetch` 的配额告警明说「超了多少、该拧哪个旋钮」；体检的 `repair_plan` / `remediation` 同理。没旋钮的告警三周内一定被忽略。

---

## 5. 数据质量守卫

### 5.1 三者定位：Great Expectations / pandera / 本仓 `LaneContract`

| | Great Expectations 1.21.0 | pandera 0.32.1 | 本仓 `source_contract.py` |
|---|---|---|---|
| 定位 | 数据质量**平台**（Suite / Checkpoint / Data Docs / Store） | dataframe **schema 断言库** | **出口契约**（列映射 + 数值化 + 单位换算 + 缺列校验） |
| 基础依赖 | **22**（含 altair / **scipy** / marshmallow / ruamel.yaml / tzlocal / tqdm） | **5**（packaging / pydantic / typeguard / typing_extensions / typing_inspect） | **0**（纯标准库，领域层不依赖 pandas） |
| 本仓增量 | 5.4 MB + **scipy 33.7 MB（现在没装）** | 0.4 MB（pydantic 已随 FastAPI 存在） | 0 |
| 能做什么本仓做不了的 | 跨批次历史 profiling、Data Docs 网页 | **行级断言 + 失败行回收**、类型声明、`Check` 组合、与 pydantic 共用模型 | 单位换算（GE/pandera 都不管这个） |
| 判定 | **拒绝**：拉 scipy 进一个现在没有 scipy 的 venv，只为了跑几条区间断言 | **唯一值得评估的**，但不是现在 | 保留为契约层 |

**为什么 pandera 也不是现在**：本仓的断言不是「这列是 float 且 ≥ 0」那种。真正要拦的是 **跨列关系**（`high ≥ max(o,l,c)`）、**跨行关系**（复权因子跳变、交易日缺口）、**跨源关系**（东财百分数 vs 新浪小数）。前两类 pandera 的 `Check` 能写但优势不大（现在就是一行向量化表达式），第三类它**根本不具备概念**。真要上 pandera，应该先把下面 A/B/C 三档断言清单写成纯函数与回归测试，再讨论要不要换壳。

### 5.2 【清单】行情入库前必须过的断言

**A 档：硬拒（reject row，写回执 `rejected_ohlc_rows`）**

| # | 断言 | 现状 |
|---|---|---|
| Q-1 | `open/high/low/close` 四列都存在且非 NaN | ✅ `partition_valid_ohlc_rows`：缺任一列 → **整帧拒** |
| Q-2 | 四个价 > 0 | ✅ 同上 |
| Q-3 | `high ≥ max(open, low, close)` | ✅ 同上 |
| Q-4 | `low ≤ min(open, high, close)` | ✅ 同上 |
| Q-5 | `(code, trade_date)` 去重，`keep=last` | ✅ `quote_payload_from_bars` |
| Q-6 | 批量源夹带的**未请求代码不入库** | ✅（否则产生没有 receipt 的遗留行情） |
| Q-7 | **当日 K 线只接受自报交易日的源** | ✅ `dated_spot_adapter_ids()`（东财现价表无日期列 → 挡在写库外）。这条拦的是「节假日把昨收写成今日并往日历插假交易日」 |
| Q-8 | **指数伪代码必须声明 `instrument_type`** | ✅ 已有，但是**事后加的**：实测中证 500 当天 7717、串回来的深市同号个股 8.54，**1.2 万行基准指数已写错过** |

**B 档：入库后日内体检（warn / block，不改库）**

| # | 断言 | 判据 | 状态 |
|---|---|---|---|
| Q-9 | **涨跌幅越界** | `|close/prev_close − 1|` 超该板块制度上限 + 容差：主板 10%、创/科 20%、北交 30%、ST 5%；**新股首日与复牌首日例外** | ❌ **缺**。本仓已有板块判定（`board`）与 `_PRICE_EPSILON=0.005`，只差一条断言。越界 = 比例子弄错了或源串票，不是市场现象 |
| Q-10 | **成交量为 0 但有涨跌** | `volume<=0 且 |close−prev_close|>ε` | ❌ 缺。现只有 `zero_amount` 比例项（>10% warn），**不看与价格的矛盾**。停牌日价格应不动；动了就是源在拿另一天的价填 |
| Q-11 | **成交额三角一致** | `amount ≈ close×volume` 恒成立 → 合成假值 | ✅ `max_fabricated_rows=2000`，且**只在 `FABRICATING_SOURCES` 上算** |
| Q-12 | **隐含换手超 100%** | `amount/(close×流通股本) > 1` | ✅ `repair_inflated_turnover` / `rescale_star_daily_volumes`（判据：隐含换手 >100%，或历史线量级比自身 spot 行高 20 倍以上） |
| Q-13 | **复权因子跳变** | 相邻两日因子比 ∉ [0.2, 5]（宽口径）且无对应分红送转公告 | ❌ **缺**。现有两项只看**时效**（`factor_age` / `factor_coverage`），不看**数值合不合理**。因子跳错不报错，只让前复权面板整列失真 |
| Q-14 | **交易日缺口** | 日历相邻两日自然日差 > 10（除法定长假）；或单票序列在不停牌前提下缺日 | ⚠ 部分。`session_backfill` 只看**尖端**是否落后，不看**中间是否漏洞**。`source_evidence_gap` 已意识到同类问题（只看近窗会退化成恒真断言）并用了**近窗精确 + 历史抽样**，日历缺口应拄同一思路 |
| Q-15 | **基准指数量级** | 中证系列基点 1000，低于它 = 串成同号个股 | ✅ `min_index_close=1000.0` |
| Q-16 | **权威源水位** | 非权威源行占比 | ✅ `min_authoritative_ratio=0.95` |
| Q-17 | **归属回执缺口** | 日 K 无 `receipt_id`，或有 receipt 无 attempt | ✅ `source_evidence_gap`（近 20 交易日精确 + 5 个历史抽样日） |
| Q-18 | **证券目录骤减** | 某所列表较本地骤减 >20% → 保留旧目录 | ✅ 已有 |
| Q-19 | **退市日期完整性** | `delist_date` 非空行数 / `status='delisted'` 行数 | ❌ **缺，且现状是 0/1**（`M`）。这不是小瓕疵：它使所有历史回测的存活偏差**不可测**，直接决定 §3.4 里 `pit=unmeasurable` |

**C 档：单位与口径漂移（单列一档，见 §5.3）**

### 5.3 单位漂移怎么自动抓（本仓踩过的那个 100 倍）

**踩过的坑原文**（`src/market/domain/source_contract.py` 注释，`L`）：东财 `涨跌幅` / `主力净流入-净占比` 给百分数（2.45 = 2.45%），新浪 `changeratio` / `ratioamount` / `r0_ratio` 给小数（0.0245）。同一目标列被两家填 → 阈值判断（「主力净占比 > 5」）在**换源那天静默失效**。修法是加 `Unit.RATIO_TO_PERCENT`，仅对那三个新浪键声明。

**问题是：这是事后人工发现的。契约只能保证「已知的源 × 已知的列」换对，拦不住「上游惄惄改了口径」。** 四条可自动化的判据：

| # | 判据 | 怎么算 | 为什么能抓到 | 现成钩子 |
|---|---|---|---|---|
| U-1 | **量级分布漂移（数量级直方图）** | 对每个数值目标列统计 `floor(log10(|x|))` 的分布，比对同列近 20 日基线；**众数档位偏移 ≥2 → block** | 100 倍漂移就是数量级偏 2。这条**不需要知道正确单位**，只需要知道「昨天不长这样」 | `pipeline.normalize` 出口处；基线存 `meta` 单行 JSON |
| U-2 | **同列跨源交叉比** | 已有 `should_cross_check`（代码对 50 取模，**稳定可复现**）抽样多源；对同一 `(code, date)` 的同一列算 `a/b`，**比值落在 [95,105] 或 [0.0095,0.0105] → 单位漂移** | 直接定位到哪个源、哪一列、差多少倍 | `daily_merge.py` 已在做冲突日比对，**只差把比值落回执** |
| U-3 | **自洽性恒等式** | `turnover` 应 ≈ `volume / 流通股本`；`amount` 应 ≈ `close×volume`（非合成源上允许 ±15%）；两者**同时**偏 100 倍 → 单位；只偏一个 → 数据错 | 区分「单位错」与「值错」。`minute_sanitize.sanitize_avg_price` 已是这个思路的局部版（偏离过大按 100 倍回正，仍离谱则置空） | `turnover_repair.py` |
| U-4 | **百分数/小数二元探针** | 对每个声明为百分数的列，算全列 `|x|` 中位数；**中位数 < 0.5 且 历史基线 ≥ 0.5 → 疑似退回小数口径** | 专抓这一类：涨跌幅中位数常年在 1–2（%），掉到 0.01 量级就是换源 | `LaneContract.output_columns()` 已知哪些列是百分数口径，可直接遍历 |

**两条工程约束（比判据本身重要）**：
1. **断言失败不能静默修。** U-1/U-4 只能报警，**不可自动 ×100 回正**——`rescale_star_daily_volumes` 的注释已写明：判据只在串行下幂等，并发副本会**各除一次 100**。自动回正必须同持一把 `market_write_lock`。
2. **契约必须有录制夹具。** 已有 `tests/market/fixtures/` + `test_source_contracts.py`（东财日 K 单位、东财现价、腾讯日 K 三份）。**新增任何 `Unit` 声明都必须同批加一份夹具**，否则下一次口径漂移仍然只能人工发现。

---

## 6. AI/LLM 在量化系统里的正确位置

### 6.1 OSS 里的实践（不吹）

**第一条观察就是最重要的一条**：本轮读的三个生产级交易引擎——vn.py、NautilusTrader、Lean——**交易路径上一行 LLM 也没有**。vn.py 的 App 层、Nautilus 的 actor/strategy、Lean 的 Alpha/Portfolio/Risk 四模型，全部是确定性代码。这不是他们落后，是定位：**引擎负责可重放，LLM 不可重放**。

**第二条**：MLflow 3.x 的自我定位已改成「AI engineering platform for agents, LLMs & models」，主推能力是 **tracing / evaluation / prompt registry / AI gateway**（PyPI 介绍页原文，`X`）。即：主流对「LLM 进生产」的答案不是「让它产出数字」，而是「**给它的输出加可观测与评测**」。

**第三条（反例，本仓已有锁 commit 的一手审计）**：Vibe-Trading（锁 `3a752d5a`）把 PIT 成分、生存者偏差、`degraded` 写进**内存 `_meta`**，而后续给 LLM 的 HTML context 与工具返回**都不携带它**，也不因 `degraded` 拒绝运行；取数失败时**退化为手工 30 只静态名单继续跑** bench。这就是「AI 层看到的与数据层知道的不一致」的教科书案例——不是模型幻觉，是**管道把限定条件掉了**。

**第四条**：PanWatch 走到了另一极（定时 Agent + TradingAgents 辩论直接出「操作/决策」，持仓可手改，行情内存 TTL、重启即丢）。它能跑，但**没有一个数字是可追溯的**。

### 6.2 边界建议（能 / 不能）

| LLM **能**做 | 为什么安全 | 本仓现状 |
|---|---|---|
| 非结构化 → 结构化（公告抽成 `{event_type, amount, effective_date}`） | 输出可对照原文 span，**错了能被拓回去验** | 部分（`official_announcements` / `official_interactions` 取原文，抽取仍靠关键词） |
| 公告/研报摘要 | 摘要不是权威数字，且有原文链接 | ✅ |
| **异常解释与告警排序** | 输入已是引擎算好的 findings，LLM 只重排与改写成人话 | 部分（`repair_plan` 是表驱动不是 LLM） |
| 代码生成（公式 / 筛选条件 / 脚本） | 产物可被测试、可被 lint、可被回测 | ✅ `ScreenSkillImportDialog`（通达信/同花顺/Python）+ AI 策略转换器 |
| 把自然语言条件映射成**结构化查询参数** | 参数进了 schema，越界会被 clamp | ✅ `clamp_mcp_arguments` |

| LLM **不能**做 | 为什么 |
|---|---|
| 产出权威数字（价格/收益/胜率/因子值） | 不可重放、不可差分、错了不报错 |
| 给确定性买卖建议 | 无法回测、无法归因、无法定责 |
| 充当最后一道风控 | 模型失语时 orders 会被清空，而**清空看起来像「今天不需要操作」** |
| 把工具失败/截断讲成事实 | 本仓已有专段硬规则，且已实现（截断必须写进 `text`） |

### 6.3 「数字由量化引擎产出，AI 不发明数字」这条铁律偏保守吗？

**结论：不偏保守，而且比主流实践还少一块。** 主流（MLflow 3.x）在同一条边界上另外加了 **evaluation**；本仓把 tracing 做得很好（`ai_decisions` 存 prompt 原文 + 模型看到的报价数值 + 原始回复 + 解析 orders + 模型名/耗时/失败原因，**失语轮次同样留痕**），但 **evaluation 一步没做**。

**三处可以放开**（都不需要改铁律，只需要用已有设施）：

| # | 放开项 | 为什么安全 | 现成设施 |
|---|---|---|---|
| A-1 | **用 `ai_decisions` 做离线评测集** | 表里已有 prompt + 当时报价 + 原始回复，能重放到新模型上比对；评判标准用**引擎算的**后续收益，数字仍不由 AI 产出 | `ai_decisions` + `fills_by_decided_by`（已按 ai / rules / scenario_gate 分组） |
| A-2 | **让 LLM 提假设（hypothesis）而非结论** | 现有 `HypothesisStore` 要求证据绑 `run_id` + `artifact_sha256`，且 **hash 不在 run manifest 里就拒**；再加人工签署才能发布 | 已存且未用 |
| A-3 | **让 LLM 写结构化 PIT 事实**（公告抽取） | `PointInTimeObservation` 强制带 `available_at` + 来源 + revision；且**当前技术回测不会自动选用**它们，必须显式冻结 | 已存且未用 |

**三处必须收紧**（现在靠文档约定，不靠类型）：

| # | 收紧项 | 现状风险 | 建议 |
|---|---|---|---|
| A-4 | `ledger_record_review(return_pct…)` **接受模型转述的数字**并落库 | README 已写「禁止当权威复盘口径回读」，但**字段名与 `src.review` 引擎口径同名**，只靠人记得 | 列名改 `reported_return_pct`，或强制写 `source='ai_assistant'` 且读端默认过滤 |
| A-5 | `paper_style_memory` 把 LLM 产的「教训」回注 prompt | 自证回路：模型的判断变成下一轮模型的输入 | 已默认关（`eod_style_learn=false`）。**把理由写成「闭环污染防护」而不是「省 token」**，否则下一个人会把它打开 |
| A-6 | AI 全权路径只补 `stop_loss_safety_net` | README 自己说「这层不能省」 | **升为通用原则**：任何把 LLM 放进决策环的地方，都必须有一条规则派兜底，且**兜底在模型失语时仍执行** |

---

## 7. 本轮不做什么 / 未核验

- **未核验**：nautilus_trader 的 `LiveDataEngine` / `LiveExecutionEngine` **源码**（raw 与目录 API 均 404/403）；本文关于它的一切都是官方文档口径（P2）。Lean 的 `RiskManagementModel` 抽象基类文件本轮未单独读到，结论从目录 + 两个实现类全文推得。
- **未跑**：未安装 mlflow / pandera / GE / DVC 任一包，体积与依赖数来自 PyPI 元数据而非本机安装实测；安装后的真实磁盘/RSS 占用未测（经验上为 wheel 的 2–3 倍，**这个倍数未在本机验证**）。
- **未改**：未改任何代码、未建任何 Job、未改 `INDEX.md`、未改任何 README、未 commit。
- **不建议直接执行的**：M-8 提到的「热库 `idx_quotes_receipt` 可能白占 238.3 MB」**必须先跑 EQP 确认热库读路径真的不用它**，再讨论是否在镜像时不建。本仓已有反例（那条看着吓人的相关子查询实测反而快 18 倍）：**看计划不测量得出的结论不算数**。
- **优先级建议（若只做一件）**：**M-9（连续零信号告警）**。它是唯一一个「不做就永远不会被发现」的缺口，其余各项失效都至少会在某个页面上看得出来。

---

## 8. 摘要

两处前提已过期：订单对象与 pre-trade gate 都在，二波也已接 `skill_watch` 且 Job 在跑。真正零覆盖的是**实验可复现**（`strategy_backtests` 建表却 0 行）与**回测-实盘偏离**（2026-08 随实盘账本删除）；前者本文给出 manifest 的 JSON Schema 与三步零依赖落地。风控缺组合层集中度与信号泛滥降级；监控最危险的是降噪让「引擎坏了」与「今天没信号」同样沉默；数据质量缺涨跌幅越界、零量有涨跌、因子跳变三条断言。MLflow/GE/DVC 均拒绝，附实测依赖与体积。铁律不保守，只差 evaluation。
