<script setup lang="ts">
import { X } from '@lucide/vue'
import { computed } from 'vue'

import { chgClass } from '@/features/market/composables/dataQueryFormat'
import { Button } from '@/shared/components/ui/button'
import { compactNumber } from '@/shared/lib/format'
import { boardLimitRatio, detectLimitHit, limitLabel } from '@/shared/lib/limitBoard'
import type { KlineHoverPayload } from '@/shared/lib/klineConfig'

/**
 * 十字光标锁定的那根 K 线的读数：浮层卡（浮层底 + 大投影 + 毛玻璃），压在图上、不压弹层。
 * 头部 = 日期 + 涨跌 chip（+ 触板标签）；正文两列键值，数字等宽右对齐。
 */
const props = defineProps<{
  locked: KlineHoverPayload
  detailCode: string
  detailName: string
}>()

const emit = defineEmits<{ close: [] }>()

function fmtPx(v: unknown): string {
  const n = Number(v)
  if (!Number.isFinite(n)) return '—'
  return n.toFixed(2)
}

function fmtVol(v: unknown): string {
  return compactNumber(v)
}

function fmtAmt(v: unknown): string {
  return compactNumber(v)
}

function fmtSignedPx(delta: number | null): string {
  if (delta == null || !Number.isFinite(delta)) return '—'
  const sign = delta > 0 ? '+' : ''
  return `${sign}${delta.toFixed(2)}`
}

function fmtSignedPct(pct: number | null): string {
  if (pct == null || !Number.isFinite(pct)) return '—'
  const sign = pct > 0 ? '+' : ''
  return `${sign}${pct.toFixed(2)}%`
}

function toneOf(pct: number | null): string {
  return chgClass(pct)
}

function vsPrevPct(price: unknown): number | null {
  if (!props.locked.prevClose) return null
  const p = Number(price)
  const prev = props.locked.prevClose
  if (!Number.isFinite(p) || !prev) return null
  return ((p - prev) / prev) * 100
}

const lockPct = computed(() => {
  const close = Number(props.locked.bar.close)
  const prev = props.locked.prevClose
  if (!prev || !Number.isFinite(close)) return null
  return ((close - prev) / prev) * 100
})

const lockChange = computed(() => {
  const close = Number(props.locked.bar.close)
  const prev = props.locked.prevClose
  if (!prev || !Number.isFinite(close)) return null
  return close - prev
})

const lockAmp = computed(() => {
  const high = Number(props.locked.bar.high)
  const low = Number(props.locked.bar.low)
  const prev = props.locked.prevClose
  if (!prev || !Number.isFinite(high) || !Number.isFinite(low)) return null
  return { abs: high - low, pct: ((high - low) / prev) * 100 }
})

/** 触板方向：涨停红 / 跌停绿，跟收盘涨跌脱钩（地天板仍标跌停绿）。 */
const lockLimitKind = computed(() => {
  if (!props.locked.prevClose) return null
  return detectLimitHit(
    props.locked.bar,
    props.locked.prevClose,
    props.detailCode,
    props.detailName,
    'close',
  )
})

const lockLimitHint = computed(() => {
  const kind = lockLimitKind.value
  if (!kind) return null
  const pct = Math.round(boardLimitRatio(props.detailCode, props.detailName) * 100)
  return `${limitLabel(kind)} · ${pct}%板`
})

const lockLimitTone = computed(() => {
  if (lockLimitKind.value === 'up') return 'is-up'
  if (lockLimitKind.value === 'down') return 'is-down'
  return ''
})
</script>

