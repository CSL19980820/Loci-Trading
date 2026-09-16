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
    class="segment-switch inline-flex min-h-[var(--ctl-h)] items-center border"
    size="small"
    :options="options"
    :aria-label="ariaLabel"
  />
</template>

<style scoped>
/* 保留 EP 的键盘选择和滑块，选中态与全站导航共用柔和主色。 */
.segment-switch {
  --el-border-radius-base: var(--radius);
  --el-segmented-padding: 1px;
  --el-segmented-bg-color: var(--surface-sunken);
  --el-segmented-color: var(--muted);
  --el-segmented-item-selected-color: var(--seal-ink);
  --el-segmented-item-selected-bg-color: var(--seal-soft);
  --el-segmented-item-hover-color: var(--ink);
  --el-segmented-item-hover-bg-color: var(--surface-hover);
  --el-segmented-item-active-bg-color: var(--surface-active);
  --el-border-color: var(--rule);
  border: 1px solid var(--rule);
  font-size: var(--fs-body);
  font-weight: 500;
}

.segment-switch :deep(.el-segmented__item) {
  padding: 0 var(--gap-2);
}
</style>
