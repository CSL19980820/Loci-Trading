<script setup lang="ts">
import { ref } from 'vue'
import DataGrid from './app/DataGrid.vue'
import type { GridHandle } from './app/gridTypes'
import BasicTableCell from './BasicTableCell.vue'
import EmptyState from './EmptyState.vue'
import type { BasicTableColumn } from './basicTableTypes'

type BasicRow = Record<string, unknown>
defineSlots<{ empty?: () => unknown }>()
defineProps<{
  columns: BasicTableColumn[]
  rows: BasicRow[]
  rowKey: string
  emptyText: string
  emptyReason?: string
  border: boolean
  stripe: boolean
  size: 'large' | 'default' | 'small'
  height?: string | number
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
const grid = ref<GridHandle>()
defineExpose({
  clearSelection: () => grid.value?.clearSelection(),
  getTableRef: () => grid.value,
  doLayout: () => grid.value?.doLayout(),
})
</script>

<template>
  <DataGrid ref="grid" class="basic-table__virtual" virtualized :columns="columns" :data="rows" :row-key="rowKey"
    :height="height" :max-height="maxHeight" :size="size" :border="border" :stripe="stripe" :row-class-name="rowClassName"
    @row-click="(row, _column, event) => emit('row-click', row, event)"
    @cell-click="(row, column, cell, event) => emit('cell-click', row, column, cell, event)"
    @selection-change="rows => emit('selection-change', rows)">
    <template #cell="{ row, column, index }">
      <BasicTableCell :col="column" :row="row" :index="index" :editing="isEditing(row)"
        @update:field="(prop, value) => emit('update:field', row, prop, value)" />
    </template>
    <template #empty><slot name="empty"><EmptyState :description="emptyText" :reason="emptyReason" /></slot></template>
  </DataGrid>
</template>
