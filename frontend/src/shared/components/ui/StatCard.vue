<script setup lang="ts">
import { computed } from 'vue'

const props = withDefaults(
  defineProps<{
    label: string
    value?: string | number
    hint?: string
    tone?: 'up' | 'down' | 'neutral' | ''
    /** stack=上下；row=左右（标签左、数值右） */
    layout?: 'stack' | 'row'
  }>(),
  { layout: 'stack' },
)

const toneClass = computed(() => {
  if (props.tone === 'up') return 'tone-up'
  if (props.tone === 'down') return 'tone-down'
  if (props.tone === 'neutral') return 'tone-neutral'
  return ''
})
</script>

<template>
  <div class="stat-card" :class="[toneClass, layout === 'row' ? 'stat-card--row' : '']">
    <span class="stat-k">{{ label }}</span>
    <span class="stat-v"><slot>{{ value }}</slot></span>
    <span v-if="hint" class="stat-x">{{ hint }}</span>
  </div>
</template>

<style scoped>
.stat-card {
  display: grid;
  gap: 0.25rem;
  padding: 0.85rem 1rem;
  border: 1px solid var(--rule);
  border-radius: var(--radius);
  background: var(--sheet);
}

.stat-card--row {
  display: flex;
  flex-wrap: wrap;
  align-items: baseline;
  justify-content: space-between;
  gap: 0.45rem 0.85rem;
  padding: 0.7rem 0.95rem;
}

.stat-card--row .stat-v {
  font-size: 1.15rem;
}

.stat-card--row .stat-x {
  flex-basis: 100%;
}

.stat-k {
  color: var(--mist);
  font-size: 0.8rem;
  font-weight: 500;
}

.stat-v {
  display: inline-flex;
  flex-wrap: wrap;
  align-items: baseline;
  gap: 0.35rem;
  font: 700 1.3rem/1.15 var(--mono);
  font-variant-numeric: tabular-nums;
  letter-spacing: 0;
  color: var(--ink);
}

.stat-x {
  color: var(--muted);
  font: 0.8rem var(--mono);
}

.tone-up .stat-v {
  color: var(--up);
}

.tone-down .stat-v {
  color: var(--down);
}
</style>
