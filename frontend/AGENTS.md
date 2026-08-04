# 前端 Agent 手册 · 代码规范（Vue 3）

> 上级：[`AGENTS.md`](../AGENTS.md)。编辑 `frontend/**` 时以本文件为准。  
> 借鉴（改编到本仓 Vite + Vue3，非 Nuxt）：  
> - Vue 官方 Composition API / SFC 惯例（`<script setup lang="ts">`、props down / emits up）  
> - 社区 Vue3 AI 规则常见项（禁 Options API、Pinia setup store、composables `use*`）  
> - Feature 分目录思想（类似 Nuxt layers / Vitesse 按功能聚合，映射本仓 `features/<bc>`）

## 1. 技术栈（钉死）

| 项 | 选择 |
|---|---|
| 框架 | Vue 3.5 + Vite 7 |
| 语法 | **仅** `<script setup lang="ts">`，禁止 Options API |
| 状态 | Pinia **setup store**（`defineStore(() => { ... })`），禁止 Vuex |
| 路由 | Vue Router 4；路由表在 `shared/router` |
| UI | **Element Plus 强制**（已全局 `app.use`）；禁止再引入另一套组件库；能 EP 就 EP |
| 代码编辑 | Ops 大段文本用 `features/ops/components/CodeEditor.vue`（Monaco）；勿另引 UI 库 |
| 包管理 | **bun** |
| 别名 | `@/` → `frontend/src/` |

## 2. 目录

```
frontend/src/
  shared/
    api/              # palace.ts / quant.ts — 唯一 HTTP 出口
    components/       # layout | dialogs | charts | ui
    lib/              # 纯格式化/主题/小工具（无账本规则）
    stores/           # 跨页 Pinia
    types/            # 与后端契约
    router/
  features/<bc>/      # ledger | market | review | strategy | ops — 页面与本域小组件
  App.vue · main.ts · style.css
```

- 新页面 → `features/<bc>/XxxView.vue` + 改 router + 侧栏/底栏
- 可复用壳 → `shared/components/...`
- **禁止**再建顶层 `views/` / `components/`（已迁完）

## 3. Vue / TS 代码规范

### 3.1 SFC 结构

顺序固定：

1. `<script setup lang="ts">`
2. `<template>`
3. `<style scoped>`（或依赖全局变量；避免无 scoped 污染）

```vue
<script setup lang="ts">
import { computed, ref } from 'vue'
// ...
</script>

<template>
  <!-- 声明式；复杂分支放到 script 的 computed/函数 -->
</template>

<style scoped>
</style>
```

### 3.2 响应式（Do / Don't）

| Do | Don't |
|---|---|
| 优先 `ref`；大列表/重对象用 `shallowRef` | 滥用深层 `reactive` 再整体替换导致丢代理 |
| 派生用 `computed` | 在 template 里重算昂贵逻辑 |
| 副作用用 `watch` / `watchEffect`，并清理 | 无清理的 `setInterval` / 事件监听 |
| `async/await` | `.then()` 链 |
| props 类型：`defineProps<{...}>()` | 无类型 props / Options API `props:` |

本仓是 **Vite Vue（非 Nuxt）**：**必须显式** `import { ref, computed, ... } from 'vue'`（不要假设 auto-import）。

### 3.3 组件边界（基础）

- **单文件 ≤ 600 行**；触发拆分：≥3 个独立 UI 区块、或「编排 + 大段展示」并存。
- 路由级 View **偏薄**：壳 + 组合子组件；逻辑进 composable 或子组件。
- 数据流：**Props down, Events up**；`defineEmits<{...}>()` 打类型。
- `v-model` 仅用于真正的双向控件契约。
- `provide/inject` 仅主题/稀树依赖；不要当全局事件总线。

### 3.3.1 组件封装：放哪、怎么封

#### 放哪里（「是否进 shared」）

| 放这里 | 条件（需同时满足或明显倾向） |
|---|---|
| `shared/components/ui` | 无业务语义：纯展示/交互原子（`NumText`、`EmptyState`、`StatCard`、`RowActions`） |
| `shared/components/layout` | 壳层：侧栏、页头、底栏、Sheet、LiveTape |
| `shared/components/dialogs` | **≥2 个 feature 会打开**的同一对话框（成交/记一笔/主题…） |
| `shared/components/charts` | 通用图：K 线、Sparkline；不绑单一业务页 |
| `features/<bc>/components` | 只服务该 bc：筛选条、业务表格列、本页 Tab 子块 |
| **不要封装** | 只用一次、且拆开会变成「传 15 个 props 的空壳」→ 留在 View 内局部即可 |

**经验法则**：去掉业务名词（股票、候选、胜率）后组件名仍成立 → 倾向 `shared`；名字必须带「候选池/运维 Job」→ 留在 `features/<bc>`。

