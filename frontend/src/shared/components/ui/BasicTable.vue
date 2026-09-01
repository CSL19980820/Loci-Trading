<script setup lang="ts">
import { computed, onMounted, onUnmounted, provide, reactive, ref, shallowRef, useAttrs, useSlots, watch } from 'vue'
import type { TableInstance } from 'element-plus'
import { RefreshRight, Setting } from '@element-plus/icons-vue'

import BasicTableColumns from './BasicTableColumns.vue'
import BasicTableVirtual from './BasicTableVirtual.vue'
import { createSpanMethod } from './basicTableMerge'
import { canVirtualizeBasicTable } from './basicTableVirtualSupport'
import type {
  BasicTableColumn,
  BasicTableEditConfig,
  BasicTablePagination,
  BasicTableRequest,
  BasicTableToolbarConfig,
} from './basicTableTypes'

export type {
  BasicTableColumn,
  BasicTableEditConfig,
  BasicTablePagination,
  BasicTableRequest,
  BasicTableToolbarConfig,
} from './basicTableTypes'

defineOptions({ inheritAttrs: false })

const columns = defineModel<BasicTableColumn[]>('columns', { default: () => [] })

defineSlots<{
  toolbarButtons?: () => unknown
  [name: string]: ((props: {
    row: Record<string, unknown>
    prop?: string
    index?: number
  }) => unknown) | undefined
}>()

const props = withDefaults(
  defineProps<{
    dataSource?: Record<string, unknown>[]
    request?: BasicTableRequest
    pagination?: BasicTablePagination | boolean
    hasDefaultRequest?: boolean
    offsetHeight?: number
    mergeField?: string[]
    editConfig?: BasicTableEditConfig
    rowKey?: string | ((row: Record<string, unknown>) => string)
    stripe?: boolean
    border?: boolean
    size?: 'large' | 'default' | 'small'
    height?: string | number
    maxHeight?: string | number
    emptyText?: string
    toolbarConfig?: BasicTableToolbarConfig
    loading?: boolean
    virtualized?: boolean
    rowClassName?: string | ((data: { row: Record<string, unknown>; rowIndex: number }) => string)
  }>(),
  {
    dataSource: () => [],
    hasDefaultRequest: true,
    offsetHeight: 0,
    mergeField: () => [],
    editConfig: () => ({}),
    stripe: false,
    border: false,
    size: 'small',
    emptyText: '没有匹配的记录',
    pagination: () => ({}),
  },
)

const emit = defineEmits<{
  'cell-click': [row: Record<string, unknown>, column: unknown, cell: HTMLElement, event: Event]
  'row-click': [row: Record<string, unknown>, column: unknown, event: Event]
  'selection-change': [selection: Record<string, unknown>[]]
  'current-change': [page: number]
  'size-change': [size: number]
  refresh: []
}>()

const attrs = useAttrs()
const slots = useSlots()
provide('basicTableSlots', slots)
const tableRef = ref<TableInstance>()
const virtualTableRef = ref<InstanceType<typeof BasicTableVirtual>>()
// shallowRef：几千行的业务表不必再被本组件深度代理一层。写入全是整表替换
// （见下方两处 `rows.value = …`）；行内字段的响应式由父层自己的 ref 提供。
const rows = shallowRef<Record<string, unknown>[]>([])
const innerLoading = ref(false)
const zoomed = ref(false)
const autoHeight = ref<number | undefined>()
const editRowKey = ref('')
const editColumn = ref<unknown>(null)
let requestGeneration = 0

const pager = reactive({
  currentPage: 1,
  pageSize: 20,
  total: 0,
})

const showPager = computed(() => props.pagination !== false)

const pagerOpts = computed(() => {
  const base =
    typeof props.pagination === 'object' && props.pagination
      ? props.pagination
      : ({} as BasicTablePagination)
  return {
    pageSizes: base.pageSizes ?? [10, 20, 30, 40, 50, 80],
    layout: base.layout ?? 'total, sizes, prev, pager, next, jumper',
    background: base.background ?? true,
    hideOnSinglePage: base.hideOnSinglePage ?? false,
  }
})

const showToolbar = computed(
  () =>
    Boolean(
      // slots checked in template; config flags here
      props.toolbarConfig?.refresh || props.toolbarConfig?.zoom || props.toolbarConfig?.custom,
    ),
)

const busy = computed(() => props.loading || innerLoading.value)

const resolvedHeight = computed(() => props.height ?? autoHeight.value)

const spanMethod = computed(() =>
  createSpanMethod(props.mergeField ?? [], rows.value, columns.value),
)

