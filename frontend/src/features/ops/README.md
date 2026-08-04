# ops

运维页（侧栏「设置」）：模型与本机系统配置。

- 壳：`OpsView.vue` — **左脊索引**（`SettingsRail`）+ 右面板；`?tab=` 路由；按当前 tab 按需 `load`；窄屏折成单条 `PageTabs`
- 面板壳：`SettingsPanel.vue`（标题 / 主操作 / body / foot）；联内壳 `SettingsSection.vue`（左槽联名 + 印章状态；无选中粉底）
- Tab：`McpTab` · `LlmTab`（供应商**卡片名册** + 分区编辑 `LlmProviderDialog` + `LlmModelCatalogDrawer`）· **`SystemTab`**（四联纵向；统一左标签 + 同行多列；推送预览为电报纸条；页脚「保存全部」）
- `LlmModelCatalogDrawer`：宽 `min(64rem, 92vw)`；表体单行（开 / id·徽标 / 展示名 / 上下文·hint / 输出 / 操作）；默认行印泥浅底；表 min-width 960px 可横滚
- LLM：`LlmProviderCard`（端点条 / 模型芯片 / ⋯ 菜单）；添加与编辑共用宽屏左右分栏 dialog（左身份/接入 · 右目录摘要）；完整目录仍走右侧 drawer
- 本机启动自动准备 AI 主密钥（`.palace_ai_master_key`）；生产仍须显式 `PALACE_AI_MASTER_KEY`
- **定时任务 / 执行历史已迁工坊**：`JobsTab` + `JobEditorDialog` + `JobRunsDialog` 挂在 `/quant?tab=jobs`；执行历史是定时台「执行历史」按钮弹窗
- 推送联：Webhook + 选股 text 模板（默认/简洁/含日期/自定义，实时双预览）
- `JobsTab`：左条右详（`JobDetailPane`）；战法绑定 `screen:{slug}` 只读（可执行 / 去战法改）；本机任务可 CRUD
- `JobDetailPane`：元信息铺满 + `JobRecentRunsPanel`（BasicTable 分页，仅当前 `job_id`）；顶栏「全部历史」仍开 `JobRunsDialog`
- 下次触发：`GET /api/jobs/schedule` 在调度器未启动时仍按 cron 推算 `next_run_at`
- `JobRunsDialog`：任务列最左（min 200）· 时间 min 160 · 耗时 `formatRunDuration`（如 `11h2min3s`，≥1s 忽略 ms）；表体 nowrap
- 归属判定：`composables/jobOwnership.ts`（与后端 `get_job_by_name("screen:{slug}")` 一致）
- 系统草稿：`composables/useSystemSettings.ts`（分联 dirty / 串行 saveAll / 推荐配置只写草稿）
- 左栏尾注：`composables/useSettingsSummaries.ts`（状态印记 ok/idle/bad；`system` 优先显示同步时刻）
- 共享：`composables/useOpsFeedback.ts`（busy/guard）、`composables/opsLabels.ts`；模型选择器辅助在 `@/shared/lib/llm`
- 大段 JSON：`components/CodeEditor.vue`；`useJobsQuery` / `useJobRunsQuery`
- **旧深链**：`?tab=jobs|runs` → `/quant?tab=jobs`（runs 另带 `runs=1` 打开历史弹窗）；`?tab=data-dir|market-sync|notify|appearance` → `?tab=system` + `#sys-*`；`?tab=skills` → 工坊市场；`?tab=lanes|akshare` → 工坊数据源
- 有未保存系统改动时切分区 / 离开路由会确认
- `McpTab` 内置 `loci-market` 详情用 `tools_catalog`；生效调用仍走 `tools`（按 lane 过滤）
- MCP Server 仅支持直连服务；界面与前端请求不提供代理字段，旧客户端传入代理会由服务端明确拒绝
- MCP 工具弹窗：`McpToolsDialog`
