<script setup lang="ts">
import { computed, h, ref, watch } from 'vue'
import {
  ElCheckbox,
  TableV2FixedDir,
  type Column,
  type RowEventHandler,
  type TableV2Instance,
} from 'element-plus'

import BasicTableCell from './BasicTableCell.vue'
import EmptyState from './EmptyState.vue'
import type { BasicTableColumn } from './basicTableTypes'
import { distributeVirtualColumnWidths } from './basicTableVirtualSupport'

type BasicRow = Record<string, unknown>

defineSlots<{
  empty?: () => unknown
}>()

const props = defineProps<{
  columns: BasicTableColumn[]
  rows: BasicRow[]
  rowKey: string
  emptyText: string
  emptyReason?: string
  border: boolean
  stripe: boolean
  size: 'large' | 'default' | 'small'
  maxHeight?: string | number
  rowClassName?: string | ((data: { row: BasicRow; rowIndex: number }) => string)
  isEditing: (row: BasicRow) => boolean
}>()

const emit = defineEmits<{
  'row-click': [row: BasicRow, event: Event]
  'cell-click': [row: BasicRow, column: BasicTableColumn, cell: HTMLElement, event: Event]
  'selection-change': [selection: BasicRow[]]
  'update:field': [row: BasicRow, prop: string, value: unknown]
}>()

const tableRef = ref<TableV2Instance>()
const selectedKeys = ref(new Set<string>())

const visibleColumns = computed(() => props.columns.filter((column) => !column.hidden))

const rowHeight = computed(() => {
  if (props.size === 'large') return 48
  if (props.size === 'default') return 40
  return 32
})

/* 与 --head-h（30px）对齐；large 才跟 48 行高走。勿写 40，会比实体表头高出一截。 */
const headerHeight = computed(() => (props.size === 'large' ? 48 : 30))

const numericMaxHeight = computed(() => {
  if (typeof props.maxHeight === 'number') return props.maxHeight
  if (!props.maxHeight) return undefined
  const parsed = Number.parseFloat(props.maxHeight)
  return Number.isFinite(parsed) ? parsed : undefined
})

const hasFixedColumns = computed(() => visibleColumns.value.some((column) => Boolean(column.fixed)))

function rowKeyOf(row: BasicRow): string {
  return String(row[props.rowKey] ?? '')
}

function columnKeyOf(column: BasicTableColumn, index: number): string {
  return `${column.prop ?? column.type ?? column.label ?? 'column'}-${index}`
}

function fixedDirectionOf(
  fixed: BasicTableColumn['fixed'],
): true | TableV2FixedDir | undefined {
  if (fixed === true) return true
  if (fixed === 'left') return TableV2FixedDir.LEFT
  if (fixed === 'right') return TableV2FixedDir.RIGHT
  return undefined
}

function stopPropagation(event: Event): void {
  event.stopPropagation()
}

function selectedRows(): BasicRow[] {
  return props.rows.filter((row) => selectedKeys.value.has(rowKeyOf(row)))
}

function emitSelection(): void {
  emit('selection-change', selectedRows())
}

function updateRowSelection(row: BasicRow, checked: boolean): void {
  const key = rowKeyOf(row)
  if (!key) return
  const next = new Set(selectedKeys.value)
  if (checked) next.add(key)
  else next.delete(key)
  selectedKeys.value = next
  emitSelection()
}

function updateAllSelection(checked: boolean): void {
  selectedKeys.value = checked ? new Set(props.rows.map(rowKeyOf).filter(Boolean)) : new Set()
  emitSelection()
}

const allSelected = computed(
  () => props.rows.length > 0 && props.rows.every((row) => selectedKeys.value.has(rowKeyOf(row))),
)
const hasSelected = computed(() => props.rows.some((row) => selectedKeys.value.has(rowKeyOf(row))))

function selectionCell(row: BasicRow, rowIndex: number) {
  return h(
    'div',
    {
      class: 'basic-table__virtual-selection',
      onClick: stopPropagation,
      onKeydown: stopPropagation,
    },
    [
      h(ElCheckbox, {
        modelValue: selectedKeys.value.has(rowKeyOf(row)),
        ariaLabel: `选择第 ${rowIndex + 1} 行`,
        onChange: (value: unknown) => updateRowSelection(row, value === true),
      }),
    ],
  )
}

