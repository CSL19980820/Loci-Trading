# 回测（backtest）

## 职责
把策略信号变成可比较绩效（事件驱动、尊重入场时点）。

含两条路径：

| 模式 | 入口 | 问题 |
|------|------|------|
| `trade` | `run_backtest` / `backtest_strategy` | 按入场价模拟买卖（止损止盈） |
| `horizon` | `run_horizon_backtest` / `backtest_strategy_horizon` | 选股日后视 T+N：标记日最高 ÷ 选股日收盘 |

## 边界
读 market + strategy；不写 palace。

## 重任务执行边界

`compare` / `optimize` 的 HTTP 分析入口默认把计算交给 `spawn` 子进程（请求体的
`execution_mode` 可显式设为 `thread`）。子进程只接收显式的 `market_db` 路径和
当前租户标识，在自己的连接中加载行情与 Screen Skill；取消、超时、进程异常由
父任务收口到既有 `ops.db.job_runs` 状态机，不另建内存任务表。进程槽默认 1 个，
可用 `LOCI_BACKTEST_PROCESS_SLOTS` 调到 1–4；槽满会返回可重试的容量错误。

单次 `backtest` Job 也支持 `config.execution_mode=process`。默认仍是线程，保证
旧 CLI/测试的低延迟；需要运行大面板或参数扫描时应使用进程模式。结果会附带
`execution.mode / worker_pid / peak_rss_bytes`（未安装 `psutil` 时 RSS 为 `null`），
用于运维核对实际隔离是否生效。

## 关键入口
- 成交：`run_backtest` / `backtest_strategy` / `run_backtest_fast`
- Horizon：`run_horizon_backtest` / `backtest_strategy_horizon`
- HTTP：`POST /api/backtest`（`mode=trade|horizon`）
- 指标：`compute_metrics`（无资金假设）、`compute_trade_performance`（诊断曲线）

### 成交统计口径
- `data_end` 明细仍保留供审计；绩效指标只统计完整持有期，并通过 `data_end_trades` 单独披露尾部记录数。最后一根缺失或非法收盘价不构成可结算交易，会按“持有期内始终无法卖出”跳过。
- 策略信号和执行价格可以声明不同口径：例如尾盘版用 `qfq` 计算指标、用 `none` 的原始 OHLC 模拟实际成交；结果配置会回显 `execution_adjust`。不能把复权收盘价直接当作除权日成交价。
- `metrics`（无组合假设）：胜率、均值/中位/标准差、盈亏比、期望、profit factor、payoff、连胜/连亏、分位数、分月/年、收益直方、`sample_confidence`（n&lt;30 为 low，n&lt;100 为 medium，否则 high）、小样本 `caution`。
- `performance`（**诊断假设**，见下）：累计/CAGR、最大回撤及峰谷日、波动/下行波动、夏普/索提诺/Calmar、资金曲线与回撤曲线。

#### performance 诊断假设（必须原样回显）
- `assumption.model = trade_sequence_compounding`
- 仅非 `data_end` 交易，按 `(exit_date, entry_date, code)` 排序后**顺序复利**；每笔占满名义资金
- 无风险利率默认 `0%`（`assumption.risk_free_rate_pct`）
- **不是**真实多仓组合；真实槽位账本见 `analyze_portfolio` / `research_portfolio`
- 禁止把该曲线冒充账户净值

#### 组合账本的权益口径（`analyze_portfolio` / `research_portfolio`）

**未实现盈亏不盯市。** 输入只有逐笔 `Trade`（入场价、退出价、净收益、MAE/MFE），
没有逐日收盘价，所以 `equity = cash + Σ 入场名义额`：持仓期内曲线是平的，全部盈亏在
退出日一次性落地。因此 `max_drawdown_pct` 量的是**已实现盈亏回撤**，不是账户回撤——
一只票持仓中途跌 30% 又涨回来，这条曲线上一个点都看不到。

读结果必须先读 `metrics.assumption`（`equity_basis="cost_until_exit"`、
`marks_to_market=false`、`drawdown_basis="realized_only"`），再读回撤。另有
`mae_bound_max_drawdown_pct`：用每笔**已测得**的 MAE 算的保守上界（假设所有持仓同时
落在各自最差点），真实账户回撤介于两者之间。两者接近说明这条曲线可用；相差很大说明
必须拿逐日行情重算。

不变式 I1（现金守恒）由 `assert_cash_conservation` 在收口处强制：期末权益必须等于
初始资金 + 全部已实现盈亏，破了直接抛 `PortfolioInvariantError`。

