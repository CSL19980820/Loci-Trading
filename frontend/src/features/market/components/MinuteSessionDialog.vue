<script setup lang="ts">
/**
 * 日 K 双击打开的分时会话：实时拉取、不落库。
 * 签名动效：加载时「走带」沿交易时段横扫，避免空白干等。
 */
import * as echarts from 'echarts/core'
import { BarChart, LineChart } from 'echarts/charts'
import {
  GridComponent,
  MarkLineComponent,
  MarkPointComponent,
  TooltipComponent,
} from 'echarts/components'
import { CanvasRenderer } from 'echarts/renderers'
import { LoaderCircle } from '@lucide/vue'
import { computed, nextTick, onBeforeUnmount, ref, watch } from 'vue'

import { getMinuteBars, type MinuteBar } from '@/shared/api/quant_market'
import {
  buildMinuteOption,
  computeMinuteDayStats,
  formatMinutePxPct,
} from '@/shared/lib/minuteChartOption'
import EmptyState from '@/shared/components/ui/EmptyState.vue'
import { Button } from '@/shared/components/ui/button'
import { Dialog, DialogContent, DialogDescription, DialogHeader, DialogTitle } from '@/shared/components/ui/dialog'
import { useChartTheme } from '@/shared/lib/useChartTheme'

echarts.use([
  LineChart,
  BarChart,
  GridComponent,
  TooltipComponent,
  MarkLineComponent,
  MarkPointComponent,
  CanvasRenderer,
])

const props = defineProps<{
  modelValue: boolean
  code: string
  name: string
  tradeDate: string
  prevClose: number | null
  /** 与日 K 当前复权一致；源无前复权分时，由后端用因子缩放 */
  adjust?: 'qfq' | 'hfq' | 'none'
}>()

const emit = defineEmits<{
  'update:modelValue': [boolean]
}>()

const busy = ref(false)
const error = ref('')
const bars = ref<MinuteBar[]>([])
const source = ref('')
const sessionAdjust = ref<'qfq' | 'hfq' | 'none'>('none')
/** 优先用接口昨收（已按 adjust 对齐）；仅在缺库时回退日 K 传入值 */
const sessionPrevClose = ref<number | null>(null)
const chartEl = ref<HTMLElement | null>(null)
const { tokens } = useChartTheme()
let chart: echarts.ECharts | null = null
let resizeObs: ResizeObserver | null = null
let seq = 0

const open = computed({
  get: () => props.modelValue,
  set: (v: boolean) => emit('update:modelValue', v),
})

const title = computed(() => {
  const who = props.name ? `${props.name} ${props.code}` : props.code
  return `${who} · ${props.tradeDate} 分时`
})

const prevClose = computed(() => sessionPrevClose.value)

const lastClose = computed(() => {
  const b = bars.value
  if (!b.length) return null
  const n = Number(b[b.length - 1]?.close)
  return Number.isFinite(n) ? n : null
})

const dayPct = computed(() => {
  const c = lastClose.value
  const p = prevClose.value
  if (c == null || p == null || !Number.isFinite(p) || p === 0) return null
  return ((c - p) / p) * 100
})

const pctTone = computed(() => {
  const p = dayPct.value
  if (p == null) return ''
  if (p > 0) return 'tone-up'
  if (p < 0) return 'tone-down'
  return ''
})

const dayStats = computed(() => computeMinuteDayStats(bars.value))

/** 只有真有走带时舞台才吃高度；空 / 报错时跟着内容缩 */
const hasBars = computed(() => !busy.value && !error.value && bars.value.length > 0)

function disposeChart(): void {
  resizeObs?.disconnect()
  resizeObs = null
  chart?.dispose()
  chart = null
}

function paint(): void {
  if (!chartEl.value) return
  if (!chart) {
    chart = echarts.init(chartEl.value, undefined, { renderer: 'canvas' })
    resizeObs = new ResizeObserver(() => chart?.resize())
    resizeObs.observe(chartEl.value)
  }
  if (!bars.value.length) {
    chart.clear()
    return
  }
  chart.setOption(
    buildMinuteOption({
      bars: bars.value,
      prevClose: prevClose.value,
      tokens: tokens.value,
    }) as echarts.EChartsCoreOption,
    { notMerge: true },
  )
}