<template>
  <aside class="k-readout" aria-label="K 线读数">
    <header class="k-readout__head">
      <div class="k-readout__lead">
        <strong class="k-readout__date">{{ locked.bar.trade_date.replaceAll('-', '/') }}</strong>
        <span class="k-readout__chip" :class="toneOf(lockPct)">{{ fmtSignedPct(lockPct) }}</span>
        <span v-if="lockLimitHint" class="k-readout__limit" :class="lockLimitTone">{{ lockLimitHint }}</span>
      </div>
      <Button access="read"
        type="button"
        variant="ghost"
        size="icon-xs"
        class="k-readout__close"
        aria-label="关闭读盘"
        @click="emit('close')"
      >
        <X aria-hidden="true" />
      </Button>
    </header>
    <dl class="k-readout__body">
      <div class="k-readout__row">
        <dt>开</dt>
        <dd :class="toneOf(vsPrevPct(locked.bar.open))">{{ fmtPx(locked.bar.open) }}</dd>
      </div>
      <div class="k-readout__row">
        <dt>高</dt>
        <dd :class="toneOf(vsPrevPct(locked.bar.high))">{{ fmtPx(locked.bar.high) }}</dd>
      </div>
      <div class="k-readout__row">
        <dt>低</dt>
        <dd :class="toneOf(vsPrevPct(locked.bar.low))">{{ fmtPx(locked.bar.low) }}</dd>
      </div>
      <div class="k-readout__row">
        <dt>收</dt>
        <dd :class="toneOf(lockPct)">{{ fmtPx(locked.bar.close) }}</dd>
      </div>
      <div class="k-readout__row">
        <dt>涨跌</dt>
        <dd :class="toneOf(lockPct)">{{ fmtSignedPx(lockChange) }}</dd>
      </div>
      <div v-if="lockAmp" class="k-readout__row">
        <dt>振幅</dt>
        <dd>{{ lockAmp.pct.toFixed(2) }}%</dd>
      </div>
      <div class="k-readout__row">
        <dt>量</dt>
        <dd class="k-readout__vol">{{ fmtVol(locked.volume) }}</dd>
      </div>
      <div v-if="locked.bar.amount != null" class="k-readout__row">
        <dt>额</dt>
        <dd>{{ fmtAmt(locked.bar.amount) }}</dd>
      </div>
      <div v-if="locked.bar.turnover != null" class="k-readout__row">
        <dt>换手</dt>
        <dd>{{ (Number(locked.bar.turnover) * 100).toFixed(2) }}%</dd>
      </div>
    </dl>
  </aside>
</template>

<style scoped>
/* 图内浮层（压图表不压弹层），组件内部层叠，不进全局 --z-* 序列 */
.k-readout {
  position: absolute;
  top: 8px;
  left: 8px;
  z-index: 5;
  width: 11.5rem;
  max-height: min(58%, 24rem);
  display: flex;
  flex-direction: column;
  overflow: auto;
  border: 1px solid var(--border-default);
  border-radius: var(--radius-lg);
  background: color-mix(in oklab, var(--surface-raised) 92%, transparent);
  box-shadow: var(--shadow-md);
  backdrop-filter: blur(12px) saturate(1.3);
  -webkit-backdrop-filter: blur(12px) saturate(1.3);
  pointer-events: auto;
  user-select: text;
}

.k-readout__head {
  position: sticky;
  top: 0;
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: var(--gap-1);
  padding: 8px 6px 6px 10px;
  border-bottom: 1px solid var(--border-subtle);
  background: inherit;
}

.k-readout__lead {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 4px 6px;
  min-width: 0;
}

.k-readout__date {
  color: var(--text-primary);
  font: 600 var(--fs-aux) / 1.3 var(--mono);
  font-variant-numeric: tabular-nums;
}

.k-readout__chip {
  display: inline-flex;
  align-items: center;
  height: 18px;
  padding: 0 6px;
  border-radius: var(--radius-sm);
  background: var(--surface-sunken);
  color: var(--text-secondary);
  font: 600 var(--fs-kicker) / 1 var(--mono);
  font-variant-numeric: tabular-nums;
}

.k-readout__chip.is-up {
  background: var(--up-soft);
  color: var(--up);
}

.k-readout__chip.is-down {
  background: var(--down-soft);
  color: var(--down);
}

.k-readout__limit {
  flex-basis: 100%;
  font-size: var(--fs-kicker);
  font-weight: 600;
}

.k-readout__close {
  flex: 0 0 auto;
  color: var(--text-tertiary);
}

.k-readout__body {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 2px 10px;
  margin: 0;
  padding: 8px 10px 10px;
}

.k-readout__row {
  display: flex;
  align-items: baseline;
  justify-content: space-between;
  gap: 6px;
  min-height: 20px;
  font-size: var(--fs-aux);
}

.k-readout__row dt {
  margin: 0;
  color: var(--text-tertiary);
  font-weight: 500;
  white-space: nowrap;
}

.k-readout__row dd {
  margin: 0;
  color: var(--text-primary);
  font-family: var(--mono);
  font-weight: 600;
  font-variant-numeric: tabular-nums;
  text-align: right;
}

/* 量不是涨跌语义，用状态橙 */
.k-readout__vol {
  color: var(--warn);
}

.k-readout .is-up {
  color: var(--up);
}

.k-readout .is-down {
  color: var(--down);
}

@media (prefers-reduced-motion: reduce) {
  .k-readout {
    backdrop-filter: none;
    -webkit-backdrop-filter: none;
    background: var(--surface-raised);
  }
}

@media (max-width: 640px) {
  .k-readout {
    width: calc(100% - 16px);
    max-height: 44%;
  }

  .k-readout__body {
    grid-template-columns: repeat(3, minmax(0, 1fr));
  }
}
</style>
