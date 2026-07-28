# 账本 HTTP API

归属：`/api/dashboard` `/api/positions` `/api/trades` `/api/candidates`
`/api/plans` `/api/reviews` `/api/pools` `/api/analytics` `/api/scorecard`
`/api/snapshots` `/api/cashflows` `/api/daily-pnl` `/api/timeline/*`
`/api/import/qianlong/*` `/api/alerts/today`。

挂载：`src.ledger.api.router.build_ledger_router(write_dependency=..., get_store=...)`，
由组合根 `src.app.main.create_app` `include_router`。

请求模型：`src.ledger.api.schemas`（写入 `extra=forbid`）。

鉴权 / Session / health / SPA 仍在组合根；本目录不持有写令牌逻辑。
