归属：`/api/strategies*` `/api/backtest` `/api/analysis/*` `/api/screen/*` `/api/insights/*`。

挂载：
- `src.strategy.api.router.build_strategy_router`
- `src.strategy.api.convert.build_strategy_convert_router`（转换器 / 自定义策略）

由 `src.app.legacy.quant_router.build_quant_router` 聚合 include。
