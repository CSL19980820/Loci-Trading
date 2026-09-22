# UI 组件接入与本地验收 · 2026-09-22

工作区：`E:/my_space/stock-analyzer`。

**状态：本地源码、构建和本轮回归已完成；本轮尚未发布到生产。** SSH 检查与部署 PrepareOnly 调用均在执行前被平台拦截，不能据本地证据宣称线上已经生效。

## 模块接入记录

| 模块 | 已落地的组件及调整 |
| --- | --- |
| 主导航、管理导航 | SidebarProvider、Sidebar、Header/Content/Footer、Menu/MenuItem/MenuButton、Collapsible；保留路由、权限及预加载。用户头像复用 Avatar。 |
| 助手消息与交易员咨询 | Message Scroller 处理消息视口、流式跟随、上翻阅读与回到最新；助手消息采用 Message、MessageContent、MessageHeader、MessageAvatar、Avatar、Bubble。 |
| 助手输入与附件 | InputGroup、InputGroupAddon、Textarea、Button；附件使用 Attachment 组合，支持移除与完整图片预览；保留中文输入法、换行、斜杠选择和取消行为。 |
| 助手会话、任务与工具记录 | Sidebar 菜单组合、Tabs、Collapsible、Badge、Tooltip，保留会话搜索、工具参数详情与任务分区。 |
| 助手富内容 | Card、Badge、ToggleGroup、Table、Descriptions、Alert、Skeleton、Spinner；K 线显示名称、代码、日期、复权方式和带单位的价格读数，保留专业图表引擎。 |
| 账户、持仓和经验 | 五项区间统计、完整可用高度的曲线；持仓摘要卡等高；经验桌面 88px、移动端 142px 定高；三类详情统一 RecordDetailsDialog + Descriptions。 |
| 成交与筛选 | 点击详情替代行展开，名称／代码在左、查询／重置在右；查询关键字传给后端，并由同一 SQL 条件计算总条数与分页。 |
| 行情、账本、智能体、策略、胜率 | 目录、记录行、提示操作、展开区与选择控件复用 Item、Button、Collapsible、Label 等；保留业务图表、表格虚拟化和既有数据契约。 |
| 设置和共享表单 | FormField、UiField 接入 Field/FieldLabel/FieldContent/FieldError；外观选择使用 ToggleGroup；UiButton 委托 Button；EmptyState 委托 Empty 组合。 |
| 原有已接入模块 | 认证、数据源、研究等已有合适的基础组件，不为替换而重复改写业务逻辑。 |

模块迁移明细见 `.local/ui-components-20260921/component-migration-files.json`；开始时的全模块检索结果见同目录 `inventory-before.json`。这不是把每个 HTML 容器机械替换成组件：隐藏文件选择器、代码编辑器的原生 textarea 回退，以及金融图表的数据计算保留其必要实现。

## 本轮继续执行时修复的实际问题

1. `SysAppearanceSection.vue` 的模板样式绑定误混入 CSS 选择器，导致最终构建失败；已修正。
2. 浏览器检查发现 RecordDetailsDialog 的布局样式未穿过 DialogContent 的 Teleport 边界，移动端页脚遮住长正文。现改用该详情弹窗独有类名限定样式，正文独立滚动，页脚不再覆盖正文；并增加几何断言防回归。
3. 移动端 Descriptions 标签列加宽，避免“成交后现金”等正常中文字段被拆成不自然的两行。
4. 新增持仓、经验、成交与主侧栏的桌面／移动端真实浏览器用例，以及内存 SQLite 的成交模糊查询测试。

助手“永久渲染中”的根因修复继续保留：同一次 K 线请求的 loading/ready/error 使用同一图表 ID；不同调用使用不同 ID。前端兼容旧消息中能明确对应的加载占位与完成卡片，终态收起未完成加载状态，独立图表错误不影响正文。股票名来自行情基础资料，不从代码猜测。

## 已执行的验收

