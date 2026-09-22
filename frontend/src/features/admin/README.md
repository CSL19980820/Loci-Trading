# 管理后台 (Admin View)

平台级治理与管理后台前端，路由 `/admin`。

## 权限与路由

- 仅 `role === 'admin'` 可见与操作。
- `NAV_LABELS` 登记为 `admin: { path: '/admin', title: '管理后台' }`（不配置 `short`，不上主侧栏，由头像菜单「管理后台」进入）。
- 非管理员直接通过 URL 访问 `/admin` 时，由 `AdminView.vue` 内部检测 `!userStore.isAdmin` 呈现「需要管理员权限」受限空态并提供「返回首页」引导，不堵塞全局路由守卫。

## 公共骨架（六个分区共用）

| 件                                                                                             | 落点                          | 用途                                                                                                                            |
| ---------------------------------------------------------------------------------------------- | ----------------------------- | ------------------------------------------------------------------------------------------------------------------------------- |
| `.admin-pane` / `.admin-pane__filters` / `.admin-pane__filter-actions` / `.admin-pane__scroll` | `style.components.css` 全局层 | 分区壳与筛选行的排版。**不要**在 SFC 里另写 `.xxx-tab { padding: 1.25rem }`                                                     |
| `PageContainer` + `BasicForm` + `BasicTable`                                                   | `shared/components`           | 列表页三件套：筛选进 `#search`，表进 `#main`，分页由 `BasicTable` 自管                                                          |
| `ListToolbar` / `RowActions`                                                                   | `shared/components/ui`        | 表头新增动作 / 行内动作。行操作一律 `:max-visible="1"`：**只留最主要的一颗，其余进「更多」**                                    |
| `lib/adminDict.ts`                                                                             | 本目录                        | 角色 / 状态 / 结果 / 级别 / 动作 / 租户 / 时间的**中文唯一真相**。界面禁止出现 `admin.set_role`、`ok`、`__primary__` 这类机器码 |

新增枚举先加进 `adminDict.ts`，再在页面里用 `*Label` 与 `*_OPTIONS`——下拉选项与表格文案共用同一张表，
「筛选框写中文、表格里也写中文」因此是结构保证，不是人肉对齐。

## 子模块

1. **平台总览 (`OverviewTab.vue`)**
   - 账号指标下方独立整行展示大模型用量：今天、本月或自选日期；可按模型汇总或按日查看输入/输出 Tokens 和调用次数，列表分页。
   - 用量源为各租户既有 `ai_usage_daily`；读取失败明确提示统计不完整。
   - 下方最近动作使用服务端分页，列为登录人、登录时间、动作、IP、描述。登录时间关联该动作发生前最近一次成功登录；未知显示空值，描述保留动作时间。
2. **用户管理 (`UsersTab.vue`)**
   - 骨架：`.admin-pane` + `PageContainer` + `BasicForm` 三格筛选（关键词 / 账号状态 / 角色）+ `BasicTable` 分页（每页 20，可切 50 / 100），工具行给「新增」「刷新」「列设置」。
   - **列一格一件事**：用户名称 / 登录账号 / 邮箱（带「已验证」标记）/ 角色 / 状态 / 租户 / 当月用量 · 额度 / 注册时间 / 最后登录时间。
     旧版把「昵称 + @登录名」塞一格、「注 xx / 登 xx」塞一格，28px 行高下糊成一团，也没法按单列读。
     租户走 `tenantLabel`：`__primary__` 显示为「主租户」，不把内部代号漏给管理员。
   - **操作列只留启用 / 停用**（`RowActions` `:max-visible="1"`），设为管理员 / 降为普通成员、发送站内通知、重置口令都进「更多」。
     旧版五颗常驻文字按钮把操作列撑到 230px，还把危险动作摆在了顺手位置。
   - **新增用户 (`CreateUserDialog.vue`)**：本系统不开放自助注册（后端 `LOCI_ALLOW_SIGNUP` 默认关，`/api/auth/register` 直接 403，
     登录页的「注册」入口随 `GET /api/auth/options` 的 `email_signup=false` 一起消失），**这是全站唯一的开号入口**。
     表单走 `BasicForm`（`:columns="2"`）：登录账号 / 用户名称 / 初始口令 / 邮箱 / 角色 / 账号状态。
     新号一律带 `must_change_password`，首次登录必须改密——管理员长期知道别人的明文口令是安全事故的起点。
   - **安全控制**：降级、停用、重置口令等危险操作统一走 `confirmDangerous` 二次确认；
     当前登录管理员不可停用自己、不可取消自身管理员角色（`RowActions` 的 `disabled` + `tip` 就地置灰并说明原因，而不是让动作凭空消失）。
   - **角色筛选是当页本地过滤**：`GET /admin/users` 不收 `role` 参数，分页总数仍报后端口径，与登录日志的「登录方式」同口径。
3. **登录日志 (`LoginsTab.vue`)**
   - 走 `listAdminLogins`：审计流里按登录动作白名单收窄的那一支，后端已按时间倒序，前端不再排序。
   - 骨架同用户管理：`.admin-pane` + `PageContainer` + `BasicForm` 三格筛选 + `BasicTable` 分页（每页 20，可切 50 / 100），工具行给刷新与列设置。
   - 筛选：关键词（登录账号 / 用户名称）、登录方式、登录结果。
     **「登录方式」是当页本地过滤**——`/admin/logins` 不收 `action` 参数，分页总数仍报后端口径，与 `UsersTab` 的角色筛选同口径。
   - 列：时间 / 登录账号（`actor_id` 挂 tooltip）/ 登录方式 / 结果 / 来源 IP / 备注（`detail_json.provider` 显示为「渠道：xxx」）。
   - 失败登录（`outcome !== 'ok'`）整行淡琥珀底，便于一眼扫出连续爆破尝试。
     用告警色而非红底：**红绿只属于价格涨跌**（D1），登录失败是运维告警，不该和行情抢同一套色彩记忆。
