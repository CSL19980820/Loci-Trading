# 前端手册 · Loci / stock-analyzer（Vue 3）

> **这份文件是导览和经验笔记，不是法规。** 它告诉你这个仓库通常长什么样、哪里踩过坑、
> 怎么验证改动。具体怎么做，按当轮任务和你的判断来；**用户的当轮指令优先于本文件**。
>
> 人类入门见 [`README.md`](README.md)；后端见 [`../src/AGENTS.md`](../src/AGENTS.md)；
> 视觉与密度细节见 [`docs/ui-spec.md`](docs/ui-spec.md)。
> shadcn-vue 的组件层细则见 [`.cursor/skills/shadcn-vue/SKILL.md`](../.cursor/skills/shadcn-vue/SKILL.md)。

## 1. 这是什么

一个**专业行情终端**（信息密度对标通达信 / TradingView / 悟道），不是内容站：
私人工作台（行情 / 策略 / 复盘 / 运维 / AI 助手）+ 策略广场。

前端是 Vite + Vue 3.5 + TypeScript 的单页应用，按限界上下文切 `features/`。

## 2. 技术栈

| 项 | 选择 | 备注 |
|---|---|---|
| 框架 | Vue 3.5 + Vite 7 | |
| 语法 | `<script setup lang="ts">` | |
| 状态 | Pinia setup store | `defineStore(() => {...})` |
| 路由 | Vue Router 4 | 路由表在 `shared/router` |
| UI | **shadcn-vue** | 原语来自 `reka-ui`，源码进仓、可以直接改 |
| 图表 | ECharts 6 | 从 `echarts/core` 按需 `use()` |
| 只读查询 | `@pinia/colada` | `use*Query.ts` |
| 样式 | `style.*.css` 令牌六层 + Tailwind 4 | 语义类映射在 `style.tw-theme.css` |
| 代码编辑 | Monaco | `features/ops/components/CodeEditor.vue` |
| 包管理 | bun | |
| 别名 | `@/` → `frontend/src/` | |

## 3. UI 层：shadcn-vue

组件源码进仓、归我们所有，所以**生成出来的 SFC 直接改就行**——目标是让它服从本仓的
令牌与密度（控件高、圆角、无阴影），而不是让页面对齐 shadcn 的默认尺度。

> **迁移进行中（2026-09）。** shadcn-vue 已就位，但存量页里仍跑着约 2200 处 `<el-*>`。
> **新代码一律写 shadcn 原语**；改造某个页面时，同批把那页的 `el-*` 一并换掉。
> EP → shadcn 的对照表、以及依赖清理的前置条件见
> [`.cursor/skills/shadcn-vue/SKILL.md`](../.cursor/skills/shadcn-vue/SKILL.md)。

```powershell
cd frontend
bunx shadcn-vue@latest add button
bunx shadcn-vue@latest info --json   # 改过 components.json 先跑这个校验落点
```

`components.json` 已就位，别名指向 `src/shared/components/ui`。
**不要跑 `init`**：令牌真值在 `style.base.css` / `style.theme.css`，`init` 会塞一套默认变量
并可能改写 `style.css`。

注册表可以用 `.cursor/mcp.json` 里配的 shadcn MCP 查（只读，不落地文件）；
真正写文件仍走上面的 `bunx ... add`。

### 3.1 三条容易踩的

1. **颜色只写已映射的语义类**——`bg-background` / `text-muted-foreground` / `border-input` /
   `bg-seal` 这类，映射表在 `style.tw-theme.css`。色值真值只在 `style.base.css`（日盘 `:root`）
   与 `style.theme.css`（外观档）。新写 `#hex` 或 `bg-zinc-800` 会让暗色档错版。
2. **删掉生成代码里的 `dark:*` 变体。** 四档外观（`day`/`paper`/`night`/`ink`）是**换 CSS 变量**
   实现的，颜色会整体跟着翻；而 Tailwind 的 `dark:` 在本仓**没有**接线（`style.css` 里没有
   `@custom-variant dark`）。留着它只会跟**操作系统**偏好走——白天档配上系统深色就是错版。
   确实要 `dark:` 的话，先在 `style.css` 里加 `@custom-variant dark` 锚到
   `html[data-appearance='night']` / `ink` / `html.dark`，再跑四档 `taste-audit` 验证。
3. **`Ui*` 原子与生成的原语不要长期并存。** `shared/components/ui/Ui{Button,Card,Badge,Input,
   Skeleton,Separator}.vue` 是早期手写的同职责组件。替换时一次换到位（删 `Ui*`、改引用点、
   跑 typecheck），别留两套按钮。

### 3.2 shadcn 没有对应物、本仓自研的大件

换 UI 底座时这些**保留契约、只换内部实现**，不要顺手拆掉：

