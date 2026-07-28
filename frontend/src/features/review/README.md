# review

本限界上下文的页面。

- `ReviewCenterView.vue`：绩效中心；权益 / trips / 候选验证 / 预案兑现均走 Pinia Colada 只读缓存（`useEquityQuery`、`useRoundTripsQuery`、`useCandidateOutcomesQuery`、`usePlanOutcomesQuery`），刷新统一 refetch

