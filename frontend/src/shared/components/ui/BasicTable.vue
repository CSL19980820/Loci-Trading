<script setup lang="ts">
import { type GridHandle } from '@/shared/components/ui/app/gridTypes'
import { vBusy } from '@/shared/directives/busy'
import { default as DataGrid } from '@/shared/components/ui/app/DataGrid.vue'
import { default as Pager } from '@/shared/components/ui/app/Pager.vue'

/**
 * 全站表格契约。本文件只做三件事：收 props / 拼装、把事件原样转发出去、
 * 编排「工具行 — 表体 — 分页器」三段版型。
 *
 * 真正有状态的三块各自成文件，改动前先看它们头部的说明：
 * useBasicTableSource —— 取数、分页与请求世代（并发丢弃旧响应）
 * useBasicTableEdit —— 行内编辑态与行主键口径
 * useBasicTableHeight —— offsetHeight 自适应与 resize 监听对称性
 */
import { computed, provide, ref, useAttrs, useSlots } from 'vue'


import BasicTableCell from './BasicTableCell.vue'
import BasicTableToolbar from './BasicTableToolbar.vue'
import BasicTableVirtual from './BasicTableVirtual.vue'
import EmptyState from './EmptyState.vue'

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
  empty?: () => unknown
  [name: string]: ((props: {
    row: Record<string, unknown>
    prop?: string
    index?: number
  }) => unknown) | undefined
}>()

const props = withDefaults(
  defineProps<{
    dataSource?: object[]
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
    emptyReason?: string
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
const tableRef = ref<GridHandle>()
const virtualTableRef = ref<InstanceType<typeof BasicTableVirtual>>()
const bodyRef = ref<HTMLElement>()
const zoomed = ref(false)

const fillParent = computed(() => props.height === '100%' || props.height === '100')

// 注册顺序即生命周期钩子的调用顺序：高度先算（onMounted 里 calcOffsetHeight 在前），
// 再发默认请求——与拆分前组件内那一个 onMounted 的语义一致。
const { autoHeight, fillHeight } = useBasicTableHeight(props, {
  bodyRef,
  fillParent: () => fillParent.value && !zoomed.value,
})
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

const resolvedHeight = computed(() => {
  if (fillParent.value && !zoomed.value) return fillHeight.value
  return props.height ?? autoHeight.value
})

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
  <div class="basic-table" :class="{ 'basic-table--zoom': zoomed, 'basic-table--fill': fillParent && !zoomed }">
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

    <div ref="bodyRef" class="basic-table__body" v-busy="busy">
      <BasicTableVirtual
        v-if="useVirtualized"
        ref="virtualTableRef"
        :columns="columns"
        :rows="rows"
        :row-key="typeof rowKey === 'string' ? rowKey : 'id'"
        :empty-text="emptyText"
        :empty-reason="emptyReason"
        :border="border"
        :stripe="stripe"
        :size="size"
        :max-height="maxHeight"
        :height="resolvedHeight"
        :row-class-name="rowClassName"
        :is-editing="isEditByRow"
        v-bind="attrs"
        @row-click="onVirtualRowClick"
        @cell-click="onCellClick"
        @selection-change="onSelectionChange"
        @update:field="onUpdateField"
      >
        <template #empty>
          <slot name="empty">
            <EmptyState :description="emptyText" :reason="emptyReason" />
          </slot>
        </template>
      </BasicTableVirtual>
      <DataGrid
        v-else
        ref="tableRef"
        :data="rows"
        :columns="columns"
        :stripe="stripe"
        :border="border"
        :size="size"
        :height="resolvedHeight"
        :max-height="maxHeight"
        :row-key="rowKey ? resolveRowKey : undefined"
        :row-class-name="rowClassName"
        :empty-text="emptyText"
        :span-method="spanMethod"
        class="basic-table__grid"
        v-bind="attrs"
        @row-click="onRowClick"
        @cell-click="onCellClick"
        @selection-change="onSelectionChange"
      >
        <template #cell="{ row, column, index }">
          <BasicTableCell :col="column" :row="row" :index="index" :editing="isEditByRow(row)"
            @update:field="(prop, value) => onUpdateField(row, prop, value)" />
        </template>
        <template #empty>
          <slot name="empty">
            <EmptyState :description="emptyText" :reason="emptyReason" />
          </slot>
        </template>
      </DataGrid>
    </div>

    <div
      v-if="showPager && (!pagerOpts.hideOnSinglePage || pager.total > pager.pageSize)"
      class="basic-table__foot"
    >
      <Pager
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
.basic-table { display:flex; flex-direction:column; min-height:0; flex:1 1 auto; background:transparent; }
.basic-table--fill { height:100%; }
.basic-table--fill .basic-table__body { height:0; background:var(--surface); }
.basic-table--fill :deep(.data-grid) { height:100%; background:var(--surface); }
.basic-table--zoom { position:fixed; inset:var(--gap-4); z-index:var(--z-table-zoom); padding:var(--gap-2); background:var(--surface-raised); border:1px solid var(--border-subtle); border-radius:var(--radius-xl); box-shadow:var(--shadow-lg); }
.basic-table__body { flex:1 1 auto; min-height:0; overflow:hidden; }
.basic-table__foot { flex-shrink:0; display:flex; justify-content:flex-end; padding:5px 0 0; background:transparent; }
.basic-table__foot :deep(.pager) { justify-content:flex-end; margin-top:0; }
.basic-table__grid :deep(.is-up) { color:var(--up); }
.basic-table__grid :deep(.is-down) { color:var(--down); }
.basic-table__grid :deep(.is-flat) { color:var(--flat); }
.basic-table__grid :deep(.is-frozen) { color:var(--text-tertiary); }
@media (max-width: 640px) {
  .basic-table--zoom { inset:0; border-radius:0; }
  .basic-table__foot { justify-content:center; padding:5px 0 0; }
}
</style>
