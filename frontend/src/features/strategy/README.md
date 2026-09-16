# strategy

带 `backtest_config.signal_dataset` 的战法选择后默认成交模式，并带入完整日期、持期、止损止盈和实验成本。请求显式传递时点数据ID、严格价格限制、经济收益与估值末日；估值末日跟随用户当前end。此模板切Horizon会明确拒绝，不能悄悄改成收盘回测；含买入日的持期说明同时显示。其他战法没有模板字段时保持旧行为。

选股台 + 工坊工具匣 + 策稿。

## 界面与回归

- 回测参数按面板实际宽度排布，工坊与策稿底部结果面板共用 `QuantBacktestPanel`。结果卡片、极端样本和成本表单在窄屏纵向展开，滚动保留在内容区。
- 回测进度不覆盖操作栏。「停止等待」只取消本页请求和结果回写，服务端已提交计算可能继续执行；不显示虚假的百分比，也不改变回测成本、成交口径或策略模板。
- 策稿结果面板可通过右上角关闭按钮收起；回测分区获得较大的展示区域，短窗口仍保留编辑器状态栏。参数区的 `Sheet`、诊断区的 `EmptyState` 需显式导入，避免空壳标签。
- 在 `frontend` 执行 `node e2e/ui-finish.mjs` 可复核回测空态、运行中停止、两类结果、成本表单、策稿助手和结果面板。可用 `UI_AUDIT_WIDTHS`、`UI_AUDIT_HEIGHT`、`UI_AUDIT_THEMES` 选择尺寸及外观；使用模拟数据，不触发真实交易。

## 页面与功能

- `ScreenHistoryView.vue`（路由 `/screen-history` · 选股台）：**选条 / 跑道 / 弹窗账页**
  - 顶栏：交易日**区间**（`TradeDateRangeField`：daterange + 今日/本周/上周/近一月/上一月快捷泡，跨度 ≤31 自然日）· 入库候选 ·（Skill 时 LLM）· **详情** · **入库历史** · 刷新 · 主按钮「选股 / 区间选股 / 跑技能」
  - 选中战法、区间、`kind` 写入 URL query（`select`/`from`/`to`/`kind`），点开行情批再返回可还原
  - 选条：`ScreenCatalogRail` — 战法 + 技能同目录；样本不足不刷文案（右侧 `—`），样本够才出胜率·均收益；搜索「搜名称」
  - 跑道：`ScreenRunPanel` — 待命/状态行折叠日志（默认展开，跑完自动收起；贴底滚动）；今日/区间末日结果把正式精选与“低吸观察（不计正式胜率）”分区，**零条也留 `BasicTable` 列头**，空文案走表内 `EmptyState`
  - 入库历史：顶栏按钮打开宽弹窗；默认 `live_only` 仅盘后真选，开关「含回填」可审计；`ScreenHistoryPanel` 按“正式 / 观察”分别计数，详情显示每票裁决（日期区间筛选 · BasicTable 分页 · 详情/重跑）
    - 详情：顶栏打开既有 `StrategyDetailDialog` / `SkillDetailDialog`（与工坊战法/技能页一致）
