# features

按后端限界上下文拆分的页面。新增页面放对应 bc 目录并改 shared/router。

## 路由页开篇约定

新路由页用 `shared/components/layout/PageHeader.vue` 起头：衬线标题 + 一句口径 `note`（讲清数字从哪来、是否只读）+ `stats` 槽放 `HeaderStat` 读数 + `actions` 槽放主操作。
页头要放在 `.page-fill` 内、`.page-scroll` / `PageContainer` **之外**，才不会随内容滚走。

已有自有顶栏的页面（盘面的 tape 条、策稿的编辑器工具条、档案的身份行）不强制换成 PageHeader，但标题字要走 `--font-display` 与 `--fs-hero` 字阶，保持同一套开篇语言。

内容不足半屏时不要拿占位块填白：`.page-fill` 自带极淡账页衬线，留白会读作「这张账页还没写满」。
