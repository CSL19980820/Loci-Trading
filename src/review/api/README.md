归属：`/api/review/*` `/api/winrate/*`。

挂载：`src.review.api.router.build_review_router`，由 `src.app.legacy.quant_router.build_quant_router` 聚合 include。

`/api/winrate/summary`：精选候选 T+N（主 T+5）优先，手工复盘兜底；每行带全档 `horizons`、`best_horizon`、`best_sample` / `worst_sample`。
`/api/winrate/trend`：同口径按选出日分月/周；无候选样本才回退 `reviews`（行内 `source` 标明）。
`/api/winrate/samples?tag=&horizon=&limit=`：某战法逐条样本，`settled` 即胜率分母、`observing` 不进分母；`horizon` 只认 `HORIZONS`（1/3/5/10/20/60），其余 422。
洞察衰减/重叠见 strategy api（`/api/insights/*`）；衰减优先候选 T+5。

`GET /api/review/candidates`：可选 `window_days`（近 N 交易日选出）、`selected_only`、`as_of`；盘面「近选跟踪」用 `window_days=5&selected_only=true`。

结果缓存：进程内 LRU，键 = 端点 + 参数 + `palace.review_read_fingerprint()` + `market.market_revision()`；
挂在 candidates / plans / winrate_summary / winrate_trend / winrate_samples 上，外加内部 scope `candidate_outcomes`——winrate 三兄弟从它派生，一条请求链只重算一次。

2026-08 实盘项下线：`/api/review/equity|trips|positions|drift` 已删除——它们读真实成交 / 持仓，
而复盘已改为只基于「候选池 + 行情」算纸上收益。缓存层保留，只是把这几个 scope 摘掉了。
