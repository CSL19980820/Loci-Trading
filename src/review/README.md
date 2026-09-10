# 复盘（review）

## 职责
候选池 T+N、预案兑现、战法胜率、衰减与重叠等确定性计算。

**口径（2026-08 实盘项下线后）**：复盘只基于**候选池 + 行情**算**纸上收益**——
「如果信号日收盘买了会怎样」。它不再读真实成交 / 持仓，因此也不再回答「我实际赚了多少」。

## 边界
只读 ledger 的候选池 / 预案 / 复盘三类表（`candidate_reviews` / `plans` / `reviews`）+ market。
触价（`GET /api/alerts/today`，ledger 路由经 `open_market_hot`）与容量
（`check_capacity`，调用方应注入热库）读 `market_hot.db` 近窗，不扫全量写库。
候选 T+N / 预案兑现 / 胜率（`/api/review/candidates|plans`、`/api/winrate/*`）仍读**全量**
`market.db`——长历史可能超出热库 700 交易日。见 [ADR-007](../../docs/adr/ADR-007-market-hot-readonly-window.md)。
可写 market 侧缓存表。AI 不得替代本模块出数。

## 关键入口
`evaluate_candidates` / `filter_recent_outcomes` / `track_candidate_outcomes` /
`build_winrate_summary` / `winrate_periods` / `winrate_samples`（合称 winrate 三视角，都吃同一批已算好的 outcomes）；
盘面近选跟踪用 `window_days=5`（T～T+4）过滤精选候选。
HTTP：`/api/review/candidates|plans` `/api/winrate/*` `/api/insights/*`

洞察与胜率口径：
- `/api/winrate/summary`：精选候选 **T+5** 胜率优先（另附 T+1/T+3）；无候选样本时回退手工 `reviews`。每行还带 `horizons`（T+1…T+60 全档）、`best_horizon`（样本 ≥3 的最优持有期）、`best_sample` / `worst_sample`（点名到票+日期）——胜率页要能回答「凭什么」
- `/api/winrate/trend`：**与 summary 同源**，精选候选 T+5 按**选出日**分月/周聚合；一条候选样本都没有时才回退手工 `reviews`（行内 `source` 标明是哪种）。2026-09 之前它只读 `reviews`，而线上那张表 0 行，页面「分周期明细」于是永远空着
- `/api/winrate/samples?tag=`：某战法逐条样本（选出日 / 代码 / 基准价 / 各档收益 / 是否计赢）。`settled` 是胜率分母，`observing` 不进分母
- `/insights/decay`：优先候选 T+5 滚动胜率 vs 基线；无候选回退复盘；前端消费在选股目录「近期胜率」
- `/insights/overlap`：core 候选按 `rule_version` 的信号重叠（日均 Jaccard + 常撞代码）；**不是**持仓风险；排除回填源
- `evaluate_candidates` / 胜率链路默认排除 `%backfill%` / `%:history`，避免区间重放抬高 T+N
- 候选观察窗：`PRIMARY_HORIZONS=(1,3,5)`，完整窗含 10/20/60
- 胜率**样本披露**：`horizon_aggregate`（公开，`winrates` 复用同一口径）与 `summarize_by_strategy` 的每一行都带 `sample_confidence`（`low`/`medium`/`high`，阈值 30/100，与 `backtest.application.metrics` 同口径），不足 30 只候选再附 `caution`。胜率数值口径不变——只是一只候选走完 T+5 就报「100%」时必须标出样本档，否则会被当成结论
- 盘后托管 Job「候选T+N跟踪」（`kind=outcome`，cron `45 15 * * 1-5`）重算近 5 个交易日窗口

## API 层的结果缓存
`api/router.py` 有一层进程内 LRU，键 = 端点 + 参数 + `palace.review_read_fingerprint()` +
`market.market_revision()`，命中 candidates / plans / winrate_summary / winrate_trend /
winrate_samples，外加一个内部 scope `candidate_outcomes`——winrate 三兄弟都从它派生，同一条请求链上 `evaluate_candidates` 只跑一次。
不设 TTL：靠版本号换键，账本或行情一写立刻失效，不引入隐式陈数据。
`review_read_fingerprint()` 必须是**逐行摘要**而不是 `COUNT(*)`——候选**等长改判**
（行数不变、裁决变了）也得换键，否则会发陈数据。
`/api/winrate/trend` 改成候选口径后不再是几毫秒的裸 SQL，因此也进了缓存。

## 如何扩展
新指标放 application/，经 API 暴露；补 tests/review。

## 给 Agent 的用法
- 候选 T+N：`from src.review import evaluate_candidates, summarize_candidates`
- 预案兑现：`evaluate_plans`（实现于 `application/outcomes_plans.py`）
- 自动胜率：`track_candidate_outcomes` / `strategy_winrate_summary`（HTTP 侧用
  `build_winrate_summary` + `winrate_periods` + `winrate_samples`，三者共用一次 `evaluate_candidates`）
- 输入只能是候选池 / 预案 / 手工复盘 + 真实行情；产出是**纸上收益**，不是实盘盈亏
- 候选裁决按 ledger 的公开 `normalize_decision` 归一；不导入 `ledger.infrastructure`
- **Store 直捅债**（收拢中）：`evaluate_plans` → `plans_payload`；触价 → `active_plans_with_stops` + `market.latest_bars`；`evaluate_candidates` → `candidate_outcome_rows`；`check_decay` → `review_returns_for_tag` / `review_strategy_tags_with_returns`；`check_capacity` → `market.recent_amounts`。仍直捅：`overlap`——新代码勿再增加 `.conn`
- 禁忌：用 LLM 结果冒充复盘数字

## 2026-08 实盘项下线（已删）
复盘改为只算纸上收益后，以下依赖真实成交 / 持仓的能力**整体删除**，不做降级保留——
留一个读不到成交的「胜率」比没有更糟，它会被当成纸面舱的结论：

| 已删 | 读的是 |
|---|---|
| `application/equity.py`（`build_equity_curve`） | `account_snapshots` / `daily_pnl_ledger` / `position_events` |
| `application/replay.py`（`positions_as_of` / `round_trips` / `holdings_timeline`） | `position_events` |
| `application/attribution.py`（往返 MAE/MFE 归因） | 上游是 `replay` 的真实往返 |
| `application/marks.py`（`attach_mark_prices` / `summarize_marks`） | 真实 `holdings` 盯市 |
| `application/drift.py`（`compute_drift` / `sync_position_tracking`） | `position_tracking` + `position_events` |
| 端点 `/api/review/equity|trips|positions|drift` | 同上 |

`track_candidate_outcomes` **保留**，签名不变；只摘掉了它尾部那段把精选候选镜像写入
`position_tracking` 的只写不读旁路，返回值里的 `tracking` 键随之消失。T+N 数字一个都没变——
它们从来只由 `candidate_reviews` + 行情推导。

## README 维护
改指标口径、缓存表、公开函数签名、T+N 窗口或胜率数据源时必须更新本文。

## 相关测试
`tests/review/`
