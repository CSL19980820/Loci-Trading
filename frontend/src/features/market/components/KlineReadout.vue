<script setup lang="ts">
import { Close } from '@element-plus/icons-vue'
import { computed } from 'vue'

import { chgClass } from '@/features/market/composables/dataQueryFormat'
import { compactNumber } from '@/shared/lib/format'
import { boardLimitRatio, detectLimitHit, limitLabel } from '@/shared/lib/limitBoard'
import type { KlineHoverPayload } from '@/shared/lib/klineConfig'

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
      <div>
        <strong>{{ locked.bar.trade_date.replaceAll('-', '/') }}</strong>
        <span v-if="lockLimitHint" class="k-readout__limit" :class="lockLimitTone">
          {{ lockLimitHint }}
        </span>
      </div>
      <el-button
        native-type="button"
        class="k-readout__close"
        circle
        text
        size="small"
        :icon="Close"
        aria-label="关闭读盘"
        @click="emit('close')"
      />
    </header>
    <dl class="k-readout__body">
      <div class="k-readout__row">
        <dt>开</dt>
        <dd class="mono" :class="toneOf(vsPrevPct(locked.bar.open))">{{ fmtPx(locked.bar.open) }}</dd>
      </div>
      <div class="k-readout__row">
        <dt>高</dt>
        <dd class="mono" :class="toneOf(vsPrevPct(locked.bar.high))">{{ fmtPx(locked.bar.high) }}</dd>
      </div>
      <div class="k-readout__row">
        <dt>低</dt>
        <dd class="mono" :class="toneOf(vsPrevPct(locked.bar.low))">{{ fmtPx(locked.bar.low) }}</dd>
      </div>
      <div class="k-readout__row">
        <dt>收</dt>
        <dd class="mono" :class="toneOf(lockPct)">{{ fmtPx(locked.bar.close) }}</dd>
      </div>
      <div class="k-readout__row">
        <dt>量</dt>
        <dd class="mono k-readout__vol">{{ fmtVol(locked.volume) }}</dd>
      </div>
      <div v-if="locked.bar.amount != null" class="k-readout__row">
        <dt>额</dt>
        <dd class="mono">{{ fmtAmt(locked.bar.amount) }}</dd>
      </div>
      <div class="k-readout__row">
        <dt>涨幅</dt>
        <dd class="mono k-readout__pair" :class="toneOf(lockPct)">
          <span>{{ fmtSignedPx(lockChange) }}</span>
          <span>{{ fmtSignedPct(lockPct) }}</span>
        </dd>
      </div>
      <div v-if="lockAmp" class="k-readout__row">
        <dt>振幅</dt>
        <dd class="mono k-readout__pair">
          <span>{{ lockAmp.abs.toFixed(2) }}</span>
          <span>{{ lockAmp.pct.toFixed(2) }}%</span>
        </dd>
      </div>
      <div v-if="locked.bar.turnover != null" class="k-readout__row">
        <dt>换手</dt>
        <dd class="mono">{{ (Number(locked.bar.turnover) * 100).toFixed(2) }}%</dd>
      </div>
    </dl>
  </aside>
</template>

<style scoped>
/* 图内浮层（压图表不压弹层），组件内部层叠，不进全局 --z-* 序列 */
.k-readout {
  position: absolute;
  top: 0.45rem;
  left: 0.45rem;
  z-index: 5;
  width: 10.25rem;
  max-height: min(52%, 22rem);
  display: flex;
  flex-direction: column;
  overflow: auto;
  border: 1px solid color-mix(in oklab, var(--rule) 70%, var(--seal) 18%);
  border-radius: var(--radius);
  background: color-mix(in oklab, var(--sheet) 95%, transparent);
  backdrop-filter: blur(10px);
  -webkit-backdrop-filter: blur(10px);
  /* D3：卡片无阴影，靠 hairline 与半透明底分层 */
  pointer-events: auto;
  user-select: text;
}
.k-readout__head {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 0.35rem;
  padding: 0.4rem 0.45rem 0.3rem;
  border-bottom: 1px solid color-mix(in oklab, var(--rule) 65%, transparent);
  position: sticky;
  top: 0;
  background: color-mix(in oklab, var(--paper) 88%, transparent);
  backdrop-filter: blur(8px);
}
.k-readout__head strong {
  display: block;
  font: 700 var(--fs-aux)/1.3 var(--mono);
  color: var(--ink);
}
.k-readout__limit {
  display: inline-block;
  margin-top: 0.15rem;
  font-size: var(--fs-kicker);
  font-weight: 700;
}
.k-readout__close.el-button {
  --el-button-text-color: var(--mist);
  --el-button-hover-text-color: var(--ink);
  --el-button-hover-bg-color: color-mix(in oklab, var(--sheet) 72%, transparent);
  --el-button-active-text-color: var(--ink);
  flex: 0 0 auto;
  width: var(--ctl-h);
  height: var(--ctl-h);
  margin: -0.18rem -0.15rem 0 0;
  padding: 0;
}
.k-readout__body {
  margin: 0;
  padding: 0.25rem 0.45rem 0.45rem;
}
.k-readout__row {
  display: grid;
  grid-template-columns: 1.6rem 1fr;
  gap: 0.25rem;
  align-items: baseline;
  padding: 0.12rem 0;
  font-size: var(--fs-aux);
  font-variant-numeric: tabular-nums;
  border-bottom: 1px dashed color-mix(in oklab, var(--rule) 55%, transparent);
}
.k-readout__row:last-child {
  border-bottom: 0;
}
.k-readout__row dt {
  margin: 0;
  color: var(--mist);
  font-weight: 500;
}
.k-readout__row dd {
  margin: 0;
  text-align: right;
  font-weight: 700;
}
.k-readout__pair {
  display: flex;
  justify-content: flex-end;
  align-items: baseline;
  gap: 0.35rem;
  white-space: nowrap;
}
.k-readout__pair span:last-child {
  font-size: var(--fs-kicker);
  font-weight: 500;
  opacity: 0.9;
}
/* 量不是涨跌语义，用状态橙 */
.k-readout__vol {
  color: var(--warn);
}
/* D1：读盘里的涨跌只能是涨跌色，旧版借了 --seal（品牌）与 --lake（旧湖绿） */
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
    background: var(--sheet);
  }
}
</style>
