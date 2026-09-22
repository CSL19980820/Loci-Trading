<script setup lang="ts" generic="T = unknown">
import { computed } from 'vue'
import ChoiceField from './ChoiceField.vue'
import { hierarchyChoices, type HierarchyOptions } from './hierarchicalChoices'
const props = defineProps<{
  modelValue?: T; data?: unknown[]; props?: HierarchyOptions; multiple?: boolean;
  nodeKey?: string; disabled?: boolean; clearable?: boolean; checkStrictly?: boolean
}>()
const emit = defineEmits<{ 'update:modelValue': [value: T]; change: [value: T] }>()
const options = computed(() => hierarchyChoices(props.data ?? [], { ...props.props, value: props.nodeKey || props.props?.value, checkStrictly: props.checkStrictly ?? props.props?.checkStrictly }))
</script>
<template><ChoiceField :model-value="modelValue" :options="options" :multiple="multiple" :disabled="disabled" :clearable="clearable" filterable @update:model-value="emit('update:modelValue', $event)" @change="emit('change', $event)" /></template>
