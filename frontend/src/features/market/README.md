# market

行情数据台与 Peek。

- `DataQueryView.vue`：壳（Tab、覆盖状态、交割/候选查询）
- `components/`：本机库条、行情列表、个股 K 线、交割表、候选表
- `composables/`：`useDataQueryMarket`（列表/详情/轮询）、`useQuotesQuery`（Pinia Colada 日线缓存试点）、`dataQueryFormat`
- K 线：详情默认 Lightweight Charts（`loci.market.useLwChart`，从未写过 localStorage 时为开；开关切回 ECharts）
