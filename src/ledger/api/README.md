# 账本 HTTP API

归属：`/api/dashboard` `/api/positions` `/api/trades` `/api/candidates`
`/api/plans` `/api/reviews` `/api/pools` `/api/analytics` `/api/scorecard`
`/api/snapshots` `/api/cashflows` `/api/daily-pnl` `/api/timeline/*`
`/api/import/qianlong/*` `/api/alerts/today`。

候选列表 `strategy` 查询参数为战法名模糊匹配（`LIKE %keyword%`；旧 slug 会顺带匹配归一后的中文名）。
`/api/candidates` 与 `/api/candidates/list` 默认排除回填源；`include_backfill=true` 可放开。

挂载：`src.ledger.api.router.build_ledger_router(write_dependency=..., get_store=...)`，
由组合根 `src.app.main.create_app` `include_router`。

请求模型：`src.ledger.api.schemas`（写入 `extra=forbid`）。

鉴权 / Session / health / SPA 仍在组合根；本目录不持有写令牌逻辑。
