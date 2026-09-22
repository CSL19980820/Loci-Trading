<script setup lang="ts" generic="T = unknown">
import { computed } from 'vue'
import ChoiceField from './ChoiceField.vue'
import { hierarchyChoices, type HierarchyOptions } from './hierarchicalChoices'
const props = defineProps<{ modelValue?: T; options?: unknown[]; props?: HierarchyOptions; disabled?: boolean; clearable?: boolean }>()
const emit = defineEmits<{ 'update:modelValue': [value: T]; change: [value: T] }>()
const options = computed(() => hierarchyChoices(props.options ?? [], props.props, true))
</script>
<template><ChoiceField :model-value="modelValue" :options="options" :multiple="props.props?.multiple" :disabled="disabled" :clearable="clearable" filterable @update:model-value="emit('update:modelValue', $event)" @change="emit('change', $event)" /></template>
