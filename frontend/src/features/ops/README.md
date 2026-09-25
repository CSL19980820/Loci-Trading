# ops

运维页（侧栏「设置」）：模型与本机系统配置。

展示约定：导航、读数、表单和正文使用现有 surface / rule / seal、字号与间距令牌；默认模型与选中项使用主题色，涨跌使用 up / down。设置区保持 `page-fill`，列表、报告及咨询消息在内部滚动；窄屏导航改用 PageTabs。任务编辑、执行记录、错误全文、LLM 与 MCP 弹层通过 `OpsDialogSurface.css` 的 `style scoped src` 复用视口高度和页脚布局，禁止改为全局导入。键盘焦点、开关名称和实时保存状态必须保留。

- 壳：`OpsView.vue` — **左脊索引**（`SettingsRail`）+ 右面板；`?tab=` 路由；按当前 tab 按需 `load`；窄屏折成单条 `PageTabs`
- 面板壳：`SettingsPanel.vue`（标题 + 回执读数 + 主操作；可用宽度不足时换行，回执可省略；≤900px rail 隐藏，且 `/quant` 的 `JobsTab` 复用同一个壳；`fill` 让 body 吃满剩余高度，MCP / LLM / 定时任务名册用，表单页不要传）；联内壳 `SettingsSection.vue`（左槽联名 + 可读保存状态，窄屏收窄左槽）
- Tab：`McpTab` · `LlmTab`（供应商**卡片名册** + 分区编辑 `LlmProviderDialog` + `LlmModelCatalogDrawer`）· **`SystemTab`**（四联纵向；标题回执含版本号；页脚「保存全部」）· **`PackTab`**（一键打包 → 加密 zip）
- `PackTab` **默认出脱敏包**：运维库与 MCP 只带骨架，API Key / Webhook / 纸面交易记录都不进包。勾了「账本」或「包含我的密钥与个人记录」会变红条警告并高亮该行；打包完成的提示会说明是脱敏包还是含个人数据（读响应头 `X-Loci-Sanitized`）
- `LlmModelCatalogDrawer`：宽 `min(64rem, 92vw)`；表体单行（开 / id·徽标 / 展示名 / 上下文·hint / 输出 / 操作）；默认行印泥浅底；表 min-width 960px 可横滚
- LLM：`LlmProviderCard`（端点条 / 模型芯片 / ⋯ 菜单）；添加与编辑共用宽屏左右分栏 dialog（左身份/接入 · 右目录摘要）；完整目录仍走右侧 drawer
- 本机 LLM / MCP Key 明文落库（ops.db / mcp.json）；旧密文启动时尽量自动迁明文
- **定时任务 / 执行历史已迁工坊**：`JobsTab` + `JobEditorDialog` + `JobRunsDialog` 挂在 `/quant?tab=jobs`；执行历史是定时台「执行历史」按钮弹窗
- 推送联：Webhook + 选股 text 模板（默认/简洁/含日期/自定义，实时双预览）+「低吸观察」开关（`show_watch_picks`，默认关：推送不显示观察票、双预览同步隐藏；开后预览恢复观察分区）。模板契约保留正式空态与低吸观察分区文案，正文不会把观察票混入正式精选；观察票仍写入候选库并在前端分区展示。
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
- 左栏尾注：`composables/useSettingsSummaries.ts`（状态印记 ok/idle/bad；`system` 显示 `v*` 版本；`pack` 显示可封箱/未编译）；`mcp` / `llm` 主标是「工具连接」「AI 模型」，缩写由 `OpsView` 拼在尾注前（`MCP · 2 台`）。**尾注刷新不进 `guard`**：它要打 7 个接口，页级遮罩只盖当前分区自己的 `load()`——曾因 `/ops/data-location` 冷读 30 s 让已渲染的 LLM 卡片蒙着「加载设置…」半分钟
- 共享：`composables/useOpsFeedback.ts`（busy/guard）、`composables/opsLabels.ts`；模型选择器辅助在 `@/shared/lib/llm`
- 大段 JSON：`components/CodeEditor.vue`；`useJobsQuery` / `useJobRunsQuery`
  - Monaco **只装配 `json` / `python` / `plaintext` 三种语言**（`editor.api.js` + `features/register.all.js` + 两个语言 register，不走 `editor.main` barrel）。传别的 `language` 不会报错，但按 plaintext 渲染；要新语言就在 `CodeEditor.vue` 的 `loadMonaco()` 里加一行 `languages/definitions/<id>/register.js`
  - 编辑器功能（折叠 / 查找 / 右键菜单 / 撤销 / 多光标）由 `features/register.all.js` 全量提供；相对 `editor.main` 少了 `caretOperations` / `copyPasteContribution` / `markerSelectionStatus` / `documentSemanticTokens` 四项（monaco 未发它们的 `.d.ts`）——当前两种语言下是空操作，**接入 LSP / diagnostics 时需重新评估**
  - **CSS 全靠 contrib 自带**：ESM 侧每个 contrib 模块自带样式，随上面几个 import 进异步分片（`editor-*.css` / `format-*.css` / `wordPartOperations-*.css`，合计 162 KB raw / 25.9 KB gz）。**不要再引 `monaco-editor/min/vs/editor/editor.main.css`**——那是 AMD 版全量样式（349 KB raw / 117 KB gz），2026-09 实测是 100% 重复：把它的 1242 条顶层规则块拆成 1510 条「单选择器」逐条比对 contrib 分片，**独有选择器 0 条、独有声明 0 条**（余下差异全是 minifier 归一化，如 `transparent`↔`#0000`、属性重排、`var()` 回退值里的空格、`flex:0 1 auto`↔`flex:0 auto`）；codicon 字体只是从内联 base64 换成外链 `codicon-*.ttf`（本就已产出，删掉反而少一份重复）。删除后真机验证过背景/行号/等宽字体/光标/选区/括号匹配/查找面板与 `.mtk*` 六色分层均正常
