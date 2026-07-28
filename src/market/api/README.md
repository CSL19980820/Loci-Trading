归属 URL：`/api/market/*` `/api/universe/*`。

挂载：`src.market.api.router.build_market_router`，由 `src.app.legacy.quant_router.build_quant_router` 聚合 include。

`GET /api/capabilities` 仍留在聚合层（system tag）。
