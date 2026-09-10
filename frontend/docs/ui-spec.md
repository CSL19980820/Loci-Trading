# Loci 前端视觉与密度规范 · v2「盘口」

> 适用范围：`frontend/**` 全部页面与组件。**本文件是施工依据**：改 UI 前先读，改完按 §12 自检。
> 上级：[`frontend/AGENTS.md`](../AGENTS.md)（§3.9 摘要指到这里）。
>
> **令牌真值只在 [`frontend/src/style.base.css`](../src/style.base.css)（日盘 `:root`）与
> [`style.theme.css`](../src/style.theme.css)（外观 / 主色档）；本文件里出现的一切数值都只是副本**，
> 用于让人一眼知道量级。发现文档与 CSS 不符：**一律以 CSS 为准**，回来改这份文档，
> 不要照文档去改 CSS —— CSS 里的值是跑过 `e2e/taste-audit.mjs` 对比度探针校准过的。
> 同理 `var()` 一律不写 fallback：`:root` 恒定义的令牌写了 fallback，只是给改名那天
> 留一个必然过期、还会静默生效的错值（只有**故意不定义**的令牌才需要 fallback）。
>
> 产品定位：**专业行情终端**（信息密度对标通达信 / 同花顺 / 悟道），保留一层克制的墨色账本气质。
> 「奶白纸 + 大号衬线中文标题 + 印章红品牌色」的书卷风已于 2026-08 退场。

## 目录

