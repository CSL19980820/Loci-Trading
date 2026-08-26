---
name: 龙回头
slug: dragon-return
version: 1.2.0
description: 龙王套件·可买层：龙空龙闸门 + 龙头战法角色 + 回头形态；输出次日可买(intent=buy)与观察(intent=observe)
strategy_skill: true
signal_engine: dragon_return
signals: [paper_candidate, gate_empty, invalidated, watch_only, leader_watch, theme_interval_weak, theme_interval_degraded]
validation: unverified
entry_gate: dragon_empty_dragon
mcp_servers: [wudao-a-stock, loci-market]
tools:
  - short_term_emotion
  - trading_calendar
  - limit_stats
  - limit_up_ladder
  - limit_up_filter
  - theme_intraday_capital
  - sector_analysis
  - theme_stocks
  - auction_opening_snapshot
  - stock_screener
  - kline
  - capital_flow
  - intraday_main_flow
policy: research
---

# 龙回头（龙王套件·可买层）

## 固定流程

本战法**不自己猜龙头**，而是消费龙头战法（`market-leader-map`）角色。

1. 跑龙头战法（内含龙空龙闸门 + 区间强度软过滤主线 + 角色判定 + 竞价复核）
2. 对 `leader` / `secondary` 打回头形态分
3. 进攻窗且达线 → `intent=buy`（可买，默认最多 2）
4. 其余入池角色 → `intent=observe`（次日观察，不开仓）
5. 空仓窗仍可出观察；`weakened` / `failed` 出 `invalidated`
6. 日终重扫发现后写入次日预案；竞价/开盘门闩由纸面舱决定是否跟随

## 组合关系（龙王战法大成体）

```text
龙空龙闸门 → 区间强度软过滤 → 龙头战法(角色/观察) → 龙回头(可买) → 次日情景预案 → 纸面舱
```

## 评分（100）

- 龙头基因 35：涨停次数、连板梯队、题材强度
- 回头形态 35：回撤/缩量/支撑
- 二次启动 20：放量阳线、站回均线
- 风险扣分：破位、市场退潮、数据缺失

## 输出

- **纸面候选 ≤2 只**（形态分 ≥65，未经过前向验证）
- **观察**（闸门为观察或形态分未达线）
- **空仓窗口**（市场数据不完整或退潮）
- **区间走弱预警**（`theme_interval_weak`，软信号，不单独改开仓）

## 信号定义

| 信号 | 条件 |
|---|---|
| paper_candidate | 闸门为“龙”、角色为 leader/secondary 且形态分 ≥65 |
| gate_empty | 市场闸门为“空”，不生成开仓候选 |
| invalidated | 龙头地图判为 weakened / failed |
| watch_only | 市场仍在观察，或形态分未达候选线 |
| leader_watch | 观察池角色条（次日观察） |
| theme_interval_weak | 入选主线落在开盘啦「高位走弱/弱势」象限 |
| theme_interval_degraded | 区间强度不可用或题材名未对齐（软过滤未真正生效） |

本地 K 线验证优先走 `loci-market`；涨停梯队／题材／情绪／区间强度只用 `wudao-a-stock`。
本包的 `validation` 固定为 `unverified`，不得把纸面候选表述成已验证买卖建议。

## 公开口径参考

- https://m.eastmoney.com/blog/article/1081687485
- https://finance.sina.com.cn/roll/2025-06-26/doc-infcmcye4619814.shtml
- https://finance.sina.com.cn/roll/2024-12-16/doc-inczrenx6071815.shtml
- https://www.fupanwang.com/zhishi/7813.html