function selectionHeaderCell() {
  return h(ElCheckbox, {
    modelValue: allSelected.value,
    indeterminate: hasSelected.value && !allSelected.value,
    ariaLabel: '选择全部行',
    onChange: (value: unknown) => updateAllSelection(value === true),
  })
}

function displayTitle(column: BasicTableColumn, row: BasicRow): string | undefined {
  if (!column.showOverflowTooltip) return undefined
  if (column.formatter) return column.formatter(row)
  if (column.prop) return String(row[column.prop] ?? '')
  return undefined
}

function cellClickHandler(
  row: BasicRow,
  column: BasicTableColumn,
  event: Event,
): void {
  const currentTarget = event.currentTarget
  if (!(currentTarget instanceof HTMLElement)) return
  emit('cell-click', row, column, currentTarget, event)
}

function dataCell(column: BasicTableColumn, row: BasicRow, rowIndex: number) {
  const align = column.align ?? 'center'
  const justifyContent = align === 'left' ? 'flex-start' : align === 'right' ? 'flex-end' : 'center'
  return h(
    'div',
    {
      class: 'basic-table__virtual-cell',
      style: { justifyContent },
      title: displayTitle(column, row),
      onClick: (event: Event) => cellClickHandler(row, column, event),
    },
    [
      h(BasicTableCell, {
        col: column,
        row,
        index: rowIndex,
        editing: props.isEditing(row) && !!column.editRender,
        'onUpdate:field': (prop: string, value: unknown) => emit('update:field', row, prop, value),
      }),
    ],
  )
}

function virtualColumn(
  column: BasicTableColumn,
  index: number,
  width: number,
): Column<BasicRow> {
  const key = columnKeyOf(column, index)
  const base = {
    key,
    dataKey: column.prop ?? key,
    title: column.label,
    width,
    flexGrow: 0,
    flexShrink: 0,
    align: column.align ?? 'center',
    fixed: fixedDirectionOf(column.fixed),
  } satisfies Partial<Column<BasicRow>>

  if (column.type === 'selection') {
    return {
      ...base,
      headerCellRenderer: selectionHeaderCell,
      cellRenderer: ({ rowData, rowIndex }) => selectionCell(rowData as BasicRow, rowIndex),
    }
  }
  if (column.type === 'index') {
    return {
      ...base,
      cellRenderer: ({ rowIndex }) => h('span', rowIndex + 1),
    }
  }
  return {
    ...base,
    cellRenderer: ({ rowData, rowIndex }) =>
      dataCell(column, rowData as BasicRow, rowIndex),
  }
}

function buildVirtualColumns(containerWidth: number): Column<BasicRow>[] {
  const cols = visibleColumns.value
  const widths = distributeVirtualColumnWidths(cols, containerWidth)
  return cols.map((column, index) => virtualColumn(column, index, widths[index] ?? 120))
}

const onRowClick: RowEventHandler = ({ rowData, event }) => {
  emit('row-click', rowData as BasicRow, event)
}

const rowEventHandlers = { onClick: onRowClick }

function rowClass(params: { rowData: BasicRow; rowIndex: number }): string {
  if (typeof props.rowClassName === 'function') {
    return props.rowClassName({ row: params.rowData, rowIndex: params.rowIndex })
  }
  return props.rowClassName ?? ''
}

function rowProps(params: { rowData: BasicRow; rowIndex: number }): Record<string, unknown> {
  return {
    tabindex: 0,
    'aria-rowindex': params.rowIndex + 2,
    onKeydown: (event: KeyboardEvent) => {
      const target = event.target as HTMLElement | null
      if (target?.closest('button,input,textarea,select,a,[role="button"]')) return
      if (event.key !== 'Enter' && event.key !== ' ') return
      event.preventDefault()
      emit('row-click', params.rowData, event)
    },
  }
}

watch(
  () => props.rows,
  (rows) => {
    const available = new Set(rows.map(rowKeyOf).filter(Boolean))
    const next = new Set([...selectedKeys.value].filter((key) => available.has(key)))
    if (next.size === selectedKeys.value.size) return
    selectedKeys.value = next
    emitSelection()
  },
)

function clearSelection(): void {
  if (!selectedKeys.value.size) return
  selectedKeys.value = new Set()
  emitSelection()
}