const useVirtualized = computed(() => {
  return (
    props.virtualized &&
    canVirtualizeBasicTable(columns.value, props.mergeField ?? [], props.rowKey)
  )
})

const customizableColumns = computed(() =>
  columns.value.filter((c) => c.type !== 'selection' && c.type !== 'index' && c.type !== 'expand'),
)

// 依赖只需要「数组换了」或「长度变了」；原来的 deep 会在每次触发时遍历
// 全部行的每个字段（几千行 × 几十列），而回调根本不读字段值。
// 元素级改动仍由父层自己的 ref 驱动重渲染，不经这个 watch。
watch(
  [() => props.dataSource, () => props.dataSource?.length],
  ([list]) => {
    if (props.request) return
    rows.value = list ?? []
    pager.total =
      typeof props.pagination === 'object' && props.pagination?.total != null
        ? props.pagination.total
        : (list?.length ?? 0)
  },
  { immediate: true },
)

// 只有三个标量字段，逐个监听即可，不必深遍历整个对象。
watch(
  () => {
    const p = typeof props.pagination === 'object' ? props.pagination : null
    return p ? [p.currentPage, p.pageSize, p.total] : null
  },
  (values) => {
    if (!values) return
    const [currentPage, pageSize, total] = values
    if (currentPage != null) pager.currentPage = currentPage
    if (pageSize != null) pager.pageSize = pageSize
    if (total != null) pager.total = total
  },
  { immediate: true },
)

async function fetch(opt: Record<string, unknown> = {}, resetPage = false): Promise<void> {
  if (!props.request) return
  if (resetPage) pager.currentPage = 1
  const generation = ++requestGeneration
  innerLoading.value = true
  try {
    const result = await props.request({
      ...opt,
      currentPage: pager.currentPage,
      pageSize: pager.pageSize,
    })
    if (generation !== requestGeneration) return
    rows.value = result.list
    pager.total = result.total
  } finally {
    if (generation === requestGeneration) innerLoading.value = false
  }
}

function reloadTable(opt: Record<string, unknown> = {}): Promise<void> {
  return fetch(opt, false)
}

function restReload(opt: Record<string, unknown> = {}): Promise<void> {
  return fetch(opt, true)
}

function onPageChange(page: number): void {
  pager.currentPage = page
  emit('current-change', page)
  if (props.request) void fetch()
}

function onSizeChange(size: number): void {
  pager.pageSize = size
  pager.currentPage = 1
  emit('size-change', size)
  if (props.request) void fetch()
}

function resolveRowKey(row: Record<string, unknown>): string {
  if (typeof props.rowKey === 'function') return props.rowKey(row)
  if (typeof props.rowKey === 'string') return String(row[props.rowKey] ?? '')
  return String(row.id ?? '')
}

function isEditByRow(row: Record<string, unknown>): boolean {
  return editRowKey.value !== '' && resolveRowKey(row) === editRowKey.value
}

function setEditRow(row: Record<string, unknown>, column?: unknown): void {
  editRowKey.value = resolveRowKey(row)
  editColumn.value = column ?? null
}

function clearEdit(): void {
  editRowKey.value = ''
  editColumn.value = null
}

function getRowEdit(): { rowKey: string; column: unknown } {
  return { rowKey: editRowKey.value, column: editColumn.value }
}

function onRowClick(row: Record<string, unknown>, column: unknown, event: Event): void {
  emit('row-click', row, column, event)
}

function onCellClick(
  row: Record<string, unknown>,
  column: unknown,
  cell: HTMLElement,
  event: Event,
): void {
  emit('cell-click', row, column, cell, event)
  if (props.editConfig?.trigger !== 'click') return
  const rowIndex = rows.value.indexOf(row)
  const ok = props.editConfig.beforeEditMethod?.({ row, column, rowIndex }) ?? true
  if (ok) setEditRow(row, column)
}

function onSelectionChange(selection: Record<string, unknown>[]): void {
  emit('selection-change', selection)
}

function onVirtualRowClick(row: Record<string, unknown>, event: Event): void {
  onRowClick(row, undefined, event)
}

function onUpdateField(row: Record<string, unknown>, prop: string, value: unknown): void {
  row[prop] = value
}

function onToolbarRefresh(): void {
  emit('refresh')
  if (props.request) void restReload()
}

function calcOffsetHeight(): void {
  if (!props.offsetHeight) {
    autoHeight.value = undefined
    return
  }
  autoHeight.value = Math.max(120, window.innerHeight - props.offsetHeight)
}

