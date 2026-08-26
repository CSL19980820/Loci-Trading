<script setup lang="ts">
import { h, inject, type Slots } from 'vue'

import type { BasicTableColumn } from './basicTableTypes'

const props = defineProps<{
  col: BasicTableColumn
  row: Record<string, unknown>
  index: number
  editing: boolean
}>()

const emit = defineEmits<{
  'update:field': [prop: string, value: unknown]
}>()

const tableSlots = inject<Slots>('basicTableSlots', {})

function onEditInput(value: unknown): void {
  if (props.col.prop) emit('update:field', props.col.prop, value)
}

function slotVNode() {
  const name = props.col.slotName
  if (!name) return null
  const fn = tableSlots[name]
  if (!fn) return null
  return fn({
    row: props.row,
    prop: props.col.prop,
    index: props.index,
  })
}
</script>

<template>
  <template v-if="editing && col.editRender">
    <el-input
      v-if="!col.editRender.component || col.editRender.component === 'el-input'"
      :model-value="col.prop ? String(row[col.prop] ?? '') : ''"
      v-bind="col.editRender.componentProps ?? {}"
      size="small"
      @update:model-value="onEditInput"
    />
    <el-input-number
      v-else-if="col.editRender.component === 'el-input-number'"
      :model-value="col.prop ? Number(row[col.prop] ?? 0) : 0"
      v-bind="col.editRender.componentProps ?? {}"
      size="small"
      @update:model-value="onEditInput"
    />
    <el-select
      v-else-if="col.editRender.component === 'el-select'"
      :model-value="col.prop ? row[col.prop] : undefined"
      v-bind="col.editRender.componentProps ?? {}"
      size="small"
      @update:model-value="onEditInput"
    >
      <el-option
        v-for="opt in ((col.editRender.componentProps?.options as { label: string; value: unknown }[]) ?? [])"
        :key="String(opt.value)"
        :label="opt.label"
        :value="opt.value"
      />
    </el-select>
    <span v-else>{{ col.prop ? row[col.prop] : '' }}</span>
  </template>
  <component :is="{ render: () => slotVNode() }" v-else-if="col.slotName" />
  <component
    :is="{
      render: () =>
        col.render?.(h, { row, prop: col.prop, index }) ?? null,
    }"
    v-else-if="col.render"
  />
  <span v-else-if="col.formatter" class="cell-text">{{ col.formatter(row) }}</span>
  <span v-else class="cell-text">{{ col.prop ? row[col.prop] : '' }}</span>
</template>

<style scoped>
.cell-text {
  display: inline-block;
  max-width: 100%;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  vertical-align: middle;
}
</style>
