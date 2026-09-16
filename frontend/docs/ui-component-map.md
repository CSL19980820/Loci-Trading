# 全站 Tailwind / shadcn-vue组件映射

> `frontend/src/style.tw-theme.css` 把现有六层令牌映射为 shadcn 语义 token；不引入第二套颜色真相。
> **目标栈是 shadcn-vue**（原语来自 `reka-ui`）；Element Plus 是**存量**：冻结不再新增，
> 存量页改造时同批换掉。政策与清理时机见 [`../AGENTS.md`](../AGENTS.md) §1.1 / §1.2。

| 现有场景 | 统一构造 | 允许保留（存量，改造时同批换掉） |
|---|---|---|
| 区块/卡片/统计卡 | `UiCard` + `UiCardHeader` + `UiCardTitle` + `UiCardContent` + `UiCardFooter` | `Sheet` 兼容存量页 |
| 标签/状态/数量 | `UiBadge` / shadcn `Badge` | 存量 `el-tag` |
| 表单行 | `BasicForm` 契约（见 `shared/components/ui/README.md`） | 存量 `el-form` 校验、日期、树选择、级联 |
| 主按钮/行按钮 | shadcn `Button` 变体（尺度对齐 `UiButton`） | 存量 `el-button`、命令式入口 |
| 空态 | `EmptyState` | 助手/大屏专用空态 |
| 分隔/加载 | `UiSeparator` / `UiSkeleton` | ECharts/Monaco loading |
| Tabs / 侧栏 | Tailwind 布局 + `PageTabs` / `SegmentSwitch` | 存量 `el-menu` / `el-tabs` 的路由行为 |
| 表格 | `BasicTable` 统一入口（**接口不动，内部换皮**） | 存量 `el-table` / `el-table-v2` 的虚拟化与复杂展示 |
| 弹层 | shadcn `Dialog` / `Sheet`（footer 契约见 `ui-spec.md` §8） | 存量 `el-dialog` / `el-drawer` 的 teleport 与业务契约 |
| 图表/编辑器 | 原有 ECharts / Monaco | 不用 UI 框架包裹内部绘图区 |

## 页面族

- 市场/大屏：数据优先，`PageToolbar` + `UiCard`，表格/图表内部滚动。
- 候选/复盘/体检：`UiCard` 分组 + `BasicTable`，空态同一契约。
- 工坊/研究：左 rail + 主面板，`min-h-0` 高度链，表单用 `UiField`。
- 运维/管理/账号：设置面板统一 Card头/脚，弹层正文独立滚动。
- 助手/数据源：专用高密度内容壳保留，外部间距和状态标记走 Tailwind语义类。

## 硬验收

1.任何路由根：`page-fill` 或等价 `flex min-h-0 flex-1`。
2.任何长内容：`.page-scroll` / `overflow-auto`，禁止 `body` 滚动。
3.任何 overlay：父定位 +令牌层级；dialog 正文有 `max-height` 与 `overflow:auto`。
4. `--up/--down`只用于价格语义；健康/告警用 `--ok/--warn`。
5.存量 `el-*` 冻结、不再新增；改造某页时同批换成 shadcn-vue 原语，依赖清理时机见 `AGENTS.md` §1.2。