- [1. 三条硬纪律](#1-三条硬纪律)
- [2. 令牌表](#2-令牌表)
- [3. 排版与字阶](#3-排版与字阶)
- [4. 密度与间距](#4-密度与间距)
- [5. 表格规范](#5-表格规范)
- [6. 表单对齐规范](#6-表单对齐规范)
- [7. 空态规范](#7-空态规范)
- [8. 文案规范](#8-文案规范)
- [9. 壳层组件用法](#9-壳层组件用法)
- [10. 颜色语义速查](#10-颜色语义速查)
- [11. 禁止清单](#11-禁止清单)
- [12. 自检清单](#12-自检清单)

---

## 1. 三条硬纪律

### D1 红绿只属于价格

`--up` / `--down`（及 `-soft` / `-ink` 变体）**只能**出现在：涨跌数字、涨跌箭头/标记、买卖方向标、
K 线与量柱。品牌色、主按钮、选中态、进度条、链接、tab 下划线、事件点、评分徽章、
成功/失败提示——**一律不用红绿**，用 `--seal`（品牌靛）/ `--warn` / `--info` / `--mist`。

破坏性操作（删除、清库、重置）用 `--stamp`（印章红 `#c41e3a`），它与 `--up` 是两个不同的红：
「删除」和「涨」不该长一样。

```css
/* DO */
.pct-cell { color: var(--up); }                 /* 涨跌数字 */
.el-button--primary { background: var(--seal); } /* 主操作 = 品牌靛 */
.progress__fill { background: var(--seal); }

/* DON'T */
.tab.is-active { border-color: var(--up); }      /* 选中态偷用涨色 */
.badge-ok { background: var(--down-soft); }      /* 「成功」不是「跌」 */
```

### D2 页面上最大的字必须是数字

数字一律 `font-family: var(--mono)` + `font-variant-numeric: tabular-nums`（否则换值时左右横跳）。
中文标题小而稳：**≤20px / 700 / `letter-spacing: .03em`**，不换字族、不用衬线。
关键报价用 `--fs-tape`（26px）或工具类 `.tape-num`；页内最大的中文标题用 `--fs-hero`（20px）。

```css
/* DO */
.quote { font: 700 var(--fs-tape) / 1.05 var(--mono); font-variant-numeric: tabular-nums; }
.page-title { font: 700 var(--fs-hero) / 1.2 var(--font); letter-spacing: .03em; }

/* DON'T */
.page-title { font-family: var(--font-display); font-size: 1.45rem; } /* 旧衬线大标题 */
```

> `--font-display` 现在就是 `--font-sans`：留着只为不炸存量引用，**新代码直接写 `var(--font)`**。

### D3 密度优先

| 项 | 值 | 令牌 |
|---|---|---|
| 表格行高 | 32px | `--row-h`（紧凑档 `--row-h-sm` 28px） |
| 表头高 | 30px | `--head-h` |
| 控件高 | 30px | `--ctl-h`（EP 全局 `size='small'`） |
| 区块间距 | 8px | `--gap-2`（`.mb` / `.page-scroll` gap） |
| Sheet 内边距 | 10px 14px | `--pad-sheet`（另拆 `--pad-sheet-y` / `--pad-sheet-x`） |
| 圆角 | 6px | `--radius`（小件 4px `--radius-sm`、大件 10px `--radius-lg`、整卡 14px `--radius-xl`） |
| 阴影 | 业务卡片不挂 | `--shadow` 只喂 EP 弹层桥接（`--el-box-shadow`）；卡片分层用 `1px solid var(--rule)` |
| 分隔线 | 1px hairline | `1px solid var(--rule)`（行级更淡一档用 `--rule-soft`） |

禁止成片 >16px 的死留白：`padding` 超过 `--gap-4`、`min-height` 撑空、内容不足却写死列数
（用 `repeat(auto-fit, minmax(…, 1fr))`）都算违规。

---

## 2. 令牌表

### 2.1 日盘（`:root`，`style.base.css`）

| 令牌 | 定义 | 用途 |
|---|---|---|
| `--paper` | `var(--surface-canvas)`（色阶 3） | 页面底色（`.page-fill` / 主区） |
| `--sheet` | `rgba(250,251,253,.94)`（色阶 2 的 sRGB 兑现 @94%） | 区块底色（Sheet / 页头 / 表体） |
| `--sheet-alt` | `var(--surface-sunken)`（色阶 4） | 表头、斑马行、次级底 |
| `--rule` / `--rule-strong` | `#d0d6dc` / `#bec5cc`（色阶 7 / 8 的 sRGB 兑现） | 1px 分隔线 / 边框强调、次级按钮描边 |
| `--rule-soft` | 色阶 7 @55% | 行级 hairline，密表里不至于变成栅格纸 |
| `--ink` / `--muted` / `--mist` | `#1b252f` / `#4e5761` / `#626c76`（色阶 12 / 11 / 10 的 sRGB 兑现） | 正文数字 / 次要文字 / 弱文字与口径 |
| `--seal` | `#cc323e` 朱红（随 `data-primary` 切换，见 §2.6） | **品牌主色**，EP primary 派生源 |
| `--on-primary` | `#ffffff`（`shared/lib/theme.ts` 按 OKLCH 亮度阈值 0.62 决定黑白） | 压在**实心主色**上的文字色，保证 ≥4.5:1 |
| `--seal-ink` / `--seal-soft` | 由 `--seal` 用 `color-mix(in oklab)` 派生（78% 混墨 / 12% 透明） | 主色文字态 / 主色浅底（选中行、hover 行、chip） |
| `--stamp` | `oklch(.53 .19 20)` | 印章红：logo、登录印记、破坏性操作 |
| `--up` / `--up-soft` / `--up-ink` | `#c8282a` / 本色 @10% / `oklch(.465 .17 26)` | 涨（sRGB 兑现 `oklch(.542 .196 26)`） |
| `--down` / `--down-soft` / `--down-ink` | `#00793a` / 本色 @10% / `oklch(.45 .115 152)` | 跌（sRGB 兑现 `oklch(.5025 .135 152)`） |
| `--up-1..5` / `--down-1..5` | OKLCH 等距 5 档，5 = 本色 | 分布条 / 热力 / 筹码分布 |
| `--flat` | 色阶 10 | 平盘 / 停牌 |
| `--warn` / `--info` | `#a05e00` / `#1174b4`（各带 `-soft` / `-ink`） | 警告 / 信息 |
| `--ok` / `--ok-soft` | `#007c7c`（青绿 hue 195） | **非价格语义**的健康/成功色：绿被 D1 占给了「跌」，状态色必须离开纯绿 |
| `--radius` / `--radius-lg` / `--shadow` | `6px` / `10px` / 两层实心阴影 | 形状；业务卡片仍然不挂阴影（D3） |

> 表面 / 边框 / 文字各自还有一层语义档，全部建在 12 阶中性色阶 `--n-1..12` 上：
> `--surface-raised|surface|surface-canvas|surface-sunken|surface-hover|surface-active`、
> `--border-subtle|border-default|border-strong`、`--text-primary|secondary|tertiary|disabled`。
> **交互底（hover / 选中）一律用 `--surface-hover` / `--surface-active`**，不要手写 `rgba(…, .04)`——
> 那种写法在夜盘两档上肉眼不可见，等于没有 hover 反馈。
>
> `--stamp` **没有** `-ink` / `-soft` 变体：它只做前景色或小面积底块。压在它上面的文字写 `#fff`
> 是规范值（`--stamp` 固定印章红、不随 `data-primary`），但要留一句 why 注释；不要再造一个深红文字态。

### 2.2 其余三档外观（`style.theme.css`）

四档外观：`day`（缺省 `:root`）/ `paper` 暖纸 / `night` 蓝灰 / `ink` 中性纯黑。
**每档只改中性色阶 `--n-1..12` 与少数「sRGB 兑现」键**，语义层（表面 / 边框 / 文字 / 底色别名）
建在色阶上自动跟随：

| 档 | 选择器 | 改了什么 |
|---|---|---|
| 暖纸 | `html[data-appearance='paper']` | 色阶换暖调 hue 82；`--sheet` `rgba(255,248,237,.95)`；涨跌不动 |
| 夜盘公共层 | `html[data-appearance='night'], html[data-appearance='ink'], html.dark` | `color-scheme: dark`；涨跌提亮到 `--up #f67168` / `--down #57c37b`；阴影更重更散；`--seal-*` 派生比例重调 |
| 夜间 | `html[data-appearance='night'], html.dark` | 色阶换蓝灰 hue 258；`--sheet` `rgba(23,30,39,.92)` |
| 墨黑 | `html[data-appearance='ink']` | 色阶 chroma 全 0 纯灰；`--up #ff7b72` / `--down #5cd283` 再提一档 |

夜盘那三个选择器**写在同一个选择器列表里**，不要再各存副本（历史上改前面被后面静默覆盖）。
`html.dark` 额外把 EP 变量指回本仓令牌。

### 2.3 字体与字阶

```
--font-sans / --font   -apple-system / BlinkMacSystemFont / Segoe UI / Roboto / PingFang SC / Hiragino Sans GB / Microsoft YaHei UI
--mono / --font-mono   JetBrains Mono / SF Mono / Roboto Mono / Consolas / Menlo
--font-display         = --font-sans（历史别名，中文标题不换族）
--font-serif    宋体族；**当前无消费方**，正文与标题一律不用
```

**不挂任何 webfont**：`index.html` 的 Google Fonts `<link>` 与 `preconnect` 已删——国内网络基本
拉不到，实际渲染一直是系统字，等于设计从未生效，还阻塞首屏。不要再加回来，也不要塞字体文件。

| 令牌 | 值 | 用在哪 |
|---|---|---|
| `--fs-tape` | 26px | 指数 / 关键报价，等宽（工具类 `.tape-num`） |
| `--fs-hero` | 20px | 页内最大的中文标题、`HeaderStat` lead 档、`StatCard` 读数 |
| `--fs-title` | 16px | 区块标题（`.sheet-bar h2`、弹窗标题） |
| `--fs-body` | 14px | 正文 / 表格 / 控件（`--el-font-size-base`） |
| `--fs-aux` | 12px | 辅助、口径、表头、`.code` |
| `--fs-kicker` | 11px | 微标：大写 + `letter-spacing:.14em` + `--mono`（工具类 `.kicker`） |
| `--fs-micro` | 10px | 移动底栏标签一类极小标注，不承载信息 |

### 2.4 密度令牌

```
--row-h 32px   --row-h-sm 28px   --head-h 30px   --ctl-h 30px
--gap-1 4px    --gap-2 8px    --gap-3 12px  --gap-4 16px
--pad-page-x 12px（右侧内容容器的左右沟槽）
--pad-sheet 10px 14px（另拆 --pad-sheet-y / --pad-sheet-x 供负 margin 贴边）
--form-label-w 7em
```

### 2.5 legacy 别名（保留，不要删）

`--bg` `--panel` `--panel-2` `--line` `--line-2` `--text` `--dim` `--accent` `--accent-soft`
`--accent-text` `--blue` `--lake` `--lake-soft` `--success` `--loss` —— 全部指向新值。
存量页仍在引用，删了会整仓塌；**新代码不要用它们**，直接写语义令牌。

### 2.6 主色八档（`data-primary`）

只换 `--seal` 与 `--on-primary`，其余派生档全部由 `--seal` 混出：
`seal #cc323e` 朱红（缺省）/ `flame #c15108` / `amber #d79700` / `moss #298646` /
`lake #008471` / `teal #007ca8` / `blue #396ed6` / `violet #854ece`。

`amber` 的 L≈0.72，白字在它上面必然不够，所以该档 `--on-primary` 反转成深字 `#14181f`，
深色档再把主色提亮到 `#ebaa2d`。自定义主色同理由 `shared/lib/theme.ts` 按 L>0.62 决定黑白。
**压在实心主色上的文字一律 `var(--on-primary)`，不要写 `#fff`。**
**`--up` 绝不等于 `--seal`**——涨跌色不跟随 `data-primary`，这是 D1 的实现保证。

---

## 3. 排版与字阶

| 层级 | 规格 | 说明 |
|---|---|---|
| 页标题 | 20px / 700 / `.03em` / sans | `--fs-hero`；路由页正文顶上**不再印页面名**（`PageHeader` 已下线，见 §9） |
| 区块标题 | 16px / 700 / `.03em` | `--fs-title`；`.sheet-bar h2` / `el-card__header` |
| 正文、表格 | 14px / 400 / 行高 1.45 | `--fs-body`，`body` 已是这个档 |
| 口径、表头、meta | 12px / `--mist` | `--fs-aux`；表头再加 600 字重 |
| 微标 | 11px / 大写 / `.14em` / mono | `--fs-kicker`，只用于标签，不承载信息 |
| 数字 | mono + `tabular-nums` | 任何位数会变的数字都要加 |

中文不做斜体，不做 `text-transform`（只有拉丁微标可以大写）。行内代码/股票代码用
`.code`（12px mono，`letter-spacing:.02em`）。

---

## 4. 密度与间距

- 页面骨架：`.page-fill`（`--paper` 纯色，无边框、无纹理）→ 可选 `PageToolbar`（顶部唯一功能行）
  → 可选 `PageTabs` → `.page-scroll`（`gap: --gap-2`，`padding: --gap-2`；`.page-fill` 直接子的
  左右内边距被清零，沟槽由 `--pad-page-x` 统一给）或表体自滚。
- 区块之间只用 `--gap-2`；区块内部行距 `--gap-1`；两栏栅格 `--gap-2`。
- `.page-fill` 的「账页衬线」背景纹已删除：**空白就是空白**，正确的修法是把内容排满或缩小区块，
  不是画格子把空白伪装成留白。
- 业务卡片没有阴影。层级靠 `1px solid var(--rule)` + `--sheet` / `--sheet-alt` 的底色差表达；
  `--shadow` 只留给 EP 弹层。
- 高度不足时用 `flex: 1 1 auto; min-height: 0` 吃满，不写 `min-height: 14rem`。

---

## 5. 表格规范

皮肤在 `style.components.css`（`el-table` / `table.dense` 共用）+ `BasicTable.vue` 作用域内的少量补充。
**新表一律 `el-table` / `BasicTable`**，不要自绘 `<table>`（`table.dense` 只为存量页保留）。

| 项 | 规格 |
|---|---|
| 行高 | `--row-h` 32px，单元格竖向 padding `--gap-1` |
| 表头 | 高 `--head-h` 30px，底色 `--sheet-alt`，`--fs-aux` / 600 / `--muted` |
| 单元格水平 padding | `--gap-2`（`.cell`） |
| hover 行 | `--seal-soft`（不是灰） |
| 斑马行 | `--sheet-alt`（默认关，长表再开） |
| 外框 | 无阴影；表格贴 Sheet 边（`sheet-body` 下唯一子表自动反推负 margin） |
| 数字列 | `align="right"` → 自动 mono + `tabular-nums` |
| 代码列 | `class-name="is-code"` → mono + `.02em` |
| 涨跌 | `class-name` / 单元格 class 用 `is-up` / `is-down` / `is-flat` |
| 空表 | `empty-text` 一句话（≤14 字），空块高度 96px |

```vue
<!-- DO：数字列右对齐即得等宽 + tabular-nums -->
<el-table :data="rows" size="small">
  <el-table-column prop="code" label="代码" width="88" class-name="is-code" />
  <el-table-column prop="name" label="名称" min-width="110" />
  <el-table-column prop="last" label="最新" width="82" align="right" />
  <el-table-column prop="chg" label="涨跌幅" width="88" align="right">
    <template #default="{ row }">
      <span :class="row.chg >= 0 ? 'is-up' : 'is-down'">{{ signedPct(row.chg) }}</span>
    </template>
  </el-table-column>
</el-table>
```

```vue
<!-- DON'T：在 SFC 里再写一套行高/边框/表头色，或用 <table class="dense"> 起新表 -->
```

---

## 6. 表单对齐规范

全局默认（`style.components.css`）：

- `el-form-item` 间距 `--gap-2`；
- 未显式设 `label-width` 的块级表单：label 宽 `--form-label-w`（7em）、右对齐、
  行高 `--ctl-h`、色 `--muted`；显式 `label-width` 仍然生效（EP 写内联 style，优先级更高）；
- `label-position="top"` 与 `inline` 表单不套定宽；
- 980px 以下 label 自动转左对齐自适应，输入框不被挤成缝。

### 6.1 多列表单：`.form-grid`

```vue
<el-form :model="form" label-width="7em">
  <div class="form-grid">
    <el-form-item label="股票池"><el-select v-model="form.pool" /></el-form-item>
    <el-form-item label="起始日"><el-date-picker v-model="form.from" /></el-form-item>
    <el-form-item label="备注" class="full-span"><el-input v-model="form.note" /></el-form-item>
  </div>
</el-form>
```

`.form-grid` = `repeat(auto-fit, minmax(260px, 1fr))`：列数随宽度自适应，label 宽度全表一致，
换行不错位。整行字段加 `.full-span`。**不要**在 SFC 里另写 `grid-template-columns: repeat(3, …)`
覆盖 `el-form`，也不要 `.el-form-item { margin-bottom: 0 }` 局部重置。

### 6.2 筛选条：`.filter-bar`

```vue
<Sheet class="filter-bar" plain>
  <div class="filters">
    <el-input v-model="kw" placeholder="代码 / 名称" clearable style="width: 180px" />
    <el-select v-model="decision" placeholder="决策" style="width: 120px" />
    <el-button type="primary" @click="reload">筛选</el-button>
  </div>
</Sheet>
```

`.filter-bar .filters`（或内部 `el-form--inline`）自动 flex + `align-items: center` +
控件高度统一 `--ctl-h`，换行后两行控件左缘对齐。inline 的 label 不定宽（12px `--mist`）。

### 6.3 禁止自绘表单行

`<div class="field-header">` + `<div class="field-controls">` + `<p class="field-hint">` 这种
自绘三件套一律换 `el-form-item` + `#label` / `el-form-item__error` / `.form-hint`。
`PageHeader` / `Sheet` 里的 label 行同样走这套类名，别再造。

---

## 7. 空态规范

用 `shared/components/ui/EmptyState.vue`。整块 **≤96px 高**，结构固定：

1. 一行主文案 `description`：**为什么空**，≤14 字；
2. 一行 `reason`（可选，12px）：**下一步做什么**，与主文案合计 ≤24 字；
3. 最多一个主操作（默认插槽放 `el-button`）。

**没有插图**：空不是异常，不需要一张图来渲染情绪（旧版 96px 插图 + 三行解释，比它要解释的表还高）。

```vue
<!-- DO -->
<EmptyState description="今天还没有候选" reason="盘后 15:30 自动跑一遍">
  <el-button type="primary" size="small" @click="run">立即选股</el-button>
</EmptyState>

<!-- DON'T -->
<el-empty :image-size="120" description="这里空空如也，可能是因为您还没有创建任何记录，
  也可能是筛选条件过于严格，请尝试调整筛选条件或稍后再试" />
```

存量 `el-empty` 已被全局压到插图 40px、上下 `--gap-3`；新代码不要再传 `:image-size`。

---

## 8. 文案规范

| 规则 | 要求 |
|---|---|
| 页面不写介绍段落 | 页面开头不放「本页用于……」；口径写进 `PageHeader` 的 `note`（单行截断 + tooltip） |
| 解释进 tooltip | 长解释一律 `el-tooltip` / `el-popover`，正文不留说明段 |
| `el-alert` | 只报**当前真实异常**；`title` ≤20 字；**禁止 `description`**；不做常驻说明条 |
| 按钮 | 动词短语，2-4 字：「选股」「重跑」「记一笔」；禁止「点击这里开始执行选股任务」 |
| 空态 | 为什么空 + 下一步，合计 ≤24 字（见 §7） |
| 数字口径 | 用 `shared/lib/format` 的 `pct` / `signedPct` / `price` / `money`；不在页面里解释算法 |
| 表头 | 名词，2-5 字；单位进表头括号（`涨跌幅(%)`），不进每个单元格 |
| 时间 | 相对时间只用于 24h 内，其余写 `MM-DD HH:mm`，等宽 |
| 禁止 | 感叹号堆叠、「请注意」「温馨提示」、颜文字、emoji |

```vue
<!-- DO -->
<el-alert v-if="err" type="error" :closable="false" title="行情源连接失败" />
<el-tooltip content="胜率 = 精选候选 T+5 收益为正的比例；样本 < 5 仅供参考">
  <span class="kicker">胜率</span>
</el-tooltip>

<!-- DON'T -->
<el-alert type="info" title="使用说明" description="本页展示候选池……（120 字）" />
<p class="page-intro">这个页面可以帮助您回顾最近的交易情况……</p>
```

---

## 9. 壳层组件用法

| 组件 | 形态 | 要点 |
|---|---|---|
| `PageToolbar` | 路由页顶部**唯一**一条功能行：筛选（default 槽）→ 读数（`stats`）→ 操作（`actions`）；`min-height: --ctl-h + --gap-2`，`dense` 档等于 `--ctl-h` | **没有标题**——页面身份由侧栏高亮交代（`PageHeader` 已下线，`features/review/pageTopBar.test.ts` 会拦回来）；`note` 只渲染一枚 `--fs-aux` 的 ⓘ，全文进 tooltip |
| `HeaderStat` | 一行「小标签 + 等宽数值」 | `lead` 档抬到 `--fs-hero`，一条功能行至多一次；`tone` 只给涨跌 |
| `Sheet` | 无阴影 + 1px 边 + `--radius` 圆角；`sheet-bar` 高 `--head-h` | `meta` 槽放 `--fs-aux` 弱色口径；`padded` 才有内边距，表格直接放 `default` 槽 |
| `PageTabs` | 高 `--ctl-h`（`dense` 档 `--row-h-sm`），激活下划线 2px `--seal` | 放在 `.page-scroll` 外；badge 等宽 `--fs-kicker` |
| `BasicTable` | 见 §5 | `size` 默认 `small`；放大态无阴影 |
| `EmptyState` | 见 §7 | ≤96px |
| `PageContainer` | 左栏 + 右主体，`gap: --gap-2` | 左栏底色 `--sheet-alt` |
| `HeaderActions` | 主操作在右，溢出进「更多」 | `danger` 用 `--stamp` |

```vue
<template>
  <div class="page-fill">
    <PageToolbar note="盘后 15:30 自动生成，只读">
      <el-input v-model="kw" placeholder="代码 / 名称" clearable style="width: 180px" />
      <template #stats>
        <HeaderStat label="精选" :value="counts.selected" />
        <HeaderStat label="观察" :value="counts.watching" />
      </template>
      <template #actions>
        <el-button @click="reload">刷新</el-button>
        <el-button type="primary" @click="open = true">记一笔</el-button>
      </template>
    </PageToolbar>

    <Sheet class="list-sheet">
      <el-table :data="rows" height="100%">…</el-table>
    </Sheet>
  </div>
</template>
```

---

## 10. 颜色语义速查

| 语义 | 令牌 | 反例 |
|---|---|---|
| 品牌 / 主操作 / 选中 / 进度 | `--seal`、`--seal-soft`、`--seal-ink` | 用 `--up` 当强调色 |
| 涨 / 跌 / 平 | `--up` / `--down` / `--flat` | 用它们标「成功 / 失败」 |
| 健康 / 成功 / 连接正常 / 会话状态 | `--ok` / `--ok-soft` | 用 `--down`（跌绿）标「成功」「开盘中」 |
| 破坏性操作 / logo 印记 | `--stamp` | 用 `--up` 做删除按钮 |
| 警告（配置缺失、限流） | `--warn` / `--warn-soft` | 用红色喊 |
| 信息（中性提示、事件点） | `--info` / `--info-soft` | 用主色抢注意力 |
| 弱化（占位、禁用、口径） | `--mist` / `--flat` | 直接降 opacity 到看不清 |

---

## 11. 禁止清单

1. 大号衬线中文标题（`--font-display` / `--font-serif` 当衬线用、超过 `--fs-hero`（20px）的中文标题）。
2. 品牌色 / 按钮 / 选中态 / 进度条 / tab 下划线用红绿。
3. 业务卡片阴影（`box-shadow` 只留给 EP 弹层 / 遮罩）、圆角超过 `--radius-lg`（10px）。
4. 自绘表单行（`div.field-*` 冒充 `el-form-item`）、自绘表格（新建 `<table class="dense">`）、
   自绘 modal / 页码条 / 勾选。
5. `el-alert` 写 `description` 或当常驻说明条；页面顶部写介绍段落。
6. 硬编码颜色 / 字号 / 间距：出现新的 `#hex`、`px` 字号、裸 `rem` 间距必须有注释说明为什么不能用令牌；
   实在没有对应令牌的，就近声明一个局部自定义属性（如 `--tape-cell-w`）并写清理由，不要继续裸 px。
7. `min-height` / 大 `padding` 撑空；写死 `repeat(N, 1fr)` 却没有 N 个内容。
8. 引入新 UI 库、webfont、图标字体；把 Tailwind 使用面扩大到 `PulseView.vue` 之外。
9. 同一选择器在两个 `style.*.css` 里各写一份（后者会静默覆盖前者）。
10. 在 SFC 里重写 `el-table` / `el-form` 的密度与配色——改全局层，别在 32 个页面里各调一次。
11. **装饰性左竖条**：`border-left` / `border-inline-start` ≥2px 且另外三边为 0，用来标状态、
    等级、层级或「当前选中」。2026-08 全站清过一轮（9 处 + 管理后台分区栏 + 公告级别条）——
    到处都是竖条时它就不再是信号，只是噪声。替代写法：整块 1px hairline 外框 + 极淡状态底色
    （`color-mix(in srgb, var(--seal) 6%, transparent)` 一档），或把状态收进 `el-tag`。
    **`el-timeline` 同样禁用**（它自带左轴线 + 节点圆点）：四列以内的事件流一律用 `BasicTable`。
    结构性列分隔（指数带 / 行情格的 1px 单元格竖线）、面板边界、Markdown `blockquote` 不在此列。
12. `var(--token, 字面量)`：`:root` 恒定义的令牌不写 fallback。它永不触发，却是读代码的人唯一能
    看到的令牌值，还会互相矛盾；令牌改名那天它会静默生效成错值。只有**故意不定义**的令牌才写。

---

## 12. 自检清单

改完 UI，逐条过：

- [ ] 页面上最大的字是数字；中文标题 ≤`--fs-hero`（20px）/ 700 / `.03em`，无衬线。
- [ ] 全页搜不到 `--up` / `--down` 用在非价格语义上（状态用 `--ok` / `--warn` / `--info`）。
- [ ] 表格行高走 `--row-h`、表头走 `--head-h`；数字列右对齐且等宽。
- [ ] 区块间距 `--gap-2`；没有超过 `--gap-4` 的成片空白；业务卡片无 `box-shadow`。
- [ ] 表单 label 列对齐；多列走 `.form-grid`；筛选条控件同高同基线。
- [ ] 空态 ≤96px、≤24 字、最多一个操作；`el-alert` 无 `description`。
- [ ] 新增 CSS 全部用令牌，`var()` 不带 fallback；如有硬编码，注释写清 why。
- [ ] 键盘 Tab 能走完主流程，`:focus-visible` 有 2px `--seal` 轮廓。
- [ ] `prefers-reduced-motion: reduce` 下无动画。
- [ ] 980px / 640px 宽度下不塌、无文档级滚动条（滚动在 `.page-scroll` / 表体内）。
- [ ] `cd frontend; bun run typecheck` 与 `bun run test` 通过。
