# 全站 Tailwind / shadcn-vue组件映射

> `frontend/src/style.tw-theme.css` 把现有六层令牌映射为 shadcn语义 token；不引入第二套颜色真相。
> Element Plus继续承担复杂业务控件，shadcn 原语承担外层构造与视觉一致性。

|现有场景 |统一构造 |允许保留 |
|---|---|---|
| 区块/卡片/统计卡 | `UiCard` + `UiCardHeader` + `UiCardTitle` + `UiCardContent` + `UiCardFooter` | `Sheet`兼容存量页 |
| 标签/状态/数量 | `UiBadge` | `el-tag`复杂状态 |
| 表单行 | `UiField` + EP 控件 | `el-form` 校验、日期、树选择、级联 |
| 主按钮/行按钮 | `UiButton`变体 | `el-button` 命令式、图标、loading |
| 空态 | `EmptyState` | 助手/大屏专用空态 |
| 分隔/加载 | `UiSeparator` / `UiSkeleton` | ECharts/Monaco loading |
| Tabs /侧栏 | Tailwind 布局 + `PageTabs` / EP `el-menu` | 键盘导航和路由行为 |
| 表格 | `BasicTable`统一入口 | EP `el-table` / `el-table-v2` 的虚拟化与复杂展示 |
| 弹层 | EP `el-dialog` / `el-drawer`，统一 token 与内滚 | focus trap、teleport、业务契约 |
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
5.复杂 EP 控件不强行替换；替换仅发生在外层构造与轻量原子。
