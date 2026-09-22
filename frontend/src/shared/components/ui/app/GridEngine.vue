<script setup lang="ts">
import { computed, nextTick, ref, toRaw, useId, watch, type CSSProperties } from 'vue'
import { useElementSize } from '@vueuse/core'
import { createSortedRowModel, rowSelectionFeature, rowSortingFeature, sortFns, tableFeatures, useTable, type ColumnDef, type SortingState, type RowSelectionState } from '@tanstack/vue-table'
import { useVirtualizer } from '@tanstack/vue-virtual'
import { ArrowDown, ArrowUp, ArrowUpDown, ChevronRight, Filter } from '@lucide/vue'
import { Table, TableHeader, TableHead, TableBody, TableRow, TableCell } from '../table'
import { Button } from '../button'
import { Popover, PopoverTrigger, PopoverContent } from '../popover'
import CheckboxField from './CheckboxField.vue'
import { EmptyBlock } from './presentation'
import { cssLength } from './context'
import { VNodeContent } from './vnodeContent'
import { leafColumns, type GridColumn, type GridHandle, type GridProps, type GridRecord } from './gridTypes'

const props = withDefaults(defineProps<GridProps>(), { data: () => [], columns: () => [], size: 'small', emptyText: '暂无数据' })
const emit = defineEmits<{
  'row-click': [row: GridRecord, column: GridColumn | undefined, event: Event]
  'cell-click': [row: GridRecord, column: GridColumn, cell: HTMLElement, event: Event]
  'selection-change': [rows: GridRecord[]]
  'sort-change': [value: { column?: GridColumn; prop: string; order: string | null }]
}>()
const viewport = ref<HTMLElement>()
const { width } = useElementSize(viewport)
const sorting = ref<SortingState>(props.defaultSort ? [{ id: props.defaultSort.prop, desc: props.defaultSort.order === 'descending' }] : [])
const selected = ref<RowSelectionState>({})
const filters = ref<Record<string, unknown[]>>({})
const expanded = ref<Set<string>>(new Set())
const current = ref('')
const leaves = computed(() => leafColumns(props.columns))
const featureSet = tableFeatures({ rowSortingFeature, rowSelectionFeature, sortedRowModel: createSortedRowModel(), sortFns })
const rowHeight = computed(() => props.size === 'large' ? 48 : props.size === 'default' ? 40 : 34)
const minimumWidths = computed(() => leaves.value.map(column => Number.parseFloat(String(column.width ?? column.minWidth ?? (column.type ? 48 : 120))) || 120))
const widths = computed(() => {
  const min = minimumWidths.value
  const extra = Math.max(0, width.value - min.reduce((sum, value) => sum + value, 0))
  const flexible = leaves.value.filter(column => !column.width).length
  return min.map((value, index) => value + (!leaves.value[index].width && flexible ? extra / flexible : 0))
})
const totalWidth = computed(() => widths.value.reduce((sum, value) => sum + value, 0))
function valueOf(row: GridRecord, path: string | undefined): unknown {
  if (!path) return undefined
  return path.split('.').reduce<unknown>((value, key) => value && typeof value === 'object' ? (value as GridRecord)[key] : undefined, row)
}
const filtered = computed(() => (props.data as GridRecord[]).filter(row => leaves.value.every(column => {
  const values = filters.value[column.prop || '']
  return !values?.length || values.some(value => column.filterMethod ? column.filterMethod(value, row, column) : Object.is(valueOf(row, column.prop), value))
})))
const definitions = computed(() => {
  function convert(columns: GridColumn[], prefix = ''): ColumnDef<typeof featureSet, GridRecord>[] {
    return columns.filter(column => !column.hidden).map((column, index) => ({
      id: column.prop || `${prefix}${column.type || 'column'}-${index}`,
      accessorFn: row => valueOf(row, column.prop),
      enableSorting: Boolean(column.sortable && column.sortable !== 'custom'),
      header: column.label || '',
      meta: { spec: column },
      ...(column.children?.length ? { columns: convert(column.children, `${prefix}${index}-`) } : {}),
    }))
  }
  return convert(props.columns)
})
function rowKey(row: GridRecord, index: number) { return typeof props.rowKey === 'function' ? props.rowKey(row) : String(valueOf(row, props.rowKey || 'id') ?? index) }
const table = useTable({
  key: `grid-${useId()}`, features: featureSet, data: filtered,
  get columns() { return definitions.value },
  getRowId: rowKey,
  enableRowSelection: row => leaves.value.find(column => column.type === 'selection')?.selectable?.(row.original, row.index) ?? true,
  onSortingChange: updater => { sorting.value = typeof updater === 'function' ? updater(sorting.value) : updater },
  onRowSelectionChange: updater => { selected.value = typeof updater === 'function' ? updater(selected.value) : updater; emitSelection() },
  state: { get sorting() { return sorting.value }, get rowSelection() { return selected.value } },
})
const rows = computed(() => table.getRowModel().rows)
const virtualizer = useVirtualizer(computed(() => ({
  count: rows.value.length, getScrollElement: () => viewport.value ?? null,
  estimateSize: () => rowHeight.value, overscan: 8,
  enabled: Boolean(props.virtualized), initialRect: { width: 800, height: 400 },
  getItemKey: (index: number) => rows.value[index]?.id ?? index,
})))
const virtualItems = computed(() => virtualizer.value.getVirtualItems())
const displayed = computed(() => props.virtualized ? virtualItems.value.map(item => ({ row: rows.value[item.index], index: item.index })) : rows.value.map((row, index) => ({ row, index })))
const paddingTop = computed(() => props.virtualized ? virtualItems.value[0]?.start ?? 0 : 0)
const paddingBottom = computed(() => props.virtualized ? Math.max(0, virtualizer.value.getTotalSize() - (virtualItems.value.at(-1)?.end ?? 0)) : 0)
const expandColumn = computed(() => leaves.value.find(column => column.type === 'expand'))
function spec(column: { columnDef: { meta?: unknown } }): GridColumn { return (column.columnDef.meta as { spec: GridColumn }).spec }
function columnStyle(column: GridColumn, header = false): CSSProperties {
  const index = leaves.value.indexOf(column)
  const children = column.children?.length ? leafColumns(column.children) : [column]
  const size = children.reduce((sum, child) => sum + (widths.value[leaves.value.indexOf(child)] || 0), 0)
  const fixed = column.fixed === true ? 'left' : column.fixed
  const offset = fixed === 'right' ? widths.value.slice(index + 1).reduce((sum, value, i) => sum + (leaves.value[index + i + 1].fixed === 'right' ? value : 0), 0)
    : widths.value.slice(0, index).reduce((sum, value, i) => sum + (leaves.value[i].fixed && leaves.value[i].fixed !== 'right' ? value : 0), 0)
  return { width: `${size}px`, minWidth: `${size}px`, maxWidth: `${size}px`, textAlign: header ? column.headerAlign || column.align || 'center' : column.align || 'center',
    ...(fixed ? { position: 'sticky', [fixed]: `${offset}px`, zIndex: header ? 4 : 2 } : {}) }
}
function span(row: GridRecord, rowIndex: number, column: GridColumn) {
  const value = props.spanMethod?.({ row, column, rowIndex, columnIndex: leaves.value.indexOf(column) })
  return Array.isArray(value) ? { rowspan: value[0], colspan: value[1] } : value ?? { rowspan: 1, colspan: 1 }
}
function rowClass(row: GridRecord, rowIndex: number) { return typeof props.rowClassName === 'function' ? props.rowClassName({ row, rowIndex }) : props.rowClassName }
function rowStyle(row: GridRecord, rowIndex: number) { return typeof props.rowStyle === 'function' ? props.rowStyle({ row, rowIndex }) : props.rowStyle }
function emitSelection() { void nextTick(() => emit('selection-change', table.getSelectedRowModel().rows.map(row => row.original))) }
function clicked(row: GridRecord, column: GridColumn, event: MouseEvent) {
  const key = rowKey(row, (props.data as GridRecord[]).indexOf(row))
  current.value = key
  emit('cell-click', row, { ...column, property: column.prop }, event.currentTarget as HTMLElement, event)
  emit('row-click', row, { ...column, property: column.prop }, event)
}
function toggleFilter(column: GridColumn, value: unknown, checked: boolean) {
  const key = column.prop || ''
  const next = (filters.value[key] ?? []).filter(item => !Object.is(item, value))
  if (checked) next.push(value)
  filters.value = { ...filters.value, [key]: column.filterMultiple === false ? next.slice(-1) : next }
}
function sort(prop: string, order: string | null) {
  const column = leaves.value.find(column => column.prop === prop)
  sorting.value = order && column?.sortable !== 'custom' ? [{ id: prop, desc: order === 'descending' }] : []
  emit('sort-change', { column, prop, order })
}
function sortHeader(column: { id: string; columnDef: { meta?: unknown }; getIsSorted: () => false | 'asc' | 'desc'; toggleSorting: () => void }) {
  const col = spec(column)
  if (col.sortable === 'custom') { const last = customSort.value; const order = last.prop !== col.prop || !last.order ? 'ascending' : last.order === 'ascending' ? 'descending' : null; customSort.value = { prop: col.prop || '', order }; sort(col.prop || '', order) }
  else { column.toggleSorting(); const order = column.getIsSorted(); emit('sort-change', { column: col, prop: col.prop || '', order: order ? order === 'desc' ? 'descending' : 'ascending' : null }) }
}
const customSort = ref<{ prop: string; order: string | null }>({ prop: '', order: null })
watch(() => props.data, () => {
  const available = new Set((props.data as GridRecord[]).map(rowKey))
  const next = Object.fromEntries(Object.entries(selected.value).filter(([key]) => available.has(key)))
  if (Object.keys(next).length !== Object.keys(selected.value).length) { selected.value = next; emitSelection() }
  expanded.value = new Set([...expanded.value].filter(key => available.has(key)))
})
defineExpose({
  clearSelection: () => { selected.value = {}; emitSelection() },
  toggleRowSelection: (row: object, checked?: boolean) => {
    const record = toRaw(row) as GridRecord
    const key = props.rowKey || 'id' in record ? rowKey(record, -1) : undefined
    const match = table.getRowModel().rows.find(item => key !== undefined ? item.id === key : toRaw(item.original) === record)
    match?.toggleSelected(checked)
  },
  getSelectionRows: () => table.getSelectedRowModel().rows.map(row => row.original),
  doLayout: () => { virtualizer.value.measure() }, sort, clearSort: () => { sorting.value = [] },
  scrollTo: (options: ScrollToOptions) => viewport.value?.scrollTo(options),
} satisfies GridHandle)
</script>
<template>
  <div class="data-grid" :class="{ 'data-grid--striped': stripe, 'data-grid--bordered': border, 'data-grid--virtual': virtualized }"
    :style="{ height: cssLength(height, virtualized ? '400px' : undefined), maxHeight: cssLength(maxHeight), '--grid-row-height': `${rowHeight}px` }">
    <div ref="viewport" class="data-grid__viewport">
      <Table :style="{ width: `${totalWidth}px`, minWidth: '100%', tableLayout: 'fixed' }" :aria-rowcount="rows.length + table.getHeaderGroups().length">
        <TableHeader class="data-grid__header">
          <TableRow v-for="group in table.getHeaderGroups()" :key="group.id">
            <TableHead v-for="(header, index) in group.headers" :key="header.id" :colspan="header.colSpan" :style="columnStyle(spec(header.column), true)"
              :data-pinned="Boolean(spec(header.column).fixed) || undefined" :aria-sort="header.column.getIsSorted() ? header.column.getIsSorted() === 'asc' ? 'ascending' : 'descending' : undefined">
              <template v-if="!header.isPlaceholder">
                <CheckboxField v-if="spec(header.column).type === 'selection'" :model-value="table.getIsAllRowsSelected()" :indeterminate="table.getIsSomeRowsSelected() && !table.getIsAllRowsSelected()" aria-label="选择所有行" @change="value => table.toggleAllRowsSelected(value)" />
                <div v-else class="data-grid__heading">
                  <Button access="read" variant="ghost" v-if="spec(header.column).sortable" type="button" class="data-grid__sort" @click="sortHeader(header.column)"><span>{{ spec(header.column).label }}</span><component :is="header.column.getIsSorted() === 'asc' ? ArrowUp : header.column.getIsSorted() === 'desc' ? ArrowDown : ArrowUpDown" class="size-3.5" /></Button>
                  <VNodeContent v-else-if="spec(header.column).headerSlot" :render="() => spec(header.column).headerSlot!({ column: spec(header.column), $index: index })" />
                  <span v-else>{{ spec(header.column).label }}</span>
                  <Popover v-if="spec(header.column).filters?.length"><PopoverTrigger as-child><Button access="read" type="button" variant="ghost" size="icon-sm" :aria-label="`筛选${spec(header.column).label}`"><Filter class="size-3" /></Button></PopoverTrigger><PopoverContent class="data-grid__filters">
                    <CheckboxField v-for="option in spec(header.column).filters" :key="String(option.value)" :model-value="filters[spec(header.column).prop || '']?.includes(option.value)" @change="value => toggleFilter(spec(header.column), option.value, value)">{{ option.text }}</CheckboxField>
                  </PopoverContent></Popover>
                </div>
              </template>
            </TableHead>
          </TableRow>
        </TableHeader>
        <TableBody>
          <TableRow v-if="paddingTop" aria-hidden="true"><TableCell :colspan="leaves.length" :style="{ height: `${paddingTop}px`, padding: 0, border: 0 }" /></TableRow>
          <template v-for="{ row, index } in displayed" :key="row.id">
            <TableRow :class="rowClass(row.original, index)" :style="rowStyle(row.original, index)" :data-state="row.getIsSelected() || (highlightCurrentRow && current === row.id) ? 'selected' : undefined"
              :aria-rowindex="index + table.getHeaderGroups().length + 1" tabindex="0" @keydown.enter.self="emit('row-click', row.original, undefined, $event)" @keydown.space.self.prevent="emit('row-click', row.original, undefined, $event)">
              <template v-for="cell in row.getAllCells()" :key="cell.id">
                <TableCell v-if="span(row.original, index, spec(cell.column)).rowspan && span(row.original, index, spec(cell.column)).colspan"
                  v-bind="span(row.original, index, spec(cell.column))" :style="columnStyle(spec(cell.column))" :data-pinned="Boolean(spec(cell.column).fixed) || undefined"
                  :title="spec(cell.column).showOverflowTooltip && !spec(cell.column).cellSlot ? String(cell.getValue() ?? '') : undefined" @click="clicked(row.original, spec(cell.column), $event)">
                  <CheckboxField v-if="spec(cell.column).type === 'selection'" :model-value="row.getIsSelected()" :disabled="!row.getCanSelect()" :aria-label="`选择第 ${index + 1} 行`" @click.stop @change="value => row.toggleSelected(value)" />
                  <span v-else-if="spec(cell.column).type === 'index'">{{ index + 1 }}</span>
                  <Button access="read" v-else-if="spec(cell.column).type === 'expand'" type="button" variant="ghost" size="icon-sm" :aria-expanded="expanded.has(row.id)" aria-label="展开行详情" @click.stop="expanded.has(row.id) ? expanded.delete(row.id) : expanded.add(row.id)"><ChevronRight :class="{ 'rotate-90': expanded.has(row.id) }" /></Button>
                  <VNodeContent v-else-if="spec(cell.column).cellSlot" :render="() => spec(cell.column).cellSlot!({ row: row.original, column: spec(cell.column), $index: index })" />
                  <slot v-else name="cell" :row="row.original" :column="spec(cell.column)" :index="index"><span class="data-grid__text">{{ spec(cell.column).formatter?.(row.original) ?? cell.getValue() ?? '' }}</span></slot>
                </TableCell>
              </template>
            </TableRow>
            <TableRow v-if="expanded.has(row.id) && expandColumn"><TableCell :colspan="leaves.length"><VNodeContent v-if="expandColumn.cellSlot" :render="() => expandColumn!.cellSlot!({ row: row.original, column: expandColumn!, $index: index })" /></TableCell></TableRow>
          </template>
          <TableRow v-if="paddingBottom" aria-hidden="true"><TableCell :colspan="leaves.length" :style="{ height: `${paddingBottom}px`, padding: 0, border: 0 }" /></TableRow>
          <TableRow v-if="!rows.length"><TableCell :colspan="Math.max(1, leaves.length)" class="data-grid__empty"><slot name="empty"><EmptyBlock :description="emptyText" /></slot></TableCell></TableRow>
        </TableBody>
      </Table>
    </div>
  </div>
</template>