- **旧深链**：`?tab=jobs|runs` → `/quant?tab=jobs`（runs 另带 `runs=1` 打开历史弹窗）；`?tab=data-dir|market-sync|notify|appearance` → `?tab=system` + `#sys-*`；`?tab=skills` → 工坊市场；`?tab=lanes|akshare` → 工坊数据源
- 有未保存系统改动时切分区 / 离开路由会确认
- `McpTab` 内置 `loci-market` 详情用 `tools_catalog`；生效调用仍走 `tools`（按 lane 过滤）
- MCP Server 仅支持直连服务；界面与前端请求不提供代理字段，旧客户端传入代理会由服务端明确拒绝
- MCP 工具弹窗：`McpToolsDialog`（两组标题压成一行：标题 + 计数 chip；线路/AkShare 口径与「测连通只验握手」都进 tooltip）

- 文案纪律：ops 下不留常驻介绍段（规则进 `el-tooltip` / placeholder），`el-alert` 只报真实异常、标题 ≤20 字且禁 `description`；读数（下次触发 / 今日剩余额度 / 告警证据行）留在页面上，必要时用 `HeaderStat`
- `McpTab`「添加外部 MCP」按钮在「外部 MCP」那一行（标题 + 计数 chip + 按钮同排），面板头只留「配置悟道」
- slug 不上展示位：`JobRunsDialog` 任务列与 `JobRunErrorDialog` 把 `screen:{slug}` / `skill:{slug}` 过一遍 `cnStrategyName`；`PaperQuantPanel`「战法标识」输入框旁挂中文名 chip
## 智能守护

`/ops?tab=guardian`：`GuardianTab.vue` 展示观察/持有/仓位概览、可筛选股票池、持有计划和模型研判。
`GuardianSettingsDrawer.vue` 独立承载模型、提示词及通知草稿；主面板可以直接启停并提交研判。
持有与买卖分开表达，持有不产生模拟成交。后台刷新可取消且不覆盖编辑中的配置；窄屏优先展示模型结论。
沿用客户模型目录与推送通道。样式由 `GuardianTab.css` scoped src 加载。
测试：`GuardianTab.test.ts`；业务边界见 `docs/guardian.md`。

### 守护现金账户

`GuardianAccountPanel` 展示20万元账户的资产、现金、逐股持仓/可卖股数、含费成本与盈亏，以及分页成交流水和个股累计盈亏。策略池仅参考，交易范围不受其限制。T+1与佣金万2.5免5由后端执行，前端只展示已记账数字及行情时间。

天才交易员支持止盈/止损动作、持股计划与持久自主观察池；策略外观察不产生交易，现金与 T+1 规则不变。详见 docs/guardian.md。

交易员持仓默认3只、符合当日可卖退出计划的换仓例外最多4只；成功和异常通知均优先展示完整含费持仓成本。新增测试 tests/ledger/test_guardian_position_limit.py。

GuardianReviewPanel展示盘前/日/周复盘的完整正文、状态和回执，支持历史选择与后台补跑；不重复拉取状态未变的报告，不把生成失败显示为已完成。

天才交易员按账户与持仓、复盘与计划、观察与研判分区。GuardianReportDocument渲染服务端语义分区，同股票的回顾与全部行动计划集中呈现，运行口径默认折叠。

天才交易员新增“与交易员沟通”，保存话题和实际持仓背景，异步轮询回答并支持连续追问；请求失败重试保持request_id。咨询不执行交易。日内无成交显示无动作，边界预案显示仅研判。

咨询话题及请求编号通过 `shared/lib/uuid.ts` 生成：优先使用原生 `randomUUID`，HTTP 环境回退到 `getRandomValues` 生成 UUID v4。首次进入、新话题、历史加载失败后的提问及网络失败重试均覆盖 HTTP 兼容回归测试。
