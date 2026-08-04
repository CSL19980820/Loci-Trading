# strategy

选股台 + 工坊工具匣 + 策稿。

- `ScreenHistoryView.vue`（路由 `/screen-history` · 选股台）：**选条 / 跑道 / 弹窗账页**
  - 顶栏：交易日**区间**（`TradeDateRangeField`：daterange + 今日/本周/上周/近一月/上一月快捷泡，跨度 ≤31 自然日）· 入库候选 ·（Skill 时 LLM）· **详情** · **入库历史** · 刷新 · 主按钮「选股 / 区间选股 / 跑技能」
  - 选中战法、区间、`kind` 写入 URL query（`select`/`from`/`to`/`kind`），点开行情批再返回可还原
  - 选条：`ScreenCatalogRail` — 战法 + 技能同目录；样本不足不刷文案（右侧 `—`），样本够才出胜率·均收益；搜索「搜名称」
  - 跑道：`ScreenRunPanel` — 待命/状态行折叠日志（默认展开，跑完自动收起；贴底滚动）；今日/区间末日 picks / 空态占满剩余高度
  - 入库历史：顶栏按钮打开宽弹窗；默认 `live_only` 仅盘后真选，开关「含回填」可审计；`ScreenHistoryPanel` 为列表页样式（日期区间筛选 · BasicTable 分页 · 详情/重跑）
    - 详情：顶栏打开既有 `StrategyDetailDialog` / `SkillDetailDialog`（与工坊战法/技能页一致）
- **选股后台**：`useScreenRunStore` 全局轮询；顶栏 `ScreenRunChip` 可点回进度；区间跑按交易日循环通用 `screen` + 同日同池入库，进度日志逐日输出
- `composables/tradeDateRange.ts`：快捷区间与跨度校验（前后端对齐）
- `composables/useScreenCatalog.ts`：合并 strategies + skills + 复盘/候选胜率 + `/insights/decay`；保留 `selectedStrategy` / `selectedSkill` 供详情弹窗
- `composables/useWorkbenchSkillRun.ts`：Skill 后台事件流 / HITL；日志经 `skillRunLog.ts` 全中文细粒度渲染（阶段/轮次/子任务启停/工具启停），跑道日志贴底自动滚动
- `composables/useScreenHistoryQuery.ts`：入库历史 Colada 缓存
- `QuantView.vue`（路由 `/quant` · 工坊）：**维护选股可用工具 + 本机货架 + 定时**
  - Tab：**战法** · **技能** · **数据源** · **定时** · **市场** · **回测**（市场右侧；`QuantBacktestPanel` + `QuantBacktestExtremeTape` → `mode=horizon`；T+1/T+3 胜率·平均；样本最佳/最差标注个股与选股日/标记日，点击跳 `/archive/:code?date=`；区间快捷近一月/三月/六月）
  - 选股结果 / 入库历史 / 跑道 picks：`StockLink` 带选股日 `date`，进行情默认落在该日 K
  - 数据源角标只数源家数（面板 `count-changed`），不数线路条数、不数 AkShare 接口数；`?view=` 透传给面板做深链（运维旧 `?tab=akshare` 就落在 `view=interfaces`）
  - 定时角标=启用任务数；运维旧 `?tab=jobs` 深链落到本 Tab；`?tab=runs` / `?runs=1` 打开执行历史弹窗
  - 定时台顶栏「执行历史」→ `JobRunsDialog`（任务名最左 min200、时间 min160、耗时如 `11h2min3s`）
  - 战法区：统一目录；来源/修订中文（内置·公式）；名称不展示 slug；产品内置为潜龙出海 / 潜龙尾盘 / 三源尾盘共振 / RSI22 次日低吸；海底捞月、三外有三与其他旧版只保留在归档回测，不进入活动目录；`formula` 可跳工坊编辑，`builtin` 行点击打开详情弹窗
  - 详情/配置弹窗 `StrategyDetailDialog`（行「配置」或点行）：默认打开**配置** Tab；含行情范围、定时选股、**推送企微**（定时结束后自动推，默认开；关定时则开关禁用）；底栏保存 → `PUT /api/strategies/{slug}/job`；**关定时（off）自动剔除绑定**
  - 定时台对 `screen:{slug}` 战法绑定只读（改配置走战法详情 / 「去战法改」带 `?strategy=`）；本机任务可 CRUD，战法/技能/供应商下拉选择
  - 主动作「选股」深链 `/screen-history?select=engine:|skill:`；操作列仅「选股」与「编辑(可编辑时)」；技能维持独立入口，不再混入公式工坊
  - 技能区与战法区同构：`QuantSkillsPanel` 行点击打开 `SkillDetailDialog`；工具栏「上传技能」支持 zip 或文件夹（文件夹本机打成 zip 再 `POST /api/skills`）
  - 详情弹窗 `SkillDetailDialog`：默认**配置** Tab（定时 + 推送企微 + LLM）/ 基础信息 / 说明书 / 工具；说明书按需拉 `instructions`，行内 Markdown 由 `ManualInline` 渲染；定时落库 `PUT /api/skills/{slug}/job`
  - `composables/skillManual.ts`：块级分块 + 行内解析；不用 `v-html`
  - 市场子区：`?shelf=` 浏览/已装/发布；装包变更会刷新战法/技能列表
- `StrategyConverterView.vue`（路由 `/strategy-converter` · 量化技能工坊）：一个共享 `ScreenSkillDraftModel` 的工作台。左侧 `ScreenWorkbenchCatalog` 使用目录 API 提供函数/字段/片段；中间 `ScreenWorkbenchEditor` 编辑逻辑、数据、来源和源码；右侧 `ScreenAiCopilot` 对当前草稿提出修改；底部 `ScreenSkillTestReport` 展示中文 IR/manifest 解释、逐条 citation 对应的资料定位、诊断与试跑。
- 顶部和设置抽屉的 Formula/Python 切换共用 `switchScreenSkillRuntime()`，同步方言、Python 入口和默认源码并清空旧预览，禁止产生运行时与方言不一致的草稿。
- `components/ScreenSkillImportDialog.vue`：导入 TDX、THS 或 Python 源码到当前草稿；TDX/THS 只是方言导入，能否执行由当前公式子集和预览诊断决定，不宣称厂商全函数兼容。
- `components/ScreenWorkbenchCatalog.vue`、`ScreenWorkbenchEditor.vue`、`ScreenAiCopilot.vue`、`ScreenSkillTestReport.vue`：统一工作台组件。
- `composables/screenSkillDraft.ts`：Screen Skill 草稿与 manifest/runtime 契约互转、局部校验、参数/逻辑/逐条 citation/数据构造；人工与 AI 共用该草稿。
- 装包 / 卸载货架 → [`../marketplace/README.md`](../marketplace/README.md)
