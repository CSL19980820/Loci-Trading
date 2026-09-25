# Shared UI · 组件导览

这里记录当前可复用实现与接口，帮助定位代码，不规定唯一的页面结构。设计建议见 `frontend/docs/ui-spec.md`。

## 组件地图

原语目录（`button/`、`dialog/`、`sheet/`、`table/`、`tabs/`、`command/` 等）使用可编辑的 shadcn-vue / Reka 源码。`app/` 是面向项目的组合控件（表单字段、DataGrid、Pager、DialogPanel / SidePanel 等）。

页面级组合：

- `layout/PageHeader`：眉题 + 24px 标题 + 描述 + 动作，可挂下划线 Tab（`:tabs` / `v-model:tab`）；`compact` / `sticky` / `seamless`。
- `layout/PageToolbar`：筛选 / 读数 / 操作三槽的透明工具行；`framed` 装进面板壳；≤640 三段各自成行、操作可横滑。
- `layout/CommandPalette`：⌘K 命令面板（页面、操作、外观），状态在 `shared/lib/commandPalette.ts`。
- `PageTabs`：`variant="underline"`（页级）或 `"pill"`（面板内二级）；`dense`、`sticky`、`badge`。
- `StatCard`：KPI 卡（label / value / delta / deltaLabel / hint / tone / layout / loading）；配合 `.stat-strip` 栅格。
- `EmptyState`：图标 + 一句为什么 + 一句下一步 + 动作；`compact` 给表格与小面板。
- `UiBadge` / `badge/Badge`：药片徽标，`dot` 带状态点；涨跌变体等宽 tabular。
- `HeaderStat`：工具行内的「标签 + 等宽数字」读数。
- `SegmentSwitch`：药片分段切换（`size="sm|default"`）。
- `RowActions`：行内文字按钮 + `⋯` 更多菜单。
- `PageBusy`：行内或 overlay 加载态。

## 弹层与移动端

`dialog/DialogContent`、`sheet/SheetContent`、`drawer/DrawerContent` 在 ≤640px 自动变为贴底 sheet（满宽、上圆角、可滚、带拖拽指示条）；`DialogFooter` 在手机端粘底、按钮满宽。不要给弹窗写固定 px 宽度，用 `class="sm:max-w-*"`；`DialogContent` 的 `fullscreen-mobile` 让手机端铺满。
`app/DialogPanel` 与 `app/SidePanel` 通过 `--dialog-panel-w` / `--side-panel-w` 变量设桌面宽度，手机端由 `style.controls.css` 覆盖为满宽。

## BasicForm

`schemas` 描述字段；`v-model` 同步值；`columns`、`labelPosition`、`labelWidth`、`inline` 和 `disabled` 控制展示。
字段可通过 `componentProps.options` 或 `request` 获取选项，也可以使用 `slotName` / `render` 自定义。
`rules` 使用 async-validator。`hint`、`tooltip` 和 `fullRow` 是当前展示接口。

常用方法：`submit`、`getFieldsValue`、`setFieldsValue`、`resetForm`、`setProps`、`getFormRef`、`getFieldRef`。
`submit` 先提交防抖草稿再校验；未通过时返回 `false`，错误显示在对应字段。
`basicFormEqual` 比较结构，避免数组或对象在父子同步时因引用更新造成循环。

## BasicTable

`request(params)` 返回 `{ list, total }` 时由组件加载和分页；`dataSource` 搭配 `pagination` 对象时由外部控页。
`pagination=false` 展示完整数据；`virtualized` 在适合的列表上减少实际渲染行数（判据见 `basicTableVirtualSupport.ts`）。

列支持 `prop`、`label`、`width` / `minWidth`、`align`、`children`、`formatter`、`render`、`slotName`、筛选与固定列。
选择、排序、行内编辑、合并单元格和自定义空态仍由相应接口控制。
皮肤在 `style.controls.css` 的 `.data-grid`：表头 12px 三级色下沉底、行 36px、hairline 分隔、悬停抬底；≤640 首列自动冻结。榜单 / 记录类列表在手机端优先改成卡片列表（`useMediaQuery('(max-width: 640px)')`）。

常用方法：`fetch`、`reloadTable`、`restReload`、`setPagination`、`getTableData`、`doLayout`、`setEditRow`、`clearEdit`、`getRowEdit`、`isEditByRow`、`clearSelection`、`getTableRef`。

## 主题与验证

令牌在 `style.base.css` / `style.theme.css`，Tailwind 语义类在 `style.tw-theme.css`；组合控件默认外观在 `style.controls.css`。
弹层会传送到页面根节点，专属样式和变量应考虑这一点。
可按改动选择表单草稿、校验、表格选择与排序、弹窗焦点、日期范围、窄屏和长内容测试；测试关注行为和可访问性，而不是锁定某个库的内部 DOM。