// 注册/移除都必须无条件：以前两边都包在 `if (props.offsetHeight)` 里，
// prop 在生命周期中间变化（0 → 非 0 或反过来）就会漏掉一次 remove，监听器永久泄漏。
// calcOffsetHeight 自己在 offsetHeight 为空时会置空高度，所以空跑无副作用。
onMounted(() => {
  calcOffsetHeight()
  window.addEventListener('resize', calcOffsetHeight)
  if (props.request && props.hasDefaultRequest) void fetch()
})

onUnmounted(() => {
  requestGeneration += 1
  window.removeEventListener('resize', calcOffsetHeight)
})

watch(() => props.offsetHeight, calcOffsetHeight)

function clearSelection(): void {
  if (useVirtualized.value) {
    virtualTableRef.value?.clearSelection()
    return
  }
  tableRef.value?.clearSelection()
}

function doLayout(): void {
  tableRef.value?.doLayout()
  virtualTableRef.value?.doLayout()
}

defineExpose({
  fetch,
  reloadTable,
  restReload,
  setPagination: (info: Partial<typeof pager>) => Object.assign(pager, info),
  getTableData: () => rows.value,
  doLayout,
  setEditRow,
  clearEdit,
  getRowEdit,
  isEditByRow,
  clearSelection,
  getTableRef: () => virtualTableRef.value?.getTableRef() ?? tableRef.value,
})
</script>

<template>
  <div class="basic-table" :class="{ 'basic-table--zoom': zoomed }">
    <div
      v-if="$slots.toolbarButtons || showToolbar"
      class="basic-table__toolbar"
    >
      <div class="basic-table__toolbar-left">
        <slot name="toolbarButtons" />
      </div>
      <div class="basic-table__toolbar-right">
        <el-button
          v-if="toolbarConfig?.refresh"
          size="small"
          :icon="RefreshRight"
          :loading="busy"
          @click="onToolbarRefresh"
        >
          刷新
        </el-button>
        <el-button
          v-if="toolbarConfig?.zoom"
          size="small"
          @click="zoomed = !zoomed"
        >
          {{ zoomed ? '还原' : '放大' }}
        </el-button>
        <el-popover
          v-if="toolbarConfig?.custom"
          placement="bottom-end"
          :width="200"
          trigger="click"
        >
          <template #reference>
            <el-button size="small" :icon="Setting">列设置</el-button>
          </template>
          <div class="basic-table__cols">
            <el-checkbox
              v-for="(col, i) in customizableColumns"
              :key="col.prop ?? col.label ?? i"
              :model-value="!col.hidden"
              @change="(v: string | number | boolean) => { col.hidden = !v }"
            >
              {{ col.label || col.prop || `列${i + 1}` }}
            </el-checkbox>
          </div>
        </el-popover>
      </div>
    </div>

    <div class="basic-table__body" v-loading="busy">
      <BasicTableVirtual
        v-if="useVirtualized"
        ref="virtualTableRef"
        :columns="columns"
        :rows="rows"
        :row-key="typeof rowKey === 'string' ? rowKey : 'id'"
        :empty-text="emptyText"
        :border="border"
        :stripe="stripe"
        :size="size"
        :max-height="maxHeight"
        :row-class-name="rowClassName"
        :is-editing="isEditByRow"
        v-bind="attrs"
        @row-click="onVirtualRowClick"
        @cell-click="onCellClick"
        @selection-change="onSelectionChange"
        @update:field="onUpdateField"
      />
      <el-table
        v-else
        ref="tableRef"
        :data="rows"
        :stripe="stripe"
        :border="border"
        :size="size"
        :height="resolvedHeight"
        :max-height="maxHeight"
        :row-key="rowKey ? resolveRowKey : undefined"
        :row-class-name="rowClassName"
        :empty-text="emptyText"
        :span-method="spanMethod"
        class="basic-table__el"
        v-bind="attrs"
        @row-click="onRowClick"
        @cell-click="onCellClick"
        @selection-change="onSelectionChange"
      >
        <BasicTableColumns
          :columns="columns"
          :is-editing="isEditByRow"
          @update:field="onUpdateField"
        />
      </el-table>
    </div>

    <div
      v-if="showPager && (!pagerOpts.hideOnSinglePage || pager.total > pager.pageSize)"
      class="basic-table__foot"
    >
      <el-pagination
        v-model:current-page="pager.currentPage"
        v-model:page-size="pager.pageSize"
        :total="pager.total"
        :page-sizes="pagerOpts.pageSizes"
        :layout="pagerOpts.layout"
        :background="pagerOpts.background"
        size="small"
        @current-change="onPageChange"
        @size-change="onSizeChange"
      />
    </div>
  </div>
</template>

