<script setup lang="ts">
import { ref, useSlots } from 'vue'
import GridEngine from './GridEngine.vue'
import { collectColumns, type GridHandle, type GridProps, type GridRecord, type GridColumn } from './gridTypes'
defineOptions({ inheritAttrs: false })
defineProps<GridProps>()
const emit = defineEmits<{
  'row-click': [row: GridRecord, column: GridColumn | undefined, event: Event]
  'cell-click': [row: GridRecord, column: GridColumn, cell: HTMLElement, event: Event]
  'selection-change': [rows: GridRecord[]]
  'sort-change': [sort: { column?: GridColumn; prop: string; order: string | null }]
}>()
const slots = useSlots()
const engine = ref<GridHandle>()
defineExpose({
  clearSelection: () => engine.value?.clearSelection(),
  toggleRowSelection: (row: object, selected?: boolean) => engine.value?.toggleRowSelection(row, selected),
  getSelectionRows: () => engine.value?.getSelectionRows() ?? [],
  doLayout: () => engine.value?.doLayout(),
  sort: (prop: string, order: string | null) => engine.value?.sort(prop, order),
  clearSort: () => engine.value?.clearSort(),
  scrollTo: (options: ScrollToOptions) => engine.value?.scrollTo(options),
} satisfies GridHandle)
</script>
<template>
  <GridEngine ref="engine" v-bind="{ ...$props, ...$attrs }" :columns="columns ?? collectColumns(slots.default?.() ?? [])"
    @row-click="(row, column, event) => emit('row-click', row, column, event)"
    @cell-click="(row, column, cell, event) => emit('cell-click', row, column, cell, event)"
    @selection-change="rows => emit('selection-change', rows)"
    @sort-change="sort => emit('sort-change', sort)">
    <template v-if="$slots.cell" #cell="scope"><slot name="cell" v-bind="scope" /></template>
    <template v-if="$slots.empty" #empty><slot name="empty" /></template>
  </GridEngine>
</template>