async function load(): Promise<void> {
  const my = ++seq
  busy.value = true
  error.value = ''
  bars.value = []
  source.value = ''
  sessionAdjust.value = props.adjust ?? 'none'
  sessionPrevClose.value = null
  disposeChart()
  try {
    const res = await getMinuteBars(props.code, {
      date: props.tradeDate,
      period: '1',
      adjust: props.adjust ?? 'none',
    })
    if (my !== seq) return
    bars.value = res.bars ?? []
    source.value = res.source || ''
    if (res.adjust === 'qfq' || res.adjust === 'hfq' || res.adjust === 'none') {
      sessionAdjust.value = res.adjust
    }
    const apiPrev = Number(res.prev_close)
    // 有接口昨收时必用（已按 adjust 对齐）；缺库才回退日 K 传入值
    sessionPrevClose.value =
      Number.isFinite(apiPrev) && apiPrev > 0 ? apiPrev : props.prevClose
    if (!bars.value.length) {
      error.value = `${props.tradeDate} 无分时数据，换个交易日`
    } else {
      // 防错日：源若返回其它交易日的走带，不静默展示
      const sample = String(bars.value[0]?.datetime || '').slice(0, 10)
      if (/^\d{4}-\d{2}-\d{2}$/.test(sample) && sample !== props.tradeDate) {
        error.value = `源返回 ${sample} 而非 ${props.tradeDate}，已拒绝展示`
        bars.value = []
      }
    }
  } catch (e) {
    if (my !== seq) return
    error.value = e instanceof Error ? e.message : String(e)
  } finally {
    if (my === seq) busy.value = false
  }
  await nextTick()
  if (my === seq && bars.value.length) paint()
}

watch(
  () => [props.modelValue, props.code, props.tradeDate, props.adjust, tokens.value] as const,
  ([openNow]) => {
    if (openNow && props.code && props.tradeDate) void load()
    if (!openNow) {
      seq += 1
      disposeChart()
      bars.value = []
      error.value = ''
      sessionPrevClose.value = null
    }
  },
)

onBeforeUnmount(() => {
  seq += 1
  disposeChart()
})
</script>

<template>
  <Dialog v-model:open="open">
    <DialogContent class="minute-dialog gap-0 p-0 sm:max-w-4xl">
      <DialogHeader class="minute-head text-left">
        <div class="minute-head__id">
          <DialogTitle class="minute-head__title">{{ title }}</DialogTitle>
          <DialogDescription class="minute-head__meta">
            <span v-if="prevClose != null">昨收 {{ prevClose.toFixed(2) }}</span>
            <template v-if="dayStats">
              <span :class="prevClose == null || dayStats.high === prevClose ? '' : dayStats.high > prevClose ? 'tone-up' : 'tone-down'">高 {{ formatMinutePxPct(dayStats.high, prevClose) }}</span>
              <span :class="prevClose == null || dayStats.low === prevClose ? '' : dayStats.low > prevClose ? 'tone-up' : 'tone-down'">低 {{ formatMinutePxPct(dayStats.low, prevClose) }}</span>
              <span v-if="dayStats.avg != null" class="tone-avg">均 {{ formatMinutePxPct(dayStats.avg, prevClose) }}</span>
            </template>
            <span v-if="source">来源 {{ source }}</span>
            <span v-if="sessionAdjust === 'qfq'">前复权</span>
            <span v-else-if="sessionAdjust === 'hfq'">后复权</span>
            <span v-else>不复权</span>
          </DialogDescription>
        </div>
        <div class="minute-head__price" :class="pctTone" aria-label="收盘价">
          <template v-if="lastClose != null">
            <span class="minute-head__last">{{ lastClose.toFixed(2) }}</span>
            <span v-if="dayPct != null" class="minute-head__pct" :class="pctTone">
              {{ dayPct > 0 ? '+' : '' }}{{ dayPct.toFixed(2) }}%
            </span>
          </template>
          <span v-else class="minute-head__last">—</span>
        </div>
      </DialogHeader>

      <div class="minute-shell">
        <div class="minute-stage" :class="{ 'minute-stage--charted': hasBars }">
          <div v-if="busy" class="tape-load" aria-live="polite" aria-busy="true">
            <div class="tape-load__track">
              <div class="tape-load__stitch" />
            </div>
            <p class="tape-load__label">正在获取 {{ tradeDate }} 分时…</p>
            <div class="tape-load__slots" aria-hidden="true">
              <span>09:30</span>
              <span>11:30</span>
              <span>13:00</span>
              <span>15:00</span>
            </div>
          </div>
          <div v-else-if="error" class="minute-error-wrap">
            <EmptyState description="暂无分时数据" :reason="error">
              <Button access="read" size="sm" :disabled="busy" @click="load">
                <LoaderCircle v-if="busy" class="size-3.5 animate-spin" aria-hidden="true" />
                重新拉取
              </Button>
            </EmptyState>
          </div>
          <div v-show="hasBars" ref="chartEl" class="minute-chart" />
        </div>
      </div>
    </DialogContent>
  </Dialog>
</template>

