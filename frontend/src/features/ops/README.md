# ops

运维页（侧栏「设置」）：模型与本机系统配置。

- 壳：`OpsView.vue` — **左脊索引**（`SettingsRail`）+ 右面板；`?tab=` 路由；按当前 tab 按需 `load`；窄屏折成单条 `PageTabs`
- 面板壳：`SettingsPanel.vue`（**头恒为一行**：标题 + 回执读数 + 主操作，回执超宽省略；标题保留是因为 ≤900px rail 隐藏、且 `/quant` 的 `JobsTab` 复用同一个壳）；联内壳 `SettingsSection.vue`（左槽联名 + 印章状态，窄屏只收窄左槽不塌成单列；无选中粉底）
- **`SignalRulesTab`**（rail「模型与工具」分区，`?tab=signals`）：大屏实时信号的规则维护。**一条两行**：第一行只放控件（`el-switch` + 中文名 + `code` + 可调参数 `el-input-number` + 文字按钮「恢复默认」），第二行整宽给口径说明（单行截断 + `el-tooltip` 全文，ui-spec §8）。参数轨吃弹性并**右对齐收口**，所以 1~3 个参数的行右缘一致——旧版把弹性留给口径之外的空隙，参数块会随参数个数左右横跳，六行右缘全是锯齿；壳也别再传 `fill`（那会把 body padding 置 0，内容贴边）。**改完即时 PUT**，失败整条回滚并 `ElMessage.error` 报后端原话。参数口径优先用后端 `param_specs`（键 / 中文名 / 上下限 / 单位 / 整数），缺席才退到 `composables/signalRuleMeta.ts` 的静态表。接口：`GET /api/market/signals/rules`、`PUT /api/market/signals/rules/{rule_id}`（早期契约 `/market/signal-rules` 作 404 回退）。rail 尾注「N/M 启用」由面板 `@summary` 回传，不进 `useSettingsSummaries` 的全局批量拉取
- Tab：`McpTab` · `LlmTab`（供应商**卡片名册** + 分区编辑 `LlmProviderDialog` + `LlmModelCatalogDrawer`）· **`SystemTab`**（四联纵向；标题回执含版本号；页脚「保存全部」）· **`PackTab`**（一键打包 → 加密 zip）
- `PackTab` **默认出脱敏包**：运维库与 MCP 只带骨架，API Key / Webhook / 纸面交易记录都不进包。勾了「账本」或「包含我的密钥与个人记录」会变红条警告并高亮该行；打包完成的提示会说明是脱敏包还是含个人数据（读响应头 `X-Loci-Sanitized`）
- `LlmModelCatalogDrawer`：宽 `min(64rem, 92vw)`；表体单行（开 / id·徽标 / 展示名 / 上下文·hint / 输出 / 操作）；默认行印泥浅底；表 min-width 960px 可横滚
- LLM：`LlmProviderCard`（端点条 / 模型芯片 / ⋯ 菜单）；添加与编辑共用宽屏左右分栏 dialog（左身份/接入 · 右目录摘要）；完整目录仍走右侧 drawer
- 本机 LLM / MCP Key 明文落库（ops.db / mcp.json）；旧密文启动时尽量自动迁明文
- **定时任务 / 执行历史已迁工坊**：`JobsTab` + `JobEditorDialog` + `JobRunsDialog` 挂在 `/quant?tab=jobs`；执行历史是定时台「执行历史」按钮弹窗
- 推送联：Webhook + 选股 text 模板（默认/简洁/含日期/自定义，实时双预览）；模板契约保留正式空态与低吸观察分区文案，后端推送不会把观察票混入正式精选。
- 纸面量化工作台在工坊 `/quant?tab=paper`（`PaperQuantPanel`）；通知策略安静时段/Bark 同面板可改。
  龙回头纸面舱已退役，面板默认 `demo`，不要再填 `dragon-return`。
  最近盯盘快照若含 `trading_day_gate`，面板会提示非交易日 / **交易日历缺失买入 fail-closed**（与 `POST .../orders` 409 对齐）。
  刷新舱时并行拉 `GET /api/skills/{slug}/leader-roles`，`PaperRoleReviewPanel` 展示**角色演进图**（ECharts 阶梯线，纵轴角色档位）、存活榜/角色转移/持仓告警；风格记忆里 `role_alert` 教训单独高亮。
