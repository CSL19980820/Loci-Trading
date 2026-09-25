---
name: shadcn-vue
description: Loci 的 shadcn-vue 源码组件与主题定位参考，按任务选择使用。
---

# shadcn-vue 工作参考

这些信息用于减少重复查找，不限制模型、工具、设计或架构演进。用户当前需求优先于历史偏好，组件生成模板也可以修改。

配置在 `frontend/components.json`；原语在 `frontend/src/shared/components/ui/`；工具函数在 `frontend/src/shared/lib/utils.ts`。
当前采用 Reka UI、Tailwind CSS 4 和 `@lucide/vue`。消息提示由 `vue-sonner` 提供；具体依赖以包清单和锁文件为准。

需要额外原语时可以参考 shadcn-vue 官方文档，或在 `frontend/` 运行 `bunx shadcn-vue@latest add <组件>` 后检查差异。生成器不是唯一实现途径。
主题映射见 `style.tw-theme.css`、`style.theme.css` 和 `shared/lib/theme.ts`；设计建议见 `frontend/docs/ui-spec.md`，无需每次全部读取。

组合组件关注实际业务行为和可访问性。可直接使用原语、保留有效的业务封装，或在收益明确时引入更合适的能力；没有统一的页面模板和强制 retokenize 步骤。