defineExpose({
  clearSelection,
  getTableRef: () => tableRef.value,
  doLayout: () => undefined,
})
</script>

<template>
  <div
    class="basic-table__virtual"
    :class="{
      'basic-table__virtual--border': border,
      'basic-table__virtual--stripe': stripe,
    }"
  >
    <el-auto-resizer class="basic-table__virtual-resizer">
      <template #default="{ height, width }">
        <el-table-v2
          ref="tableRef"
          :columns="buildVirtualColumns(width)"
          :data="rows"
          :width="Math.max(width, 1)"
          :height="Math.max(height, 1)"
          :max-height="numericMaxHeight"
          :row-key="rowKey"
          :row-height="rowHeight"
          :header-height="headerHeight"
          :fixed="hasFixedColumns"
          :row-class="rowClass"
          :row-props="rowProps"
          :row-event-handlers="rowEventHandlers"
          class="basic-table__virtual-el"
        >
          <template #empty>
            <slot name="empty">
              <EmptyState :description="emptyText" :reason="emptyReason" />
            </slot>
          </template>
        </el-table-v2>
      </template>
    </el-auto-resizer>
  </div>
</template>

<style scoped>
.basic-table__virtual {
  width: 100%;
  height: 100%;
  min-height: 0;
  flex: 1 1 auto;
  overflow: hidden;
  background-color: var(--surface);
  background-image: repeating-linear-gradient(
    to bottom,
    transparent 0,
    transparent calc(var(--row-h) - 1px),
    var(--rule-strong) calc(var(--row-h) - 1px),
    var(--rule-strong) var(--row-h)
  );
}

.basic-table__virtual-resizer {
  width: 100%;
  height: 100%;
  min-height: 0;
}

.basic-table__virtual-el {
  width: 100%;
  background: transparent;
}
.basic-table__virtual-el :deep(.el-table-v2__table),
.basic-table__virtual-el :deep(.el-table-v2__main),
.basic-table__virtual-el :deep(.el-table-v2__body),
.basic-table__virtual-el :deep(.el-vl__wrapper) {
  background: transparent;
}

.basic-table__virtual-el :deep(.el-table-v2__header-cell) {
  background: var(--sheet-alt);
  color: var(--muted);
  font-size: var(--fs-aux);
  font-weight: 400;
}

/* 组件内部层叠（冻结列压行），不进全局 --z-* 序列 */
.basic-table__virtual-el :deep(.el-table-v2__left),
.basic-table__virtual-el :deep(.el-table-v2__right) {
  z-index: 3;
}

.basic-table__virtual-el :deep(.el-table-v2__row-cell) {
  padding: 0 0.65rem;
  background-color: var(--surface);
}

/* 窄屏固定列不再悬浮盖字：阴影与背景收掉，列随表横滚 */
@media (max-width: 900px) {
  .basic-table__virtual-el :deep(.el-table-v2__left),
  .basic-table__virtual-el :deep(.el-table-v2__right) {
    box-shadow: none;
  }
}

.basic-table__virtual-el :deep(.el-table-v2__row:hover .el-table-v2__row-cell) {
  background-color: var(--surface-hover);
}

.basic-table__virtual--stripe :deep(.el-table-v2__row:nth-child(odd) .el-table-v2__row-cell) {
  background-color: var(--surface-canvas);
}

.basic-table__virtual--border :deep(.el-table-v2__row-cell),
.basic-table__virtual--border :deep(.el-table-v2__header-cell) {
  border-right: 1px solid var(--rule);
  border-bottom: 1px solid var(--rule);
}

/* 单元格容器只裁剪：省略只作用文本节点，按钮/tag/复选框不再被强制单行 */
.basic-table__virtual-cell {
  width: 100%;
  min-width: 0;
  display: flex;
  align-items: center;
  overflow: hidden;
}

.basic-table__virtual-cell :deep(.cell-text),
.basic-table__virtual-cell :deep(.pool-reason-text),
.basic-table__virtual-cell :deep(.el-table-v2__row-cell-text) {
  max-width: 100%;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.basic-table__virtual-selection {
  display: flex;
  align-items: center;
  justify-content: center;
  width: 100%;
  height: 100%;
}

.basic-table__virtual-el :deep([tabindex='0']:focus-visible) {
  outline: 2px solid var(--seal);
  outline-offset: -2px;
}
</style>
