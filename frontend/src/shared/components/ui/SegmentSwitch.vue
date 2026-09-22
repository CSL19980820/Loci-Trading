<script setup lang="ts">
import { computed } from 'vue'

import { ToggleGroup, ToggleGroupItem } from '@/shared/components/ui/toggle-group'

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
    /** sm=28px（默认，工具行）；default=32px */
    size?: 'sm' | 'default'
  }>(),
  {
    ariaLabel: '切换视图',
    size: 'sm',
  },
)

const emit = defineEmits<{
  'update:modelValue': [string]
}>()

/**
 * reka 的 ToggleGroup 在 `type="single"` 下不会发出取消选中（空串），
 * 点了已选中的项就是原值回来；这里再挡一层，保证不会把 '' 抛给父级。
 */
const value = computed({
  get: () => props.modelValue,
  set: (next: string) => {
    if (!next || next === props.modelValue) return
    emit('update:modelValue', next)
  },
})
</script>

<template>
  <ToggleGroup
    v-model="value"
    type="single"
    class="segment-switch inline-flex items-center"
    :class="`segment-switch--${size}`"
    :aria-label="ariaLabel"
  >
    <ToggleGroupItem
      v-for="item in items"
      :key="item.name"
      :value="item.name"
      :disabled="item.disabled"
      class="segment-switch__item"
    >
      {{ item.label }}
    </ToggleGroupItem>
  </ToggleGroup>
</template>

<style scoped>
/*
 * 药片分段（iOS / shadcn Tabs 一路）：下沉底 + 3px 内边距，选中项浮起成白片带极淡投影。
 * 键盘交互（方向键 + roving tabindex）由 reka 的 ToggleGroup 提供。
 */
.segment-switch {
  gap: 2px;
  padding: 3px;
  border: 0;
  border-radius: var(--radius);
  background: var(--surface-sunken);
  font-size: var(--fs-aux);
  font-weight: 500;
}

.segment-switch--sm {
  height: var(--ctl-h-sm);
  min-height: var(--ctl-h-sm);
}

.segment-switch--default {
  height: var(--ctl-h);
  min-height: var(--ctl-h);
}

.segment-switch__item {
  height: 100%;
  min-width: 0;
  gap: 0;
  padding: 0 10px;
  border: 0;
  border-radius: var(--radius-sm);
  background: transparent;
  color: var(--text-tertiary);
  font-size: var(--fs-aux);
  font-weight: 500;
  box-shadow: none;
  transition:
    background-color var(--dur-fast) var(--ease),
    color var(--dur-fast) var(--ease),
    box-shadow var(--dur-fast) var(--ease);
}

.segment-switch--default .segment-switch__item {
  padding: 0 12px;
  font-size: var(--fs-ui);
}

.segment-switch__item:hover {
  background: transparent;
  color: var(--text-primary);
}

.segment-switch__item[data-state='on'] {
  background: var(--surface);
  color: var(--text-primary);
  font-weight: 600;
  box-shadow: var(--shadow-xs);
}

.segment-switch__item:focus-visible {
  outline: 2px solid var(--focus-ring);
  outline-offset: 1px;
  z-index: 1;
}
</style>
