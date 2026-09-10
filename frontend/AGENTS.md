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
| UI | **Element Plus 强制**（**按需注册**，见 §1.1）；禁止再引入另一套组件库；能 EP 就 EP |
| UI 例外 | `vue-element-plus-x` 仅限助手层，由 [ADR-006](../docs/adr/ADR-006-assistant-rich-render-and-streaming.md) 决策 4 授权；业务页保持 Element Plus |
| 图表 | ECharts 6（`echarts/core` + 按需 `use()`，勿全量引） |
| 只读查询 | `@pinia/colada`（`use*Query.ts`），只读列表优先走它 |
| 样式 | 本仓 CSS 变量六层体系（`style.*.css`）。Tailwind 4 已装但**只有 `PulseView.vue` 在用**，新代码不要扩大它的使用面 |
| 代码编辑 | Ops 大段文本用 `features/ops/components/CodeEditor.vue`（Monaco）；勿另引 UI 库 |
| 包管理 | **bun** |
| 别名 | `@/` → `frontend/src/` |

### 1.1 Element Plus 按需注册（写模板不用改习惯，写测试要注意）

`main.ts` **不再** `app.use(ElementPlus)`。`shared/plugins/element.ts` 只调
`provideGlobalConfig({ locale: zhCn, size: 'default' }, app, true)`——那正是全量安装里
配置的那一半；组件与指令由 `vite.config.ts` 的
`unplugin-vue-components` + `ElementPlusResolver` 在**模板编译期**逐个 import。

| 场景 | 怎么做 |
|---|---|
| 模板里用 `<el-xxx>` / `v-loading` | **照旧直接写**，不要手动 `import`；resolver 会补 |
| 命令式 `ElMessage` / `ElMessageBox` | 照旧 `import { ElMessage } from 'element-plus'` |
| 测试里 mock `element-plus` | **必须 partial mock**（`importOriginal` 展开 `...actual`），整包替换会让模板里的 `ElDialog`/`ElTabPane` 全变 `undefined` |
| 测试里挂载含 EP 的组件 | 不需要 `global.plugins: [ElementPlus]`；resolver 在 vitest 下同样生效 |
| 新用一个没用过的 EP 组件 | 直接写标签即可；`shared/plugins/elementOnDemand.test.ts` 会校验它在 `element-plus` 里真实存在 |

**CSS 仍是全量**（`element-plus/dist/index.css`）：按需 CSS 省的是 gzip 后约 8 KB，
但漏一个命令式入口的样式就是线上白板，收益/风险不成比例。别改成 `importStyle: 'css'`。

### 1.2 分包（`vite.config.ts` 的 `manualChunks`）

`build.rollupOptions.output.manualChunks` 只给**首屏必然加载**的依赖建组
（`vendor-element-plus`、`vendor-vue`）。三条硬规矩：

1. **不要给纯异步依赖建组**（`vue-element-plus-x`、`marked`/`dompurify` 这类）。
   实测 rolldown 会把这种组和首屏组合并成一个 chunk，反而把 270 KB 助手 UI
   拽回首屏。让它们自然留在各自的异步分片里。
2. **不要合并 monaco / echarts 的语言与图表模块**。它们已经是按需 import 的小分片，
   粗粒度合并会让 CodeEditor 一次拉全部语言。
3. 只在**壳上挂着、但多数会话用不到**的重组件（如 `AssistantHost`）用
   `defineAsyncComponent(() => import(...))`，不要静态 import 进 `App.vue`。

改完 `manualChunks` 或 EP 注册方式，**必须**跑一次 `bun run build` 并对比首屏体积：
`bun scripts/dist-stats.mjs dist`（打印 `index.html` 入口 + modulepreload + stylesheet 的 raw/gzip 合计）。

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
  features/<bc>/      # ai | datasource | ledger | market | marketplace | ops | research | review | strategy
         # ledger 自 2026-08 只剩候选池 / 个股档案 / 登录：持仓与成交已整体下线
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
| 监听器**注册与移除必须无条件对称** | `onMounted` / `onUnmounted` 两端各包一层 `if (props.x)`——prop 中途一变就永久泄漏（真出过：`BasicTable` 的 resize） |
| 长轮询函数必须收 `signal?: AbortSignal`，循环头与 sleep 都检查 | 裸 `await new Promise(r => setTimeout(r, ms))`——组件卸载后它照样 resolve，循环跑满超时上限（真出过：`awaitJobResult` 最多空转 15 分钟） |
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
| `shared/components/ui` | 无业务语义：纯展示/交互原子（`EmptyState`、`StatCard`、`RowActions`） |
| `shared/components/layout` | 壳层：侧栏、页头、底栏、Sheet、LiveTape |
| `shared/components/dialogs` | **≥2 个 feature 会打开**的同一对话框（记一笔/主题…） |
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

