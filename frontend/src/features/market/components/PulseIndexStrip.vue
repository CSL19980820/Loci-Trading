<script setup lang="ts">
import type { LiveTapeItem } from '@/shared/api/quant'
import { pct as fmtPct, price as fmtPrice } from '@/shared/lib/format'

const props = defineProps<{
  indices: LiveTapeItem[]
  alertCount: number
  asOf: string
  sessionText: string
}>()


function tone(value: number | null | undefined): string {
  if (value == null || value === 0) return ''
  return value > 0 ? 'is-up' : 'is-down'
}

</script>

<template>
  <div class="pulse-strip" aria-label="指数与触价提醒">
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
    <div class="pulse-strip__cell pulse-strip__cell--alerts">
      <span class="pulse-strip__k">{{ props.asOf || '—' }} · {{ props.sessionText }}</span>
      <div class="pulse-strip__v">
        <strong :class="props.alertCount > 0 ? 'is-down' : ''">
          {{ props.alertCount > 0 ? `触价 ${props.alertCount}` : '无触价' }}
        </strong>
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

.pulse-strip__cell--alerts {
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

.is-up {
  color: var(--up, #c41e3a);
}

.is-down {
  color: var(--down, #0f6b5c);
}
</style>