默认成本（可经 `BacktestConfig` / `POST /api/backtest` 的 `commission_bps`·`stamp_duty_bps`·`slippage_bps` 改）：佣金单边 3bps、卖出印花税 10bps、滑点单边 5bps → 一趟约 0.26%。

### Horizon 口径
- 信号窗最长 186 自然日（约 6 个月）
- `close`：T+N → `high(D+N)/close(D)-1`
- `next_open`：T+N → `high(D+1+N)/close(D)-1`
- `next_dip`：T+N → 入场日为 D+1；成交回测按 D 日目标价判断 D+1 是否触价，未触价不成交
- 聚合：保留 `n` / `win_rate` / `avg` / `best` / `worst` / `best_event` / `worst_event`；并**追加**（不改旧字段）：
  - `median` / `std` / `percentiles` / `payoff_ratio` / `distribution` / `by_month` / `sample_confidence` / `caution`
  - `close_*`：标记日收盘相对选股日收盘（更接近可兑现；仍非成交引擎）
  - `mark_basis=high` + 说明：高点口径属乐观上沿
- **不**构造资金曲线 / 夏普 / 回撤——horizon 无持仓资金约束，禁止为凑指标编造等权组合
- 一次 `load_panel` 覆盖预热+信号+尾巴，禁止按信号日循环拉 history

## 如何扩展
改成交假设须同步策略 entry_timing 语义与测试；改 Horizon 标记规则须同步计划文档与 `test_horizon.py`。
新增指标一律 application 即时算，不落权威表。

### 旧快速入口兼容
- `LOCI_BACKTEST_FAST=1` 和公开 `run_backtest_fast` 保留，统一委托 `engine.run_backtest`。已删除重复的无止损成交循环，停牌、一字板、T+1、止损止盈及数据末尾只维护一套规则。
- 旧入口的 `config["fast"]` 回显 `engine="classic"` 和原因；不再声称使用 `numpy_fast`，也不再用异常重跑整次回测。
- 核心循环将信号坐标一次转换为 Python 整数，成本只算一次，无止损止盈时跳过空的逐日触价扫描。固定合成数据对照旧引擎，四种入场时点 × 四种止损止盈组合，逐笔交易与全部指标相同；未测得稳定的整体提速，不作速度承诺。
- `entry_timing` 只能来自策略引擎，Job 参数不可覆盖成前视口径。
- 回测加载面板后、`compute` 前跑 `guard_strategy`：小宇宙（≤100 列）全列截断一致性；大宇宙按 `LOCI_AUDIT_PANEL_SAMPLE_SIZE`（默认 200、上限 500）分片探测，任一片 block 即失败。
- 不写 `palace.db`；不发明信号。

## 给 Agent 的用法
- `from src.backtest import backtest_strategy, backtest_strategy_horizon, run_horizon_backtest, compute_trade_performance`
- 入场时点以策略声明为准，禁止调用方随意覆盖成前视口径
- `next_dip` 的目标价由策略参数 `dip_pct` 生成（默认回撤 2%）；成交价只允许是次日开盘价或目标价。目标价一律在**执行面板**（`execution_adjust` 那一份）的价格坐标系里生成——策略若声明 `execution_adjust="none"` 而信号面板是 `qfq`，用信号面板算目标价再去比不复权最低价，两边差一个复权因子，触价判断会整体错位
- 止损/止盈的触发只说明当天能成交，成交价另算：跳空低开穿过止损位按开盘价出（`min(open, stop)`），跳空高开越过止盈价按开盘价出（`max(open, target)`）。按限价记账会让偏差全落在最差的那批交易上
- 一字板按方向区分：一字涨停买不进但**卖得掉**，只有一字跌停才顺延退出日。两者共用一个方向无关的掩码会系统性低估打板类策略
- 参数扫描 / ops Job 直接复用统一成交引擎；旧 `LOCI_BACKTEST_FAST` 仅为兼容，不代表独立加速能力
- 需要原始成交价的策略通过 `execution_adjust = "none"` 声明，`backtest_strategy` 会保留信号面板的复权口径并单独加载执行面板
- 读 `performance` 时必须先读 `assumption.model`，勿与组合研究账本混谈

## README 维护
改成交假设、Horizon 口径、公开 API、加速旁路、指标字段时必须更新本文。

## 相关测试
`tests/backtest/`（含 `test_horizon.py`、`test_metrics_performance.py`、`test_fast_engine.py`）
