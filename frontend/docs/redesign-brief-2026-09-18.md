# Loci 前端重构简报 · 2026-09-18

本文是本轮「整体重构 + 移动端适配」的协作契约。多名执行者并行改不同 feature，全部以本文为准。
设计令牌与共享原语（`frontend/src/shared/**`、`frontend/src/style.*.css`、`App.vue`）由主执行者维护；feature 执行者只改自己范围内的 `frontend/src/features/<area>/**`。

## 0. 这不是换皮，是重做

用户原话：「翻天覆地、翻云覆雨，一个页面一个组件都别放过」。旧界面是 Element 时代的「灰边框表格 + 挤满控件的工具条」堆叠。
本轮每个页面都要**重新排版**——不是把旧结构换个颜色：

- 每个路由页顶部用 `PageHeader`：眉题 + 24px 标题 + 一句描述 + 右侧 1–3 个动作。移动端没有侧栏，标题是用户唯一的方位感。
- 关键数字先行：页面上方一排 KPI 卡（`StatCard`，28px 等宽大数 + 趟势 chip），再是内容。
- 内容用 **bento 网格**：不等宽的卡片组合（如 2:1、1:1:1），而不是一张表铺满全屏。表格只是卡片里的一种内容。
- 表格重排：去掉无意义的列，名称列 = 名称（加粗）+ 代码（等宽小字）两行；数字列右对齐等宽；涨跌带符号；行 36px。
- 手机端表格 → **卡片列表**（每行一张卡：名称 + 关键数字 + 一行次要信息 + 可点整卡进详情）。不要让用户在 390px 屏上横滑 8 列。
- 空态用 `EmptyState`（图标 + 一句为什么 + 一句下一步 + 一个动作）。
- 大段说明、口径注释进 tooltip 或折叠，不占版面。
- 深色档同样好看：面板与画布靠 `--surface` / `--surface-canvas` 分层。

参照（直接借鉴其排版）：**Linear**（列表密度、状态点、侧栏）、**Vercel Dashboard**（KPI 卡、页头、下划线 Tab、表格）、**Raycast**（命令面板、设置页）、**shadcn/ui dashboard-01 / blocks**（卡片网格、图表卡）、**Robinhood / 富途牛牛 移动端**（行情列表、涨跌数字排版、底部导航）。

## 1. 设计令牌（只消费 `var(--token)` 或 Tailwind 语义类，不写魔法色值）

定义在 `frontend/src/style.base.css`（day）与 `style.theme.css`（paper / night / ink 覆盖）。Tailwind 4 语义类在 `style.tw-theme.css`。

| 语义 | CSS 变量 | Tailwind 类 |
| --- | --- | --- |
| 画布 / 面板 / 浮层 / 下沉 | `--surface-canvas` `--surface` `--surface-raised` `--surface-sunken` | `bg-canvas` `bg-surface` `bg-raised` `bg-sunken` |
| 悬停 / 按下 | `--surface-hover` `--surface-active` | `bg-hover` `bg-active` |
| 边框 淡 / 默认 / 强 | `--border-subtle` `--border-default` `--border-strong` | `border-line` `border-line-default` `border-line-strong` |
| 文字 主 / 次 / 三级 / 禁用 | `--text-primary` `--text-secondary` `--text-tertiary` `--text-disabled` | `text-ink` `text-ink-2` `text-mist` `text-disabled` |
| 主色 实心 / 悬停 / 文字 / 浅底 / 描边 | `--seal` `--seal-hover` `--seal-ink` `--seal-soft` `--seal-border` | `bg-seal` `text-seal-ink` `bg-seal-soft` `border-seal-border` |
| 涨 / 跌 / 平 | `--up` `--down` `--flat`（+ `-soft` `-ink`） | `text-up` `text-down` `text-flat` `bg-up-soft` `bg-down-soft` |
| 警告 / 信息 / 健康 / 危险 | `--warn` `--info` `--ok` `--stamp`（+ `-soft` `-ink`） | `text-warn` `text-info` `text-ok` `text-stamp` |
| 阴影 | `--shadow-xs` `--shadow-sm` `--shadow-md` `--shadow-lg` | `shadow-xs` `shadow-sm` `shadow-md` `shadow-lg` |
| 圆角 | `--radius-xs` 4 / `--radius-sm` 6 / `--radius` 8 / `--radius-lg` 12 / `--radius-xl` 16 | `rounded-xs` `rounded-sm` `rounded-md` `rounded-lg` `rounded-xl` |
| 字号 | `--fs-kicker` 11 / `--fs-aux` 12 / `--fs-ui` 13 / `--fs-body` 14 / `--fs-title` 15 / `--fs-hero` 20 / `--fs-tape` 24 / `--fs-display` 28 | `text-kicker` `text-aux` `text-ui` `text-body` `text-title` `text-hero` `text-tape` `text-display` |
| 间距 | `--gap-1` 4 / `--gap-2` 8 / `--gap-3` 12 / `--gap-4` 16 / `--gap-5` 20 / `--gap-6` 24 | Tailwind spacing |
| 密度 | `--ctl-h` 32 / `--ctl-h-sm` 28 / `--ctl-h-lg` 36 / `--row-h` 36 / `--row-h-sm` 30 / `--head-h` 34 | — |
| 动效 | `--dur-fast` 150ms / `--dur` 200ms / `--ease` | — |
| 字体 | `--font`（Loci CJK + Inter/Segoe）/ `--mono`（JetBrains Mono / Cascadia） | `font-sans` `font-mono` |

