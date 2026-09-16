# Loci 前端视觉与密度参考 · v2「盘口」

> **这份文件是参考资料，不是审批清单。** 它记录这套界面当初为什么长成这样、令牌有哪些、
> 哪些做法在实测里出过问题。具体怎么落，按当轮任务和你的判断来——**用户的当轮指令优先于本文件**。
>
> 上级：[`frontend/AGENTS.md`](../AGENTS.md)。组件落点与 shadcn-vue 用法见
> [`.cursor/skills/shadcn-vue/SKILL.md`](../../.cursor/skills/shadcn-vue/SKILL.md)。
>
> **令牌真值只在 [`src/style.base.css`](../src/style.base.css)（日盘 `:root`）与
> [`src/style.theme.css`](../src/style.theme.css)（外观 / 主色档）。** 本文件里出现的所有数值
> 都只是**副本**，用于让人一眼知道量级。发现文档与 CSS 不符：以 CSS 为准，回来改这份文档——
> CSS 里的值是跑过 `e2e/taste-audit.mjs` 对比度探针校准过的。
>
> 产品定位：**专业行情终端**（信息密度对标 TradingView / Bloomberg / 通达信）。
> 视觉语言是 shadcn zinc + 金融终端 hairline。
> 「奶白纸 + 大号衬线中文标题 + 印章红」的书卷风已于 2026-08 退场。

## 目录

