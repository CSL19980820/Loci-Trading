# Loci / stock-analyzer · 项目结构（已采纳）

> 状态：**已采纳**（2026-07-28）  
> 形态：DDD **模块化单体**；删除旧 analyze/discover 报告链。

## 原则

1. 一个限界上下文 = `src/<context>/`，含 `domain` / `application` / `infrastructure` / `api` + `README.md`
2. 依赖方向：`api → application → domain`；infrastructure 实现端口
3. `market` 不写 `palace.db`；`ai` 不发明数字
4. 组合根仅在 `src/app/`；横切仅在 `src/shared/`
5. 前端按上下文落在 `frontend/src/features/<bc>/`，共享能力在 `shared/`

## 目录

见仓库根 [README.md](../../README.md) 与 [bounded-contexts.md](bounded-contexts.md)。

## 新增内容

- 新策略 → `src/strategy/application` + 注册 + `tests/strategy`
- 新行情源 → `src/market/infrastructure/adapters`
- 新复盘指标 → `src/review/application` + API
- 新前端页 → `features/<bc>/` + `shared/router`

## 原有内容

- 改账本：优先 `ledger/infrastructure/store.py`，行为保守 + 测试
- 改 HTTP：量化路由现聚合于 `src/app/legacy/quant_router.py`，按 URL 前缀归属到各上下文 api README；下沉时不改 URL
- 禁止恢复旧报告 CLI（analyze/fetcher/reporter）

## 相关

- [bounded-contexts.md](bounded-contexts.md)
- [ADR-001](../adr/ADR-001-server-ledger-and-sqlite.md)（已废止的公网部署决策）
