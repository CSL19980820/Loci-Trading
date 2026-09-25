# 全系统 shadcn-vue 基础能力落地与复审回执

日期：2026-09-22。基线：`2cabf932adb90c89f898eadc116b796a2dfee79c` 加工作区既有改动。本次在本地完成实现、隔离验证与复审，未部署、提交或推送；既有 Guardian/MCP 工作保留。

后续发布：用户另行授权部署后，已将这批改动发布为 `2.0.0-20260922-200909`。生产迁移、回滚备份及线上证据见 [生产发布回执](./2026-09-22-shadcn-production-release.md)；下文的开发验收边界保持原样。

## 结论

初审列出的 28 项已按实际调用链实施。通用基础控件统一到仓库内的 shadcn-vue / Reka UI 原语，业务适配器继续保留原有 props、事件、权限与中文密度。新增 Tags Input、Resizable 两类原语，未添加第三方依赖，也没有为凑齐官方目录引入无业务用途的组件。

后置源码扫描覆盖整个 `frontend/src`，包括被 Git 忽略规则命中的源文件。业务与共享适配层中，原生 button、select、table、progress 为 0；仅保留 4 个隐藏文件选择 input 和 Monaco 加载失败时的 textarea。UiBadge、UiField 名称保留，但已经委托 Badge、Field；旧 UiCard 系列及无引用的兼容实现已删除。

后置规模为 535 个 Vue 文件（204 个业务、252 个原语、78 个共享、1 个壳层）。非原语组件中，204 个直接引用、54 个间接引用基础原语，25 个纯展示/布局/图形/上下文组件经逐项审读保留；保留理由绑定源码哈希，后续内容变化会重新要求复核。原生控件未决、未复核组件、本地 Vue 导入缺失和 AST 解析错误均为 0。

“统一基础能力”不等于把所有 HTML 布局标签改成组件。ECharts、Monaco、SVG 环形/分段数据图、领域统计排版、消息滚动行为仍保留其必要实现；不把直接导入率当成全站质量百分比。

## 初审清单逐项处理

