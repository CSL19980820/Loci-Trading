# 管理后台 (Admin View)

平台级治理与管理后台前端，路由 `/admin`。

## 权限与路由

- 仅 `role === 'admin'` 可见与操作。
- `NAV_LABELS` 登记为 `admin: { path: '/admin', title: '管理后台' }`（不配置 `short`，不上主侧栏，由头像菜单「管理后台」进入）。
- 非管理员直接通过 URL 访问 `/admin` 时，由 `AdminView.vue` 内部检测 `!userStore.isAdmin` 呈现「需要管理员权限」受限空态并提供「返回首页」引导，不堵塞全局路由守卫。

## 公共骨架（五个分区共用，别再各写各的）

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
   - `.admin-pane` + `.admin-pane__scroll`：整块在内层滚，页面级不出滚动条；间距一律 `--gap-*`，不留自绘魔法值。
   - 四张核心数字卡走 `StatCard`（`label` / `value` / `hint`），口径写在卡上的 `hint`（如「全平台注册账号」），**不再靠悬停 tooltip 才看得见**；
     外层 `auto-fit minmax(180px, 1fr)` 自适应列数并 `align-items: start`，卡高由内容决定。
   - 当月大模型用量前 10 名（ECharts 水平条形图，按需引入，跟随日间/夜间主题切换）；画布高度跟着面板长，条厚封顶 24px（只有两三个用户时不画成色块）。
   - 最近 20 条审计事件改用 `BasicTable`（`:data-source` + `:pagination="false"`，**不设 `max-height`**，表体吃满面板并在 `.basic-table__body` 内层滚）：
     列为时间 / 操作人（空则「系统」）/ 操作类型（中文 `el-tag`）/ 目标对象。
     **不用时间线**：它自带左侧竖轴线与节点圆点（正是全站在清的装饰线），而这块数据本就是四列的表，表格才能对齐列、截断长目标串并限高滚动。
     空态走 `EmptyState`（「还没有审计事件」+「管理动作会实时落在这里」），不用带插图的空态。
   - 两栏面板仍是 `Sheet`，且**吃满数字卡以下的全部剩余高度**（`.overview-panels { flex: 1 1 auto; min-height: 24rem }`，`Sheet` 与 `.sheet-slot` 逐层转成纵向 flex）：
     写死 280px 图 + 320px 表时，1080p 的下半屏是一整片死白。窄屏断点用全站的 980px（侧栏消失、底栏出现那条线），单列后改回内容定高，不另立门户。
2. **用户管理 (`UsersTab.vue`)**
   - 骨架：`.admin-pane` + `PageContainer` + `BasicForm` 三格筛选（关键词 / 账号状态 / 角色）+ `BasicTable` 分页（每页 20，可切 50 / 100），工具行给「新增」「刷新」「列设置」。
     旧版是自绘 `.filter-bar` + 裸 `el-table` + 自绘 `.pagination-bar`，与全站列表页各长各的。
   - **列一格一件事**：用户名称 / 登录账号 / 邮箱（带「已验证」标记）/ 角色 / 状态 / 租户 / 当月用量 · 额度 / 注册时间 / 最后登录时间。
     旧版把「昵称 + @登录名」塞一格、「注 xx / 登 xx」塞一格，28px 行高下糊成一团，也没法按单列读。
     租户走 `tenantLabel`：`__primary__` 显示为「主租户」，不把内部代号漏给管理员。
   - **操作列只留启用 / 停用**（`RowActions` `:max-visible="1"`），设为管理员 / 降为普通成员、调整配额、发送站内通知、重置口令都进「更多」。
     旧版五颗常驻文字按钮把操作列撑到 230px，还把危险动作摆在了顺手位置。
   - **新增用户 (`CreateUserDialog.vue`)**：本系统不开放自助注册（后端 `LOCI_ALLOW_SIGNUP` 默认关，`/api/auth/register` 直接 403，
     登录页的「注册」入口随 `GET /api/auth/options` 的 `email_signup=false` 一起消失），**这是全站唯一的开号入口**。
     表单走 `BasicForm`（`:columns="2"`）：登录账号 / 用户名称 / 初始口令 / 邮箱 / 角色 / 账号状态。
     新号一律带 `must_change_password`，首次登录必须改密——管理员长期知道别人的明文口令是安全事故的起点。
   - **安全控制**：降级、停用、重置口令等危险操作统一走 `confirmDangerous` 二次确认；
     当前登录管理员不可停用自己、不可取消自身管理员角色（`RowActions` 的 `disabled` + `tip` 就地置灰并说明原因，而不是让动作凭空消失）。
   - **角色筛选是当页本地过滤**：`GET /admin/users` 不收 `role` 参数，分页总数仍报后端口径，与登录日志的「登录方式」同口径。