- [1. 三条主干](#1-三条主干)
- [2. 令牌](#2-令牌)
- [3. 排版](#3-排版)
- [4. 密度与间距](#4-密度与间距)
- [5. 表格](#5-表格)
- [6. 表单](#6-表单)
- [7. 空态](#7-空态)
- [8. 文案](#8-文案)
- [9. 壳层组件](#9-壳层组件)
- [10. 颜色语义速查](#10-颜色语义速查)
- [11. 容易出问题的地方](#11-容易出问题的地方)
- [12. 改完可以看一眼](#12-改完可以看一眼)

---

## 1. 三条主干

这套视觉只有三条主干。它们最初是为了解决三个具体问题，理解「为什么」比记住规则有用。

### D1 红绿只属于价格

`--up` / `--down`（含 `-soft` / `-ink` 变体）留给：涨跌数字、涨跌箭头 / 标记、买卖方向标、
K 线与量柱。

原因很直接：A 股界面里红绿是**强语义**的。如果「成功提示」也是绿的、「主按钮」也是红的，
屏幕上就再没有颜色能干净地表示涨跌了。所以强调色走 `--seal`（品牌朱红）、状态走
`--ok` / `--warn` / `--info`、破坏性操作走 `--stamp`（印章红）。

`--stamp` 与 `--up` 是两个不同的红：「删除」和「涨」不该长一样。

```css
/* 直观 */
.pct-cell { color: var(--up); }                       /* 涨跌数字 */
.progress__fill { background: var(--seal); }          /* 主色，不是涨色 */

/* 会让颜色失去意义的用法 */
.tab.is-active { border-color: var(--up); }           /* 选中态偷用涨色 */
.badge-ok { background: var(--down-soft); }           /* 「成功」不是「跌」 */
```

### D2 页面上最大的字是数字

数字用 `--mono` + `font-variant-numeric: tabular-nums`——不加等宽的话，
行情刷新时数字会左右横跳，读数体验很差。

中文标题保持小而稳：≤20px / 700 / `letter-spacing: .03em`，不换字族、不用衬线。
关键报价用 `--fs-tape`（26px）或工具类 `.tape-num`；页内最大的中文标题用 `--fs-hero`（20px）。

```css
.quote      { font: 700 var(--fs-tape) / 1.05 var(--mono); font-variant-numeric: tabular-nums; }
.page-title { font: 700 var(--fs-hero) / 1.2 var(--font); letter-spacing: .03em; }
```

> `--font-display` 现在就是 `--font-sans`，留着只为不炸存量引用；新代码直接写 `var(--font)`。

### D3 密度优先

每屏能看多少行，是这个产品最重要的体验指标之一。

| 项 | 值 | 令牌 |
|---|---|---|
| 表格行高 | 32px（紧凑档 28px） | `--row-h` / `--row-h-sm` |
| 表头高 | 30px | `--head-h` |
| 控件高 | 30px | `--ctl-h` |
| 区块间距 | 8px | `--gap-2` |
| Sheet 内边距 | 10px 14px | `--pad-sheet` |
| 圆角 | 6px（小件 4px / 大件 10px / 整卡 14px） | `--radius` / `--radius-sm` / `--radius-lg` / `--radius-xl` |
| 阴影 | 业务卡片不挂 | `--shadow` 只留给弹层 |
| 分隔线 | 1px hairline | `1px solid var(--rule)`（更淡一档 `--rule-soft`） |

成片 >16px 的空白通常是内容没排满的信号：写死的 `min-height`、大 `padding`、
内容不足却写死列数（`repeat(3, 1fr)`）都会造成这种观感。可用 `repeat(auto-fit, minmax(…,1fr))`
让列数跟着宽度走。

---

## 2. 令牌

### 2.1 日盘（`:root`，`style.base.css`）

| 令牌 | 定义 | 用途 |
|---|---|---|
| `--paper` | `var(--surface-canvas)`（色阶 3） | 页面底色（`.page-fill` / 主区） |
| `--sheet` | `rgba(252,253,254,.94)` | 区块底色（Sheet / 页头 / 表体） |
| `--sheet-alt` | `var(--surface-sunken)`（色阶 4） | 表头、斑马行、次级底 |
| `--rule` / `--rule-strong` | `#cdd1d8` / `#bac0c7` | 1px 分隔线 / 边框强调 |
| `--rule-soft` | 色阶 7 @55% | 行级 hairline，密表里不至于变成栅格纸 |
| `--ink` / `--muted` / `--mist` | `#192029` / `#4d5560` / `#626a73` | 正文数字 / 次要文字 / 弱文字与口径 |
| `--seal` | `#cc323e` 朱红（随 `data-primary` 切换，见 §2.6） | 品牌主色 |
| `--on-primary` | `#ffffff`（`shared/lib/theme.ts` 按 OKLCH 亮度阈值 0.62 决定黑白） | 压在实心主色上的文字色 |
| `--seal-ink` / `--seal-soft` | 由 `--seal` 用 `color-mix(in oklab)` 派生 | 主色文字态 / 主色浅底 |
| `--stamp` | `oklch(.53 .19 20)` | 印章红：logo、登录印记、破坏性操作 |
| `--up` / `--up-soft` / `--up-ink` | `#c8282a` / 本色 @10% / `oklch(.465 .17 26)` | 涨 |
| `--down` / `--down-soft` / `--down-ink` | `#00793a` / 本色 @10% / `oklch(.45 .115 152)` | 跌 |
| `--up-1..5` / `--down-1..5` | OKLCH 等距 5 档，5 = 本色 | 分布条 / 热力 / 筹码分布 |
| `--flat` | 色阶 10 | 平盘 / 停牌 |
| `--warn` / `--info` | `#a05e00` / `#1174b4`（各带 `-soft` / `-ink`） | 警告 / 信息 |
| `--ok` / `--ok-soft` | `#007c7c`（青绿 hue 195） | **非价格语义**的健康 / 成功色——绿被 D1 占给了「跌」，状态色得离开纯绿 |
| `--radius*` / `--shadow` | 见 §1 D3 | 形状 |

> 表面 / 边框 / 文字另有一层语义档，全建在 12 阶中性色阶 `--n-1..12` 上：
> `--surface-raised|surface|surface-canvas|surface-sunken|surface-hover|surface-active`、
> `--border-subtle|border-default|border-strong`、`--text-primary|secondary|tertiary|disabled`。
>
> **交互底（hover / 选中）用 `--surface-hover` / `--surface-active`**，别手写 `rgba(…, .04)`
> ——那种写法在夜盘两档上肉眼不可见，等于没有 hover 反馈。
>
> `--stamp` 没有 `-ink` / `-soft` 变体：它只做前景色或小面积底块。压在它上面的文字写 `#fff`
> 是规范值（它固定印章红、不随 `data-primary`），但值得留一句 why 注释。

### 2.2 其余三档外观（`style.theme.css`）

四档外观：`day`（缺省 `:root`，shadcn zinc）/ `paper` 暖纸 / `night` TradingView 炭黑 / `ink` 中性纯黑。
**每档只改中性色阶 `--n-1..12` 与少数「sRGB 兑现」键**，语义层建在色阶上自动跟随。

| 档 | 选择器 | 改了什么 |
|---|---|---|
| 暖纸 | `html[data-appearance='paper']` | 色阶换暖调 hue 80；`--sheet` `rgba(255,250,239,.94)`；涨跌不动 |
| 夜盘公共层 | `html[data-appearance='night'], html[data-appearance='ink'], html.dark` | `color-scheme: dark`；涨跌提亮；阴影更重更散 |
| 夜间 | `html[data-appearance='night'], html.dark` | 色阶换 TV 炭黑 hue 264；`--sheet` `rgba(23,27,33,.92)` |
| 墨黑 | `html[data-appearance='ink']` | 色阶 chroma 全 0；涨跌再提一档 |

夜盘那三个选择器**写在同一个选择器列表里**——历史上分开写时，改前面那份会被后面静默覆盖。

### 2.3 字体与字阶

```
--font-sans / --font   Loci CJK + -apple-system / BlinkMacSystemFont / Segoe UI / Roboto
--mono / --font-mono   JetBrains Mono / SF Mono / Roboto Mono / Consolas / Menlo
--font-display         = --font-sans（历史别名）
--font-serif    宋体族；当前无消费方
```

**不挂 webfont**：`index.html` 的 Google Fonts `<link>` 与 `preconnect` 已删——国内网络基本
拉不到，实际渲染一直是系统字，等于设计从未生效，还阻塞首屏。
`Loci CJK` 是 `local()` + `unicode-range` 的简体钉，不是网络字体。

| 令牌 | 值 | 用在哪 |
|---|---|---|
| `--fs-tape` | 26px | 指数 / 关键报价，等宽（`.tape-num`） |
| `--fs-hero` | 20px | 页内最大的中文标题、`HeaderStat` lead 档、`StatCard` 读数 |
| `--fs-title` | 16px | 区块标题（`.sheet-bar h2`、弹窗标题） |
| `--fs-body` | 14px | 正文 / 表格 / 控件 |
| `--fs-aux` | 12px | 辅助、口径、表头、`.code` |
| `--fs-kicker` | 11px | 微标：大写 + `letter-spacing:.14em` + `--mono`（`.kicker`） |
| `--fs-micro` | 10px | 移动底栏标签一类极小标注 |

### 2.4 密度令牌

```
--row-h 32px   --row-h-sm 28px   --head-h 30px   --ctl-h 30px
--gap-1 4px    --gap-2 8px    --gap-3 12px  --gap-4 16px
--pad-page-x 12px      --pad-sheet 10px 14px（另拆 -y / -x 供负 margin 贴边）
--form-label-w 7em
```

### 2.5 legacy 别名（保留）

`--bg` `--panel` `--panel-2` `--line` `--line-2` `--text` `--dim` `--accent` `--accent-soft`
`--accent-text` `--blue` `--lake` `--lake-soft` `--success` `--loss` —— 全部指向新值。
存量页仍在引用，删了会整仓塌；新代码直接写语义令牌。

### 2.6 主色八档（`data-primary`）

只换 `--seal` 与 `--on-primary`，其余派生档由 `--seal` 混出：
`seal #cc323e` 朱红（缺省）/ `flame #c15108` / `amber #d79700` / `moss #298646` /
`lake #008471` / `teal #007ca8` / `blue #396ed6` / `violet #854ece`。

`amber` 的 L≈0.72，白字在它上面必然不够，所以该档 `--on-primary` 反转成深字 `#14181f`，
深色档再把主色提亮到 `#ebaa2d`。自定义主色同理由 `shared/lib/theme.ts` 按 L>0.62 决定黑白。

压在实心主色上的文字用 `var(--on-primary)` 而不是写死 `#fff`，才跟得上主色切换。
`--up` 绝不等于 `--seal`——涨跌色不跟随 `data-primary`，这是 D1 的实现保证。

---

## 3. 排版

| 层级 | 规格 | 说明 |
|---|---|---|
| 页标题 | 20px / 700 / `.03em` / sans | `--fs-hero`；路由页正文顶上不再印页面名 |
| 区块标题 | 16px / 700 / `.03em` | `--fs-title`；`.sheet-bar h2` |
| 正文、表格 | 14px / 400 / 行高 1.45 | `--fs-body`，`body` 已是这个档 |
| 口径、表头、meta | 12px / `--mist` | `--fs-aux`；表头再加 600 字重 |
| 微标 | 11px / 大写 / `.14em` / mono | `--fs-kicker`，只用于标签 |
| 数字 | mono + `tabular-nums` | 任何位数会变的数字都该加 |

中文不做斜体、不做 `text-transform`（只有拉丁微标可以大写）。
行内代码 / 股票代码用 `.code`（12px mono，`letter-spacing:.02em`）。

---

## 4. 密度与间距

- 页面骨架：`.page-fill` → 可选 `PageToolbar`（顶部唯一功能行）→ 可选 `PageTabs`
  → `.page-scroll`（`gap: --gap-2`，`padding: --gap-2`）或表体自滚。
  沟槽由 `--pad-page-x` 统一给。
- 区块之间用 `--gap-2`；区块内部行距 `--gap-1`；两栏栅格 `--gap-2`。
- `.page-fill` 的「账页衬线」背景纹已删除：**空白就是空白**。正确的修法是把内容排满或
  缩小区块，而不是画格子把空白伪装成留白。
- 层级靠 `1px solid var(--rule)` + `--sheet` / `--sheet-alt` 的底色差表达，不靠阴影。
- 高度不足时用 `flex: 1 1 auto; min-height: 0` 吃满。

---

## 5. 表格

表皮肤在 `style.components.css` 与 `BasicTable.vue` 的作用域补充里。
**新表走 `BasicTable`**——它的 `columns` / `request` 契约是资产，换 UI 底座时保留契约、
只换内部实现，不要在迁移中顺手拆掉。

| 项 | 规格 |
|---|---|
| 行高 | `--row-h` 32px，单元格竖向 padding `--gap-1` |
| 表头 | 高 `--head-h` 30px，底色 `--sheet-alt`，`--fs-aux` / 600 / `--muted` |
| 单元格水平 padding | `--gap-2` |
| hover 行 | `--seal-soft`（不是灰） |
| 斑马行 | `--sheet-alt`（默认关，长表再开） |
| 外框 | 无阴影；表格贴 Sheet 边 |
| 数字列 | `align="right"` → 自动 mono + `tabular-nums` |
| 代码列 | `class-name="is-code"` → mono + `.02em` |
| 涨跌 | `is-up` / `is-down` / `is-flat` |
| 空表 | 一句话（≤14 字），空块铺满表体并居中 |

在 SFC 里另写一套行高 / 边框 / 表头色的代价是：以后要调密度得改几十个文件，
所以这类改动更适合落在全局层一次。

---

## 6. 表单

表单走 `BasicForm`（契约见 [`../src/shared/components/ui/README.md`](../src/shared/components/ui/README.md)）。
下面这些数值是要保住的不变量——换实现时按它们对齐，不必照抄旧类名：

- 字段间距 `--gap-2`
- 块级表单 label 宽 `--form-label-w`（7em）、右对齐、行高 `--ctl-h`、色 `--muted`
- `label-position="top"` 与 inline 表单不套定宽
- 980px 以下 label 转左对齐自适应，输入框不被挤成缝

### 6.1 多列表单：`.form-grid`

```vue
<BasicForm :schemas="schemas" class="form-grid" />
```

`.form-grid` = `repeat(auto-fit, minmax(260px, 1fr))`：列数随宽度自适应，
label 宽度全表一致，换行不错位。整行字段加 `.full-span`。

### 6.2 筛选条：`.filter-bar`

```vue
<Sheet class="filter-bar" plain>
  <div class="filters">
    <Input v-model="kw" placeholder="代码 / 名称" class="w-[180px]" />
    <Select v-model="decision" placeholder="决策" />
    <Button variant="default" @click="reload">筛选</Button>
  </div>
</Sheet>
```

`.filter-bar .filters` 自动 flex + `align-items: center` + 控件高度统一 `--ctl-h`，
换行后两行控件左缘对齐。inline 的 label 不定宽（12px `--mist`）。

### 6.3 自绘表单行

`<div class="field-header">` + `<div class="field-controls">` + `<p class="field-hint">`
这种自绘三件套，换成 `BasicForm` 的字段通常更好维护（错误行、必填星号、label 对齐都有人管）。

---

## 7. 空态

用 `shared/components/ui/EmptyState.vue`，铺满父级剩余高度并居中：

1. 一行主文案 `description`：**为什么空**，≤14 字
2. 一行 `reason`（可选，12px）：**下一步做什么**，与主文案合计 ≤24 字
3. 最多一个主操作

```vue
<EmptyState description="今天还没有候选" reason="盘后 15:30 自动跑一遍">
  <Button size="sm" @click="run">立即选股</Button>
</EmptyState>
```

空态配大插图 + 三行解释，观感上会把主区切成「小岛 + 大片空白」；
把 `:image-size` 锁到 96px 也是同一个问题。文案短、铺满，通常更好。

---

## 8. 文案

| 规则 | 要求 |
|---|---|
| 页面不写介绍段落 | 页面开头不放「本页用于……」；口径写进 `PageToolbar` 的 `note`（ⓘ + tooltip） |
| 解释进 tooltip | 长解释放 `Tooltip` / `Popover`，正文不留说明段 |
| 告警条 | 只报**当前真实异常**；标题 ≤20 字；不做常驻说明条（常驻说明读起来像噪声，会被忽略） |
| 按钮 | 动词短语，2-4 字：「选股」「重跑」「记一笔」 |
| 空态 | 为什么空 + 下一步，合计 ≤24 字（见 §7） |
| 数字口径 | 用 `shared/lib/format` 的 `pct` / `signedPct` / `price` / `money` |
| 表头 | 名词，2-5 字；单位进表头括号（`涨跌幅(%)`），不进每个单元格 |
| 时间 | 相对时间只用于 24h 内，其余写 `MM-DD HH:mm`，等宽 |
| 语气 | 不用感叹号堆叠、「请注意」「温馨提示」、颜文字、emoji |

```vue
<!-- 好 -->
<Alert v-if="err" variant="destructive" title="行情源连接失败" />
<Tooltip content="胜率 = 精选候选 T+5 收益为正的比例；样本 < 5 仅供参考">
  <span class="kicker">胜率</span>
</Tooltip>

<!-- 读起来费力 -->
<Alert variant="info" title="使用说明" description="本页展示候选池……（120 字）" />
<p class="page-intro">这个页面可以帮助您回顾最近的交易情况……</p>
```

---

## 9. 壳层组件

| 组件 | 形态 | 要点 |
|---|---|---|
| `PageToolbar` | 路由页顶部**唯一**一条功能行：筛选（default 槽）→ 读数（`stats`）→ 操作（`actions`） | **没有标题**——页面身份由侧栏高亮交代（`PageHeader` 已下线，`features/review/pageTopBar.test.ts` 会拦回来）；`note` 只渲染一枚 `--fs-aux` 的 ⓘ，全文进 tooltip |
| `HeaderStat` | 一行「小标签 + 等宽数值」 | `lead` 档抬到 `--fs-hero`，一条功能行至多一次；`tone` 只给涨跌 |
| `Sheet` | 无阴影 + 1px 边 + `--radius`；`sheet-bar` 高 `--head-h` | `meta` 槽放 `--fs-aux` 弱色口径；`padded` 才有内边距，表格直接放 `default` 槽 |
| `PageTabs` | 高 `--ctl-h`（`dense` 档 `--row-h-sm`），激活下划线 2px `--seal` | 放在 `.page-scroll` 外；badge 等宽 `--fs-kicker` |
| `BasicTable` | 见 §5 | 放大态无阴影 |
| `EmptyState` | 见 §7 | 铺满父级、内容居中 |
| `PageContainer` | 左栏 + 右主体，`gap: --gap-2` | 左栏底色 `--sheet-alt` |
| `HeaderActions` | 主操作在右，溢出进「更多」 | `danger` 用 `--stamp` |

```vue
<template>
  <div class="page-fill">
    <PageToolbar note="盘后 15:30 自动生成，只读">
      <Input v-model="kw" placeholder="代码 / 名称" class="w-[180px]" />
      <template #stats>
        <HeaderStat label="精选" :value="counts.selected" />
        <HeaderStat label="观察" :value="counts.watching" />
      </template>
      <template #actions>
        <Button variant="outline" @click="reload">刷新</Button>
        <Button variant="default" @click="open = true">记一笔</Button>
      </template>
    </PageToolbar>

    <Sheet class="list-sheet">
      <BasicTable :columns="columns" :request="fetchRows" />
    </Sheet>
  </div>
</template>
```

---

## 10. 颜色语义速查

| 语义 | 令牌 |
|---|---|
| 品牌 / 主操作 / 选中 / 进度 | `--seal`、`--seal-soft`、`--seal-ink` |
| 涨 / 跌 / 平 | `--up` / `--down` / `--flat` |
| 健康 / 成功 / 连接正常 / 会话状态 | `--ok` / `--ok-soft` |
| 破坏性操作 / logo 印记 | `--stamp` |
| 警告（配置缺失、限流） | `--warn` / `--warn-soft` |
| 信息（中性提示、事件点） | `--info` / `--info-soft` |
| 弱化（占位、禁用、口径） | `--mist` / `--flat` |

---

## 11. 容易出问题的地方

按「曾经真的出过事」整理，不是偏好清单：

1. **装饰性左竖条**：`border-left` / `border-inline-start` ≥2px 且另外三边为 0，
   用来标状态、等级或「当前选中」。2026-08 全站清过一轮（9 处 + 管理后台分区栏 + 公告级别条）
   ——到处都是竖条时它就不再是信号，只是噪声。替代写法：整块 1px hairline 外框 + 极淡状态底色，
   或把状态收进 `Badge`。
   结构性列分隔（指数带 / 行情格的 1px 单元格竖线）、面板边界、Markdown `blockquote` 不在此列。
2. **`var(--token, 字面量)`**：`:root` 恒定义的令牌不写 fallback。它永不触发，却是读代码的人
   唯一能看到的令牌值，还会互相矛盾；令牌改名那天它会静默生效成错值。
   只有**故意不定义**的令牌才写。
3. **同一选择器在两个 `style.*.css` 里各写一份**——后者会静默覆盖前者，
   排查时看不到任何报错。
4. **在 SFC 里重写表格 / 表单的密度与配色**——改全局层，别在几十个页面里各调一次。
5. **硬编码颜色 / 字号 / 间距**：出现的 `#hex`、`px` 字号、裸 `rem` 间距最好要么换成令牌，
   要么就近声明局部自定义属性（如 `--tape-cell-w`）并写清理由。
6. **引入第二套 UI 库 / webfont / 图标字体**：会和现有令牌与图标体系打架。
7. **业务卡片挂阴影或大圆角找「精致感」**：会让密集表格显得松散。
8. **`min-height` / 大 `padding` 撑空**；写死 `repeat(N, 1fr)` 却没有 N 个内容。
9. **品牌色 / 按钮 / 选中态 / 进度条 / tab 下划线用红绿**（见 §1 D1）。
10. **大号衬线中文标题**（超过 `--fs-hero` 20px 的中文标题、用 `--font-display` 当衬线用）。

---

## 12. 改完可以看一眼

不是审批门槛，是自查时不容易想到的几条：

- 页面上最大的字是数字；中文标题 ≤`--fs-hero`（20px）/ 700 / `.03em`，无衬线
- 全页搜不到 `--up` / `--down` 用在非价格语义上（状态用 `--ok` / `--warn` / `--info`）
- 表格行高走 `--row-h`、表头走 `--head-h`；数字列右对齐且等宽
- 区块间距 `--gap-2`；没有超过 `--gap-4` 的成片空白；业务卡片无 `box-shadow`
- 表单 label 列对齐；多列走 `.form-grid`；筛选条控件同高同基线
- 空态铺满主区并居中、≤24 字、最多一个操作
- 新增 CSS 用令牌，`var()` 不带 fallback
- 键盘 Tab 能走完主流程，`:focus-visible` 有 2px `--seal` 轮廓
- `prefers-reduced-motion: reduce` 下无动画
- 980px / 640px 宽度下不塌、无文档级滚动条（滚动在 `.page-scroll` / 表体内）
- `cd frontend; bun run typecheck` 与 `bun run test` 通过