存量别名仍可用（`--paper` `--sheet` `--sheet-alt` `--rule` `--rule-strong` `--ink` `--muted` `--mist`），值已跟随新色阶；新代码优先用语义名。

## 2. 共享组件 API（已实现，直接用）

```ts
// 页头（每个路由页必用）
import PageHeader from '@/shared/components/layout/PageHeader.vue'
<PageHeader title="候选池" eyebrow="我的 · 2026-08-27" description="一句话说明这页看什么"
            :tabs="tabItems" v-model:tab="activeTab" compact sticky seamless>
  <template #actions> <Button size="sm">主操作</Button> </template>
  <template #eyebrow / #title / #description>  <!-- 可选覆盖 -->
  <!-- default slot：页头下方的一行元信息（徽标 / 读数） -->
</PageHeader>

// 工具行（页头下方，透明底；framed 给它一张面板壳）
import PageToolbar from '@/shared/components/layout/PageToolbar.vue'
<PageToolbar note="口径说明" dense framed> 筛选控件 <template #stats>…</template> <template #actions>…</template> </PageToolbar>

// 分区 Tab：variant="underline"（页级，默认） | "pill"（面板内二级）
import PageTabs from '@/shared/components/ui/PageTabs.vue'
<PageTabs v-model="tab" :items="[{ name, label, badge?, disabled? }]" variant="pill" dense :sticky="false" />

// KPI 卡
import StatCard from '@/shared/components/ui/StatCard.vue'
<StatCard label="今日选出" :value="12" :delta="4.2" delta-label="较昨日" hint="口径…" tone="up" layout="stack|row" :loading="busy">
  <template #icon><Target /></template>
  <!-- default slot 覆盖数值；可放 <small>单位</small> -->
</StatCard>
// 栅格：<div class="stat-strip"> 自适应；或 class="stat-strip cols-4"

// 空态
import EmptyState from '@/shared/components/ui/EmptyState.vue'
<EmptyState description="近 5 日无精选" reason="去选股页跑一次战法" :icon="Search" compact> <Button size="sm">去选股</Button> </EmptyState>

// 徽标
import UiBadge from '@/shared/components/ui/UiBadge.vue'
<UiBadge variant="default|secondary|outline|up|down|warn|info|ok|stamp" dot>运行中</UiBadge>
import { Badge } from '@/shared/components/ui/badge'   // variant 同上 + soft/destructive

// 按钮：variant default|outline|secondary|ghost|link|destructive|soft-destructive；size default(32)|sm(28)|xs(24)|lg(36)|icon|icon-sm|icon-xs|icon-lg
import { Button } from '@/shared/components/ui/button'

// 卡片
import { Card, CardHeader, CardTitle, CardDescription, CardAction, CardContent, CardFooter } from '@/shared/components/ui/card'
<Card interactive> <CardHeader class="border-b"><CardTitle>…</CardTitle><CardDescription>…</CardDescription><CardAction>…</CardAction></CardHeader> <CardContent>…</CardContent> </Card>
// 或存量 .sheet / .sheet-bar / .sheet-body 类（已同步新皮肤）

// 对话框 / 抽屉：≤640 自动变贴底 sheet；不要写固定 px 宽，用 class="sm:max-w-2xl"
import { Dialog, DialogContent, DialogHeader, DialogTitle, DialogDescription, DialogFooter } from '@/shared/components/ui/dialog'
<DialogContent class="sm:max-w-xl" fullscreen-mobile>
import { Sheet, SheetContent, SheetHeader, SheetTitle } from '@/shared/components/ui/sheet'   // side="right" 手机自动贴底

// 表格：BasicTable（列定义 prop/label/width/align/formatter/slotName）与 DataGrid 皮肤已更新；
// 手机端首列自动冻结。但优先考虑 ≤640 切成卡片列表（v-if="isMobile"）。
import { useMediaQuery } from '@vueuse/core'
const isMobile = useMediaQuery('(max-width: 640px)')

// 其余原语：Input(size="sm")、Select、Switch、Tabs、Tooltip、DropdownMenu、Popover、Skeleton、Progress、Avatar、Separator、ScrollArea、Command、Alert、Accordion、Collapsible、ToggleGroup —— 都在 '@/shared/components/ui/<name>'
```

