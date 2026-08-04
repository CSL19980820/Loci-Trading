# review

本限界上下文的页面。

- `ReviewCenterView.vue`：绩效中心（侧栏「绩效」）；`PageTabs` 分区；各分区 Colada 按当前 tab `enabled`，不预拉其它分区
- `components/RoundTripsPanel.vue`：持仓归因；去掉 sheet 标题栏；顶栏归因统计轨；`持有`/`了结` 分段（默认持有）；各自时间倒序
- `ReviewsView.vue`：复盘样本列表（`/reviews/records`）；`ListToolbar` 新增；**侧栏暂不挂入口**（「手记」已撤），深链/胜率「去补复盘」仍可用；后续 AI 复盘可挂靠绩效 Tab 或独立入口
- `InsightsView.vue`：管家式数据体检（印鉴分盘 / 一键扫描 / 一键修复 / 进度尺 / 自动复检）+「信号重叠」Tab。逻辑在 `composables/useHealthCheckup.ts`；UI：`HealthSealDial` / `HealthScanProgress` / `HealthCheckList`。衰减在选股目录「近期胜率」；前视由测试与生成链拦。修复走 bootstrap 弹窗 + 换手回填 API + 页内/顶栏进度
- `composables/useHealthCheckup.ts`：体检状态机；分数与 `repair_plan` 以后端为准；门禁认 `blocked`
- `WinRateView.vue`：胜率；主表为精选候选 T+1/T+3/T+5（T+5 为主），无候选回退手工复盘；趋势区仍为复盘按月/周
- `ReviewCenterView.vue`：候选验证列含 T+1/3/5/10/20/60，并展示精选短线胜率卡片