<style scoped>
/*
 * 高度：舞台上限 56vh（不是下限），图表用 flex 吃满。
 * 旧写法三重定高叠加，无数据时近 800px 死白；现在空态 / 报错跟着内容缩。
 */
.minute-head {
  display: flex;
  flex-direction: row;
  align-items: flex-start;
  justify-content: space-between;
  gap: var(--gap-4);
  padding: var(--gap-5) var(--gap-5) var(--gap-4);
  padding-right: calc(var(--gap-5) + 32px);
  border-bottom: 1px solid var(--border-subtle);
}

.minute-head__id {
  display: flex;
  flex-direction: column;
  gap: 6px;
  min-width: 0;
}

.minute-head__title {
  margin: 0;
  font-size: var(--fs-title);
  font-weight: 600;
  letter-spacing: -0.01em;
}

.minute-head__meta {
  display: flex;
  flex-wrap: wrap;
  gap: 4px var(--gap-3);
  margin: 0;
  color: var(--text-tertiary);
  font-family: var(--mono);
  font-size: var(--fs-aux);
  font-variant-numeric: tabular-nums;
}

.minute-head__price {
  display: flex;
  flex-shrink: 0;
  align-items: baseline;
  gap: var(--gap-2);
}

.minute-head__last {
  font-family: var(--mono);
  font-size: var(--fs-display);
  font-weight: 600;
  letter-spacing: -0.02em;
  line-height: 1;
  color: var(--text-primary);
  font-variant-numeric: tabular-nums;
}

.minute-head__pct {
  display: inline-flex;
  align-items: center;
  height: 22px;
  padding: 0 7px;
  border-radius: var(--radius-sm);
  background: var(--surface-sunken);
  color: var(--text-secondary);
  font-family: var(--mono);
  font-size: var(--fs-aux);
  font-weight: 600;
  font-variant-numeric: tabular-nums;
}

.minute-head__pct.tone-up {
  background: var(--up-soft);
}

.minute-head__pct.tone-down {
  background: var(--down-soft);
}

.minute-shell {
  display: flex;
  flex-direction: column;
  min-width: 0;
  min-height: 0;
  padding: var(--gap-4) var(--gap-5) var(--gap-5);
}

.minute-stage {
  position: relative;
  display: flex;
  flex-direction: column;
  min-width: 0;
  min-height: 0;
  overflow: hidden;
  border: 1px solid var(--border-subtle);
  border-radius: var(--radius-lg);
  background: var(--surface);
}

.minute-stage--charted {
  height: 56vh;
  max-height: 28rem;
}

.minute-chart {
  height: 100%;
}

.tape-load {
  display: grid;
  place-content: center;
  gap: var(--gap-2);
  padding: var(--gap-6) var(--gap-4);
  text-align: center;
}

.tape-load__track {
  position: relative;
  width: min(420px, 88%);
  height: 3px;
  margin: 0 auto;
  border-radius: 999px;
  background: var(--border-subtle);
  overflow: hidden;
}

.tape-load__stitch {
  position: absolute;
  inset: 0 auto 0 0;
  width: 38%;
  border-radius: inherit;
  background: linear-gradient(90deg, transparent, var(--seal), transparent);
  animation: tape-sweep 1.35s cubic-bezier(0.45, 0.05, 0.25, 1) infinite;
}

.tape-load__label {
  margin: 0;
  color: var(--text-tertiary);
  font-size: var(--fs-aux);
}

.tape-load__slots {
  display: flex;
  justify-content: space-between;
  width: min(420px, 88%);
  margin: 0 auto;
  color: var(--text-tertiary);
  font: var(--fs-kicker) / 1 var(--mono);
  font-variant-numeric: tabular-nums;
  letter-spacing: 0.04em;
}

.tone-up {
  color: var(--up);
}

.tone-down {
  color: var(--down);
}

.tone-avg {
  color: var(--warn);
}

.minute-error-wrap {
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  padding: var(--gap-4) var(--gap-2);
}

@media (max-width: 640px) {
  .minute-head {
    flex-direction: column;
    gap: var(--gap-2);
    padding: var(--gap-3) var(--gap-4) var(--gap-3);
    padding-right: calc(var(--gap-4) + 36px);
  }

  .minute-head__last {
    font-size: var(--fs-tape);
  }

  .minute-shell {
    padding: var(--gap-3) var(--gap-4) var(--gap-4);
  }

  .minute-stage--charted {
    height: 48vh;
    max-height: none;
  }
}

@media (prefers-reduced-motion: reduce) {
  .tape-load__stitch {
    animation: none;
    width: 100%;
    opacity: 0.55;
  }
}

@keyframes tape-sweep {
  0% {
    transform: translateX(-40%);
  }

  100% {
    transform: translateX(280%);
  }
}
</style>
