---
name: 涨停 momentum 接力
slug: limit-up-momentum
version: 1.1.0
description: 追踪涨停梯队晋级与炸板回封，筛选可接力标的
strategy_skill: true
signal_engine: limit_up_momentum
signals: [paper_candidate, sell_hint, watch_only, gate_empty]
mcp_servers: [wudao-a-stock]
tools:
  - short_term_emotion
  - limit_up_ladder
  - limit_up_filter
  - broken_limit_up
  - approaching_limit_up
  - theme_intraday_capital
  - auction_market_scan
  - kline
policy: research
---

# 涨停 momentum 接力

## 流程

1. **龙空龙闸门**（`market_regime`，可经 `watch_tuning` 关闭）：晋级率/炸板率/梯队高度/主线强度 → 空仓窗口只观察、不出纸面候选
2. `short_term_emotion` 判断情绪周期（晋级率／炸板率）
3. `limit_up_ladder` 看梯队前排；`broken_limit_up` 找弱转强候选
4. `theme_intraday_capital` 参与闸门，不单独发明主线数字
5. 竞价放弃票经 `paper_eligibility` 过滤，不得进入纸面预案

## 信号定义

| 信号 | 条件 |
|---|---|
| paper_candidate | 闸门允许进攻 + 梯队/弱转强评分达线 → 结构化 picks（`validation=unverified`） |
| watch_only | 空仓/观察窗、形态分未达线、或纸面候选段关闭 |
| gate_empty | 龙空龙闸门判空仓 |
| sell_hint | 晋级率过低或炸板率飙升（风险观察，非买卖指令） |

## 调参

与龙回头共用 `watch_tuning:{slug}`：`stages.market_gate` / `paper_candidates`；阈值 `gate.*` / `scan.candidate_score` / `scan.max_candidates`。
