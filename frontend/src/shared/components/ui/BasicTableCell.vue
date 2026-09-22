<script setup lang="ts">
import { computed, h, inject, type Slots } from 'vue'
import TextField from './app/TextField.vue'
import NumberInput from './app/NumberInput.vue'
import ChoiceField from './app/ChoiceField.vue'
import ToggleSwitch from './app/ToggleSwitch.vue'
import { VNodeContent } from './app/vnodeContent'
import type { ChoiceEntry } from './app/choiceOptions'
import type { BasicTableColumn } from './basicTableTypes'

const props = defineProps<{
  col: BasicTableColumn
  row: Record<string, unknown>
  index: number
  editing: boolean
}>()
const emit = defineEmits<{ 'update:field': [prop: string, value: unknown] }>()
const tableSlots = inject<Slots>('basicTableSlots', {})
const value = computed(() => props.col.prop ? props.row[props.col.prop] : undefined)
const kind = computed(() => props.col.editRender?.component || 'input')
const editorProps = computed(() => {
  const { options: _options, ...rest } = props.col.editRender?.componentProps ?? {}
  return rest
})
const options = computed<ChoiceEntry[]>(() => {
  const options = props.col.editRender?.componentProps?.options
  if (!Array.isArray(options)) return []
  return options.map(option => {
    if (option && typeof option === 'object') {
      const item = option as Record<string, unknown>
      return { value: item.value ?? item.id, label: String(item.label ?? item.name ?? item.value ?? ''), disabled: Boolean(item.disabled) }
    }
    return { value: option, label: String(option) }
  })
})
const numberValue = computed(() => {
  if (value.value === '' || value.value == null) return undefined
  const number = Number(value.value)
  return Number.isFinite(number) ? number : undefined
})
function update(next: unknown) { if (props.col.prop) emit('update:field', props.col.prop, next) }
function updateNumber(next: unknown) {
  // Empty/invalid intermediate edits must not silently replace a saved value with zero or NaN.
  if (typeof next === 'number' && Number.isFinite(next)) update(next)
}
function slotContent() {
  const slot = props.col.slotName ? tableSlots[props.col.slotName] : undefined
  return slot?.({ row: props.row, prop: props.col.prop, index: props.index })
}
</script>

<template>
  <template v-if="editing && col.editRender">
    <NumberInput v-if="kind === 'input-number'" v-bind="editorProps" :model-value="numberValue" @update:model-value="updateNumber" />
    <ChoiceField v-else-if="kind === 'select'" v-bind="editorProps" :model-value="value" :options="options" @update:model-value="update" />
    <ToggleSwitch v-else-if="kind === 'switch'" v-bind="editorProps" :model-value="Boolean(value)" @update:model-value="update" />
    <TextField v-else v-bind="editorProps" :model-value="value" @update:model-value="update" />
  </template>
  <VNodeContent v-else-if="col.slotName" :render="slotContent" />
  <VNodeContent v-else-if="col.render" :render="() => col.render?.(h, { row, prop: col.prop, index })" />
  <span v-else class="cell-text">{{ col.formatter ? col.formatter(row) : value ?? '' }}</span>
</template>

<style scoped>
.cell-text { display:inline-block; max-width:100%; overflow:hidden; text-overflow:ellipsis; white-space:nowrap; vertical-align:middle; }
</style>
