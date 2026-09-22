<script setup lang="ts">
import { computed } from 'vue'
import { Input } from '../input'
import { useFieldControl } from './context'
const props = withDefaults(defineProps<{ modelValue?: string | null; start?: string; end?: string; step?: string; disabled?: boolean }>(), { step: '00:15' })
const emit = defineEmits<{ 'update:modelValue': [value: string]; change: [value: string] }>()
const field = useFieldControl()
const seconds = computed(() => { const [hours, minutes] = props.step.split(':').map(Number); return (hours * 60 + minutes) * 60 || 900 })
function update(value: string | number) { emit('update:modelValue', String(value)); emit('change', String(value)); field.validate() }
</script>
<template><Input v-bind="field.bindings.value" class="time-field" type="time" :model-value="modelValue ?? ''" :min="start" :max="end" :step="seconds" :disabled="disabled || field.disabled.value" @update:model-value="update" /></template>