- **选股后台（战法级多槽，可并行）**：`useScreenRunStore` 一条全局轮询拿聚合快照（`GET /api/screen/run` 返回 `runs: {slug: 槽}`），状态是**字典** `runs[slug]`——潜龙 / 三源 / 杨氏可以同时在跑，各有独立进度、日志、结果。按战法查询走 `runFor` / `isRunning` / `percentFor` / `resultFor` / `detailFor` / `elapsedTextFor`；`canStart(slug)` 只在**这个战法自己在跑**或撞到并发上限（`atCapacity`，后端 `max_concurrent_runs` 默认 3）时为假。顶栏 `ScreenRunChip` 摊开最早那条 + `+N`，并行时不给「停止」（指谁全靠猜，工作台里逐条停）；区间跑按交易日循环通用 `screen` + 同日同池入库，进度日志逐日输出
- **停止选股（协作式取消，不是掐断，且按战法点名）**：后端 `POST /api/screen/run/cancel?strategy=` 只立一面旗，选股线程在**下一个交易日**的检查点退出——当前这一日会先跑完并照常入库，**已入库的候选不回滚**。`screenRun.abandon(slug)` 先打端点、再把这一个战法从本地进度里摘掉并加入静音集（轮询回来不复活），**别的战法照旧跑、轮询不停**；受理成功文案写「已请求停止 · 当前交易日跑完后结束」，端点够不着（老后端/断网）时降级成纯前端放弃并写「仍会在后台跑完」。**任何情况都禁止写「已取消」**——检查点没到之前那是谎话。残影按战法记在 `abandonedRuns[slug]`（战法 + 停止时百分比 + `stopping` 标记后端是否受理），`dismissAbandoned(slug)` 收掉
- **谁在跑（可以有多个）**：`runs[slug]` 是每个战法自己的槽，`detailFor(slug)`（战法 · 已跑时长 · 百分比 · 当前阶段）+ `elapsedTextFor(slug)`；后端槽带 `started_at` 时耗时是权威的「已跑」，老后端缺这个字段才降级成「已跟踪」（前端观测点为下限）。`ScreenRunBanners.vue` 只出三种横幅：**并发到顶**（说清先停谁）、**其它战法并行跑着**（看进度 / 停止入口）、**本战法放弃后的残影**——历史上那句「引擎是后端全局单槽：它跑完之前，所有战法的选股都开不了」已随多槽改造删除，现在是假话。`useWorkbenchAbandon.ts` 管确认弹窗（标题带战法名）与分派（战法/技能共用）
- **技能不同**：`useWorkbenchSkillRun` 的 `abandon()` 仍**只是前端放弃**——`/api/skill-runs/{id}` 只有查询/事件/回复，没有中止端点，那条线程会跑到自己结束。所以技能的确认框文案与选股**不能共用**（见 `useWorkbenchAbandon.ts` 的两条常量）
- `composables/tradeDateRange.ts`：快捷区间与跨度校验（前后端对齐）
- `composables/useScreenCatalog.ts`：合并 strategies + skills + 复盘/候选胜率 + `/insights/decay`；保留 `selectedStrategy` / `selectedSkill` 供详情弹窗
- `composables/useWorkbenchSkillRun.ts`：Skill 后台事件流 / HITL；日志经 `skillRunLog.ts` 全中文细粒度渲染（阶段/轮次/子任务启停/工具启停），跑道日志贴底自动滚动
- `composables/useScreenHistoryQuery.ts`：入库历史 Colada 缓存
- `QuantView.vue`（路由 `/quant` · 工坊）：**维护选股可用工具 + 本机货架 + 定时 + 研究证据台**
  - Tab：**战法** · **技能** · **数据源** · **定时** · **市场** · **回测** · **研究** · **纸面量化**（`PaperQuantPanel`：舱配置 / 立即盯盘 / 日终 / 价格提醒 / 通知策略；`?tab=paper`）
  - **Tab 懒挂（首屏只挂当前 Tab）**：七块非默认面板都是 `defineAsyncComponent`，进过哪个 Tab 才下那个分片；`mountedTabs` 记「进过没」，进过的仍 `v-show` 常挂保状态（滚动位置 / 填一半的表单 / 回测结果）。研究台与技能台照旧 `v-if`——它们带轮询，离开必须整块卸掉。回归测试 `__tests__/quantViewLazyTabs.test.ts`
  - 定时 Tab 首次进入由 `JobsTab` 自己的 `onMounted` 拉数，父级只在**回访**时补一次 `load()`（别打两枪）
  - 研究台默认只读本地证据，显示 21 维状态、实际来源回执、缺口和质量门禁；用户可显式归档输入快照；`?code=` 可预填标的；不生成生产信号
  - 纸面舱与真实 `palace` 隔离；跟随仅企微，见 [ADR-008](../../../../docs/adr/ADR-008-paper-quant-cabin.md)
  - **次日情景预案**：每票高开/平开/低开是否买、买点区间、层数；09:15–09:30 竞价/开盘前只纠偏（follow/revise/abandon/wait），≥09:30 过门闩才允许纸面开仓——不是选股池随便市价开
  - **战法风格记忆**：长期评头论足写入教训并吸入「该怎么买/该看哪些」；与全局助手记忆隔离；另有 **记忆知识图**（类 codegraph explore：节点/边/子图查询）落在 ops.db
  - **日终复盘**：强制回看近五个交易日，对照买过/没买/没卖的完整日 K，并看池内量能与板块环境（资金流可选）；另追加「角色演进」段（龙头存活、角色转移、走弱预警提前量），持仓里已判走弱/破位的票会落成 `role_alert` 教训
  - 选股结果 / 入库历史 / 跑道正式与观察候选：`StockLink` 带选股日 `date`，进行情默认落在该日 K
  - 数据源角标只数源家数（面板 `count-changed`，故**首次进入该 Tab 后**才出现——角标是面板算出来的，不值得为它把整块面板预挂在首屏），不数线路条数、不数 AkShare 接口数；`?view=` 透传给面板做深链（运维旧 `?tab=akshare` 就落在 `view=interfaces`）
  - 定时角标=启用任务数；运维旧 `?tab=jobs` 深链落到本 Tab；`?tab=runs` / `?runs=1` 打开执行历史弹窗
  - 定时台顶栏「执行历史」→ `JobRunsDialog`（任务名最左 min200、时间 min160、耗时如 `11h2min3s`）
  - 战法区：统一目录；来源/修订中文（内置·公式）；名称不展示 slug；产品内置为潜龙出海 / 三源尾盘共振（15:30 定时）/ 杨氏尾盘选股（15:30 定时）；14:50 两档已整体删除，不再出现在目录；RSI 抄底、潜龙尾盘、海底捞月、三外有三与其他旧版只保留在归档回测，不进入活动目录；`formula` 可跳工坊编辑，`builtin` 行点击打开详情弹窗。**零条战法也留 `BasicTable` 列头**，空文案走表内 `EmptyState`，不再整表换成白板
  - 详情/配置弹窗 `StrategyDetailDialog`（行「配置」或点行）：壳层编排 hydrate/save/版本回滚；**基础信息** Tab → `StrategyDetailBasicsPane`；**配置** Tab → `StrategyDetailConfigPane`（行情范围、定时选股、**推送企微**）；纯展示/格式化在 `strategyDetailFormat.ts`；底栏保存 → `PUT /api/strategies/{slug}/job`；**关定时（off）自动剔除绑定**
    - `StrategyDetailBasicsPane` 是**两块 `el-descriptions`**：短读数走 `:column="2"`，长文本（回测口径 / 买入说明 / 说明 / 所需字段）单独一块 `:column="1"` 吃整宽。
      合成一块时 9 个短项会把最后一行占掉一格，紧跟的 `:span="2"` 被 EP 裁成 1 格，几百字的回测参数就挤在 296px 窄栏里。
      两块都套 `table-layout: fixed`（列宽由 CSS 定，不让 `max-content` 抢）且内容用 `overflow-wrap: break-word` 而非 `word-break: break-word`（后者会把 min-content 压到一个字，「内置」被排成竖列）。
  - 定时台对 `screen:{slug}` 战法绑定只读（改配置走战法详情 / 「去战法改」带 `?strategy=`）；本机任务可 CRUD，战法/技能/供应商下拉选择
  - 主动作「选股」深链 `/screen-history?select=engine:|skill:`；操作列仅「选股」与「编辑(可编辑时)」；技能维持独立入口，不再混入公式工坊
  - 工具栏「从克隆包导入」→ `components/ScreenSkillBundleImportDialog.vue`：收克隆包 JSON，用纯函数 `shared/lib/cloneBundle.ts::planBundleImport()` 换算成 `ScreenSkillUpsertPayload`，预览 slug / 运行时 / 重建出来的 manifest / warnings 后 `POST /api/screen-skills`。克隆包里**没有** `ScreenSkillManifest`，min_bars / 输出信号 / runtime 都是推断的，逐条进 warnings。调用方若已拿到 `bundle` 对象，可直接传 `bundle` prop（不走粘贴）。`CloneBundle` 类型就住在 `shared/lib/cloneBundle.ts`——策略广场整体下线后，这条导入链路是它唯一的消费者
  - 技能区与战法区同构：`QuantSkillsPanel` 行点击打开 `SkillDetailDialog`；工具栏「上传技能」支持 zip 或文件夹（文件夹本机打成 zip 再 `POST /api/skills`）。**零条技能也留列头与工具栏**，空文案走表内 `EmptyState`
  - 详情弹窗 `SkillDetailDialog`：默认**配置** Tab（定时 + 推送企微 + LLM）/ 基础信息 / 说明书 / 工具；说明书按需拉 `instructions`，行内 Markdown 由 `ManualInline` 渲染；定时落库 `PUT /api/skills/{slug}/job`
  - **专属战法**（frontmatter 有 `strategy_skill` / `signal_engine` / `signals`）走 `SkillStrategyConfigPanel`：一屏配两档——盘后 AI 选股（`skill:{slug}`）与盘中确定性信号监测（`监测·{slug}`），落库 `PUT /api/skills/{slug}/strategy-config`。只有启用盘后 AI 或盘中 AI 解读才要求 LLM；关闭即删对应任务
  - **监测调参** `SkillWatchTuningPanel`：`GET|PUT|DELETE /api/skills/{slug}/watch-tuning`。三套命名预设（偏进攻 / 中性 / 偏防守）一键套用（确认对话框），套用后可继续手工微调保存；四个流水线开关 + 四段阈值；关掉的段会顶部告警。PUT 传 `{ preset: 'defensive' }` 整档套用（段开关保留）
  - **监测预览** `SkillWatchPreviewPanel`：`POST .../watch-preview` 试跑 + `GET .../leader-roles` 累计留痕；展示闸门、龙头地图、竞价、角色变化、存活榜与 **调参建议**（`suggestions`，`el-alert` 标明仅建议不改参）；只读不落库
  - 档位时间输入复用 `SkillScheduleFields.vue`（定点/间隔 + 下次运行预览），时间模型与转换在 `skillSchedule.ts`。**SKILL.md 不带 cron**，默认值由后端给（盘后 15:40、盘中每 10 分钟）；用户改动后预览回落本地估算，保存后再取后端按交易日历算的结果
  - `composables/skillManual.ts`：块级分块 + 行内解析；不用 `v-html`
  - 市场子区：`?shelf=` 浏览/已装/发布；装包变更会刷新战法/技能列表
