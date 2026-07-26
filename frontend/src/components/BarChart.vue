<template>
  <div class="bar-chart" role="img" :aria-label="label">
    <div v-for="item in normalized" :key="item.label" class="bar-row">
      <span class="bar-label">{{ item.label }}</span>
      <div class="bar-track">
        <div class="bar-fill" :style="{ width: `${item.ratio * 100}%`, background: item.color }" />
      </div>
      <span class="bar-value">{{ item.display }}</span>
    </div>
    <p v-if="!normalized.length" class="empty-inline">暂无数据</p>
  </div>
</template>

<script setup lang="ts">
import { computed } from 'vue'

const props = withDefaults(
  defineProps<{
    items: Array<{ label: string; value: number; color?: string }>
    label?: string
  }>(),
  { label: '柱状图' },
)

const normalized = computed(() => {
  const max = Math.max(...props.items.map((item) => Math.abs(item.value)), 1)
  return props.items.map((item) => ({
    label: item.label,
    display: String(item.value),
    ratio: Math.abs(item.value) / max,
    color: item.color ?? (item.value >= 0 ? 'var(--up)' : 'var(--down)'),
  }))
})
</script>