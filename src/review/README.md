# 复盘（review）

## 职责
资金曲线、持仓归因、候选 T+N、预案兑现等确定性计算。

## 边界
只读 ledger + market；可写 market 侧缓存表。AI 不得替代本模块出数。

## 关键入口
`build_equity_curve` / `evaluate_candidates` / `filter_recent_outcomes` / `track_candidate_outcomes` / `strategy_winrate_summary`；
盘面近选跟踪用 `window_days=5`（T～T+4）过滤精选候选。
HTTP：`/api/review/*` `/api/winrate/*` `/api/insights/*`

洞察与胜率口径：
- `/api/winrate/summary`：精选候选 **T+5** 胜率优先（另附 T+1/T+3）；无候选样本时回退手工 `reviews`
- `/insights/decay`：优先候选 T+5 滚动胜率 vs 基线；无候选回退复盘；前端消费在选股目录「近期胜率」
- `/insights/overlap`：core 候选按 `rule_version` 的信号重叠（日均 Jaccard + 常撞代码）；**不是**持仓风险；排除回填源
- `evaluate_candidates` / 胜率链路默认排除 `%backfill%` / `%:history`，避免区间重放抬高 T+N
- 候选观察窗：`PRIMARY_HORIZONS=(1,3,5)`，完整窗含 10/20/60
- 盘后托管 Job「候选T+N跟踪」（`kind=outcome`，cron `45 15 * * 1-5`）重算近 5 个交易日窗口

## 如何扩展
新指标放 application/，经 API 暴露；补 tests/review。


## 给 Agent 的用法
- 曲线/归因：`from src.review import build_equity_curve, round_trips, evaluate_candidates`
- 自动胜率：`track_candidate_outcomes` / `strategy_winrate_summary`
- `round_trips` 排序：持有在前、了结在后；各自按开仓日/了结日倒序
- 资金曲线：`总资产 = 现金 + Σ持股×收盘价`（盯市）；缺某日收盘价时用最近可用价递补，全程无行情不计市值并写 `note`
- 与总览不同：总览有现金时偏「现金 + 成本占用」，不是同一口径
- 输入只能是真实账本 + 真实行情
- 候选裁决按 ledger 的公开 `normalize_decision` 归一；不导入 `ledger.infrastructure`
- 禁忌：用 LLM 结果冒充复盘数字

## README 维护
改指标口径、缓存表、公开函数签名、T+N 窗口或胜率数据源时必须更新本文。

## 相关测试
`tests/review/`
