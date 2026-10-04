# features

当前入口：策略与技能集中于 `/quant`；数据源、定时任务和通知集中于 `/ops`。社区、市场发布和独立纸面舱页面已移除。首页研判用有界摘要接口获取，不遍历智能体完整历史；规则与技能列表独立展示请求结果。退役接口不留空壳，参见 `deploy/SLIMMING.md`。

按后端限界上下文拆分的页面。新增页面放对应 bc 目录并改 shared/router。

## 路由页开篇约定

**路由页不写标题。** 页面身份由侧栏高亮的菜单项交代；在正文顶上再印一遍「候选池」「复盘中心」既不导航也不操作，纯占一整行。
页头只剩三件事——筛选、读数、操作——一律压进页面**本来就有**的那条功能行：

1. 已有 filter-bar / 表格工具栏（`BasicTable` 的 `#toolbarButtons`）→ 合并进去，能一条不要两条；
2. 有 `PageTabs` → 放 `#trailing` 槽；
3. 什么功能行都没有 → 才用 `shared/components/layout/PageToolbar.vue`（`stats` 放 `HeaderStat`，`actions` 放主操作）。

口径说明不占正文行：一律进 `note` / `el-tooltip`，界面上只留一枚 ⓘ。这条功能行放在 `.page-fill` 内、`.page-scroll` / `PageContainer` **之外**，才不会随内容滚走。

内容不足半屏时不要拿占位块填白：`.page-fill` 自带极淡账页衬线，留白会读作「这张账页还没写满」。
