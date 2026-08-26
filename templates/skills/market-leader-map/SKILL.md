---
name: 龙头战法
slug: market-leader-map
version: 1.2.0
description: 龙王套件·角色层：先判市场窗口，再把主线题材成分标成龙头/中军/跟风/走弱/破位，供龙回头可买与次日观察复用
strategy_skill: true
signal_engine: leader_map
signals: [leader_watch, leader_weak, gate_empty, watch_only, theme_interval_weak, theme_interval_degraded]
validation: unverified
entry_gate: dragon_empty_dragon
mcp_servers: [wudao-a-stock, loci-market]
tools:
  - short_term_emotion
  - limit_up_ladder
  - theme_intraday_capital
  - sector_analysis
  - theme_stocks
  - auction_opening_snapshot
  - kline
policy: research
---

# 龙头战法（龙王套件·角色层）

本包**不直接开仓**，回答「现在谁是龙头、谁在走弱」，并作为次日**观察池**来源。
龙回头消费这里的 `leader` / `secondary` 做可买；空仓日仍出图供观察。

## 固定流程

1. `short_term_emotion` + `limit_up_ladder` + `theme_intraday_capital` 判龙/空/观察
2. 按盘中强度取更宽题材池，再用 `sector_analysis`（开盘啦区间强度四象限）软重排截到前 N 条；失败则退回盘中强度序（fail-open）
3. `theme_stocks` 拉成分，本地/`loci-market` 日 K 核验（一次最多 20 只）
4. 用连板高度 + 20 日涨幅 + 回撤 + 均线 + 量比给每只票定角色
5. 09:15–09:30 用 `auction_opening_snapshot` 复核**龙头与中军**，竞价放弃者当场降为 failed
6. 输出龙头地图与走弱名单；入选主线若落在「高位走弱/弱势」象限则附加 `theme_interval_weak`
7. 把角色追加进留痕表

退潮日**照常出图**：谁破位、谁走弱在空仓窗口里最有价值。只有下游开仓型战法
才会在空仓窗口提前收工省配额。

## 可配置项

流水线段都能单独关（工坊 → 技能 → 配置 → 监测调参）：
`market_gate`（市场择时）、`theme_interval`（区间强度软过滤）、`auction_confirm`（竞价确认）、
`role_history`（角色留痕）、`paper_candidates`（纸面候选）。题材数、成分数、角色阈值、竞价高低开阈值同样可改。
关掉的段是真的不跑，也不消耗悟道配额。

## 角色定义

判定顺序固定，先看结构是否已破，再看是否最强。

| 角色 | 条件 |
|---|---|
| failed | 放量跌破 MA20（收盘 < MA20×0.94 且量比 ≥1.2），主升结构破坏 |
| weakened | 曾强（有涨停或 20 日涨幅 ≥15%）但回撤 ≥25% 或失守 MA10 |
| leader | 题材内连板最高且 ≥2 板；题材无连板时取 20 日涨幅最高且 ≥15% |
| secondary | 连板 ≥2，或题材内涨幅前二 |
| follower | 在主线票池内但未取得高度 |

涨停判定按板块幅度走本地公式（创业板/科创 20%、北交所 30%、ST 5%），
不是一刀切 9.5%。

## 信号定义

| 信号 | 条件 |
|---|---|
| leader_watch | 判定为 leader 的标的，最多 3 只 |
| leader_weak | 判定为 weakened / failed 的标的，最多 3 只 |
| gate_empty | 市场闸门为「空」 |
| watch_only | 闸门观察中，或票池无可判定角色 |
| theme_interval_weak | 入选主线落在开盘啦「高位走弱/弱势」象限 |
| theme_interval_degraded | 区间强度不可用或题材名未对齐 |

## 组合关系

```text
market-leader-map ──角色──> dragon-return（只对 leader / secondary 找回头）
                 ├─走弱──> 纸面舱盘中监测（已有仓位的退出证据）
                 └─留痕──> 角色演进（谁从龙头掉下来、什么时候掉的）
```

角色留痕是**只追加**的观测流，落 `ops.db.leader_role_snapshots`，一次扫描写一批。
`GET /api/skills/{slug}/leader-roles` 可回看历史与角色变化。

所有输出的 `validation` 固定为 `unverified`：角色是对当下盘面的确定性描述，
不是经过前向验证的盈利结论。AI 只能解释证据，不得改写角色。
