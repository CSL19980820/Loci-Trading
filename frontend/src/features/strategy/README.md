# strategy

选股 / 回测 / 战法对比页。

- `QuantView.vue`：壳（行情仓摘要、Tab 编排、选股/回测动作）
- `components/`：范围条、战法表、分析表、结果区、定时配置弹窗
- `composables/`：universe / analysis / config 状态与 `quantFormat` 纯展示助手；`useScreenHistoryQuery`（Pinia Colada 选股历史只读缓存）
- `ScreenHistoryView.vue`：选股历史走 Colada；今日选股仍命令式，成功后 refetch 历史
