# 界面与只读访客改造验收

批次：2026-09-20。工程：`E:/my_space/stock-analyzer`。

本记录对应用户的 19 项改造要求，以下原始验收结果来自 2026-09-20 的本地源码、生产前端构建和隔离测试。当时尚未部署线上，原始浏览器截图使用测试夹具，不代表实时行情或线上账户数据。后续已按用户指令部署完整前后端版本 `2.0.0-20260921-002839`，生产验证与备份记录见 `ui-access-deployment-20260921.md`。

## 逐项落实

| 项 | 结果 | 主要落点 |
| --- | --- | --- |
| 1 | 指数名称、点位、涨跌同一行，四张紧凑卡片，淡色图标背景；窄屏横向阅读，不把数值强制拆行。 | `PulseIndexStrip.vue` |
| 2 | 情报可点击或按 Enter 打开详情弹窗，完整展示情绪、题材、竞价、断板、催化、两融和解禁等已有数据。 | `PulseWatchRail.vue`、`IntelBriefDialog.vue` |
| 3 | 候选池顶部和右侧统计及相应计算删除，主列表使用完整宽度。 | `PoolView.vue` |
| 4 | 档案身份、报价、指标紧凑横排；图表填充剩余高度；选股记录进入右上角弹窗；批次栏可动画收起/展开，股票名称和代码同一行左右对齐。 | `ArchiveView.vue/.css`、`ArchiveBatchDock.vue`、`StatCard.vue` |
| 5 | 选股目录选中项仅保留柔和主题底色，不再加框线/竖线；结果说明与正式/观察标签同行、小灰字显示。 | `ScreenCatalogRail.vue`、`ScreenRunPanel.vue/.css` |
| 6 | 分隔线采用低强度主题混色，补齐基础边框色，避免未指定边框继承黑色正文。 | `style.base.css`、`style.foundation.css` |
| 7 | 筛选和动作合并工具栏；实心彩色按钮统一白字，浅色主题种子必要时压暗底色。修复 `text-aux` 被类名合并器当成文字颜色、覆盖白字的问题。 | `PageToolbar.vue`、`ScreenHistoryView.vue`、`theme.ts`、`cn.ts` |
| 8 | 工坊等页签直接与操作同行，不再让重复模块标题占一行；策稿名称和状态信息紧凑排列。 | `PageHeader.vue`、`QuantView.vue`、`StrategyConverterView.vue` |
| 9 | 路由加载和智能体数据加载均有过渡/骨架状态；慢请求不再留出无反馈空白。 | `App.vue`、`WorkspaceLoading.vue`、智能体页面 |
| 10 | 共用页头、读数和工具栏使用同一紧凑规则；桌面优先单行，窄屏按实际空间换行，表格/列表在内容区滚动。 | 共用布局组件及相关业务页 |
| 11 | 设置入口从头像菜单直接导航到设置页，桌面/手机实际点击均通过；弹层关闭后页面可继续交互。 | `UserAvatarMenu.vue`、`MobileBottomNav.vue`、`OpsView.vue` |
| 12 | 管理后台删除重复顶栏和公告/配额入口，摘要横排，图表按内容定高，审计列表有界，不用巨大空卡片填满页面。 | `AdminView.vue`、`OverviewTab.vue` |
| 13 | 角色仅管理员/访客；前端显式只读控件策略加后端统一权限闸门；访客新登录原子撤销旧会话；管理员仍可多端使用。 | identity 域、`visitor_access.py`、`useAccess.ts`、共用控件及业务页 |
| 14 | 公告组件、接口和活动表结构删除，启动迁移清除旧公告数据；设置集中管理登录、审计、任务、助手、研究/技能产物及智能体日志保留和清理。 | `access_migration.py`、保留策略领域/应用/API、`RetentionSettingsTab.vue` |
| 15 | 桌面和手机均使用同一个头像弹出菜单，收纳主题、账号设置、设置、管理后台、退出；不在手机更多网格重复放置管理入口。 | `shared/components/layout/UserAvatarMenu.vue`、主侧栏、手机导航 |
| 16 | 主侧栏和分组展开有动效；市场/我的及管理后台一级分组都有图标；减少动画偏好下禁用动效。 | `AppSidebar.vue/.css`、`AdminView.vue` |
| 17 | `Loci` 和 `多战法账本` 同一行。 | 主侧栏品牌区 |
| 18 | 帮助入口、路由/弹层及残余调用清理；原底部帮助位置改为侧栏收缩/展开按钮。 | 导航、命令面板、路由及帮助组件清理 |
| 19 | 账号设置合为完整展开页面，移除资源配额和个人开放 API；页面外壳不超过视口，长设备列表在内部滚动。 | `AccountView.vue` 及账号组件、identity API/迁移 |

