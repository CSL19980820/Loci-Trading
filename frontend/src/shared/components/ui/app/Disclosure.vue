<script setup lang="ts" generic="T = string[]">
import { computed, ref } from 'vue'
import { Accordion } from '../accordion'
import { encodeChoice, decodeChoice } from './context'
const props = defineProps<{ modelValue?: T; accordion?: boolean }>()
const emit = defineEmits<{ 'update:modelValue': [value: T]; change: [value: T] }>()
const local = ref<unknown>(undefined)
const value = computed(() => props.modelValue ?? local.value ?? (props.accordion ? '' : []))
const encoded = computed(() => Array.isArray(value.value) ? value.value.map(encodeChoice) : encodeChoice(value.value))
function update(next: string | string[] | undefined) {
  const value = (Array.isArray(next) ? next.map(decodeChoice) : next ? decodeChoice(next) : '') as T
  local.value = value
  emit('update:modelValue', value)
  emit('change', value)
}
</script>
<template><Accordion class="disclosure" :type="accordion ? 'single' : 'multiple'" :model-value="encoded" collapsible @update:model-value="update"><slot /></Accordion></template>
