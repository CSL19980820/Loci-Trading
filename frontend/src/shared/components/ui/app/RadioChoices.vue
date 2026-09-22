<script setup lang="ts" generic="T = string">
import { computed, provide } from 'vue'
import { RadioGroup } from '../radio-group'
import { decodeChoice, encodeChoice, useFieldControl } from './context'
import { radioContextKey } from './selectionContext'
const props = defineProps<{ modelValue?: T; disabled?: boolean; size?: string }>()
const emit = defineEmits<{ 'update:modelValue': [value: T]; change: [value: T] }>()
const field = useFieldControl()
provide(radioContextKey, { value: computed(() => props.modelValue), disabled: computed(() => Boolean(props.disabled || field.disabled.value)) })
function update(value: unknown) { const next = decodeChoice(String(value)) as T; emit('update:modelValue', next); emit('change', next); field.validate() }
</script>
<template><RadioGroup v-bind="field.bindings.value" class="radio-choices" :model-value="encodeChoice(modelValue)" :disabled="disabled || field.disabled.value" @update:model-value="update"><slot /></RadioGroup></template>
