<script setup lang="ts" generic="T = string | number | boolean">
import { computed } from 'vue'
import { ToggleGroup, ToggleGroupItem } from '../toggle-group'
import { encodeChoice, decodeChoice, useFieldControl } from './context'
const props = defineProps<{ modelValue?: T; options?: (T | { label: string; value: T; disabled?: boolean })[]; disabled?: boolean; size?: string }>()
const emit = defineEmits<{ 'update:modelValue': [value: T]; change: [value: T] }>()
const field = useFieldControl()
const options = computed(() => (props.options ?? []).map(item => typeof item === 'object' && item !== null && 'value' in item
  ? item as { label: string; value: T; disabled?: boolean } : { label: String(item), value: item as T }))
function update(value: unknown) { if (!value) return; const next = decodeChoice(String(value)) as T; emit('update:modelValue', next); emit('change', next) }
</script>
<template>
  <ToggleGroup class="segmented-control" type="single" :model-value="encodeChoice(modelValue)" :disabled="disabled || field.disabled.value" variant="outline" @update:model-value="update">
    <ToggleGroupItem v-for="option in options" :key="encodeChoice(option.value)" :value="encodeChoice(option.value)" :disabled="option.disabled">{{ option.label }}</ToggleGroupItem>
  </ToggleGroup>
</template>
