---
name: 龙回头·二波监测
slug: dragon-second-wave
version: 1.0.0
description: 曾大涨的票回踩 MA10 探底回升时盘中提醒；强度低于 45 分或仅观察不刷企微
strategy_skill: true
signal_engine: second_wave
signals: [paper_candidate, watch_only, gate_empty]
mcp_servers: []
tools: []
policy: research
---

# 龙回头·二波监测

**不依赖 MCP**：全市场日 K 建池 + 实时快照判触发，没有悟道 Key 也能跑。

## 流程

1. **建池**：20 日涨幅进过全市场前 10（成交额 ≥3000 万、沪深主板/创业板/科创板）
2. **盯 20 个交易日**：同一代码取**首次**入池，重进前十不续期
3. **触发**：当日最低打到 MA10 又收复（`low ≤ MA10 < 现价`）且距 20 日最高 ≤3 天
4. **宽度闸**：全市场上涨家数占比 ≥55%，弱市只记录不提醒
5. **强度闸**：低于 45 分不进 picks（仍落库，标 `alerted=0`）。达标票标 `intent=observe`，
   首页快照更新，**不刷企微**（仅观察不算可执行候选）

## 信号定义

| 信号 | 条件 |
|---|---|
| paper_candidate | 过宽度闸 + 触发 + 强度 ≥45 → 结构化 picks（`validation=unverified`） |
| watch_only | 池内无触发、触发但强度均未达线、或纸面候选段关闭 |
| gate_empty | 市场宽度低于下限（弱市空仓） |

## 强度分（0–100，权重来自回测分档）

| 维度 | 给分 |
|---|---|
| 触发日 20 日涨幅 50~100% | +30（**W 形非单调**：20~50% 是全表最差，不给分并标「涨幅险区」；≥150% 也不给） |
| 距 20 日高点 0–1 天 | +25（2–3 天 +15） |
| 距高点回撤 10~20% | +25（5~10% / 20~30% 各 +12） |
| 筹码宽度 <15% | +20（15~25% +12） |

实测分档均净：00-44 **−0.962%**、45-59 +2.533%、60-69 −0.026%、70-79 +3.344%、80-100 +5.213%。
45 是唯一「以下全负、以上整体为正」的线。

## 调参

`watch_tuning:{slug}` 的 `second_wave` 段：`pool_top_n` / `watch_days` / `ma_window` /
`breadth_min` / `peak_days_max` / `min_strength` / `amount_min_wan`；
段开关用 `stages.paper_candidates`（关掉则不进 picks、不刷企微）。

## 边界

- **逐笔口径可信、组合口径不可信**：提醒只给信号与依据，不给预期收益
- 属于「曾大涨 + 回撤到位」家族，与已退役的龙池同源；区别是盘中触发 + 宽度闸 + 强度分档
- 观察期留痕在 `ops.db.second_wave_signals`（含未提醒的反例），保留 180 天
