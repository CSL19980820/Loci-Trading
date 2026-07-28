# 复盘（review）

## 职责
资金曲线、持仓归因、候选 T+N、预案兑现等确定性计算。

## 边界
只读 ledger + market；可写 market 侧缓存表。AI 不得替代本模块出数。

## 关键入口
`build_equity_curve` / `evaluate_candidates`；HTTP：`/api/review/*` `/api/winrate/*` `/api/insights/*`

## 如何扩展
新指标放 application/，经 API 暴露；补 tests/review。


## 给 Agent 的用法
- 曲线/归因：`from src.review import build_equity_curve, round_trips, evaluate_candidates`
- 输入只能是真实账本 + 真实行情
- 禁忌：用 LLM 结果冒充复盘数字

## README 维护
改指标口径、缓存表、公开函数签名时必须更新本文。

## 相关测试
`tests/review/`
