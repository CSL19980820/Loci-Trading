# shared/components/ui

跨 feature 的无业务语义 UI 原子。

| 组件 | 职责 |
|---|---|
| `PageBusy` | 加载态：一行 28px 的转圈 + 文案（`busy`/`label`/`overlay`）；不撑高度，首屏无数据用占位、有内容刷新用 `overlay`（父级需 `position:relative`） |
| `PageTabs` | 页级分区切换（`el-tabs` + 朱印底线）；`v-model` + `items`；可选 `#trailing` 槽；面板由父级 `v-show` 编排 |
| `SegmentSwitch` | 页头紧凑分段（`el-segmented`，28px）；`v-model` + `items`（name/label/disabled）；选中态是表面抬起，不是实心主色 |
| `BasicForm` | **全站表单契约**的唯一实现；`schemas` + `v-model` + `columns`；见下文 |
| `BasicTable` | 配置化表格；`columns` + `dataSource`/`request`；见下文 |
| `ListToolbar` | 列表工具栏（28px）；`config` 按键开关：`create`/`batchDelete`/`import`/`export`；不写或 `false` 不显示，写 `{ onClick, disabled?, loading?, show? }` 即接线。`batchDelete` 自动走印章红 |
| `RowActions` | 行内动作（28px 文字按钮 + 「更多」下拉）；`actions` + `maxVisible`；`type:'danger'` 走印章红 |
| `StatCard` | 读数卡：数值 26px 等宽 + 11px 标签 + 可选 12px 副信息；见下文 |
| `HeaderStat` | 页头行内读数，专供 `PageToolbar` 的 `stats` 槽；不带卡片壳（页头已有分隔线，再套 `StatCard` 会变「卡中卡」） |
| `EmptyState` | 空态：一行主文案 + 一行「下一步」，铺满父级并居中，无插图 |
| `UiButton` / `UiCard` / `UiBadge` / `UiInput` | shadcn 构造原子；颜色指回本仓令牌，尺寸对齐 `--ctl-h` |

页头本身是布局件，在 `shared/components/layout/PageToolbar.vue`。

---

## 表单契约（BasicForm / BasicFormField）

**所有表单一律走 `BasicForm`。** 存量页改造时照这份契约改，不要再自建 `.form-grid` 包壳。

### 四条硬规矩

1. **不许在 `el-form` 与 `el-form-item` 之间插任何元素。** 栅格是 `el-form` **自身**的
   CSS Grid。插了裸 `div`（或 `el-row`/`el-col`）就绕过 EP 的 label 宽度计算 ——
   这是全站表单错位的第一主因（`docs/ui-audit-2026-08.md` §3.5）。
2. **label 右对齐 + 定宽。** 默认 `label-position="right"`、`label-width="var(--form-label-w)"`(6.5em)、
   `size="small"`（控件 28px，label 同高，基线对齐）；必填星号钉在 label 右端
   （`require-asterisk-position="right"`），所以每行星号的横坐标一致。
3. **底距统一 8px，错误提示不跳动。** 行距来自全局 `.el-form .el-form-item{margin-bottom:var(--gap-2)}`；
   错误文案走 EP 原生绝对定位并钉成单行，出现/消失都不推动版面。
4. **字段说明只有两个去处**：≤20 字的 `hint` 渲染在控件下方、左缘与控件对齐；
   >20 字自动沉到 label 旁的 `el-tooltip` 图标（也可用 `tooltip` 显式指定）。
   **禁止**在 `el-form` 外另起 `<p class="form-hint">`。

### Props（默认值）