## 3. 壳层契约（已由主执行者实现）

- ≥ 981px：左侧 236px 侧栏（可折叠到 60px），主区 `.main-content` 左右 24px 沟槽。
- ≤ 980px：侧栏隐藏，底部毛玻璃 `MobileBottomNav`（56px + safe-area）。壳层已经给 `.app-shell--with-mobile-nav` 预留 padding-bottom，**页面不用再避让**。
- ≤ 640px：主区左右内边距 12px。
- 页面根节点用 `.page-fill`（吃满主区，内部自己滚 `.page-scroll`，区块间距 16px）；不允许文档级滚动条。
- 全局 ⌘K / Ctrl+K 命令面板已存在（跳页面、记候选/预案、切主题）。

## 4. 移动端适配要求（每个页面都要过）

断点：`980px`（平板 / 桌面半屏）与 `640px`（手机）。用 `@media (max-width: 980px)` / `(max-width: 640px)`，或 `useMediaQuery`。

1. **不许横向溢出**：390px 宽下 `document.documentElement.scrollWidth <= clientWidth`；每个 flex 行都要能 wrap 或 overflow-x:auto。
2. **单列布局**：≤640 所有多列栅格退成单列或上下叠；KPI 卡两列。
3. **工具栏**：筛选控件可换行；超过两行的改成「一行主筛选 + 更多筛选进 Sheet」。按钮 ≥ 40px 高。
4. **表格 → 卡片列表**（榜单 / 候选 / 记录类）；大宽表保留表格 + 首列冻结（已由 controls.css 自动处理）。
5. **字号**：正文 ≥ 13px，辅助 ≥ 12px，指标大数 ≥ 22px。
6. **触控**：整卡可点；hover-only 的操作在触控设备上常显或进「⋯」菜单。
7. **弹窗**：已自动贴底；表单弹窗内容可滚、`DialogFooter` 已自动粘底满宽。
8. **图表**：容器 `min-height` ≥ 160px，resize 重绘；手机端图例放图下方或隐藏。
9. 深色档同样验证一张手机截图。

## 5. 工具与验证

开发服务已在 `http://127.0.0.1:5174` 运行（`bun run dev`），**不要再起一个**。后端不在，所有 `/api/**` 由 e2e mock 兜底。

截图（在 `frontend/` 下执行；产物在 `frontend/artifacts/redesign/<tag>/`，用读文件工具直接看 PNG）：

```powershell
node e2e/redesign-shots.mjs <tag>  # 默认全部路由，day+night，1440x900
$env:SHOT_ROUTES='/pool,/winrate'; $env:SHOT_APPEARANCES='day'; node e2e/redesign-shots.mjs pool-v1
$env:SHOT_VIEWPORT='mobile'; node e2e/redesign-shots.mjs pool-m1   # 390x844 触控
$env:SHOT_VIEWPORT='tablet'; ...    # 900x1180
$env:SHOT_FULLPAGE='1'        # 整页截图
Remove-Item Env:SHOT_VIEWPORT, Env:SHOT_FULLPAGE -ErrorAction SilentlyContinue   # 换场景前清掉
```

「重构前」基线截图在 `frontend/artifacts/redesign/before/`，先看一眼自己范围的页面长什么样。

Mock 数据在 `e2e/pulse-mocks.mjs` 与 `e2e/audit-mocks.mjs`。**允许**在 `audit-mocks.mjs` 里为自己的页面补更真实的夹具（按 `src/shared/types/**` 契约），让页面渲染出有内容的状态；**不允许**为了截图改产品代码的取数逻辑。

静态检查与测试（在 `frontend/` 下）：

```powershell
bun run typecheck
bunx vitest run src/features/<area>     # 只跑自己范围的测试
```

改了用户可见行为要同步更新对应 `*.test.ts`；测试断言应围绕用户可见行为（文本、角色、可见性），不要断言内部类名。

## 6. 边界

- 只改 `frontend/src/features/<你的范围>/**`（含其中的 `*.test.ts`、`*.css`）与 `frontend/e2e/audit-mocks.mjs`。
- 不改 `frontend/src/shared/**`、`frontend/src/style.*.css`、`frontend/src/App.vue`、`package.json`、任何后端文件。需要共享层配合的，写进最终报告的「共享层请求」。
- 不改 API 调用、数据处理、业务规则、提示词；只做呈现、布局、交互。
- 保留中文文案与现有可访问性属性（`aria-*`、label 关联、焦点可见）。
- 不新增依赖。图标只用 `@lucide/vue`。

## 7. 交付报告格式

1. 改动文件清单（路径）。
2. 每个页面：桌面做了什么、手机做了什么（各一两句）。
3. 截图路径（桌面 day、手机 day、至少一张 night）。
4. 共享层请求（如有）。
5. 测试：跑了哪些、结果；更新了哪些测试及原因。
6. 未完成 / 需要主执行者决定的问题。
