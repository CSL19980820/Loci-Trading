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
/* 分段控件：控件高 28px、圆角 3px；选中态用品牌靛（D1：红绿只留给涨跌数字） */
.segment-switch {
  --el-border-radius-base: var(--radius);
  --el-segmented-padding: 1px;
  --el-segmented-bg-color: var(--sheet-alt);
  --el-segmented-color: var(--muted);
  --el-segmented-item-selected-color: var(--sheet);
  --el-segmented-item-selected-bg-color: var(--seal);
  --el-segmented-item-hover-color: var(--seal-ink);
  --el-segmented-item-hover-bg-color: var(--seal-soft);
  --el-segmented-item-active-bg-color: var(--seal-soft);
  --el-border-color: var(--rule);
  min-height: var(--ctl-h);
  border: 1px solid var(--rule);
  font-size: var(--fs-body);
  font-weight: 500;
}

.segment-switch :deep(.el-segmented__item) {
  padding: 0 var(--gap-2);
}
</style>
