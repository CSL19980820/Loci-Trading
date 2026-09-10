<script setup lang="ts">
/**
 * 全站表格契约。本文件只做三件事：收 props / 拼装、把事件原样转发出去、
 * 编排「工具行 — 表体 — 分页器」三段版型。
 *
 * 真正有状态的三块各自成文件，改动前先看它们头部的说明：
 *   useBasicTableSource —— 取数、分页与请求世代（并发丢弃旧响应）
 *   useBasicTableEdit —— 行内编辑态与行主键口径
 *   useBasicTableHeight —— offsetHeight 自适应与 resize 监听对称性
 */
import { computed, provide, ref, useAttrs, useSlots } from 'vue'
import type { TableInstance } from 'element-plus'

import BasicTableColumns from './BasicTableColumns.vue'
import BasicTableToolbar from './BasicTableToolbar.vue'
import BasicTableVirtual from './BasicTableVirtual.vue'
import { createSpanMethod } from './basicTableMerge'
import { canVirtualizeBasicTable } from './basicTableVirtualSupport'
import { useBasicTableEdit } from './useBasicTableEdit'
import { useBasicTableHeight } from './useBasicTableHeight'
import { useBasicTableSource } from './useBasicTableSource'
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
const zoomed = ref(false)

// 注册顺序即生命周期钩子的调用顺序：高度先算（onMounted 里 calcOffsetHeight 在前），
// 再发默认请求——与拆分前组件内那一个 onMounted 的语义一致。
const { autoHeight } = useBasicTableHeight(props)
const { rows, innerLoading, pager, showPager, pagerOpts, fetch, reloadTable, restReload } =
  useBasicTableSource(props)
const { resolveRowKey, isEditByRow, setEditRow, clearEdit, getRowEdit } = useBasicTableEdit(props)

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
    <BasicTableToolbar
      v-if="$slots.toolbarButtons || showToolbar"
      v-model:zoomed="zoomed"
      :config="toolbarConfig"
      :columns="columns"
      :busy="busy"
      @refresh="onToolbarRefresh"
    >
      <template #buttons>
        <slot name="toolbarButtons" />
      </template>
    </BasicTableToolbar>

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