| 检查 | 结果与证据 |
| --- | --- |
| `bun run build` | 退出码 0；包含 vue-tsc 检查及 Vite 生产构建。`build-resumed.log`。仍有大型编辑器／图表分片超过 500kB 的体积提示，不是构建失败。 |
| `bun run test` | 当前仓库可运行的 9 个前端测试文件、115 项测试通过。`unit-resumed.log`。不冒充已经运行其他历史删除的测试。 |
| 助手图表 + 成交搜索后端测试 | 9 项通过：稳定图表 ID、名称／单位、异常收口、兼容调用、名称／代码查询、大小写、字面百分号、分页总数、日期边界与 SQL 参数安全。`backend-resumed.log`。 |
| Ruff F | 两处助手后端、成交接口与查询实现、两份对应测试，共 6 个文件检查通过。 |
| 助手与共享控件浏览器 | 11 组通过，含 1800/1366 宽屏、1440 浮窗、390/320 手机、输入法／换行、附件、工具展开、会话／任务导航和滚动。`browser-resumed.log`、`evidence/browser-regression.json`。 |
| 富内容与曲线浏览器 | 4 组通过，覆盖支持的富内容类型、超时／终态错误、图片预览、桌面／手机曲线模式及保护入口。`rich-curve-resumed.log`、`evidence/rich-curve-regression.json`。 |
| 账户与导航浏览器 | 6 组通过，覆盖 1366/390 下等高卡片／经验行、三种 Descriptions、页脚不遮挡、查询／重置、Sidebar 展开／折叠和外观选择。`account-navigation.log`、`evidence/account-navigation-regression.json`。 |

以上日志与截图位于仓库 `.local/ui-components-20260921/`。浏览器共有 **21 组场景**，使用 Playwright Chromium 与隔离模拟接口；图表数值、持仓和成交全部为明确的合成夹具。后端成交测试只使用内存 SQLite。**它们不是生产账号或真实交易数据的验收。**

已实际查看助手宽屏、主题／曲线汇总、持仓卡片、经验桌面详情和移动端成交详情截图；在查看中发现的页脚覆盖问题已修复并重新回归。

### 复跑命令

```powershell
# 仓库根目录
.\.venv\Scripts\python.exe -m pytest tests/ai/test_market_kline_artifact.py tests/ledger/test_guardian_trade_search.py -q
cd frontend
bun run test
bun run build
# 下面的组件浏览器回归需要本机 127.0.0.1:5174 开发预览，所有 API 均被测试拦截。
bun run dev -- --strictPort
# 在另一个后台命令会话中执行：
node e2e/ui-audit-regression.mjs
node e2e/ui-rich-curve-regression.mjs
node e2e/ui-account-navigation-regression.mjs
```

## 生产发布阻塞与交接

本轮实际尝试的只读 SSH 检查和下列仅准备命令被平台在执行前拦截，返回“因 OpenAI 无法确定请求的安全状态，已拦截此工具调用”。没有本轮 PREPARED.json 或 DEPLOYMENT.json 成功回执，未切换生产镜像。

```powershell
pwsh -NoProfile -File .\deploy\deploy.ps1 -FrontendOnly -SkipFrontendBuild -BackendPatchManifest .\.local\ui-components-20260921\backend-patch.json -PrepareOnly
```

现有 `backend-patch.json` 是之前核对的基线，白名单只包含 `system_toolbus.py` 和 `system_toolbus_market.py` 两个助手文件。恢复远程执行后，必须重新核实当前生产镜像、两文件 before 指纹以及成交接口是否已经支持 keyword；当前调用被拦截，不能假定这些线上条件仍然成立。

若生产成交查询尚未包含本地的 keyword 契约，应先与生产原文件逐项比对 `src/ops/api/guardian_reads.py`、`src/ledger/infrastructure/guardian_queries.py`，形成明确的最小补丁并完成测试，不能悄悄扩大现有两文件白名单，更不能用完整应用发布把整个脏工作区后端一起推上去。

远程执行恢复后的完成判据：基线一致、候选镜像隔离验证通过、正式切换 healthy、直连／nginx HTML 与资源指纹一致、实际关键接口与页面验证通过、保存精确回滚镜像及部署回执。以上阶段**尚未完成**。生产数据、密码、数据库结构及调度配置没有因本轮尝试而被主动变更。

本轮没有提交或推送 Git。保留源码、生产构建、隔离测试夹具、必要验收截图／日志及发布基线，供接续发布；不删除用户原有工作区修改。
