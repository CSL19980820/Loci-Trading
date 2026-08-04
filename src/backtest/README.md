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

## 关键入口
- 成交：`run_backtest` / `backtest_strategy` / `run_backtest_fast`
- Horizon：`run_horizon_backtest` / `backtest_strategy_horizon`
- HTTP：`POST /api/backtest`（`mode=trade|horizon`）

### 成交统计口径
- `data_end` 明细仍保留供审计；绩效指标只统计完整持有期，并通过 `data_end_trades` 单独披露尾部记录数。最后一根缺失或非法收盘价不构成可结算交易，会按“持有期内始终无法卖出”跳过。
- 策略信号和执行价格可以声明不同口径：例如尾盘版用 `qfq` 计算指标、用 `none` 的原始 OHLC 模拟实际成交；结果配置会回显 `execution_adjust`。不能把复权收盘价直接当作除权日成交价。

### Horizon 口径
- 信号窗最长 186 自然日（约 6 个月）
- `close`：T+N → `high(D+N)/close(D)-1`
- `next_open`：T+N → `high(D+1+N)/close(D)-1`
- `next_dip`：T+N → 入场日为 D+1；成交回测按 D 日目标价判断 D+1 是否触价，未触价不成交
- 聚合：`n` / `win_rate` / `avg` / `best` / `worst`，并附 `best_event` / `worst_event`（code/name/signal_date/mark_date/return_pct）
- 一次 `load_panel` 覆盖预热+信号+尾巴，禁止按信号日循环拉 history

## 如何扩展
改成交假设须同步策略 entry_timing 语义与测试；改 Horizon 标记规则须同步计划文档与 `test_horizon.py`。

### 加速旁路（可选，仅成交路径）
- 环境变量 `LOCI_BACKTEST_FAST=1` 时走 `run_backtest_fast`（numpy 向量化批量，有止损/止盈细规则时回退经典引擎）。
- **权威路径仍是** `engine.run_backtest`（一字板 / T+1 / 止损止盈细规则）；加速失败或配置了细规则止损时回退经典引擎。
- `entry_timing` 只能来自策略引擎，Job 参数不可覆盖成前视口径。
- 不写 `palace.db`；不发明信号。

## 给 Agent 的用法
- `from src.backtest import backtest_strategy, backtest_strategy_horizon, run_horizon_backtest`
- 入场时点以策略声明为准，禁止调用方随意覆盖成前视口径
- `next_dip` 的目标价由策略参数 `dip_pct` 生成（默认回撤 2%）；成交价只允许是次日开盘价或目标价
- 参数扫描 / ops Job 可开 `LOCI_BACKTEST_FAST`；交付结论前应用经典路径复核关键数字
- 需要原始成交价的策略通过 `execution_adjust = "none"` 声明，`backtest_strategy` 会保留信号面板的复权口径并单独加载执行面板

## README 维护
改成交假设、Horizon 口径、公开 API、加速旁路开关时必须更新本文。

## 相关测试
`tests/backtest/`（含 `test_horizon.py` 口径与 6 月硬顶；`test_fast_engine.py`）