| prop | 类型 | 默认 | 说明 |
|---|---|---|---|
| `schemas` | `BasicFormSchema[]` | — | 必填 |
| `v-model` | `Record<string, unknown>` | `{}` | 与 `local` 结构相等比较后同步（见下） |
| `hint` | `string` | `''` | 表单级说明，一行，缩进自动与首个字段控件左缘对齐 |
| `columns` | `1 \| 2 \| 3` | `1` | 栅格上限；列宽 260px 起，窄容器自动退列，≤640px 退单列 |
| `labelPosition` | `'right' \| 'left' \| 'top'` | `'right'` | |
| `labelWidth` | `string \| number` | `'var(--form-label-w)'` | 可覆盖；`'auto'` 交给 EP 自测宽 |
| `size` | `'large' \| 'default' \| 'small'` | `'small'` | |
| `inline` | `boolean` | `false` | 走 EP inline 排布，不套栅格 |
| `disabled` | `boolean` | `undefined` | |
| `collapse` | `boolean` | `false` | 开启后只显示第一行字段 + 「展开」（长筛选条用） |
| `inputDebounceMs` | `number` | `500` | 文本输入防抖；**弹窗类表单传 `0`** |
| `colProps` | `{ span?: number }` | `undefined` | 24 栅格兼容入口，只服务尚未迁移的存量筛选条 |

`el-form` 的其余 prop（`rules` 之外的 `validate-on-rule-change`、`scroll-to-error`…）照常透传。

### schema

```ts
type BasicFormSchema = {
  field: string
  label?: string | ((h, ctx) => VNode | string)
  component?: 'input' | 'input-number' | 'select' | 'date-picker' | 'switch'
    | 'RadioGroup' | 'checkbox' | 'CheckboxGroup' | 'tree-select' | 'cascader'
  componentProps?: Record<string, unknown>   // options / request / placeholder / rows…
  componentEvents?: Record<string, (...args: unknown[]) => void>
  hint?: string      // ≤20 字跟控件左缘；>20 字自动进 tooltip
  tooltip?: string     // 显式指定 label 旁的 tooltip
  fullRow?: boolean    // 占满整行（textarea / 长文本）
  required?: boolean   // 省略时由 rules 推导
  rules?: FormRules[string]
  defaultValue?: unknown
  hidden?: boolean
  slotName?: string
  render?: (h, ctx) => VNode | string | number | null
  labelWidth?: string | number
}
```

### 用法

```vue
<script setup lang="ts">
import BasicForm from '@/shared/components/ui/BasicForm.vue'
import type { BasicFormSchema } from '@/shared/components/ui/basicFormTypes'

const form = ref<Record<string, unknown>>({})
const formRef = ref<InstanceType<typeof BasicForm>>()

const schemas: BasicFormSchema[] = [
  {
    field: 'code',
    label: '代码',
    componentProps: { maxlength: 6, placeholder: '6 位数字' },
    rules: [{ required: true, message: '填 6 位代码', trigger: 'change' }],
  },
  { field: 'pool_id', label: '池', hint: '默认按日期归池' },
  {
    field: 'strategy_tag',
    label: '战法',
    tooltip: '战法标识，与工坊里的 slug 一致，如 qianlong-close-v3',
  },
  { field: 'reason', label: '理由', componentProps: { type: 'textarea', rows: 3 }, fullRow: true },
]

async function save() {
  const values = await formRef.value?.submit()   // 校验不过返回 false，错误就地显示
  if (!values) return
  await createCandidate(values)
}
</script>

<template>
  <!-- 两列栅格；textarea 用 fullRow 占满 -->
  <BasicForm
    ref="formRef"
    v-model="form"
    :schemas="schemas"
    :columns="2"
    hint="同日同池同标的会覆盖上次裁决"
    :input-debounce-ms="0"
  />
</template>
```

**选项**：`componentProps.options` 静态，或 `componentProps.request` 接口驱动
（`fieldValue`/`fieldLabel`/`immediate`）；联动刷新用 `getFieldRef(field)?.getRequest()`。

**方法**：`submit`（先落地防抖草稿再校验）/ `getFieldsValue` / `setFieldsValue` /
`resetForm` / `setProps` / `getFormRef` / `getFieldRef`。

**v-model 同步**：`local` ↔ `modelValue` 用结构相等（`basicFormEqual`），避免 `daterange`
等数组字段因父级每次克隆新引用而与 emit 互相追打卡死页面（`BasicForm.sync.test.ts` 守着）。

---

## 弹窗规矩（shared/components/dialogs）

