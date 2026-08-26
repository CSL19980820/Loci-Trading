# Loci / stock-analyzer 全系统审计 · 第六轮（R6）

> 执行日期：2026-08-07  
> 前提：[R5](./2026-08-system-wide-audit-r5.md) open 项收口后  
> 方法：Grok 多 agent 落地剩余 P2 + 只读再审 + 本地回归  
> 约束：不收紧 AI ExecutionGrant / HITL / AI `add`

---

## 0. 结论

R5 原 open 项（前视分片、rules 退出、Pulse 错峰、Dashboard 本月%、Bearer≥32、preview 写鉴权、CLI/import-linter、review alerts Store 等）**已 closed**。  
再审 **无新 P0**；发现 2 条 P1 **本轮已修**：

1. **R6-P1-1**：轮询 `persist: live` 在写鉴权环境整请求 401 → 轮询改 `persist: false`  
2. **R6-P1-2**：手工纸面下单未接交易日闸 → `post_manual_orders` 对齐 monitor

`lint-imports` **11 kept**；目标 verify pytest **422 passed**。

---

## 1. R5 open → R6 状态

| ID | 状态 |
|---|---|
| P2-1 CLI 深掏 | **fixed**（包根 + cli 合约） |
| P2-2 screen_skills `_REGISTRY` | **fixed**（公开 API） |
| P2-3 review `.conn` | **partial→alerts/equity/decay/drift/capacity fixed**；overlap/replay 仍债 |
| P2-4 import-linter research/cli | **fixed**（11 合约） |
| P2-6 rules 退出 | **fixed** |
| P2-8 前视 40 列 | **fixed**（分片全覆盖） |
| P2-9 Pulse 8s | **fixed**（错峰 + persist false） |
| P2-11 Dashboard 本月% | **fixed** |
| P2-12 Bearer | **fixed**（≥32 + 轮换文档/告警） |
| P2-13 潜龙 preview | **fixed**（WriteAccess） |
| P2-16 贴线簇 | **partial**（拆 `peek_dock_geometry` / `backtest_run_phase` / SenderDock CSS；禁止再堆） |

**wontfix**：AI HITL / 限制 AI add。

---

## 2. R6 新发现与修复

| ID | 标题 | 状态 |
|---|---|---|
| R6-P1-1 | live 轮询绑 persist → 写鉴权 401 | **fixed**（Pulse/DataQuery `persist:false`） |
| R6-P1-2 | 手工下单无交易日闸 | **fixed**（`resolve_trading_day_gate`） |

### 残余 P2（可后续）

- 前视分片 CPU 成本（全覆盖换时间）
- review overlap/replay 仍 `.conn`
- rules 舱依赖配置就绪；贴线文件勿再堆

### R6 后续落地（同日）

| 项 | 状态 |
|---|---|
| Pulse「同步现价」→ `POST /market/board/spot` | **done** |
| PaperQuant 展示 `trading_day_gate` + 手工买入日历缺失 409 测 | **done** |
| review decay/drift/capacity Store 收拢 | **done**（overlap/replay 仍债） |
| 贴线拆分：`peek_dock_geometry` / `backtest_run_phase` / SenderDock CSS | **done** |
| 行情适配器/upsert 测假绿 | **done** |

---

## 3. 回归摘录

```
lint-imports: 11 kept
pytest ops + board_live_persist + audit_* + intel + write_token_policy → 422 passed
```

---

## 4. 给 Agent

再审从本文件 §2 残余起；禁止恢复报告链；禁止 AI 造复盘权威数字。