3. **配额管理 (`QuotaTab.vue`)**
   - 结构：`.admin-pane` > `Sheet`（批量表单，固定在上）+ `BasicTable`（用户表，吃满剩余高度并在内部滚）。
   - 批量表单走 `BasicForm`（`:columns="3"`、`:input-debounce-ms="0"`），六项配额仍由 `QUOTA_FIELDS` 表驱动。
   - **一格一个数字的取舍**：每项配额只有一个 `input-number`，取代旧版「`调整` 复选框 + 数值框 + `不限` 复选框」三控件。
     口径靠值本身表达 —— **留空 = 这项不改**（不进 payload）；**`-1` = 不限**（与后端一致）；`≥ 0` = 具体上限。
     于是两层互斥开关（未勾选时置灰 / 不校验 / 不提交）连带十八个控件一起消失，六项一行三列就排得下，校验只剩 `min: -1`。
     写入语义仍复用 `lib/adminFormat.ts` 的 `uiValueToQuota`（负值 → -1，正值向下取整且不小于 0），不在页面里另造取整规则。
   - 字段中文化：月度额度（每月大模型 Token 上限）、每日调用、策略槽位、发布槽位、定时任务、目录容量（单位 MB）。
   - 用户表走 `BasicTable` 的 `:request` 分页（每页 20，可切 50 / 100），首列 `type: 'selection'`，`@selection-change` 收集勾选，chip 显示「已选 N 人」。
     列：用户名称 / 登录账号 / 月度额度 / 每日调用 / 策略槽位 / 发布槽位（-1 一律显示为「不限」）。**表头不出现英文**。
   - **换页会清空勾选**（选择列不带 `reserve-selection`），所以「已选 N 人」永远只表示当前页，不会出现「跨页勾了 80 人却只改了 20 人」的静默偏差。
4. **登录日志 (`LoginsTab.vue`)**
   - 走 `listAdminLogins`：审计流里按登录动作白名单收窄的那一支，后端已按时间倒序，前端不再排序。
   - 骨架同用户管理：`.admin-pane` + `PageContainer` + `BasicForm` 三格筛选 + `BasicTable` 分页（每页 20，可切 50 / 100），工具行给刷新与列设置。
   - 筛选：关键词（登录账号 / 用户名称）、登录方式、登录结果。
     **「登录方式」是当页本地过滤**——`/admin/logins` 不收 `action` 参数，分页总数仍报后端口径，与 `UsersTab` 的角色筛选同口径。
   - 列：时间 / 登录账号（`actor_id` 挂 tooltip）/ 登录方式 / 结果 / 来源 IP / 备注（`detail_json.provider` 显示为「渠道：xxx」）。
   - 失败登录（`outcome !== 'ok'`）整行淡琥珀底，便于一眼扫出连续爆破尝试。
     用告警色而非红底：**红绿只属于价格涨跌**（D1），登录失败是运维告警，不该和行情抢同一套色彩记忆。
5. **审计日志 (`AuditTab.vue`)**
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
   - **正文不进列表**：全文在「预览正文」弹窗里读（`width="min(92vw, 560px)"`，正文限高样式写在非 scoped 块，因为弹窗 teleport 到 body）。
     旧版把每条公告的 Markdown 全文摊在卡片里，三条就能拉出两屏；级别也不再用左侧色条标记 —— 那正是全站在清的装饰线。
   - 「发布新公告」并进 `BasicTable` 的 `#toolbarButtons`（`ListToolbar` 的 `create`），**不另起一条 `PageToolbar`**（`features/README.md`：能一条不要两条）。
   - 编辑弹窗 (`AnnouncementEditorDialog.vue`)：`BasicForm`（`:columns="2"`，正文 `fullRow` + `textarea`），级别选项取自 `LEVEL_OPTIONS`（通知 / 警告 / 严重）；
     「编辑 / 预览」是一个 schema 字段，正文与预览靠 `hidden` 互斥，Markdown 实时预览保持原有实现。
   - 渲染安全：通过 `marked` + `dompurify` 净化 Markdown 渲染。
