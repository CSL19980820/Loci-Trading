归属：`/api/review/*` `/api/winrate/*`。

挂载：`src.review.api.router.build_review_router`，由 `src.app.legacy.quant_router.build_quant_router` 聚合 include。

`/api/winrate/summary`：精选候选 T+N（主 T+5）优先，手工复盘兜底。
洞察衰减/重叠见 strategy api（`/api/insights/*`）；衰减优先候选 T+5。

`GET /api/review/candidates`：可选 `window_days`（近 N 交易日选出）、`selected_only`、`as_of`；盘面「近选跟踪」用 `window_days=5&selected_only=true`。