| 项 | 规矩 |
|---|---|
| 宽度 | `width="min(92vw, XXXpx)"`，不写死 px；表单弹窗 560、状态弹窗 520、设置类 420 |
| 标题 | `:title` 交给 EP，样式由全局 `.el-dialog__title`（14px/700，不用衬线）统一；**不要自绘 `#header`** |
| 正文 | 不写介绍段落。要解释就进字段 `hint`/`tooltip`，或压成「事实格」（label 11px + 等宽值） |
| 长正文 | 在 dialog body 内滚：`.xxx-dialog .el-dialog__body{max-height:min(62vh,30rem);overflow:auto}`（非 scoped，因为 dialog teleport 到 body） |
| footer 主操作 | 在最右，动词短语：「记下候选」「保存预案」「开始初始化」；**不许**「确定/提交」 |
| footer 次/破坏性操作 | 放最左，加 `class="is-leading"`（全局 `margin-right:auto`）；破坏性用 `type="danger" plain` |
| 键盘 | ESC 关闭、焦点陷阱、`destroy-on-close` 全用 EP 默认行为，别自己接管 |

---

## StatCard（数字主导）

```vue
<StatCard label="胜率" value="62.5%" tone="up" hint="T+5 · 48 样本" />
<StatCard label="成交笔数" value="128" layout="row" />
```

- `layout="stack"`（默认）：数值 `--fs-tape`(26px) 等宽 + `tabular-nums`，标签 `--fs-kicker`(11px)/`--mist`，副信息 `--fs-aux`(12px)。
- `layout="row"`：标签左、数值右（`--fs-hero`），用于卡片内的 KV 行。
- `tone="up|down"` **只给数值上色**（D1：红绿只属于价格）；卡壳永远是 1px hairline + 3px 圆角 + 无阴影。
- **不写 `min-height`**：卡高由内容决定，一排卡靠容器 `align-items:start` 收边。

---

## BasicTable

**模式**

- `request`：`(params) => { list, total }`，组件管分页与加载
- `dataSource` + `pagination` 对象：外部控页；`@current-change` / `@size-change`
- `pagination=false`：无分页（短列表）
- `pagination=true` / `{}`：内置分页（默认 layout 含 jumper）
- `virtualized`：启用 `el-table-v2`；与完整数据 `dataSource`、`pagination=false` 搭配用于大表。空态一律走 `EmptyState`（`emptyText` 作主文案，`emptyReason` 作下一步）；多级表头、展开、列筛选/排序、合并单元格或函数 `rowKey` 会自动回退到 `el-table`，但 `#empty` 槽仍在，不把整表卸掉

**能力**：`v-model:columns`、`toolbarConfig`（refresh / zoom / custom 列设置）、`mergeField`、`editConfig`+`editRender`、多级表头 `children`、列 `filters`/`filterMethod`、`formatter`/`render`/`slotName`、`offsetHeight`、`cell-click`/`row-click`/`selection-change`

**方法**：`fetch` / `reloadTable` / `restReload` / `setPagination` / `getTableData` / `doLayout` / `setEditRow` / `clearEdit` / `getRowEdit` / `isEditByRow` / `clearSelection` / `getTableRef`

**样式**：表头 `sheet-alt` + mist、单元格 padding、斑马纹全站统一（全局内置，页面无需再写 `:deep`）。

列表页推荐骨架：

```vue
<div class="page-fill">
  <PageContainer>
    <template #search>
      <BasicForm ref="formRef" v-model="filters" :schemas="schemas" :columns="3" />
      <el-button type="primary" @click="tableRef?.restReload()">查询</el-button>
      <el-button @click="onReset">重置</el-button>
    </template>
    <template #main>
      <BasicTable
        ref="tableRef"
        v-model:columns="columns"
        :request="loadDataTable"
        :pagination="true"
        :toolbar-config="{ refresh: true, custom: true }"
        stripe
      />
    </template>
  </PageContainer>
</div>
```

**视口**：`PageTabs` 优先放在 `.page-scroll` 外。有图/表可吃高度的面板加 `.page-pane`；短文案面板不要硬撑 Sheet。细则见 `frontend/AGENTS.md` §3.7.1。

扩展：新交互原子先确认「去掉业务名词仍成立」再放本目录；只服务单一 bc 的放 `features/<bc>/components`。