<style scoped>
/*
 * 不写 height: 100%。在弹性父级里 flex:1 1 auto 已经能吃满高度；
 * 而在普通块级父级（如账本持仓卡）里，100% 会把只有几行的表撑成整屏，
 * 把后面的兄弟节点顶出父级 overflow:hidden 之外——账本页的「交割绩效 /
 * 月度盈亏」曾因此被整块裁掉且无法滚动到。
 */
.basic-table {
  display: flex;
  flex-direction: column;
  min-height: 0;
  flex: 1 1 auto;
  background: transparent;
}

/*
 * 放大态：整屏浮层。不加投影——终端里的层级靠边框与底色区分（D3 卡片无阴影），
 * 一圈 40px 的模糊阴影只会让下面的行看起来发灰。
 */
.basic-table--zoom {
  position: fixed;
  inset: var(--gap-2);
  z-index: 50;
  padding: var(--gap-2);
  background: var(--sheet);
  border: 1px solid var(--rule-strong);
  border-radius: var(--radius);
}

.basic-table__toolbar {
  display: flex;
  justify-content: flex-start;
  align-items: center;
  gap: var(--gap-2);
  padding: var(--gap-1) var(--pad-sheet-x);
  border-bottom: 1px solid var(--rule);
  background: var(--sheet-alt);
  flex-shrink: 0;
}

.basic-table__toolbar-left,
.basic-table__toolbar-right {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: var(--gap-2);
}

.basic-table__toolbar-right {
  margin-left: auto;
}

.basic-table__toolbar-left :deep(.el-button),
.basic-table__toolbar-right :deep(.el-button) {
  margin: 0;
}

.basic-table__toolbar-left :deep(.el-button + .el-button),
.basic-table__toolbar-right :deep(.el-button + .el-button) {
  margin-left: 0;
}

.basic-table__toolbar-right :deep(.el-button) {
  --el-button-bg-color: var(--sheet);
  --el-button-border-color: var(--rule-strong);
  --el-button-text-color: var(--ink);
  --el-button-hover-bg-color: var(--sheet-alt);
  --el-button-hover-border-color: var(--rule-strong);
  --el-button-hover-text-color: var(--ink);
}

.basic-table__cols {
  display: flex;
  flex-direction: column;
  gap: var(--gap-1);
  max-height: 16rem;
  overflow: auto;
}

.basic-table__body {
  flex: 1 1 auto;
  min-height: 0;
  overflow: auto;
}

/* 表格皮肤的真相在 style.components.css（el-table 与 BasicTable 同一套）；
   这里只补作用域内必须的几项：行高、表头字色、贴边 padding。 */
.basic-table__el {
  width: 100%;
  --el-table-header-bg-color: var(--sheet-alt);
  --el-table-row-hover-bg-color: var(--seal-soft);
  --el-table-border-color: var(--rule);
  background: transparent;
}

.basic-table__el :deep(.el-table__header-wrapper th.el-table__cell) {
  height: var(--head-h);
  background: var(--sheet-alt);
  color: var(--muted);
  font-size: var(--fs-aux);
  font-weight: 600;
  text-align: center;
}

.basic-table__el :deep(.el-table__body td.el-table__cell) {
  height: var(--row-h);
  padding: var(--gap-1) 0;
  text-align: center;
}

.basic-table__el :deep(.el-table__header .cell),
.basic-table__el :deep(.el-table__body .cell) {
  padding-left: var(--gap-2);
  padding-right: var(--gap-2);
  text-align: center;
}

.basic-table__el :deep(.el-table__cell.is-left .cell) {
  text-align: left;
}

.basic-table__el :deep(.el-table__cell.is-right .cell) {
  text-align: right;
}

.basic-table__el :deep(.el-table__row--striped td.el-table__cell) {
  background: var(--sheet-alt);
}

.basic-table__el :deep(.el-table__inner-wrapper::before) {
  background-color: var(--rule);
}

/* D1：表内只有这三类语义可以上红绿 */
.basic-table__el :deep(.is-up) {
  color: var(--up);
}

.basic-table__el :deep(.is-down) {
  color: var(--down);
}

.basic-table__el :deep(.is-flat) {
  color: var(--flat);
}

.basic-table__el :deep(.is-frozen) {
  color: var(--mist);
}

.basic-table__foot {
  flex-shrink: 0;
  display: flex;
  justify-content: flex-end;
  padding: var(--gap-1) var(--pad-sheet-x);
  border-top: 1px solid var(--rule);
  background: var(--sheet);
}

.basic-table__foot :deep(.el-pagination) {
  flex-wrap: wrap;
  justify-content: flex-end;
}
</style>