| ID | 最终实现 | 验证证据 |
|---|---|---|
| F01 | ResearchEvidencePanel、TemporalDataPanel 使用实际 Card/CardAction/Badge，修复模板未注册组件与状态色 | 强化模板检查；研究证据浏览器用例 |
| F02 | 角色过滤下沉 list/count；手机维护独立 offset、去重及失败重试游标 | 用户列表单元测试；后端混合角色分页回归 |
| F03 | HTTP 期限包含 JSON body；统一总 deadline；解除 abort 监听；退避可取消；写请求不重试 | palace.test.ts：慢 body、取消、监听释放、读写重试边界 |
| F04 | lifespan 恢复现有主/子租户研究任务；SQL 只修改旧进程 pending 记录 | 临时多租户、custom ops 路径及本进程 running 保护回归 |
| F05 | DateField 导入 Label；时间输入使用独立 ID | datetime range 浏览器取消草稿与 ID 验证 |
| U01 | UiBadge 成为 Badge 适配器，保留 dot、状态与行情颜色 | 路由渲染及主题组件验收 |
| U02 | 研究 Card 调用迁移后，移除无引用 UiCard 六件套 | AST 引用复扫、typecheck、构建 |
| U03 | Pager 使用 Pagination、Item、Ellipsis、Prev/Next/First/Last；手机缩减相邻页与冗余首末按钮 | 单次 emit/禁用/边界单测；两视口键盘和截图 |
| U04 | TextField 采用 InputGroup，保留密码、清空、焦点、autosize、前后缀 | 访客基础交互单测；四主题浏览器回归 |
| U05 | EmptyBlock 委托 EmptyState / Empty，保留 image/description/action 槽 | 共享空态截图与原有表格调用构建 |
| U06 | 任务、容量和路由加载条采用 Progress；未知进度为 indeterminate | 页面与共享已知/未知进度浏览器检查 |
| U07 | 功能页及共享 Loader 统一 Spinner；busy 指令用 Vue render 挂载并卸载 Spinner；StatCard 使用 Skeleton | 四主题、减弱动画、加载切换验收 |
| U08 | 关闭、移除、悬浮球等按钮委托 Button，纯阅读操作显式 access=read | 访客单测；助手关闭/重开浏览器验收 |
| U09 | 真分区补 tab/panel 配对；筛选药片改 ToggleGroup；Ops 导航采用 Tabs | 32 路由场景、53 次分区切换；SettingsRail 键盘回归 |
| U10 | UiField/原始输入控件补 for、id、description/error；组合字段显式分配独立 ID | 标签聚焦单测；Quant、日期与通知表单 DOM 复审 |
| U11 | 因子与引用清单采用 TagsInput，保留原字符串解析和保存协议 | 分隔符/重复项单测；键盘输入与删除浏览器验收 |
| U12 | 多题人工确认使用 RadioGroup/Field；单题立即提交、自由文本和数字键保持 | 助手确认单测与浏览器用例 |
| U13 | 桌面策略工作区采用 Resizable，持久化分栏；手机继续切换内容；Monaco 自动测量 | 鼠标拖动、刷新持久化、手机切换验收 |
| U14 | 删除未引用 UiButton/UiInput/UiSkeleton/UiSeparator、UiCard 系列与 navigation.ts；移除死导出的 ButtonGroup/ScrollContainer | 全量源码引用图、模板检查和生产构建 |
| T01 | tsconfig 开启 checkUnknownComponents | 正式 typecheck 与 build 使用该配置 |
| T02 | UsersTab 引入请求世代、AbortSignal、卸载取消、重复加载保护 | 倒序响应、筛选与分页回归 |
| B01 | 研究 executor 总容量 8、每租户 2；入队前预留；429/409；关闭取消待执行任务 | HTTP 202/409/429、名额单次提交、取消持久状态测试 |
| B02 | JSON/SSE 共享物理行 cursor，坏行不重放、半行不消耗 | 坏行/断尾/空批次回归；451 条 SSE 分批输出 |
| B03 | JSONL 采用 LRU 字节偏移索引与有界批次，重复轮询仅增量索引；补轮换/截断失效 | 文件轮换、同长度重写、句柄 fstat 回归 |
| B04 | 研究任务迁入租户 ops.db，按 ID 原子更新；原 JSON 一次导入且保留 | 迁移、回退导出、多租户隔离、活任务保护回归 |
| B05 | 当前页用户的 quota、usage 批量查询，列表主体固定 3 次 SELECT，total 独立计数 | SQL 次数、默认 quota、空 usage 与字段契约回归 |
| B06 | 咨询使用独立 4 worker 有界执行器；保持 request_id 幂等；SSE 无变化时 0.25→2 秒退避 | 满载无孤儿、同 ID 重试与冲突、现存咨询流测试 |
| B07 | 用量报告增加 15 秒/64 key 缓存及 freshness/partial；每 key 单飞，慢 IO 不持全局锁 | 不同根并发、同 key 单飞、异常唤醒、深拷贝回归 |

## 第二轮复审补充修复

- **弹层基础能力**：全屏档案和助手改接 Dialog，档案 Escape 复用原关闭路由；助手用 `unmountOnHide=false` 保留草稿及会话，关闭后释放模态限制。子弹窗 Escape 只关闭子层。移动端全屏弹层明确退出普通弹窗 5dvh/90dvh 样式规则。
- **列表选择基础能力**：策略目录、定时任务列表、助手斜杠菜单改用 Command/List/Item；保留输入焦点、IME、快捷键和单次提交语义。
- **浏览器发现的缺口**：补 Sonner Spinner 导入；修复 Resizable 消费 id 导致的手机 tab/panel 断链；修复比较符与阈值、Bark 多控件重复 ID；移除上下文用量 Popover 内的重复 dialog 角色。
- **复审扩展的共享收敛**：统计卡采用 Card/Skeleton；区块计数使用 Badge；手机分页减少控件挤压，四主题截图复看后确认。
- **后端复审**：恢复旧任务改为事务内精确更新；执行名额只能使用一次；缓存慢查询按 key 单飞；事件旋转、截断、同长度重写重新建立游标索引。

## 验证与证据边界

