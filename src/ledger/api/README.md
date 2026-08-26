# 账本 HTTP API

归属：`/api/candidates` `/api/candidates/list` `/api/candidates/export.csv`
`/api/plans` `/api/reviews` `/api/pools` `/api/pools/day` `/api/timeline/*`
`/api/alerts/today`。

**2026-08 持仓下线**：`/api/dashboard` `/api/positions` `/api/trades`（GET/POST）
`/api/trades/export.csv` `/api/import/qianlong/*` `/api/analytics` `/api/scorecard`
`/api/snapshots` `/api/cashflows` `/api/daily-pnl`（GET/POST）**已删除**，
对应的请求模型 `TradeInput` / `SnapshotInput` / `CashflowInput` / `DailyPnlInput` 一并删除。
`/api/timeline/{code}` 保留，但只返回候选裁决 + 预案（+ 关联复盘），没有成交段。

`GET /api/alerts/today`：活跃预案触价提醒；行情侧只读热库 `market_hot.db`（`open_market_hot`），热库不可用时降级为无报价。

候选列表 `strategy` 查询参数为战法名模糊匹配（`LIKE %keyword%`；旧 slug 会顺带匹配归一后的中文名）。
`/api/candidates` 与 `/api/candidates/list` 默认排除回填源；`include_backfill=true` 可放开。

挂载：`src.ledger.api.router.build_ledger_router(write_dependency=..., get_store=...)`，
由组合根 `src.app.main.create_app` `include_router`。路由工厂本身保留，未随端点下线移除。

请求模型：`src.ledger.api.schemas`（写入 `extra=forbid`）。

鉴权 / Session / health / SPA 仍在组合根；本目录不持有写令牌逻辑。
