<script setup lang="ts">
import type { LiveTapeItem } from '@/shared/api/quant'

const props = defineProps<{
  indices: LiveTapeItem[]
  bagPct: number | null
  positionCount: number
  alertCount: number
  asOf: string
  sessionText: string
}>()

function fmtPct(value: number | null | undefined): string {
  if (value == null || Number.isNaN(Number(value))) return '—'
  const n = Number(value)
  const sign = n > 0 ? '+' : ''
  return `${sign}${n.toFixed(2)}%`
}

function tone(value: number | null | undefined): string {
  if (value == null || value === 0) return ''
  return value > 0 ? 'is-up' : 'is-down'
}

function fmtPrice(value: number | null | undefined): string {
  if (value == null || Number.isNaN(Number(value))) return '—'
  return Number(value).toFixed(2)
}
</script>

<template>
  <div class="pulse-strip" aria-label="指数与仓摘要">
    <div
      v-for="item in props.indices"
      :key="item.code || item.label"
      class="pulse-strip__cell"
    >
      <span class="pulse-strip__k">{{ item.name || item.label }}</span>
      <div class="pulse-strip__v">
        <strong>{{ fmtPrice(item.price) }}</strong>
        <span :class="tone(item.pct)">{{ fmtPct(item.pct) }}</span>
      </div>
    </div>
    <div class="pulse-strip__cell pulse-strip__cell--bag">
      <span class="pulse-strip__k">我的仓 · {{ props.asOf || '—' }} · {{ props.sessionText }}</span>
      <div class="pulse-strip__v">
        <strong :class="tone(props.bagPct)">{{ fmtPct(props.bagPct) }}</strong>
        <span class="pulse-strip__meta">{{ props.positionCount }} 只</span>
        <RouterLink class="text-link" to="/ledger">
          {{ props.alertCount > 0 ? `触价 ${props.alertCount} →` : '账本 →' }}
        </RouterLink>
      </div>
    </div>
  </div>
</template>

<style scoped>
.pulse-strip {
  display: flex;
  flex-wrap: wrap;
  flex-shrink: 0;
  border: 1px solid var(--rule);
  border-radius: var(--radius);
  background: var(--sheet);
  overflow: hidden;
}

.pulse-strip__cell {
  flex: 1 1 96px;
  min-width: 88px;
  padding: 0.4rem 0.65rem;
  border-left: 1px solid var(--rule);
  display: flex;
  flex-direction: column;
  gap: 0.1rem;
}

.pulse-strip__cell:first-child {
  border-left: none;
}

.pulse-strip__cell--bag {
  flex: 1.3 1 160px;
}

.pulse-strip__k {
  font-size: 0.68rem;
  color: var(--mist);
  letter-spacing: 0.02em;
}

.pulse-strip__v {
  display: flex;
  flex-wrap: wrap;
  align-items: baseline;
  gap: 0.4rem;
  font-variant-numeric: tabular-nums;
}

.pulse-strip__v strong {
  font-size: 0.92rem;
  font-weight: 650;
}

.pulse-strip__v span {
  font-size: 0.78rem;
}

.pulse-strip__meta {
  color: var(--mist);
}

.is-up {
  color: var(--up, #c23b3b);
}

.is-down {
  color: var(--down, #1a8f5c);
}
</style>
