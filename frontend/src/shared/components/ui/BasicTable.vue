<script setup lang="ts">
import { computed, onMounted, onUnmounted, provide, reactive, ref, useAttrs, useSlots, watch } from 'vue'
import type { TableInstance } from 'element-plus'
import { RefreshRight, Setting } from '@element-plus/icons-vue'

import BasicTableColumns from './BasicTableColumns.vue'
import { createSpanMethod } from './basicTableMerge'
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
    emptyText: '暂无数据',
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
const rows = ref<Record<string, unknown>[]>([])
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

const customizableColumns = computed(() =>
  columns.value.filter((c) => c.type !== 'selection' && c.type !== 'index' && c.type !== 'expand'),
)

watch(
  () => props.dataSource,
  (list) => {
    if (props.request) return
    rows.value = list ?? []
    pager.total =
      typeof props.pagination === 'object' && props.pagination?.total != null
        ? props.pagination.total
        : (list?.length ?? 0)
  },
  { immediate: true, deep: true },
)

watch(
  () => (typeof props.pagination === 'object' ? props.pagination : null),
  (p) => {
    if (!p) return
    if (p.currentPage != null) pager.currentPage = p.currentPage
    if (p.pageSize != null) pager.pageSize = p.pageSize
    if (p.total != null) pager.total = p.total
  },
  { immediate: true, deep: true },
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

onMounted(() => {
  calcOffsetHeight()
  if (props.offsetHeight) window.addEventListener('resize', calcOffsetHeight)
  if (props.request && props.hasDefaultRequest) void fetch()
})

onUnmounted(() => {
  requestGeneration += 1
  if (props.offsetHeight) window.removeEventListener('resize', calcOffsetHeight)
})

defineExpose({
  fetch,
  reloadTable,
  restReload,
  setPagination: (info: Partial<typeof pager>) => Object.assign(pager, info),
  getTableData: () => rows.value,
  doLayout: () => tableRef.value?.doLayout(),
  setEditRow,
  clearEdit,
  getRowEdit,
  isEditByRow,
  getTableRef: () => tableRef.value,
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
      <el-table
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
.basic-table {
  display: flex;
  flex-direction: column;
  min-height: 0;
  flex: 1 1 auto;
  height: 100%;
  background: transparent;
}

.basic-table--zoom {
  position: fixed;
  inset: 0.75rem;
  z-index: 50;
  padding: 0.75rem;
  background: var(--sheet);
  border: 1px solid var(--rule);
  border-radius: var(--radius);
  box-shadow: 0 12px 40px rgba(20, 32, 51, 0.12);
}

.basic-table__toolbar {
  display: flex;
  justify-content: flex-start;
  align-items: center;
  gap: 0.5rem;
  padding: 0.5rem 1rem;
  border-bottom: 1px solid var(--rule);
  background: var(--panel-2);
  flex-shrink: 0;
}

.basic-table__toolbar-left,
.basic-table__toolbar-right {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 8px;
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
  --el-button-border-color: var(--line-2);
  --el-button-text-color: var(--ink);
  --el-button-hover-bg-color: var(--panel-2);
  --el-button-hover-border-color: var(--line-2);
  --el-button-hover-text-color: var(--ink);
}

.basic-table__cols {
  display: flex;
  flex-direction: column;
  gap: 0.35rem;
  max-height: 16rem;
  overflow: auto;
}

.basic-table__body {
  flex: 1 1 auto;
  min-height: 0;
  overflow: auto;
}

.basic-table__el {
  width: 100%;
  --el-table-header-bg-color: var(--panel-2);
  --el-table-row-hover-bg-color: color-mix(in srgb, var(--panel-2) 70%, var(--sheet));
  --el-table-border-color: var(--rule);
  background: transparent;
}

.basic-table__el :deep(.el-table__header-wrapper th.el-table__cell) {
  background: var(--panel-2);
  color: var(--mist);
  font-weight: 600;
}

.basic-table__el :deep(.el-table__header .el-table__cell),
.basic-table__el :deep(.el-table__body .el-table__cell) {
  padding-left: 0.75rem;
  padding-right: 0.65rem;
}

.basic-table__el :deep(.el-table__row--striped td.el-table__cell) {
  background: color-mix(in srgb, var(--panel-2) 55%, var(--sheet));
}

.basic-table__el :deep(.el-table__inner-wrapper::before) {
  background-color: var(--rule);
}

.basic-table__el :deep(.is-up) {
  color: var(--up);
}

.basic-table__el :deep(.is-down) {
  color: var(--down);
}

.basic-table__el :deep(.is-frozen) {
  color: var(--mist);
}

.basic-table__foot {
  flex-shrink: 0;
  display: flex;
  justify-content: flex-end;
  padding: 0.45rem 1rem;
  border-top: 1px solid var(--rule);
  background: var(--sheet);
}

.basic-table__foot :deep(.el-pagination) {
  flex-wrap: wrap;
  justify-content: flex-end;
}
</style>