- `JobsTab`：左条右详（`JobDetailPane`）；战法绑定 `screen:{slug}` 只读（可执行 / 去战法改）；本机任务可 CRUD；托管任务含 `kind=hot_rebuild`（行情热库重建，近 700 交易日窗口）；亦可建 `alert_scan` / `strategy_monitor` / `paper_eod`

- `JobDetailPane`：元信息铺满 + `JobRecentRunsPanel`（仅当前 `job_id`，`BasicTable` 常规表 + 工具栏标题/刷新；条数少不虚拟化）；顶栏「全部历史」仍开 `JobRunsDialog`
- 下次触发：`GET /api/jobs/schedule` 在调度器未启动时仍按 cron 推算 `next_run_at`
- `JobRunsDialog`：任务列最左（min 200）· 时间 min 160 · 耗时 `formatRunDuration`（如 `11h2min3s`，≥1s 忽略 ms）；`BasicTable` `virtualized` 保留固定任务列/选择列，表体 nowrap
- 归属判定：`composables/jobOwnership.ts`（与后端 `get_job_by_name("screen:{slug}")` 一致）
- 系统草稿：`composables/useSystemSettings.ts`（分联 dirty / 串行 saveAll / 推荐配置只写草稿）
- 左栏尾注：`composables/useSettingsSummaries.ts`（状态印记 ok/idle/bad；`system` 显示 `v*` 版本；`pack` 显示可封箱/未编译）；`mcp` / `llm` 主标是「工具连接」「AI 模型」，缩写由 `OpsView` 拼在尾注前（`MCP · 2 台`）
- 共享：`composables/useOpsFeedback.ts`（busy/guard）、`composables/opsLabels.ts`；模型选择器辅助在 `@/shared/lib/llm`
- 大段 JSON：`components/CodeEditor.vue`；`useJobsQuery` / `useJobRunsQuery`
- **旧深链**：`?tab=jobs|runs` → `/quant?tab=jobs`（runs 另带 `runs=1` 打开历史弹窗）；`?tab=data-dir|market-sync|notify|appearance` → `?tab=system` + `#sys-*`；`?tab=skills` → 工坊市场；`?tab=lanes|akshare` → 工坊数据源
- 有未保存系统改动时切分区 / 离开路由会确认
- `McpTab` 内置 `loci-market` 详情用 `tools_catalog`；生效调用仍走 `tools`（按 lane 过滤）
- MCP Server 仅支持直连服务；界面与前端请求不提供代理字段，旧客户端传入代理会由服务端明确拒绝
- MCP 工具弹窗：`McpToolsDialog`（两组标题压成一行：标题 + 计数 chip；线路/AkShare 口径与「测连通只验握手」都进 tooltip）

- 文案纪律：ops 下不留常驻介绍段（规则进 `el-tooltip` / placeholder），`el-alert` 只报真实异常、标题 ≤20 字且禁 `description`；读数（下次触发 / 今日剩余额度 / 告警证据行）留在页面上，必要时用 `HeaderStat`
- `McpTab`「添加外部 MCP」按钮在「外部 MCP」那一行（标题 + 计数 chip + 按钮同排），面板头只留「配置悟道」
- slug 不上展示位：`JobRunsDialog` 任务列与 `JobRunErrorDialog` 把 `screen:{slug}` / `skill:{slug}` 过一遍 `cnStrategyName`；`PaperQuantPanel`「战法标识」输入框旁挂中文名 chip