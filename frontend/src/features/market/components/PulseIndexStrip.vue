<script setup lang="ts">
/**
 * 报价带：本页字号最大的东西，且必须是数字。
 * 指数报价 26px 等宽 + tabular-nums；涨跌带符号并只在这里用红绿。
 */
import { computed } from 'vue'

import type { LiveTapeItem } from '@/shared/api/quant'
import { price as fmtPrice, signedPct } from '@/shared/lib/format'

import './pulseSkin.css'

const props = defineProps<{
  indices: LiveTapeItem[]
  alertCount: number
  /** 情报缓存里的涨停/跌停家数；读不到给 null，显示「—」不猜 */
  limitUp?: number | null
  limitDown?: number | null
  /** 情报缓存不可用时的说明，进 tooltip */
  breadthNote?: string
}>()

function tone(value: number | null | undefined): string {
  if (value == null || !Number.isFinite(Number(value))) return 'pulse-flat'
  if (Number(value) > 0) return 'pulse-up'
  if (Number(value) < 0) return 'pulse-down'
  return 'pulse-flat'
}

function count(value: number | null | undefined): string {
  if (value == null || !Number.isFinite(Number(value))) return '—'
  return String(Math.round(Number(value)))
}

const cells = computed(() =>
  props.indices.map((item) => ({
    key: item.code || item.label,
    name: item.name || item.label,
    price: fmtPrice(item.price),
    pct: signedPct(item.pct),
    tone: tone(item.pct),
  })),
)

const breadthTip = computed(
  () => props.breadthNote || '涨停/跌停来自情报缓存（GET /intel/brief），只读不现算',
)
</script>

<template>
  <div class="tape" aria-label="指数报价与盘面广度">
    <div v-for="cell in cells" :key="cell.key" class="tape__cell">
      <span class="tape__k">{{ cell.name }}</span>
      <span class="tape__row">
        <strong class="tape__price" :class="cell.tone">{{ cell.price }}</strong>
        <span class="tape__pct" :class="cell.tone">{{ cell.pct }}</span>
      </span>
    </div>

    <el-tooltip :content="breadthTip" placement="bottom" :show-after="200">
      <div class="tape__cell tape__cell--aux">
        <span class="tape__k">涨停 / 跌停</span>
        <span class="tape__row">
          <strong class="tape__stat">{{ count(limitUp) }}</strong>
          <span class="tape__slash">/</span>
          <strong class="tape__stat">{{ count(limitDown) }}</strong>
        </span>
      </div>
    </el-tooltip>

    <div class="tape__cell tape__cell--aux">
      <span class="tape__k">触价提醒</span>
      <span class="tape__row">
        <strong class="tape__stat" :class="{ 'is-hot': alertCount > 0 }">{{ alertCount }}</strong>
      </span>
    </div>
  </div>
</template>

<style scoped>
.tape {
  flex: 0 0 auto;
  display: flex;
  align-items: stretch;
  border: 1px solid var(--rule);
  border-radius: var(--radius-lg, 10px);
  background: var(--sheet);
  box-shadow: var(--shadow);
  overflow-x: auto;
  overflow-y: hidden;
  scrollbar-width: thin;
}

.tape__cell {
  flex: 1 1 0;
  min-width: 150px;
  display: flex;
  flex-direction: column;
  justify-content: center;
  gap: 2px;
  padding: 10px 18px;
  border-left: 1px solid var(--rule);
  transition: background-color 300ms ease;
}

.tape__cell:first-child {
  border-left: none;
}

.tape__cell:hover {
  background: rgba(74, 111, 165, 0.04);
}

.tape__cell--aux {
  flex: 0 0 auto;
  min-width: 120px;
}

.tape__k {
  font-family: var(--font);
  font-size: 12px;
  font-weight: 500;
  line-height: 1.2;
  color: var(--muted);
  letter-spacing: 0.02em;
  white-space: nowrap;
}
.tape__row {
  align-items: baseline;
  gap: 8px;
  min-width: 0;
}

.tape__price {
  font-family: var(--font-mono);
  font-variant-numeric: tabular-nums;
  font-size: 24px;
  font-weight: 700;
  line-height: 1.1;
  letter-spacing: -0.01em;
}

.tape__pct {
  font-family: var(--font-mono);
  font-variant-numeric: tabular-nums;
  font-size: 14px;
  font-weight: 600;
}

.tape__stat {
  font-family: var(--font-mono);
  font-variant-numeric: tabular-nums;
  font-size: 18px;
  font-weight: 700;
  color: var(--seal-ink);
  line-height: 1.3;
}

.tape__stat.is-hot {
  color: var(--warn);
}

.tape__slash {
  font-family: var(--font-mono);
  color: var(--mist);
}

@media (max-width: 900px) {
  .tape__cell {
    min-width: 132px;
    padding: 8px 12px;
  }
}
</style>