| 验证层 | 结果与范围 |
|---|---|
| 前端单元 | 16 个文件、133 项通过 |
| 前端静态及构建 | `checkUnknownComponents` 随 vue-tsc 运行；Vite 生产构建通过。仍有 Monaco/ECharts 相关大 chunk 提示，未伪称已解决包体性能 |
| 后端单元/HTTP 集成 | 现存全套 163 项通过；临时 data/config 根隔离，禁止外部网络，未调用真实模型或交易服务 |
| 后端导入 | `tools/import_smoke.py`：716 modules，0 failed；定向 Ruff F 通过 |
| 真实应用路由 | 16 路由 × 1440/390 两种视口，32 场景及 53 次只读分区切换通过；无页面异常、组件警告、重复有效 ID、悬空 tab/panel 或检查范围内越界 |
| 共享组件浏览器 | day/paper/night/ink × 桌面/手机，8 场景通过；日期取消、标签、焦点、分页、busy、Command 键盘选择；代表截图已目视复看 |
| 专项业务浏览器 | 5 组全部通过：研究证据、TagsInput、人工确认、Resizable、助手保活/嵌套 Escape/斜杠/IME；另验证上下文 Popover 名称与关闭层级、手机全屏边界 |
| 再次源码扫描 | Vue 模板 AST、TS 导入图与 render 调用扫描；保留原生控件列出原因；不将静态可达性冒充真实渲染 |

浏览器请求全部拦截为隔离夹具，不访问线上后端。登录扫码创建请求被 405 拦截，验证的是对应错误恢复界面。路由验收覆盖基础导航、空态及代表性恢复路径，不意味着每个业务弹窗、每种非空生产数据或全部业务算法均已验证。没有生产压测，不能量化宣称延迟提升比例。

## 可复跑入口与证据索引

从 `frontend` 启动隔离 Vite（本轮使用 5174），执行：

```powershell
node e2e/shadcn-route-smoke.mjs
node e2e/shared-foundation-regression.mjs
node e2e/feature-foundation-regression.mjs
bun run test
bun run build
```

从仓库根执行 `node tools/audit_shadcn_foundations.mjs`，输出 [后置源码清单](./2026-09-22-shadcn-system-post-inventory.json)。[原始审查](./2026-09-22-shadcn-system-review.md) 与 [初始清单](./2026-09-22-shadcn-system-inventory.json) 保留为实施前证据。

本地浏览器证据在 `.local/shadcn-foundation-20260922/`，不纳入源码提交：

- `routes-2026-09-22T11-50-11-215Z/results.json`：完整 32 场景最终轮。
- `routes-2026-09-22T11-50-52-183Z/results.json`：认证不可用页重试补验。
- `routes-2026-09-22T11-54-15-914Z/results.json`：全屏 Dialog 样式末次修复后的档案双视口补验。
- `routes-2026-09-22T11-55-44-826Z/results.json`：StatCard/Sheet 末次调整后的 Pulse、智能体、管理页六场景补验。
- `shared-results.json`、`shared-{theme}-{width}.png`：共享基础组件八场景与截图。
- `feature-results.json`、`feature-*.png`：业务专项与助手截图。
- `final-build.log`：最后一次前端 typecheck/生产构建回执。

早期 5 个路由证据目录（11:41:34、11:43:32、11:45:32、11:48:11、11:49:40）包含失败轮次，不能作为最终结果。删除操作被自动审批审查拒绝，理由仅为 `blocked by policy`；未绕过，保留并在此标明。

## 运行与回退说明

研究任务迁移在下次运行时对现有租户 ops.db 创建任务及迁移标记表，旧 JSON 不删除。回退前停止新版本执行并等待任务退出，将 `ResearchBacktestJobStore.export_legacy()` 导出到新文件，核对后再由操作人员选择切回旧实现；禁止用部署前旧 JSON 直接覆盖运行后的任务状态。本轮仅在隔离目录演练，未执行生产迁移。

执行配额是进程内的容量保护，继续遵循当前单 worker 调度部署约定；它不是跨进程分布式租约。事件首次读取/进程重启需要重建索引，缓存用量最多滞后 15 秒且显式返回 freshness/partial。后续若需要多 worker、持久任务重放或更大规模汇总，应单独确定租约与容量方案，而非把本次局部优化当作分布式能力。
