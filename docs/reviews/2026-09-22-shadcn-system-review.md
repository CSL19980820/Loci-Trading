# 全系统 shadcn-vue 使用与技术实现调整清单

审查日期：2026-09-22。源码基线：`2cabf932adb90c89f898eadc116b796a2dfee79c` 加当前工作区；已有 Guardian/MCP 等未提交改动保留。本报告保留实施前的审查事实；后续已按授权落地，当前状态见 [实施与复审回执](./2026-09-22-shadcn-system-implementation.md)。

## 1. 结论与处理顺序

系统已经广泛使用 shadcn-vue / Reka UI。主要缺口集中在旧 `Ui*` 组件残留、共享封装重复实现，以及部分已接入组件没有用完整。应优先修复已经确认的功能问题，再从共享层完成统一，最后补有实际收益的新能力。

建议顺序：

1. **P1：修复研究页组件解析失败、管理后台角色筛选与手机分页、请求超时边界、子租户研究任务中断恢复。**
2. **P2：统一 Badge/Card、分页、输入附加区、空态、进度和加载反馈；补全标签页关联与表单标签。**
3. **P2：完善事件游标、增量读取、后台任务有界执行与数据库批量查询。**
4. **P3：按真实使用场景引入 Tags Input、可调整工作区等；保留有必要的图表、编辑器、原生文件输入。**

P1 表示应优先排期的已确认行为问题；P2 表示确定的实现缺口或值得实施的收敛；P3 表示有条件的体验优化，不是现网故障。未用某个组件不自动构成问题。

## 2. 覆盖范围与证据边界

| 范围 | 本次覆盖 | 证据强度 |
|---|---|---|
| 前端源码 | 537 个 Vue 文件，其中 204 个业务 Vue 文件、12 个业务域 | 全量文件清点、模板 AST 原生控件扫描、TS `h()` 扫描、静态本地引用追踪 |
| 页面入口 | 16 个实际路由页面；另识别 1 个名称以 View 结尾的内嵌手机组件 | 路由表及 NAV_LABELS；没有把重定向当独立页面 |
| shadcn 组件 | 官方目录 70 类，本地 47 类原语目录 | 实时官方文档对照；本地 app 封装目录不算官方原语类 |
| 后端 | `src/` 下 708 个 Python 文件、14 个一级业务/基础目录 | 全量 AST 解析与异步入口清点，重点追踪请求、租户、后台任务、事件流、研究与管理查询 |
| 定向验证 | 当前 typecheck、临时强化模板检查、SSR 组件解析、模拟 HTTP、分页函数复现、隔离任务恢复、事件游标复现 | 详见第 8 节 |

机器可查清单见同目录 [2026-09-22-shadcn-system-inventory.json](./2026-09-22-shadcn-system-inventory.json)。其中逐文件记录 Vue 引用、原生控件位置、原语外部导入者、旧 Ui 组件调用者、后端目录数量和异步入口。

引用可达不等于实际渲染：桶导出可能让某个页面的可达原语集合偏大，所以不提供虚假的“页面组件化百分比”。本次没有逐页登录浏览器验收，没有生产压测，没有对全部业务算法作逐函数正确性证明，也没有访问真实数据库、调用模型或执行交易。后端属于全系统结构与重点链路审查，不能解读为 708 个文件均已完成深度语义验证。

## 3. 先修复的功能问题