| 组件 | 契约 |
|---|---|
| `BasicTable` | 配置化 `columns` + `request`，自管虚拟滚动与分页；业务页的表都走它 |
| `BasicForm` | `schemas` 契约；表单找它，别为单个字段另起一套 |
| `TradeDateRangeField` | 日期区间（shadcn 无现成 daterange） |
| 命令式消息 | 目前走 `shared/lib/confirm.ts`；要 toast 可再评估 shadcn `Sonner` |

## 4. 目录

```
frontend/src/
  shared/
    api/              # palace.ts / quant.ts — 唯一 HTTP 出口
    components/       # layout | dialogs | charts | ui
    lib/              # 纯格式化 / 主题 / 小工具（不含账本规则）
    stores/           # 跨页 Pinia
    types/            # 与后端的契约
    router/
  features/<bc>/      # ai | agents | auth | datasource | ledger | market | ops | research | review | strategy
  App.vue · main.ts · style.css
```

- 新页面 → `features/<bc>/XxxView.vue` + 改 router + 侧栏/底栏入口
- 可复用壳 → `shared/components/...`
- 顶层 `views/` / `components/` 是旧路径，已迁完

## 5. Vue / TS 约定

SFC 顺序：`<script setup lang="ts">` → `<template>` → `<style scoped>`。

本仓是 Vite Vue（非 Nuxt）：**显式** `import { ref, computed } from 'vue'`，别依赖 auto-import。

- 派生值用 `computed`；副作用用 `watch` / `watchEffect` 并在卸载时清理
- 数据流 props down / events up，`defineProps<{...}>()` 与 `defineEmits<{...}>()` 都打类型
- `v-model` 只用于真正的双向控件
- `provide/inject` 只用于主题这类稀树依赖，不当事件总线
- `v-for` 给稳定 `:key`

### 5.1 两个真实踩过的坑（性质相同：清理不对称）

- **监听器注册与移除必须无条件对称。** `BasicTable` 的 resize 曾经在
  `onMounted` / `onUnmounted` 两端各包一层 `if (props.x)`——prop 中途一变就永久泄漏。
  判空放进 handler 自身。
- **长轮询要能取消。** 等待函数（如 `awaitJobResult`）应收 `signal?: AbortSignal`，
  循环头和 sleep 各检查一次，sleep 用 `shared/api/quant_client.ts` 的 `abortableSleep`；
  调用方在 `onUnmounted` 里 `controller.abort()`。裸 `setTimeout` 在组件卸载后照样 resolve，
  曾经最多空转 15 分钟。

## 6. 组件放哪、怎么封

| 放这里 | 条件 |
|---|---|
| `shared/components/ui` | 无业务语义的原子（`EmptyState`、`StatCard`、`RowActions`） |
| `shared/components/layout` | 壳层：侧栏、页头、底栏、Sheet |
| `shared/components/dialogs` | ≥2 个 feature 会打开的同一个对话框 |
| `shared/components/charts` | 通用图：K 线、Sparkline |
| `features/<bc>/components` | 只服务该 bc：筛选条、业务列、本页 Tab 子块 |
| 就地留在 View 里 | 只用一次、拆开会变成「传 15 个 props 的空壳」 |

经验法则：去掉业务名词（股票、候选、胜率）后组件名仍成立 → 倾向 `shared`。

封装时通常：单一职责、props 与 emits 显式类型、挂载时不偷偷请求全站数据、
副作用用事件抛给父级、样式 `scoped` 且走令牌。

## 7. 数据与格式化

- 所有请求走 `shared/api/palace.ts` 或 `quant.ts`，不要在组件里裸 `fetch('/api/...')`
- 类型放 `shared/types/`；改字段前后端一起改
- 数字格式化用 `shared/lib/format` 的 `pct` / `signedPct` / `price` / `money` / `compactNumber`，
  不要在 feature 里另抄一份——此前 `fmtPct` 被抄了 9 份、`fmtPrice` 5 份，精度与正负号口径已经开始分叉
- 复盘 / 胜率这类口径由后端给，前端不自己发明算法

## 8. 布局：不要出文档级滚动条

工作台不是落地页。出现 `html` / `body` 滚动条通常意味着布局写错了：

- 路由页根用 `.page-fill`（壳已 `100dvh` + `overflow: hidden`）
- 长内容进 `.page-scroll`，或让表体自管滚动
- `PageTabs` 建议放在 `.page-scroll` 外，避免随内容滚出视口
- 高度不足时用 `flex: 1 1 auto; min-height: 0` 吃满，而不是写 `min-height: 14rem` 撑空
- 例外：`LoginView` / `PeekView` 这类非壳内页可以自管

## 9. 视觉与密度

**令牌真值只在 [`src/style.base.css`](src/style.base.css)（日盘 `:root`）与
[`src/style.theme.css`](src/style.theme.css)（外观 / 主色档）**，其余地方出现的数值都是副本。
文档与 CSS 不一致时以 CSS 为准——那份值是跑过 `e2e/taste-audit.mjs` 对比度探针校准的。

