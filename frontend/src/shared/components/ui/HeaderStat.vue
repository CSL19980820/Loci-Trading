<script setup lang="ts">
import { computed } from 'vue'

/**
 * 页头行内读数：标签在上、数值在下的一对小字，专供 PageHeader 的 stats 槽。
 * 与 StatCard 的区别是不带边框卡片壳——页头已有分隔线，再套卡会变成「卡中卡」。
 */
const props = withDefaults(
  defineProps<{
    label: string
    value?: string | number
    tone?: 'up' | 'down' | 'neutral' | ''
    /** 主读数：字号更大，一个页头至多用一次 */
    lead?: boolean
  }>(),
  { lead: false },
)

const toneClass = computed(() => {
  if (props.tone === 'up') return 'tone-up'
  if (props.tone === 'down') return 'tone-down'
  if (props.tone === 'neutral') return 'tone-neutral'
  return ''
})
</script>

<template>
  <div class="hstat" :class="[toneClass, { 'hstat--lead': lead }]">
    <span class="hstat__k">{{ label }}</span>
    <span class="hstat__v"><slot>{{ value }}</slot></span>
  </div>
</template>

<style scoped>
.hstat {
  display: grid;
  gap: 0.1rem;
  min-width: 0;
}

.hstat__k {
  font-size: var(--fs-kicker);
  font-weight: 500;
  letter-spacing: 0.04em;
  color: var(--mist);
  white-space: nowrap;
}

.hstat__v {
  font: 650 1rem/1.15 var(--mono);
  font-variant-numeric: tabular-nums;
  color: var(--ink);
  white-space: nowrap;
}

.hstat--lead .hstat__v {
  font-size: 1.3rem;
  font-weight: 700;
}

.tone-up .hstat__v {
  color: var(--up);
}

.tone-down .hstat__v {
  color: var(--down);
}

.tone-neutral .hstat__v {
  color: var(--muted);
}
</style>