Element Plus 已**按需注册**（§1.1，模板照常写 `<el-xxx>`，无需手动 import）。
**交互控件禁止手写原生 HTML 冒充组件库**——装 EP 不是摆设。

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
6. `shared/components/ui/EmptyState.vue` 内部是三个纯文本节点，不再包 `el-empty`——把 el-empty
   收进 96px 要逐条对抗它的插图槽与 40px 留白，收完也只剩这三个节点（见 `docs/ui-spec.md` §7）。
   业务页**仍然禁止**自绘空态：一律用 `EmptyState`（或存量 `el-empty`，已被全局压密）。

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
  const reviews = ref<ReviewRecord[]>([])
  async function load() { /* ... */ }
  return { reviews, load }
})

// DON'T — Options store / Vuex
```

- 只放跨页共享状态；一次性弹窗本地状态用组件 `ref`。
- Store 内可调 `shared/api`；**禁止**在组件里复制一套盈亏公式。

### 3.6 API 与类型

- 所有请求走 `shared/api/palace.ts` 或 `quant.ts`。
- 类型与后端字段对齐，放 `shared/types/`；改字段必须前后端一起改。
- **禁止**前端自行发明「总资产 / 胜率」口径。
- **长轮询/重试要可取消**：任何 `for(;;)` + sleep 的等待函数（如 `awaitJobResult`）
  必须接 `signal?: AbortSignal`，循环头检查一次、sleep 用 `abortableSleep`
  （`shared/api/quant_client.ts`）再检查一次；请求本身把 signal 传进
  `quantRequest(path, { signal })`（`palace.ts` 的 signal 管道已经通了）。
  调用方在 `onUnmounted` 里 `controller.abort()`。

### 3.7 模板与 UI

- 空态：`EmptyState`（为什么空 + 下一步，合计 ≤24 字，整块 ≤96px）。
- 数字：`shared/lib/format` 的 `pct` / `signedPct` / `price` / `money` / `compactNumber`；涨跌色用现有 tone class。**不要在 feature 里另写一份格式化**——此前 `fmtPct` 被手抄了 9 份、`fmtPrice` 5 份，精度和正负号口径已经开始分叉。
- 样式：只用 `style.*.css` 的 CSS 令牌（见 §3.9 与 [`docs/ui-spec.md`](docs/ui-spec.md)）；禁止魔法色值/字号。
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
| 类型/接口 | PascalCase | `ReviewRecord` |

### 3.9 视觉与密度规范（v2 盘口）

产品形态是**专业行情终端**（密度对标通达信 / 同花顺 / 悟道），不是内容站。
完整令牌表、表单/表格/空态/文案规范与禁止清单见 **[`docs/ui-spec.md`](docs/ui-spec.md)**（施工依据）。
三条硬纪律与硬性尺度（下表数值是 `style.base.css` 的副本，**不是**真值）：

> **令牌真值只在 [`src/style.base.css`](src/style.base.css)（日盘 `:root`）与 [`src/style.theme.css`](src/style.theme.css)（外观 / 主色档）。**
> 本节与 `docs/ui-spec.md` 里出现的一切数值都只是**副本**，用于让人一眼知道量级。
> 发现文档与 CSS 不符：**一律以 CSS 为准**，回来改文档，不要照文档去改 CSS
> （CSS 里的值是跑过 `e2e/taste-audit.mjs` 对比度探针校准过的）。
> 也因此 `var()` 一律不写 fallback —— `:root` 恒定义的令牌，fallback 永不触发，
> 却是读代码的人唯一能看到的令牌值，还会互相矛盾；改名那天它会静默生效成错值。
> 只有**故意不定义**的令牌才写 fallback。

| 项 | 硬性要求 | 令牌 / 位置 |
|---|---|---|
| D1 红绿只属于价格 | `--up` / `--down` 只用于涨跌数字与涨跌语义标记；品牌色、按钮、选中态、进度条、tab 下划线、事件点一律不用红绿 | 强调用 `--seal`；破坏性操作用 `--stamp` |
| D2 最大的字是数字 | 数字 `--mono` + `font-variant-numeric: tabular-nums`；中文标题 ≤20px / 700 / `letter-spacing:.03em`，不换字族、禁衬线 | `--fs-tape` 26 / `--fs-hero` 20 / `--fs-title` 16 / `--fs-body` 14 / `--fs-aux` 12 / `--fs-kicker` 11 / `--fs-micro` 10 |
| D3 密度优先 | 表格行高 32px（紧凑档 `--row-h-sm` 28px）、表头 30px、控件 30px、区块间距 8px、圆角 6px（大件 `--radius-lg` 10px）、业务卡片不挂阴影、分隔一律 1px hairline | `--row-h` / `--head-h` / `--ctl-h` / `--gap-1..4`（4/8/12/16）/ `--pad-sheet`（10px 14px）/ `--radius` / `--shadow`（只喂 EP 弹层，业务卡片不用） |
| 令牌唯一真相 | 日盘 `:root` 在 `style.base.css`；夜盘 `night`/`ink`/`html.dark` **同一个选择器列表**在 `style.theme.css`；同一选择器不得在两个 `style.*.css` 里各写一份 | 六层：base → layout → components → content → tail → theme |
| EP 尺寸 | 全局 `size: 'small'`（`shared/plugins/element.ts`），控件高由 `--el-component-size-small` 钉到 `--ctl-h` | 不在页面里逐个传 `size` |
| 表格 | `el-table` / `BasicTable`；数字列 `align="right"`（自动等宽 + tabular-nums），代码列 `class-name="is-code"`，涨跌用 `is-up`/`is-down`/`is-flat`；表格贴 Sheet 边 | 皮肤在 `style.components.css`，SFC 不重写行高与配色 |
| 表单 | `el-form` + `el-form-item`；多列用 `.form-grid`（`auto-fit minmax(260px,1fr)`）；筛选条用 `.filter-bar .filters`（控件同高 `--ctl-h`）；label 宽 `--form-label-w` | 禁止自绘 label 行、禁止局部改 `el-form` 栅格 |
| 文案 | 页面不写介绍段落；解释进 tooltip；`el-alert` 只报当前真实异常、标题 ≤20 字、**禁 `description`**；按钮用动词短语 | 见 `docs/ui-spec.md` §8 |
| 字体 | 不挂 webfont（Google Fonts `<link>` 已从 `index.html` 删除，国内拉不到还阻塞首屏）；`--font-display` 已等于 `--font-sans` | `--font` / `--mono` |
| 无障碍与响应式 | `:focus-visible` 2px `--seal` 轮廓可见；`prefers-reduced-motion` 生效；980px / 640px 不塌、无文档级滚动条 | §3.7.1 |

## 4. 反模式表（Agent 自查）

| 反模式 | 改法 |
|---|---|
| Options API / `export default { data() }` | 改 `<script setup lang="ts">` |
| 在 View 里堆 800 行模板+逻辑 | 拆子组件 / composable |
| 组件内 `fetch('/api/...')` 裸调 | 走 `shared/api` |
| 前端重算复盘指标当真相 | 调后端 review/winrate API |
| 调用已下线的持仓/成交端点（`/dashboard` `/positions` `/trades` `/analytics` `/scorecard` `/cashflows` `/snapshots` `/import/qianlong/*` `/review/{equity,trips,positions,drift}`） | 这些端点 2026-08 已删；前端不留封装、不留空壳 UI |
| 新建 `src/views` 旧路径 | 用 `features/<bc>` |
| 引入另一 UI 库「更好看」 | 禁止；用 Element Plus + 现有 token |
| 业务表用 `<table>`、主操作用 `<button>`、主输入用 `<input>` | 换成 `el-table` / `el-button` / `el-input` 等（见 §3.3.1） |
| 为「好看」自绘一套控件皮肤躲过 EP | 用 EP 变体 + CSS 变量微调 |
| Store 里塞仅一页用的临时 flag | 留在组件 |
| 无 key 的 `v-for` | 补稳定 key |
| 一次性业务块硬塞进 `shared/components` | 放 `features/<bc>/components` |
| 封装组件挂载时偷请求全站数据 | props/事件交给父级或显式 `load()` |
| 路由页无 `page-fill`，靠 `page-host`/body 出浏览器滚动条 | 含 `.page-fill`（根或浅层壳均可；host 用 `:has(.page-fill)`），滚动下沉到 `page-scroll`/表体 |
| PageTabs 把整页撑出视口 | Tabs 固定在 scroll 外；面板用 `page-pane` |
| 大块空白或内容挤成窄条 | 收紧/放开间距到既有 token，用 flex 吃满高度 |
| 监听器只在 `if (props.x)` 成立时注册/移除 | 两端都无条件调用，判空放进 handler 自身 |
| 轮询函数没有 `signal`，或 sleep 用裸 `setTimeout` | 加 `signal?: AbortSignal` + `abortableSleep`，调用方 `onUnmounted` 里 abort |
| 壳上静态 import 一棵多数人用不到的重组件 | `defineAsyncComponent(() => import(...))` |
| 测试里 `vi.mock('element-plus', () => ({ ... }))` 整包替换 | 用 `importOriginal` 展开 `...actual` 再覆盖（EP 已按需注册，见 §1.1） |
| 给纯异步依赖建 `manualChunks` 组 | 只给首屏依赖建组，异步依赖留在自己的分片里（见 §1.2） |
| 大号衬线中文标题（`--font-display` 当衬线用、中文标题 > 18px） | 标题 ≤18px / 700 / `letter-spacing:.03em` / `var(--font)`；最大的字留给数字（§3.9 D2） |
| 品牌色 / 按钮 / 选中态 / 进度条 / tab 下划线用红绿 | 强调一律 `--seal`，破坏性操作 `--stamp`；`--up`/`--down` 只给价格（§3.9 D1） |
| 卡片加 `box-shadow` 或圆角 > 4px 找「精致感」 | `--shadow: none` + `1px solid var(--rule)` + `--radius` 3px（§3.9 D3） |
| 自绘表单行（`div.field-header` + `div.field-controls` + `p.field-hint`） | `el-form-item`（+ `.form-grid` / `.filter-bar`），label 宽走 `--form-label-w` |
| `el-alert` 写 `description` 长说明 / 当常驻说明条 | 只报当前真实异常，`title` ≤20 字；解释进 `el-tooltip` |
| 硬编码颜色 / 字号 / 间距（`#hex`、`px` 字号、裸 `rem` 间距） | 用令牌；确实无法用令牌时必须写注释说明 why（`docs/ui-spec.md` §11.6） |
| 用 `min-height` / 大 `padding` 撑空，或写死 `repeat(N,1fr)` 但内容不足 | `flex:1 1 auto; min-height:0` 吃满；栅格用 `repeat(auto-fit, minmax(…,1fr))` |
| 页面顶部写介绍段落 / 副标题段 | 口径进 `PageHeader` 的 `note`（单行 + tooltip）或 docs；页面只放数据与操作 |
| 空态用大插图 + 三行解释（`el-empty :image-size="120"`） | `EmptyState`：一行主文案 ≤14 字 + 一行下一步，整块 ≤96px |
| 在 SFC 里重写 `el-table` / `el-form` 的行高与配色 | 改 `style.components.css` 全局层一次，别在 32 个页面各调一遍 |

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

**观感自查（改样式/令牌后必跑）** —— 靠机器量，不靠肉眼说「差不多」：

```powershell
cd frontend
bun run build
bunx vite preview --host 127.0.0.1 --port 4174   # 另一个终端
node e2e/runtime-smoke.mjs          # 全路由 + 全 Tab + 弹层真挂一遍：白屏 / pageerror / 空壳弹层
node e2e/audit-shots.mjs     # 结构断言 + 截图 → artifacts/audit-*.png
node e2e/taste-audit.mjs        # 切字 / 溢出 / 死白 / 对比度，逐页逐元素量
$env:AUDIT_APPEARANCE="night"; node e2e/taste-audit.mjs   # 四档外观都要过：day|paper|night|ink
node e2e/admin-shots.mjs      # 管理后台六个分区：中文枚举 / 分页 / 无左竖条 / 未折行 → artifacts/admin-*.png
node e2e/board-theme-shots.mjs   # 大屏在 day/paper/ink 三档都不改 <html>；「暗色」开关只影响本页
```

三个脚本的 mock 走 `e2e/audit-mocks.mjs`（在 `pulse-mocks.mjs` 上补形状；未命中端点回 `{}` 会让页面抛
`xxx.map is not a function`，那是 mock 不对不是产品坏了）。`admin-shots.mjs` 自带 mock（管理后台只依赖
`/api/admin/*` 与 `/api/auth/*`，另起一份比往公共 mock 里塞 admin 夹具更好读）。**对比度探针必须用 canvas
解析颜色**：令牌层是 `oklch()`，`getComputedStyle` 回来的是 `lab(96.5% -.55 -1.79)`，正则抓数字会把 96.5
当 R 通道还吃掉负号，近白底会被算成近黑（曾据此误报 181 处）。

**上线后验收**走 `e2e/verify-admin-live.mjs`：对**刚部署的那个镜像**起一次性容器 + SSH 隧道，不 mock 任何
`/api`，真建号、真登录、真读日志（步骤写在脚本文件头）。它验的是产物而不是源码，且一个字节都不碰生产数据。
**注意本机的 `chromium.launch()` 要传 `{ channel: 'chromium' }`**：headless shell 连不上调试端口会 180s 超时。

**排错顺序**（照着走，别猜）：
1. `node e2e/mock-shapes.mjs` —— 打印每条路由请求了哪些端点、mock 回了什么形状。标「空对象」的基本就是崩因。
2. 对照 `src/shared/types/**` 补 `audit-mocks.mjs` 的形状。**注意数组端点要用尾部精确匹配**：`/skills` 用 includes 会把 `/skills/{slug}/job`（对象契约）也吞成数组。
3. 还报错就 `node e2e/resolve-stack.cjs <chunk>.js <行> <列>` 把压缩栈还原成源码位置（需先 `vite build --sourcemap`）。
4. 确认是产品 bug 再动产品代码。**mock 形状不对和产品坏了报错长得一模一样**，不查清就改代码只会改坏。

**探针的两条豁免**（都有 WCAG 依据，别随手扩大）：`aria-hidden` 的纯装饰字形（分隔点）、
以及失效控件（`disabled` / `aria-disabled` / `.is-disabled`，属 1.4.3 的 Incidental 例外）。

- [ ] `bun run typecheck` 通过
- [ ] 路由 + `AppSidebar` / `MobileBottomNav` 入口一致
- [ ] 无文档级滚动条；路由页用 `page-fill`，滚动在 `page-scroll`/表体内
- [ ] 视觉与密度过 §3.9 与 [`docs/ui-spec.md`](docs/ui-spec.md) §12 自检（红绿只给价格 / 最大的字是数字 / 行高 28px / 无阴影 / 无介绍段落）
- [ ] 交互控件已用 Element Plus（按钮/表/表单/输入/选择/弹层）；无新增裸 `<button>`/`<table>`/`<input>` 业务控件（文件选择等例外除外）
- [ ] 无超 600 行新文件；大页有拆分计划或已拆
- [ ] 新 feature 目录有简短 `README.md`（职责一句话即可）
- [ ] K 线重算走 `prepChartOffthread`（Worker）；只读列表优先 Colada，禁止前端造复盘数字
- [ ] `bun run test` 通过
- [ ] 动了 `manualChunks` / EP 注册方式 / 壳上组件 import：`bun run build` 通过，并用 `bun scripts/dist-stats.mjs dist` 对比首屏体积没变差
- [ ] 动了 `style.*.css` / 主题令牌：`node e2e/taste-audit.mjs` 在 **day / paper / night / ink 四档都「全部干净」**
- [ ] 主色只在**填充**上用 `--seal`；当**文字**用一律 `--seal-ink`（深色档 `--seal` 当文字只有 2.5–3.3:1）
- [ ] 次要文字用 `--text-tertiary` / `--mist`：它们已按「最暗承载面上仍 ≥4.5:1」校准，别再就地调浅
- [ ] 新增/改动弹层组件：`node e2e/runtime-smoke.mjs` 全绿；点不开的弹层补一条 `dialogMount.test.ts` 式的挂载用例
- [ ] 新增的事件监听器、定时器、轮询循环都有对称清理 / `AbortSignal` 出口
