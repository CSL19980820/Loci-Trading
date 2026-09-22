<script setup lang="ts" generic="T = unknown">
import { computed, provide } from 'vue'
import { checkboxContextKey } from './selectionContext'
import { useFieldControl } from './context'
const props = defineProps<{ modelValue?: T[]; disabled?: boolean }>()
const emit = defineEmits<{ 'update:modelValue': [value: T[]]; change: [value: T[]] }>()
const field = useFieldControl()
provide(checkboxContextKey, {
  value: computed(() => props.modelValue ?? []), disabled: computed(() => Boolean(props.disabled || field.disabled.value)),
  toggle(value, checked) {
    const next = (props.modelValue ?? []).filter(item => !Object.is(item, value))
    if (checked) next.push(value as T)
    emit('update:modelValue', next)
    emit('change', next)
    field.validate()
  },
})
</script>
<template><div v-bind="field.bindings.value" role="group" class="checkbox-choices"><slot /></div></template>