#### 封装契约（新组件必须满足）

1. **单一职责**：一个组件只做一件交互或一块展示；禁止「又拉数又画表又弹窗」。
2. **Props 显式类型**：`defineProps<{...}>()`；必要字段用 `required` 语义（类型非可选）；禁止 `props: { data: Object }`。
3. **事件显式类型**：`defineEmits<{ saved: []; cancel: [] }>()`；副作用用事件抛给父级，组件内尽量不直接改 Pinia（对话框「保存成功」可调 API，但刷新列表交给父/`store.load`）。
4. **默认无副作用**：mount 时不要偷偷请求全站数据；需要数据由父注入或父调用 store。
5. **可替换外壳**：能用 Element Plus 基础件就组合，不要包一层无行为的 `div` 只为「好看」。
6. **样式**：优先 CSS 变量；`scoped`；尺寸用现有 spacing，禁止魔法大数字散落。
7. **导出**：需要类型时 `export type { XxxProps }` 或导出事件 payload 类型，供父组件复用。

```vue
<!-- DO：dumb UI，数据进、事件出 -->
<script setup lang="ts">
const props = defineProps<{ title: string; loading?: boolean }>()
const emit = defineEmits<{ refresh: [] }>()
</script>

<!-- DON'T：组件里写死 /api/xxx 又算胜率又改路由 -->
```

#### 与 Element Plus（强制优先，能用就用）

本仓已全局注册 Element Plus。**交互控件禁止手写原生 HTML 冒充组件库**——装 EP 不是摆设。

| 场景 | 必须用 | 禁止 |
|---|---|---|
| 按钮 / 图标按钮 | `el-button`（`type`/`plain`/`link`/`text`/`circle`） | `<button>` 自画样式当主操作 |
| 表格 / 列表数据 | `el-table` / `el-table-v2` + `el-table-column` | `<table class="dense">` 业务表 |
| 表单 | `el-form` + `el-form-item` | 裸 `<form>` + 自拼 label 行当主表单 |
| 文本 / 数字 / 密码 | `el-input` / `el-input-number` | `<input>` / `<textarea>`（文件选择除外） |
| 下拉 / 多选 | `el-select` / `el-checkbox` / `el-radio-group` / `el-switch` | `<select>` / 自绘勾选 |
| 日期 | `el-date-picker` | 自绘日期框 |
| 弹层 | `el-dialog` / `el-drawer` / `ElMessage` / `ElMessageBox` | 自造 modal 遮罩 |
| 标签 / 提示 | `el-tag` / `el-tooltip` / `el-alert` / `el-empty` | 能 EP 却用裸 span 冒充 |
| 分页 / 加载 | `el-pagination` / `v-loading` / `el-skeleton` | 自造页码条 |

**允许保留原生的例外（写进注释说明 why）：**

1. `type="file"` 隐藏文件选择（浏览器能力；可用 `el-upload` 包一层更佳）
2. 无障碍跳转链 `a.skip-link`、纯路由 `RouterLink` 导航项（侧栏/底栏可继续用 link；**工具操作仍用 `el-button`**）
3. 图表容器（ECharts / Lightweight Charts）内部 DOM
4. Monaco `CodeEditor` 编辑区
5. 极薄封装壳（如 `PageTabs`/`SegmentSwitch`）——**内部应优先 `el-segmented` / `el-radio-group` / `el-tabs`，禁止无限期留裸 `<button>`**

**封装规矩：**

- 业务封装 = **组合** `el-table` / `el-form` / `el-dialog`，不是 fork 其源码，也不是外包一层无行为的 `div`。
- 表格列过多时：列定义可抽到同目录 `xxxColumns.ts`，不要把 30 列全堆在 template。
- 样式跟主题：优先 EP 变量 + 本仓 CSS 变量；不要为躲 EP 再写一套 `.dense table` 业务表皮肤。
- 改存量页：看到原生 `button`/`table`/`input`/`select`/`textarea` 且不在例外表 → **同批换成 EP**，不要「先不动」。

### 3.4 Composables

- 命名：`useXxx`；可放 `features/<bc>/composables/` 或确需跨域时 `shared/lib`（谨慎）。
- 返回 **含 ref/computed 的对象**，便于解构仍保持响应（按 Vue 惯例）。
- 副作用在 `onUnmounted` 清理。
- **与 Vue 无关的纯函数** → `shared/lib`，不要硬包成 composable。

### 3.5 Pinia

```ts
// DO — setup store
export const usePalaceStore = defineStore('palace', () => {
  const trades = ref<TradeRecord[]>([])
  async function load() { /* ... */ }
  return { trades, load }
})

// DON'T — Options store / Vuex
```

- 只放跨页共享状态；一次性弹窗本地状态用组件 `ref`。
- Store 内可调 `shared/api`；**禁止**在组件里复制一套盈亏公式。

