# Loci 前端组件导览

本文帮助定位现有实现，不是组件白名单、设计规则或模型能力边界。可以直接改进组件源码、采用新的组合方式或更换技术；以当前任务和验证结果判断。主题、密度、颜色、布局、说明长度、工具和测试方式都可调整。

相关材料：`../AGENTS.md`、`ui-spec.md`。实现与版本以当前源码、`package.json` 和 `bun.lock` 为准。

## 当前组织

| 层次 | 位置 | 用途 |
| --- | --- | --- |
| 源码原语 | `src/shared/components/ui/<name>/` | shadcn-vue / Reka UI 提供的按钮、输入、对话框、标签页等交互基础；代码属于仓库，可以修改。 |
| 应用组合 | `src/shared/components/ui/app/` | 把原语、主题与常见业务交互组合起来，减少重复实现；不要求所有页面必须使用这一层。 |
| 业务组件 | `src/features/<feature>/components/` | 服务具体业务的视图和交互。 |

主题通过 `style.base.css`、`style.theme.css`、`style.tw-theme.css` 连接到组件。语义令牌有助于保持多外观一致，但局部图表、品牌表达和特殊状态也可以采用专门设计。

## 表单与选择

| 组件 | 当前职责 |
| --- | --- |
| `FormLayout` / `FormField` | 表单模型、校验、标签与错误信息；字段说明的位置与长度按内容安排。 |
| `TextField` / `NumberInput` | 文本、数字输入，以及禁用、清空和模型回写。 |
| `DateField` / `TimeField` / `ColorField` | 日期、时间与颜色选择。 |
| `ChoiceField` / `ChoiceOption` / `ChoiceGroup` | 选项、分组、搜索与单选或多选。 |
| `CascadeChoice` / `TreeChoice` | 层级选择。 |
| `CheckboxField` / `CheckboxChoices` | 勾选与多选组。 |
| `RadioChoices` / `RadioChoice` / `RadioButton` | 单选及分段式单选。 |
| `SegmentedControl` / `ToggleSwitch` | 分区选择与布尔开关。 |

这些组件是可演进的应用接口，不是对其他库的逐字段兼容层。接入时可核对实际 props、事件、禁用状态和键盘行为。

## 弹层、反馈与导航

`DialogPanel` 与 `SidePanel` 组合对话框和侧面板，处理受控开关状态与关闭确认；`PopoverPanel`、`HintTooltip` 用于补充内容。`ActionMenu`、`ActionMenuItems`、`ActionMenuItem` 组合操作菜单。

`Disclosure` / `DisclosurePanel` 提供折叠区域；`TabSet` / `TabPage` 处理页内分区，`PageTabs` 处理路由级分区。`NavMenu` / `NavItem` / `NavGroup` 当前组合 `RouterLink` 与 `Collapsible`；路由链接可保留浏览器的新标签页等原生行为。

消息入口是 `vue-sonner` 的 `toast`；确认入口在 `shared/lib/confirm.ts`，由 `ConfirmHost` 渲染。调用方可区分确认、取消和失败，避免留下未完成的 Promise。

## 表格

`DataGrid` / `DataColumn` 使用 `GridEngine`；表头、列定义、排序与选择来自 TanStack Table，虚拟滚动来自 TanStack Virtual。`Pager` 提供分页组合。

`BasicTable` 与 `BasicForm` 保留已有业务封装，但接口可以演进。普通渲染、分页、虚拟化、冻结列、展开、筛选和排序可以根据真实数据规模选择，不要求所有表格使用同一种模板。

声明式 `DataColumn` 的行类型无法总是从父表自动推导。可结合显式类型参数、类型化列定义或处理函数边界收窄来改进类型精度；当前实现不是未来类型设计的上限。

表格相关 DOM 目前使用 `.data-grid`、`.data-grid__viewport` 和原语的 `data-slot`。自动化优先考虑可访问角色、名称和用户行为；结构选择器只在确实需要检查几何或内部布局时使用。

## 展示与页面组合

`app/presentation.ts` 包含 `Notice`、`StatusBadge`、`EmptyBlock`、`IconBox`、`ContextSeparator`、`ProgressMeter`、骨架、卡片、头像、计数、栅格和详情列表等展示组件。

`PageToolbar`、`PageContainer`、`HeaderStat`、`StatCard`、`EmptyState`、`RowActions`、`StockLink` 与 `PageBusy` 可辅助组织页面。页面是否需要标题、卡片、侧栏或多条工具区，由内容决定。

图表位于 `shared/components/charts/`；编辑器与大型图表可按场景延迟加载。是否继续使用现有库，可根据功能、可访问性、性能、维护成本和迁移验证结果评估。

## 可参考的验证经验

共享控件的变更值得关注模型回写、中文输入法、焦点、清空、取消、异步结果顺序与长内容。直接使用基础 `Tooltip` 时需要合适的 Provider；`HintTooltip` 已包含其上下文。

弹层内容可能传送到 `body`，测试可以查询实际传送节点，或在专注业务逻辑的单元测试中替换面板外壳；真实弹层行为仍适合用组件测试和浏览器测试覆盖。

主题变化可检查不同外观与自定义主色下的可读性。滚动范围、字号、密度、阴影和层级按使用情境设计，不用机械限制代替浏览器观察。

相关验证入口为 `bun run typecheck`、`bun run test`、`bun run build` 与 `bun run test:e2e`。选择能支持本轮结论的检查即可；历史审计与已有测试描述的是当时的实现，不是永久设计禁令。
