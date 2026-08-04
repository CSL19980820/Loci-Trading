<script setup lang="ts">
import { computed } from 'vue'

export type SegmentItem = {
  name: string
  label: string
  disabled?: boolean
}

const props = withDefaults(
  defineProps<{
    modelValue: string
    items: SegmentItem[]
    ariaLabel?: string
  }>(),
  {
    ariaLabel: '切换视图',
  },
)

const emit = defineEmits<{
  'update:modelValue': [string]
}>()

const options = computed(() =>
  props.items.map((item) => ({
    label: item.label,
    value: item.name,
    disabled: item.disabled,
  })),
)

const value = computed({
  get: () => props.modelValue,
  set: (next: string) => {
    if (next !== props.modelValue) emit('update:modelValue', next)
  },
})
</script>

<template>
  <el-segmented
    v-model="value"
    class="segment-switch"
    size="small"
    :options="options"
    :aria-label="ariaLabel"
  />
</template>

<style scoped>
.segment-switch {
  --el-border-radius-base: var(--radius);
  --el-segmented-bg-color: var(--sheet);
  --el-segmented-item-selected-color: var(--ink);
  --el-segmented-item-selected-bg-color: var(--paper);
  --el-segmented-item-hover-color: var(--ink);
  --el-border-color: var(--rule);
  font-weight: 500;
}
</style>