三条主干（细节见 [`docs/ui-spec.md`](docs/ui-spec.md)）：

1. **红绿留给价格。** `--up` / `--down` 只用于涨跌数字与涨跌语义标记；强调用 `--seal`，
   破坏性操作 `--stamp`，状态色用 `--ok` / `--warn` / `--info`。
2. **页面上最大的字是数字**（`--mono` + `tabular-nums`）；中文标题小而稳（≤20px / 700 / `.03em`）。
3. **密度优先**：表格行高 `--row-h`、表头 `--head-h`、控件 `--ctl-h`、区块间距 `--gap-1..4`。
   业务卡片通常不挂阴影，靠 1px hairline 与底色差分层。

`var()` 一律不写 fallback：`:root` 恒定义的令牌，fallback 永不触发，却是读代码的人唯一能
看到的令牌值，还会互相矛盾；改名那天它会静默生效成错值。只有**故意不定义**的令牌才写。

## 10. 命令与验证

```powershell
cd frontend
bun install
bun run dev
bun run typecheck
bun run test
bun run build
# 可选：bunx playwright install chromium; bun run test:e2e
# 可选试构建：bun run build:rolldown → dist-rolldown/
```

改样式 / 令牌后值得跑一遍观感审计，靠机器量而不是肉眼说「差不多」：

```powershell
bun run build
bunx vite preview --host 127.0.0.1 --port 4174   # 另一个终端
node e2e/runtime-smoke.mjs        # 全路由 + 全 Tab + 弹层真挂：白屏 / pageerror / 空壳弹层
node e2e/taste-audit.mjs          # 切字 / 溢出 / 死白 / 对比度，逐页逐元素量
$env:AUDIT_APPEARANCE="night"; node e2e/taste-audit.mjs   # 四档 day|paper|night|ink 都该干净
node e2e/audit-shots.mjs          # 结构断言 + 截图 → artifacts/audit-*.png
node e2e/admin-shots.mjs          # 管理后台六个分区
node e2e/board-theme-shots.mjs    # 大屏三档不改 <html>
```

### 10.1 排错时先分清「mock 不对」和「产品坏了」

两者报错长得一模一样，照这个顺序走：

1. `node e2e/mock-shapes.mjs` —— 打印每条路由请求了哪些端点、mock 回了什么形状。
   标「空对象」的基本就是崩因。
2. 对照 `src/shared/types/**` 补 `e2e/audit-mocks.mjs`。数组端点要用**尾部精确匹配**：
   `/skills` 用 includes 会把 `/skills/{slug}/job`（对象契约）也吞成数组。
3. 还报错就 `node e2e/resolve-stack.cjs <chunk>.js <行> <列>` 还原压缩栈（需先带 sourcemap 构建）。
4. 确认真是产品 bug 再动产品代码。

两个探针细节：**对比度探针必须用 canvas 解析颜色**（令牌层是 `oklch()`，
`getComputedStyle` 回来的是 `lab(...)`，正则抓数字会把 96.5 当 R 通道还会吃掉负号，
近白底会被算成近黑，曾据此误报 181 处）；本机 `chromium.launch()` 要传 `{ channel: 'chromium' }`，
否则 headless shell 连不上调试端口会 180s 超时。

## 11. 提交前值得过的几项

- `bun run typecheck` 与 `bun run test` 通过
- 路由 + `AppSidebar` / `MobileBottomNav` 入口一致
- 没有文档级滚动条
- 视觉过一遍 `docs/ui-spec.md` §12
- 交互控件用 shadcn-vue 原语 / `BasicTable` / `BasicForm`，没有新增自绘控件
- 新 feature 目录带一句 `README.md`
- 改了 `style.*.css` / 主题令牌 → `taste-audit` 四档干净
- 改了 `manualChunks` / 壳上组件 import → `bun run build` 后用 `bun scripts/dist-stats.mjs dist`
  对比首屏体积没变差
- 新增的监听器 / 定时器 / 轮询都有对称清理或 `AbortSignal` 出口

## 12. 分包经验（`vite.config.ts` 的 `manualChunks`）

`manualChunks` 只给**首屏必然加载**的依赖建组（`vendor-vue` 等）：

1. 纯异步依赖不要建组（`vue-element-plus-x`、`marked`、`dompurify` 这类）。实测 rolldown 会把
   这种组和首屏组合并，反而把 270 KB 助手 UI 拽回首屏。
2. 不要合并 monaco / echarts 的语言与图表模块——它们已按需 import，粗粒度合并会让 CodeEditor
   一次拉全部语言。
3. 只在壳上挂着、多数会话用不到的重组件（如 `AssistantHost`）用
   `defineAsyncComponent(() => import(...))`。