- `StrategyConverterView.vue`（路由 `/strategy-converter` · 策稿台）：通达信式**整页公式纸**。顶栏：名称 / 函数 / 试跑 / 选股 / 回测 / 导入 / 保存 / 助手；无常驻左栏、无顶栏脚本/标识/方言选择。
  - 函数：`ScreenCatalogDialog` + `ScreenWorkbenchCatalog`（三栏词典弹窗，默认可收）
  - 分区条右侧：行数 / 字段 / 参数统计；编辑区 `ScreenWorkbenchEditor` 仅正文 + 试跑状态纸尾
  - 助手：顶栏右上角按钮开/关；展开为右侧精简 `ScreenAiCopilot`；「在助手中继续」派发 `loci:assistant-open` 打开全局助手
  - 试跑门闩：`trialPassed`；改正文失效；通过后才能选股
  - 选股：`ScreenSelectDialog`（单日/区间 + 股票池）→ 单日走 preview run；区间需先保存后走 `useScreenRunStore`
  - 结果坞：`ScreenWorkbenchDock`（诊断 / 解释 / 选股 / 回测）；选股页分开展示正式精选与低吸观察；回测复用 `QuantBacktestPanel`（`lockedSlug`）；Horizon/成交双口径可切换且结果互不冲掉；会话记住区间与成本；对照条/乐观差/直方；成交含筛选、分月条、复制摘要；回测可**停止**（`AbortSignal` 直通 `runBacktest`/`runHorizonBacktest`，停后 token 作废、不再回写结果），预计耗时与真实已耗时写在「跑回测」按钮旁而非空态里；结果存 `shared/stores/backtestPanel.ts`，切 Tab 卸载再回来还在（仅在战法+区间未变时回填）
  - 顶层 PageTabs：公式 / 策略 / 数据 / 参数 / 资料（原设置抽屉并入，不再单独弹层）；界面文案中文化（标识、编号、链接等）
  - 资料为可选项：空白卡不拦试跑/保存；动手填写或逻辑引用了编号才校验；仅 AI 生成草稿强制要求资料
  - 试跑/保存校验失败：跳到对应 Tab，表单字段标红；Tab 角标显示缺项数
  - 公式落地方言固定通达信兼容写法（内部仍为 `loci`）
- 公式/脚本切换在「参数」Tab，共用 `switchScreenSkillRuntime()`。
- `components/ScreenSkillImportDialog.vue`：导入通达信、同花顺或脚本源码到当前草稿；能否执行由公式子集和预览诊断决定。
- `composables/useScreenSkillWorkbenchPage.ts`：策稿页编排（试跑门闩、选股、回测入口）。
- `composables/screenSkillDraft.ts`：草稿与 manifest/runtime 契约互转；公式 payload 方言固定为 `loci`。
- 装包 / 卸载货架 → [`../marketplace/README.md`](../marketplace/README.md)