4. **审计日志 (`AuditTab.vue`)**
   - 跨租户全平台审计日志，按时间倒序展示；骨架、分页与工具行同登录日志。
   - 筛选：关键词（操作人 / 目标对象）、操作类型（中文下拉，可搜索）、执行结果。
   - 列：时间 / 操作人（`actor_id` 挂 tooltip，不另起副行）/ 操作类型 / 目标对象 / 结果 / 来源 IP / 详情。
   - **界面不出现机器码**：`action`、`outcome` 一律经 `lib/adminDict` 转中文，`admin.set_role` 这类标识只活在网络层。
     `actionLabel` 四级兜底且每级都只吐中文：正式字典 → 遗留别名（存量脏数据，如一次性脚本写歪的 `account.admin_reset_password`）
     → 「域·动作」拼词（`ops.export` → 运维·导出）→ 「未登记操作」。**不再显示原值**——原值漏出去就是界面上的英文，
     看到「未登记操作」即提醒补 `ACTION_LABELS`。遗留别名不进 `ACTION_OPTIONS`，筛选下拉里同一件事只有一个选项。
   - 详情走右侧「查看」按钮开弹窗，**不用展开行**：展开后的 `<pre>` 会把行高撞成两百 px，展开箭头还白占一整列。
     弹窗上半部是「事实格」（时间 / 操作人 / 类型 / 目标 / 结果 / IP），下半部是格式化后的 `detail_json`；没有附加参数时显空态，不打一个孤零零的 `{}`。
   - 两张日志表的共用零件（列定义工厂、筛选 schema 工厂、`limit/offset` 请求包装、`detail_json` 解析）收在 `components/logTableParts.ts`，
     刻意保持为**零件**而非一个带 props 的万能表组件。
6. **全站公告 (`AnnouncementsTab.vue`)**
   - 列表页骨架：`.admin-pane` + `PageContainer` + `BasicForm` 筛选（关键词：标题/正文；级别：中文下拉）+ `BasicTable`。
   - **前端分页**：`GET /admin/announcements` 既不吃分页参数也不吃筛选参数，一次返回全量；公告总量是十量级（运营手写、过期即删），
     所以一次拉全、在 `computed` 里筛、本地切页（每页 20，`:data-source` + `pagination` 对象由父级控页）。真到千量级再给后端加参数，届时换成 `:request` 即可，列定义不动。
   - 列：级别（中文 `el-tag`）/ 标题 / 发布人 / 发布时间 / 过期时间（空显示「不过期」）/ 操作（`RowActions` `:max-visible="1"`：编辑常驻，「预览正文」与「删除」进「更多」）。
   - **正文不进列表**：全文在「预览正文」弹窗里读（`width="min(92vw, 560px)"`，正文使用 `dialog-body--scroll`，Markdown 后代通过 scoped `:deep()` 设置样式）。
     旧版把每条公告的 Markdown 全文摊在卡片里，三条就能拉出两屏；级别也不再用左侧色条标记 —— 那正是全站在清的装饰线。
   - 「发布新公告」并进 `BasicTable` 的 `#toolbarButtons`（`ListToolbar` 的 `create`），**不另起一条 `PageToolbar`**（`features/README.md`：能一条不要两条）。
   - 编辑弹窗 (`AnnouncementEditorDialog.vue`)：`BasicForm`（`:columns="2"`，正文 `fullRow` + `textarea`），级别选项取自 `LEVEL_OPTIONS`（通知 / 警告 / 严重）；
     「编辑 / 预览」是一个 schema 字段，正文与预览靠 `hidden` 互斥，Markdown 实时预览保持原有实现。
   - 渲染安全：通过 `marked` + `dompurify` 净化 Markdown 渲染。

## 布局与弹层

`AdminView.css` 管理 11rem 侧边分区与内容区。980px 以下切换为可横向滚动的分区栏；当前分区、悬停与键盘焦点用中性表面、细边框及主题文字区分。列表仍复用全站 `.admin-pane`/`PageContainer`/`BasicTable`，局部 `AdminList.css` 只补充筛选区域收缩与操作换行。

新增用户、单用户配额、重置密码、站内通知和公告编辑五种弹层共用 scoped `AdminDialog.css`，宽度受 `92vw` 限制，正文使用 `dialog-body--scroll`，长标题及底部操作可换行。单用户配额按真实请求切换保存忙态，并在请求期间阻止重复提交；批量配额的空值与 `-1` 语义保持不变，批量编辑区域内部滚动，给下方用户表保留空间。

公告预览通过 scoped `AnnouncementPreview.css` 与 `:deep()` 设置 Markdown 后代样式；图片不超过容器，代码块和表格可横向滚动。Teleport 不要求取消组件作用域。审计详情将时间、操作人、类型、目标、结果和 IP 分成响应式事实格，原始参数仍使用可读的结构化正文。

配额调整入口与可写接口已移除；底层历史配额数据和执行保护继续保留。新建账号按钮在表格工具行的刷新与列设置左侧。