| ID | 优先级与证据 | 现状及影响 | 调整方案与验收 |
|---|---|---|---|
| F01 | P1，源码 + SSR + 强化类型检查均确认 | `ResearchEvidencePanel.vue:8-10` 导入 Card/Badge，`:61-94` 却渲染未注册的 UiCard、UiCardHeader、UiCardTitle、UiBadge；研究证据区无法获得预期组件实现，header 的 action 插槽也有丢失风险 | 统一成实际导入的 Card 系列；原 `#action` 改成 CardAction 或保留兼容封装。`stamp` 映射为 `destructive`，不能只改标签名。验证有/无 findings、阻断状态、链接及窄屏；组件解析警告必须为零 |
| F02 | P1，原函数合成数据复现 | `UsersTab.vue:136-169` 在服务端分页后过滤 role；手机以过滤后的 `mobileRows.length` 推算 offset。30 条原始数据只含 3 个匹配角色时，下一次仍请求 offset=0，重复同一批账号，total 也不匹配 | `admin.ts:15`、`admin_router.py:80`、IdentityStore 的 list/count 同时增加 role 过滤；手机保存服务端分页游标，筛选变更清空并作废旧请求。用跨 3 页的混合角色数据验证无重复、无遗漏、total 一致 |
| F03 | P1，模拟 HTTP 确认 | `palace.ts:58-123` 的超时计时器在 fetch 返回响应头时清除，`response.json()` 不在期限内；调用者 abort 监听器也没有在完成时移除。注释称“单次请求墙钟上限”，实现实际只覆盖首响应 | 分清首响应超时与完整 JSON 读取期限，普通 JSON 请求让 try/finally 覆盖 body；保留主动取消，完成后解除监听；退避等待也可取消。`MAX_GET_RETRIES=4` 意味着最坏 5 次尝试，应另定总 deadline。用慢 headers、慢 body、取消、503 重试验证；写请求仍不可自动重试 |
| F04 | P1，隔离目录确认 | `backtest_router.py:98`、`factor_router.py:69` 在构造路由时只恢复当前租户；实际 job 路径却在请求租户中解析。主租户启动后，子租户上次进程遗留的 queued/running 记录仍可永久显示处理中 | 在进程启动恢复已存在租户的研究 job，或实现带进程/租约标识的安全惰性恢复；不要在每次读状态时无条件 recover，否则会误杀活任务。保留“中断标 failed、不用新行情自动重跑”的契约。验证主/子租户、因子/回测、queued/running、重复初始化与活任务保护 |
| F05 | P2，源码 + SSR + 强化类型检查确认 | `DateField.vue:107` 使用未导入的 Label；datetime 分支遗漏了预期标签组件 | 显式导入 Label 并验证时间输入标签关联；单日期、区间、datetime、禁用日期、取消草稿都需保持原行为 |

关键实现位置：

- [研究证据模板](E:/my_space/stock-analyzer/frontend/src/features/research/components/ResearchEvidencePanel.vue:61)、[研究入口](E:/my_space/stock-analyzer/frontend/src/features/research/ResearchPanel.vue:383)。
- [用户列表与手机分页](E:/my_space/stock-analyzer/frontend/src/features/admin/components/UsersTab.vue:136)、[管理 API](E:/my_space/stock-analyzer/src/identity/api/admin_router.py:80)。
- [HTTP 请求层](E:/my_space/stock-analyzer/frontend/src/shared/api/palace.ts:58)。
- [回测任务恢复](E:/my_space/stock-analyzer/src/research/api/backtest_router.py:98)、[因子任务恢复](E:/my_space/stock-analyzer/src/research/api/factor_router.py:69)、[任务存储](E:/my_space/stock-analyzer/src/research/infrastructure/backtest_jobs.py:62)。
- [日期时间控件](E:/my_space/stock-analyzer/frontend/src/shared/components/ui/app/DateField.vue:107)。

## 4. shadcn-vue 调整清单

下面的“应调整”针对现有实际使用位置；“条件引入”需要先验证是否改善使用效率。业务接口和语义封装可以保留，底层优先委托已有原语。

