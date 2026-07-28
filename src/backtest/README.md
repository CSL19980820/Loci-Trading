# 回测（backtest）

## 职责
把策略信号变成可比较绩效（事件驱动、尊重入场时点）。

## 边界
读 market + strategy；不写 palace。

## 关键入口
`run_backtest` / `backtest_strategy` / `run_backtest_fast`；HTTP：`/api/backtest`

## 如何扩展
改成交假设须同步策略 entry_timing 语义与测试。

### 加速旁路（可选）
- 环境变量 `LOCI_BACKTEST_FAST=1` 时走 `run_backtest_fast`（优先 vectorbt，否则 numpy 批量对齐）。
- **权威路径仍是** `engine.run_backtest`（一字板 / T+1 / 止损止盈细规则）；加速失败或配置了细规则止损时回退经典引擎。
- `entry_timing` 只能来自策略引擎，Job 参数不可覆盖成前视口径。
- 不写 `palace.db`；不发明信号。

## 给 Agent 的用法
- `from src.backtest import backtest_strategy, run_backtest, run_backtest_fast, fast_backtest_enabled`
- 入场时点以策略声明为准，禁止调用方随意覆盖成前视口径
- 参数扫描 / ops Job 可开 `LOCI_BACKTEST_FAST`；交付结论前应用经典路径复核关键数字

## README 维护
改成交假设、退出规则、公开 API、加速旁路开关时必须更新本文。

## 相关测试
`tests/backtest/`（含 `test_fast_engine.py`：无止损 hold 下 fast vs 经典笔数/收益对齐；有止损时断言回退经典）