## 权限和会话约定

管理员创建访客时，访客保留独立账号标识和独立 `tenant_id`，通过 `view_tenant_id` 显式获得创建者工作区的只读浏览授权。旧成员迁移为访客时保留原工作区，不擅自更换数据归属。访客升为管理员会清除只读授权并撤销旧会话，不会将创建者的工作区变成该账号的可写工作区。

访客的删除、写入、执行、生成、选股运行、同步、安装、交易及设置访问在服务端拒绝，不依赖前端按钮隐藏。共用按钮默认不对访客渲染，阅读/查询/分页/图表显示切换等须明确标注 `access="read"`。跳转到选股结果页与执行一次选股是不同能力：前者保留，后者禁止。

新会话的创建和旧会话撤销使用同一个 `BEGIN IMMEDIATE` 事务。并发登录最终只保留一个有效访客会话。旧会话下一次业务请求立即收到 401；已经打开且空闲的页面通过 10 秒会话检查、重新聚焦或接口失效事件退出。退出使用整页导航，销毁旧账号的 Pinia、KeepAlive 和查询缓存。这里限制的是有效登录会话，不按 IP 字符串粗略判断设备。

## 数据迁移与保留

`IdentityStore` 首次打开待升级身份库时执行 `access_model_admin_visitor_v1`。非空账号库先使用 SQLite backup API 生成一致性备份并校验，备份在身份库同级 `.backups/identity-before-visitor-*.db`。备份失败不继续迁移；迁移有事务和幂等标记。迁移保留账号标识、口令哈希和关联数据，重建角色 CHECK 约束，移除公告表和个人 API Key 表，并清除公告型通知。现有管理员口令不重置。

前后端应一同发布；不能仅发布前端后就将访客视为已受完整后端保护。本轮完整版本已一同上线，生产身份库的迁移标记、自动备份和退役表删除均已核对，不需要再手工删除公告或个人 API Key 表。

日志保留设置通过版本号防止多窗口覆盖，冲突返回 409。天数 0 表示不按时间清理；每任务条数上限独立生效；关闭保留策略停止定时清理。保存设置本身不删除数据，立即清理需要单独确认。运行中/等待中的任务、账本、持仓、成交和策略源文件不作为过期日志删除。自主交易员、股票智能体的详细日记策略在同一个设置页面可配置，清理先预览并保留摘要和财务事实。

## 验证结果

| 验证 | 结果 |
| --- | --- |
| 前端全量单元测试 | 164 个文件、742 个测试通过。 |
| 身份/权限/应用/保留策略回归 | 255 个测试、29 个子测试通过。 |
| Ruff F 检查 | `src` 和 `tests` 均通过。 |
| 导入冒烟 | 应用、访客中间件、身份迁移、保留设置模块可导入。 |
| 生产构建 | `vue-tsc --noEmit && vite build` 通过；仍有现有 Monaco 等大分片体积提示，不影响构建成功。 |
| 重点浏览器交互 | 11 项交互用例通过，涵盖桌面/手机入口、情报、档案、批次栏、慢加载和只读操作。 |
| 补充浏览器检查 | 四种外观、手机管理员/访客头像菜单、失效会话退出共 7 项通过。 |
| 页面矩阵 | 16 个路由场景 × 管理员/访客 × 桌面/手机，共 64 个场景通过；没有运行时错误、外层横向溢出或越出视口底部，没有访客写请求或受限设置读取。实际行情路由为 `/data`。 |

浏览器交互运行于本机 Edge。界面读取使用固定 API 夹具；后端权限、会话竞争、迁移和保留行为另外使用真实 FastAPI/SQLite 的隔离测试验证，不用前端 mock 代替权限验证。

## 复现

仓库根目录运行：

```sh
.venv/Scripts/python.exe -m ruff check src tests --select F
.venv/Scripts/python.exe -m pytest tests/identity tests/ops/test_retention_settings.py tests/ops/test_prune_retention.py tests/ops/test_prune_tenant.py tests/ai/test_retention.py tests/community/test_retention.py tests/app -q
```

在 `frontend` 运行：

```sh
bun run test
bun run build
# 浏览器脚本默认使用本机 5186 预览服务，可通过 TEST_BASE 改为其他本机预览端口。
node e2e/access-interactions.mjs
node e2e/access-final-checks.mjs
MOBILE=1 node e2e/access-acceptance.mjs
```

证据目录：`frontend/artifacts/ui-access/`。重点文件为 `interactions.json`、`final-checks.json`、`acceptance.json`、`matrix-summary.json`，以及 `final-*`、`verified-*` 截图。详细命令输出在 `.local/ui-access-20260920/`。改造前源码基线保留为该目录的 `before-source.zip` 与 `baseline.json`，不覆盖此前未提交改动。
