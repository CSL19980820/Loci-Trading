<script setup lang="ts">
import { ArrowDownRight, ArrowUpRight, Minus } from '@lucide/vue'
import { computed } from 'vue'

/** A compact readout: label and value share a line; only real context gets a second line. */
const props = withDefaults(defineProps<{
  label: string
  value?: string | number
  hint?: string
  tone?: 'up' | 'down' | 'neutral' | ''
  /** The legacy stack spelling remains accepted; all layouts avoid forced three-row tiles. */
  layout?: 'compact' | 'stack' | 'row'
  delta?: number | string | null
  deltaLabel?: string
  loading?: boolean
}>(), { layout: 'compact', delta: null, loading: false })

const toneClass = computed(() => props.tone === 'up' ? 'is-up' : props.tone === 'down' ? 'is-down' : props.tone === 'neutral' ? 'is-flat' : '')
const deltaNumber = computed(() => {
  if (props.delta == null || props.delta === '') return null
  const n = typeof props.delta === 'number' ? props.delta : Number.parseFloat(String(props.delta))
  return Number.isFinite(n) ? n : null
})
const deltaText = computed(() => {
  if (props.delta == null || props.delta === '') return ''
  if (typeof props.delta === 'string' && !/^[-+]?\d/.test(props.delta.trim())) return props.delta
  const n = deltaNumber.value
  if (n == null) return String(props.delta)
  return `${n > 0 ? '+' : ''}${n.toFixed(Math.abs(n) >= 100 ? 0 : 2)}%`
})
const deltaTone = computed(() => deltaNumber.value == null || deltaNumber.value === 0 ? 'is-flat' : deltaNumber.value > 0 ? 'is-up' : 'is-down')
const DeltaIcon = computed(() => deltaNumber.value == null || deltaNumber.value === 0 ? Minus : deltaNumber.value > 0 ? ArrowUpRight : ArrowDownRight)
</script>

<template>
  <div class="stat-card" :class="[`stat-card--${layout}`, { 'stat-card--loading': loading }]" :aria-busy="loading || undefined">
    <div class="stat-card__main">
      <div class="stat-card__head">
        <span class="stat-card__label">{{ label }}</span>
        <span v-if="$slots.icon" class="stat-card__icon"><slot name="icon" /></span>
      </div>
      <span v-if="loading" class="stat-card__skeleton" aria-hidden="true" />
      <span v-else class="stat-card__value" :class="toneClass"><slot>{{ value ?? '—' }}</slot></span>
    </div>
    <div v-if="!loading && (deltaText || hint || $slots.hint)" class="stat-card__foot">
      <span v-if="deltaText" class="stat-card__delta" :class="deltaTone">
        <component :is="DeltaIcon" class="stat-card__delta-icon" aria-hidden="true" />{{ deltaText }}
      </span>
      <span v-if="deltaLabel && deltaText" class="stat-card__delta-label">{{ deltaLabel }}</span>
      <span v-if="hint || $slots.hint" class="stat-card__hint"><slot name="hint"><span v-for="(part, index) in hint?.split(' · ')" :key="index" class="stat-card__hint-part"><span v-if="index" aria-hidden="true">· </span>{{ part }}</span></slot></span>
    </div>
  </div>
</template>

<style scoped>
.stat-card {
  container-type: inline-size;
  display: flex;
  flex-direction: column;
  justify-content: flex-start;
  gap: 4px;
  min-width: 0;
  padding: 9px 12px;
  border: 1px solid var(--border-subtle);
  border-radius: var(--radius-md);
  background: var(--surface);
  box-shadow: none;
}
.stat-card__main {
  display: flex;
  flex-wrap: wrap;
  align-items: baseline;
  justify-content: space-between;
  gap: 4px 10px;
  min-width: 0;
}
.stat-card__head { display: flex; align-items: center; gap: 6px; min-width: 0; max-width: 100%; }
.stat-card__label { color: var(--text-tertiary); font-size: var(--fs-aux); font-weight: 500; line-height: 1.4; overflow-wrap: anywhere; }
.stat-card__icon { display: inline-flex; align-items: center; flex-shrink: 0; color: var(--text-tertiary); }
.stat-card__icon :deep(svg) { width: 14px; height: 14px; }
.stat-card__value {
  display: inline-flex;
  flex-wrap: wrap;
  align-items: baseline;
  gap: 3px;
  max-width: 100%;
  min-width: 0;
  color: var(--text-primary);
  font-family: var(--mono);
  font-size: clamp(18px, 8cqi, 22px);
  font-weight: 600;
  letter-spacing: -.025em;
  line-height: 1.2;
  font-variant-numeric: tabular-nums;
  overflow-wrap: anywhere;
}
.stat-card__value :deep(small), .stat-card__value :deep(.unit) { color: var(--text-tertiary); font-size: var(--fs-aux); font-weight: 400; letter-spacing: 0; }
.stat-card__foot { display: flex; flex-wrap: wrap; align-items: baseline; gap: 2px 6px; min-width: 0; color: var(--text-tertiary); font-size: var(--fs-aux); line-height: 1.45; }
.stat-card__hint { display: inline-flex; flex-wrap: wrap; gap: 2px 4px; }
.stat-card__hint-part { display: inline-block; max-width: 100%; }
.stat-card__hint, .stat-card__delta-label { min-width: 0; overflow-wrap: anywhere; font-variant-numeric: tabular-nums; }
.stat-card__delta { display: inline-flex; align-items: center; gap: 2px; white-space: nowrap; font-family: var(--mono); font-weight: 500; font-variant-numeric: tabular-nums; }
.stat-card__delta-icon { width: 12px; height: 12px; }
.stat-card__skeleton { display: block; width: 5rem; max-width: 55%; height: 26px; border-radius: var(--radius-sm); background: linear-gradient(90deg, var(--surface-sunken) 25%, var(--surface-hover) 50%, var(--surface-sunken) 75%); background-size: 200% 100%; animation: stat-shimmer 1.4s ease-in-out infinite; }
.stat-card--row { flex-direction: row; align-items: center; gap: 8px; padding: 8px 10px; }
.stat-card--row .stat-card__main { flex: 1; flex-wrap: nowrap; align-items: center; }
.stat-card--row .stat-card__foot { flex: none; flex-wrap: nowrap; }
.stat-card--row .stat-card__label, .stat-card--row .stat-card__value { white-space: nowrap; overflow-wrap: normal; }
.stat-card--row .stat-card__value { font-size: 18px; }
.is-up { color: var(--up); }
.is-down { color: var(--down); }
.is-flat { color: var(--text-tertiary); }
@keyframes stat-shimmer { from { background-position: 200% 0; } to { background-position: -200% 0; } }
@media (prefers-reduced-motion: reduce) { .stat-card__skeleton { animation: none; } }
@media (max-width: 640px) {
  .stat-card { padding: 8px 10px; }
  .stat-card__main { gap: 3px 6px; }
  .stat-card__icon:has(> svg:only-child) { display: none; }
}
</style>