### 3.6 API 与类型

- 所有请求走 `shared/api/palace.ts` 或 `quant.ts`。
- 类型与后端字段对齐，放 `shared/types/`；改字段必须前后端一起改。
- **禁止**前端自行发明「总资产 / 胜率」口径。

### 3.7 模板与 UI

- 空态：`EmptyState`（原因 + 下一步）。
- 数字：`NumText` / `shared/lib/format`；涨跌色用现有 tone class。
- 样式：CSS 变量（`style.css`）；少写魔法色值。
- 列表 `v-for` 必须稳定 `:key`；慎用 `v-html`。
- 保持 a11y 底线：`skip-link`、主内容 `id`、按钮有文案。

### 3.7.1 视口与内容高度（硬约束）

工作台不是落地页：**禁止文档级（浏览器）滚动条**。出现 `html`/`body` 滚动 = 布局错误。

| 规则 | 做法 |
|---|---|
| 占满主区高度 | 路由页根用 `.page-fill`；壳已 `100dvh` + `overflow: hidden` |
| 内层滚动 | 长内容进 `.page-scroll`，或表体 / `el-table-v2` 自管滚动 |
| PageTabs | 优先放在 `.page-scroll` **外**（固定分区条）；有图/表可吃高度的面板加 `.page-pane`；短文案不要硬撑 Sheet |
| 疏密 | 沿用 `.mb` / `filter-bar` / `page-tabs` 尺度；禁止靠超大 padding/min-height 撑空，也禁止把主内容挤成过窄条 |
| 例外 | `LoginView` / `PeekView` 等非壳内页可自管；弹层滚动在 dialog 内 |

自检：缩小窗口高度后，应只有内层出现滚动；页头 / PageTabs 不随内容滚出视口（除非刻意 sticky 在 scroll 内）。

### 3.8 命名

| 类型 | 约定 | 例 |
|---|---|---|
| 组件文件 | PascalCase | `PoolView.vue` |
| composable | `use` + Pascal | `usePoolFilters.ts` |
| 普通 ts | camelCase | `format.ts` |
| 类型/接口 | PascalCase | `TradeRecord` |

## 4. 反模式表（Agent 自查）

| 反模式 | 改法 |
|---|---|
| Options API / `export default { data() }` | 改 `<script setup lang="ts">` |
| 在 View 里堆 800 行模板+逻辑 | 拆子组件 / composable |
| 组件内 `fetch('/api/...')` 裸调 | 走 `shared/api` |
| 前端重算复盘指标当真相 | 调后端 review/winrate API |
| 新建 `src/views` 旧路径 | 用 `features/<bc>` |
| 引入另一 UI 库「更好看」 | 禁止；用 Element Plus + 现有 token |
| 业务表用 `<table>`、主操作用 `<button>`、主输入用 `<input>` | 换成 `el-table` / `el-button` / `el-input` 等（见 §3.3.1） |
| 为「好看」自绘一套控件皮肤躲过 EP | 用 EP 变体 + CSS 变量微调 |
| Store 里塞仅一页用的临时 flag | 留在组件 |
| 无 key 的 `v-for` | 补稳定 key |
| 一次性业务块硬塞进 `shared/components` | 放 `features/<bc>/components` |
| 封装组件挂载时偷请求全站数据 | props/事件交给父级或显式 `load()` |
| 路由页无 `page-fill`，靠 `page-host`/body 出浏览器滚动条 | 根包 `page-fill`，滚动下沉到 `page-scroll`/表体 |
| PageTabs 把整页撑出视口 | Tabs 固定在 scroll 外；面板用 `page-pane` |
| 大块空白或内容挤成窄条 | 收紧/放开间距到既有 token，用 flex 吃满高度 |

## 5. 命令与自检

```powershell
cd frontend
bun install
bun run dev
bun run typecheck
bun run test
bun run build
# 可选烟雾：bunx playwright install chromium; bun run test:e2e
# 可选试构建：bun run build:rolldown → dist-rolldown/
```

- [ ] `bun run typecheck` 通过
- [ ] 路由 + `AppSidebar` / `MobileBottomNav` 入口一致
- [ ] 无文档级滚动条；路由页用 `page-fill`，滚动在 `page-scroll`/表体内
- [ ] 交互控件已用 Element Plus（按钮/表/表单/输入/选择/弹层）；无新增裸 `<button>`/`<table>`/`<input>` 业务控件（文件选择等例外除外）
- [ ] 无超 600 行新文件；大页有拆分计划或已拆
- [ ] 新 feature 目录有简短 `README.md`（职责一句话即可）
- [ ] K 线重算走 `prepChartOffthread`（Worker）；只读列表优先 Colada，禁止前端造复盘数字