| ID | 优先级 / 决定 | 位置与当前实现 | 目标及收益 | 改动边界 / 验收 |
|---|---|---|---|---|
| U01 | P2，应调整 | `UiBadge.vue:22-58` 自绘 span/CSS，37 个文件直接导入；并行存在 `badge/Badge.vue` | 让 UiBadge 成为 Badge 的业务适配层，状态和行情颜色只有一个实现 | 保留 dot；旧 default→soft、stamp→destructive；up/down 与状态色不可混淆。覆盖用户、任务、行情、智能体与策稿台四种主题 |
| U02 | P2，应调整 | `UiCard*.vue` 为独立 section/header/div；`ResearchTemporalDataPanel.vue:27-30` 仍直接导入四件套 | 改为 Card 系列的轻量适配，减少两套卡片实现 | 保留 padded/plain、头部动作和高密度尺寸；F01 先修，再迁移历史研究数据区 |
| U03 | P2，应调整 | `app/Pager.vue:14-22,32-39` 自算窗口页码，尽管仓内已有 Pagination | Pager 保留业务 API，内部使用 Pagination、PaginationList/Item 等；页长 Select 和跳页输入继续保留 | 服务端 total、0 条、单页、最后一页删除、页长变化、禁用与键盘；不得引入重复请求。不是“全站没用 Pagination” |
| U04 | P2，应调整 | `app/TextField.vue:67-94` 自绘 prepend/append/prefix/suffix；助手输入器已用 InputGroup | 在共享 TextField 接入 InputGroup/AddOn/Button，统一边框、焦点、前后缀与错误态 | 保留密码显隐、清空后焦点、字数、textarea autosize、field bindings 和 emit 契约；读控件须透传 access=read |
| U05 | P2，应调整 | `app/presentation.ts:38-45` EmptyBlock 自绘；`GuardianReviewPanel.vue:131` 与 `GridEngine.vue:187` 使用 | 委托已有 EmptyState / Empty 系列，统一说明、原因与动作槽 | 区分空结果、尚未执行、加载失败；表格空态维持紧凑，不把所有空态扩大为整页卡片 |
| U06 | P2，应调整 | `AssistantAgentThread.vue:96-109` 自绘已知百分比；`AssistantSettingsDialog.vue:256,273` 自绘容量条 | 使用 Progress；百分比、异常状态与可访问名称统一；容量条仍保留文字读数 | clamp 0–100，未知进度保持未知；多段上下文分布和环形概览属于特定图形，可保留自绘 |
| U07 | P2，应调整 | `PageBusy.vue:1,30`、`app/ActionButton.vue:3,27` 各自 LoaderCircle 动画；仓内已有 Spinner | 用 Spinner 作为共同加载图标，业务遮罩与延迟显示保留 | loading/disabled、可访问文本、减弱动画偏好；不把所有骨架占位换成 spinner |
| U08 | P2，应调整 | `presentation.ts:24,34` 使用 `h('button')` 渲染关闭/移除 | 接入 Button，统一焦点、尺寸与禁用行为 | 本项目 Button 有访客访问约束；纯关闭控件显式 access=read，删除类操作按真实权限，不能机械全设 read |
| U09 | P2，应调整 | `PageTabs.vue:38-40,61-66` 有 TabsTrigger，没有内容关联契约；父组件自行渲染面板 | 页级真分区补 TabsContent 或显式 id/aria-controls/aria-labelledby；筛选类药片用已有 ToggleGroup/SegmentSwitch | 保留 keep-alive/v-show 的状态与滚动；实际分区与筛选动作分别验收，不能仅因用了 Tabs 就认定语义完整 |
| U10 | P2，应调整 | `UiField.vue:9` for 可选，部分调用只传 label；例如 `ResetPasswordDialog.vue`、研究编辑对话框 | 使用 Field/Label 的同时补齐具体控件 id、for、错误描述关联；可扩展现有 UiField 插槽给出 id | 已使用 Field，无须再次迁移库；验证点击标签聚焦、屏幕阅读器读出错误；多控件组合使用 fieldset/legend 等合理语义 |
| U11 | P3，建议引入 | `ScreenSkillLogicPanel.vue:91-98,147-153` 因子/引用编号以逗号或换行填写 | 小型 token 列表改 Tags Input，支持逐项删除、去重、键盘与粘贴拆分 | 保留外部文本契约的适配；代码、长说明、大批股票输入不能一律 token 化。[官方 Tags Input](https://shadcn-vue.com/docs/components/tags-input) |
| U12 | P3，条件引入 | `AssistantConfirmCard.vue:135-175` 多题选项通过按钮和手工 answers 管理 | 多题场景可先用现有 RadioGroup + Field；Questionnaire 作为交互能力评估，不直接替换问答协议 | 单题点击立即回复、多题统一提交、自由文本、数字键、风险提示与 waiting_user 不得退化 |
| U13 | P3，条件引入 | `StrategyConverterView.vue:341` 编辑/结果区、助手任务侧栏使用固定布局 | 大屏确有调宽需求时用 Resizable，保存比例；移动端继续现有分区切换 | 键盘调整、最小宽度、编辑器 resize、图表 resize、持久化；这是新能力，不是现有 bug。[官方 Resizable](https://shadcn-vue.com/docs/components/resizable) |
| U14 | P3，可随相关修改清理 | `UiSkeleton.vue`、`UiSeparator.vue`、`UiInput.vue` 等没有业务直接导入；`navigation.ts` / presentation 中部分兼容导出也未找到调用 | 确认无动态引用后删除无用适配或停止新增调用，避免继续维护第三套实现 | 不为了使用 Skeleton/Separator 而先启用死组件；机器清单与编译共同确认依赖 |

共享控件证据入口：[Pager](E:/my_space/stock-analyzer/frontend/src/shared/components/ui/app/Pager.vue:14)、[TextField](E:/my_space/stock-analyzer/frontend/src/shared/components/ui/app/TextField.vue:67)、[UiBadge](E:/my_space/stock-analyzer/frontend/src/shared/components/ui/UiBadge.vue:22)、[EmptyBlock](E:/my_space/stock-analyzer/frontend/src/shared/components/ui/app/presentation.ts:38)、[PageTabs](E:/my_space/stock-analyzer/frontend/src/shared/components/ui/PageTabs.vue:38)。

InputGroup 的前后缀、按钮、textarea 组合与 U04 匹配；Empty 对应 U05，Field 对应 U10。依据：[Input Group](https://shadcn-vue.com/docs/components/input-group)、[Empty](https://shadcn-vue.com/docs/components/empty)、[Field](https://shadcn-vue.com/docs/components/field)、[Pagination](https://shadcn-vue.com/docs/components/pagination)。

### 不应误报或机械替换的位置

| 现状 | 判断 |
|---|---|
| BasicTable → DataGrid / BasicTableVirtual → GridEngine → Table + TanStack Table / Virtual | 已有官方 Data Table 所需的核心组合，保留业务封装；先修分页、排序或可访问性具体缺口，不再引入第二个表格引擎。[官方 Data Table](https://shadcn-vue.com/docs/components/data-table) |
| DateField → Calendar / RangeCalendar + Popover | 已经实现 Date Picker 组合；没有 date-picker 目录不等于未使用。修 F05 即可，保留中国日期显示、日期区间和时间草稿 |
| ChoiceField → Popover + Command | 官方明确允许这种 Combobox 组合；无需只为新增 combobox 目录而重写。[官方两种实现](https://shadcn-vue.com/docs/components/combobox) |
| NumberInput、FormField、SegmentSwitch、CommandPalette、ConfirmHost | 分别已用 NumberField、Field、ToggleGroup、Command、AlertDialog；不重复迁移 |
| Sidebar、消息组件、MessageScroller、Attachment、InputGroup | 已有业务接入，不能列为“完全未利用”的新工作 |
| ECharts / K 线 / Monaco | 保留专业实现；shadcn Chart 不是必须替换的图表引擎，不能为组件统一牺牲行情交互和编辑能力 |
| 隐藏 file input 4 处 | `AssistantSenderDock:448`、`MarketPublishPanel:71`、`QuantSkillsPanel:182,189` 是浏览器文件选择机制，保留；它们不是 4 个漏迁移的可见文本框 |
| AssistantFloatBall 原生 button、CodeEditor fallback textarea | 拖动浮球与编辑器失败降级有独立契约；可保留，分别检查键盘激活和编辑/焦点。代码编辑器不要套普通 Textarea 的样式和事件假设 |
| NativeSelect、ScrollArea 已入库但无外部静态导入 | 不能为了“用完库”强塞。原生滚动应保留于消息滚动、虚拟表格等依赖 viewport 的位置；普通局部列表有统一滚动条需求时再用 ScrollArea |
| ButtonGroup | 本地同名兼容组件没有业务调用；真正成组的工具动作可引入官方组件，普通 flex 按钮行无需批量替换 |

### 官方目录中没有独立本地目录的 23 类

- **已有等价官方组合或项目实现（不补目录）**：Combobox、Data Table、Date Picker、Form、Chart、Toast、Typography。FormLayout 已有校验与 Field 组合；消息提示已用 Sonner。Typography 属排版规范，不要求每段文字组件化。
- **可明确评估收益**：Tags Input（U11）、Questionnaire（U12）、Resizable（U13）、Button Group（成组动作场景）。
- **本次未发现必须引入的现有需求**：Aspect Ratio、Breadcrumb、Carousel、Context Menu、Hover Card、Input OTP、Marker、Menubar、Navigation Menu、Pin Input、Slider、Stepper。深层导航/OTP/向导等需求出现时再选用；尤其精确交易参数应保留 NumberField，不能强行换 Slider。

47 类本地原语和 70 类官方目录的完整列表见 JSON。以上分类覆盖所有 23 个目录差异；45 类本地原语存在外部静态引用，2 类没有。这些是源码盘点数字，不是页面渲染率。

## 5. 页面与业务域落点

所有 16 个实际路由页都有直接或间接原语引用。这里列的是下一步改动位置，不把整个页面标成“未组件化”。

| 业务域 / Vue 数 | 页面与内嵌能力 | 调整落点 |
|---|---|---|
| market / 13 | `/` 盘面、`/data` 行情、`/peek` 速览 | U01、U03、U04、U07；保留图表、实时交易时段闸门和速览轻量入口 |
| ledger / 11 | `/pool` 候选池、`/archive/:code` 档案、`/login`、`/auth-unavailable` | U01、U03、U04、U09；登录已组件化，不追加无需求 OTP |
| agents / 9 | `/agents`、`/agents/:id` 智能体工作室 | U01、U06；与 ops 的交易员内嵌面板共同验收 |
| strategy / 40 | `/quant`、`/strategy-converter`、`/screen-history` | U01、U03、U04、U09、U11、U13；保留 Monaco 和复杂表格契约 |
| review / 5 | `/winrate` 胜率统计 | U01、U03；数值和统计口径不因 UI 替换改变 |
| ops / 53 | `/ops` 与交易员/任务内嵌面板 | U01、U03、U04、U05、U07、U09；后台实现见 B01–B06 |
| auth / 8 | `/account`、资料/安全/会话分区 | U01、U04、U09、U10；密码输入与删除会话确认保留 |
| admin / 11 | `/admin`、用户、审计、登录、用量 | F02 先修；U01、U03、U04、U10，后端批量聚合 B05 |
| research / 12 | 档案/工作室内研究、证据、历史数据、假设 | F01、F04、U02、U10；并非独立路由，已纳入审查 |
| datasource / 8 | 数据源管理内嵌面板 | U01、U04、U07；探测请求保持取消和错误来源信息 |
| marketplace / 6 | 工坊市场、发布、详情与货架 | U03、U04；隐藏文件输入保留，安装/发布权限与确认保留 |
| ai / 28 | 全局助手、消息、工具回执、会话与任务侧栏 | U04、U06、U07、U08、U12；MessageScroller 已接入；F03、B02、B03、B06 影响异步体验 |

重定向 `/live`、`/reviews`、`/reviews/records`、`/insights`、`/market`、`/ops/skills` 没有独立页面，不另做迁移。壳层 AppSidebar、MobileBottomNav、CommandPalette、主题弹窗与共享对话框也纳入共享引用盘点。

## 6. 前后端技术实现调整

| ID | 优先级 / 证据 | 现状与影响 | 建议实现 | 验收与限制 |
|---|---|---|---|---|
| T01 | P1 配套 F01/F05；已运行验证 | 当前 tsconfig 的 TS strict 未启用 Vue 未知组件检查；正常 typecheck 通过但 SSR 报组件解析失败 | 在现有配置开启 `vueCompilerOptions.checkUnknownComponents=true`，先补 6 处错误；无需一口气扩大所有 strictTemplates 校验范围 | 临时配置已确切报出两文件 6 处错误。纳入持续 typecheck，生产构建和代表页 console 仍需另验 |
| T02 | P2，源码确认 | UsersTab 的手机数据加载没有请求世代保护；共享 BasicTable 已有请求世代。快速换筛选时旧响应可覆盖新状态 | F02 过程中复用已有 request-generation 思路，接口增加 AbortSignal；小范围列表可使用已安装 Colada，不全站换状态库 | 延迟响应倒序到达、卸载、重复点击与筛选切换验证；query key 包含全部筛选，写后失效更新 |
| B01 | P2，源码确认 | 回测/因子模块各有 `ThreadPoolExecutor(max_workers=1)`，提交调用没有本地待处理上限，生命周期未由 app 管理；串行执行不等于有界队列 | 以现有 job store 加全局/租户待处理配额、重复提交控制、明确队列满响应；executor 生命周期由应用托管；先完成 F04 | 队列满可恢复、完成释放槽位、关机取消未开始任务并标记状态；不立即引入 Celery/Redis。CPU 瓶颈先量测，已有回测进程隔离能力可复用 |
| B02 | P2，坏行场景已复现 | `skill_runs.list_events` 的 `_seq` 是物理行号；JSON API 的 `next_after=after+len(events)` 却按有效行数推进。跳过坏行后会重复返回事件 | JSON 和 SSE 都按实际最后 `_seq + 1` 返回 cursor；明确定义坏行/半行策略、空批次和终态 | 夹具 `_seq=[0,2]` 现返回 next_after=2，再读重复 seq=2；修后应为3。增加断线重连、半行写入、空批次回归 |
| B03 | P2，源码确认；收益未做生产压测 | `skill_runs.py:86-106` 每次 read_text+splitlines 全量扫描 JSONL；无 limit；JSON 请求及 SSE 重复发生 | 小改先加有界批次和真正可续读的偏移/索引；更稳妥的中期方案是租户 ops.db 的 `(run_id, seq)` 事件表，保留当前公开游标协议 | 1万/10万事件下读取尾部成本与新批次相关；半行、重启与迁移回退可验证。只加 limit 而仍全读文件不能算完成 |
| B04 | P2，源码确认；容量收益需量测 | `ResearchBacktestJobStore._read/_write` 每次 get/update 都读写完整 jobs.json，全局 `_LOCK` 串行所有实例 | 研究任务增长后迁移到已有租户数据库的一张任务表，按 id 更新与分页；先定义状态及迁移版本，不另加数据库产品 | 历史 job 可读、状态原子更新、备份回退、租户隔离；不要直接删原 JSON。低数据量阶段可排在 F04/B01 后 |
| B05 | P2，确定 N+1；未证明当前是线上瓶颈 | `platform.list_users:125-133` 每个用户调用 get_quota 和 usage_overview。列表主体为 `1+2N` 条 SQL，HTTP 再查 total | 一次读当前页用户，一次批量 quota，一次按 user_id 聚合 usage，内存组装；与 F02 后端 role 筛选一起做 | 相同用户行契约、默认 quota、空 usage、分页 total；SQL 次数不随 N 线性增加。SQLite 本地查询较便宜，不虚报收益倍数 |
| B06 | P2，结构性容量建议 | Guardian 咨询 `BackgroundTasks` 执行最长数分钟的同步模型研究，使用共享线程池；SSE 又每250ms打开库读全量快照 | 咨询任务使用有界独立执行资源，保留 request_id 幂等、租户上下文和持久状态；事件通知唤醒 + 持久快照兜底，或先降低空轮询成本 | 以并发咨询验证普通 API 延迟；取消/重启/租约过期、断线重连和上滑读历史保持。当前没有观测到线程池耗尽，不作为已发生故障 |
| B07 | P3，结构性扩展建议 | `usage_reporting.py:16-35` 每次按日期串行遍历所有租户数据库，单库 timeout=3；缺库只读处理正确 | 先做短期、按日期区间的缓存与显式 freshness/partial 标识，或后台生成汇总；当前规模小可保留直接读取 | 保留 unavailable_tenants；新增缓存不得把部分结果冒充完整，也不能串租户暴露细账 |

证据：[强化检查配置](E:/my_space/stock-analyzer/frontend/tsconfig.json:1)、[现有请求世代封装](E:/my_space/stock-analyzer/frontend/src/shared/components/ui/useBasicTableSource.ts:98)、[技能事件读取](E:/my_space/stock-analyzer/src/ops/application/skill_runs.py:86)、[事件 API](E:/my_space/stock-analyzer/src/ops/api/skill_runs_api.py:215)、[研究 job 全量 JSON](E:/my_space/stock-analyzer/src/research/infrastructure/backtest_jobs.py:25)、[管理用户 N+1](E:/my_space/stock-analyzer/src/identity/application/platform.py:125)、[咨询任务提交](E:/my_space/stock-analyzer/src/ops/api/guardian_consult.py:69)、[咨询执行](E:/my_space/stock-analyzer/src/ops/application/guardian_consult.py:142)、[平台用量聚合](E:/my_space/stock-analyzer/src/ai/application/usage_reporting.py:13)。

后端没有必要全面 async 化：同步 FastAPI 路由与 SQLite 组合目前有合理边界；AI SSE 已把数据库读取放入线程池、等待使用 asyncio.sleep；行情流也有专门实现。优先补容量、持久化和生命周期缺口。线程池 submit 与 shutdown 的约束参考 [Python concurrent.futures](https://docs.python.org/3/library/concurrent.futures.html)，后台工作取舍参考 [FastAPI Background Tasks](https://fastapi.tiangolo.com/tutorial/background-tasks/)。

保留并继续验证的现有机制：租户 ContextVar 与 submit_with_tenant、共享行情库、系统/租户调度池分离、单 worker 调度约束、回测 process_worker 并发槽位、社区 API 的 limit 上限、行情同步统一闸门、胜率缓存、研究 revision 契约。本次没有证据支持将它们替换成新框架；也没有以“发现不了问题”声称其所有业务边界均已验证。

## 7. 建议拆分的实施批次

| 批次 | 内容 | 范围 / 风险 | 完成判据 |
|---|---|---|---|
| A：正确性修复 | F01、F05、T01；F02/T02；F03；F04 分别交付 | 4 组独立变更，便于定位回归；F04 涉及持久状态须隔离演练 | 对应复现转为回归检查；正常 typecheck 和强化检查均通过；代表页面无解析警告 |
| B：共享组件统一 | U01–U08，优先 Badge、Pager、TextField | 改动集中但影响全站，保留对外 props/emits/slots | 四种主题、桌面/窄屏、键盘、访客/可写用户、选择/清空/取消/禁用验收 |
| C：交互语义与异步基础 | U09、U10、B01、B02、B03、B05 | Tabs 与请求竞态要检查父子契约；数据库改动单独变更 | tab/panel 关联、标签聚焦、分页不重复、事件重连不重放、队列有界 |
| D：规模与体验增强 | B04、B06、B07、U11–U14 | 按数据量和实际使用选择；不捆绑全量框架替换 | 量测证明收益；保持研究/交易/问答语义；无法证明收益的项目暂不实施 |

任何后续组件迁移都必须保留：中文密度、行情数值语义、移动端关键指标与详情入口、访客访问控制、危险操作确认、流式增量呈现、上滑阅读时不抢滚动、日期格式与租户边界。部署、commit、push 仍需后续明确任务授权。

## 8. 实际验证记录

| 检查 | 结果 | 可支持的结论 |
|---|---|---|
| `bun run typecheck` | 退出码 0 | 当前常规类型检查通过，不能排除未知模板组件 |
| 临时 tsconfig 开 `checkUnknownComponents=true` | vue-tsc 退出码2；ResearchEvidencePanel 5处 + DateField 1处 TS2339 | T01 能捕获这次确切漏迁移；临时文件已删除 |
| Vite SSR 加载 + renderToString | ResearchEvidencePanel 报4种 `Failed to resolve component`；DateField 报 Label | F01/F05 为真实解析缺口；不等于浏览器视觉截图 |
| 原 HTTP 实现 + 本地 mock fetch/body | timeoutMs=20，约113ms仍返回 body；signal未abort；caller listener增加1、移除0 | F03 超时范围与监听生命周期问题；没有外网请求 |
| 原 loadUsers/loadMobile 函数 + 合成65行 | 两次请求offset为 `[0,0]`；结果 id `[0,1,2,0,1,2]` | F02 手机角色筛选会重复翻页 |
| 真实 ResearchBacktestJobStore + 临时租户目录 | router启动恢复后 primary=failed、child=queued | F04 恢复范围缺口；临时目录退出后已确认不存在 |
| 原 list_events + 内存模拟坏行 | 首批seq `[0,2]`，JSON式next_after=2，下批仍为 `[2]` | B02 游标错误，未读写真实事件文件 |
| 全量源码扫描 | 537 Vue模板完成 AST 清点，708 Python完成 AST解析 | 支持库存和入口覆盖；不代替所有函数语义测试 |

本次仅新增报告和机器清单；没有修改业务源码、提交、推送、部署、重启服务或变更真实数据。没有运行全量后端测试、全量E2E、浏览器视觉或生产负载测试，因此未宣称线上故障已经修复，也未给出未经测量的性能提升数字。
