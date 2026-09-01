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
import { computed, nextTick, onBeforeUnmount, ref, watch } from 'vue'

import { getMinuteBars, type MinuteBar } from '@/shared/api/quant_market'
import {
  buildMinuteOption,
  computeMinuteDayStats,
  formatMinutePxPct,
} from '@/shared/lib/minuteChartOption'
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
  <el-dialog
    v-model="open"
    class="minute-dialog"
    :title="title"
    width="min(920px, 96vw)"
    top="6vh"
    destroy-on-close
    append-to-body
  >
    <div class="minute-shell">
      <header class="minute-head">
        <div class="minute-head__price mono" :class="pctTone">
          <template v-if="lastClose != null">
            {{ lastClose.toFixed(2) }}
            <span v-if="dayPct != null" class="minute-head__pct">
              {{ dayPct > 0 ? '+' : '' }}{{ dayPct.toFixed(2) }}%
            </span>
          </template>
          <template v-else>—</template>
        </div>
        <div class="minute-head__meta mist">
          <span v-if="prevClose != null">昨收 {{ prevClose.toFixed(2) }}</span>
          <template v-if="dayStats">
            <span class="tone-up">高 {{ formatMinutePxPct(dayStats.high, prevClose) }}</span>
            <span class="tone-down">低 {{ formatMinutePxPct(dayStats.low, prevClose) }}</span>
            <span v-if="dayStats.avg != null" class="tone-avg">
              均 {{ formatMinutePxPct(dayStats.avg, prevClose) }}
            </span>
          </template>
          <span v-if="source">实时 · {{ source }}</span>
          <span v-if="sessionAdjust === 'qfq'">前复权</span>
          <span v-else-if="sessionAdjust === 'hfq'">后复权</span>
          <span v-else>不复权</span>
          <span>不落库</span>
        </div>
      </header>

      <div class="minute-stage" :class="{ 'minute-stage--charted': hasBars }">
        <div v-if="busy" class="tape-load" aria-live="polite" aria-busy="true">
          <div class="tape-load__track">
            <div class="tape-load__stitch" />
          </div>
          <p class="tape-load__label">正在拉取 {{ tradeDate }} 分时走带…</p>
          <div class="tape-load__slots" aria-hidden="true">
            <span>09:30</span>
            <span>11:30</span>
            <span>13:00</span>
            <span>15:00</span>
          </div>
        </div>
        <div v-else-if="error" class="minute-error-wrap">
          <el-empty :description="error" :image-size="64">
            <template #extra>
              <el-button type="primary" size="small" :loading="busy" @click="load">
                重新拉取
              </el-button>
            </template>
          </el-empty>
        </div>
        <div v-show="hasBars" ref="chartEl" class="minute-chart" />
      </div>
    </div>
  </el-dialog>
</template>

<style scoped>
/*
* 高度：外壳给一个 55vh 的舞台上限（不是下限），图表用 flex 吃满。
* 旧写法是 .minute-shell{min-height:420px} + .minute-stage{min-height:360px}
* + .minute-chart{height:360px} 三重定高叠加：无数据时近 800px 死白。
*/
.minute-shell {
  display: flex;
  flex-direction: column;
  gap: var(--gap-2);
  min-height: 0;
}
.minute-head {
  display: flex;
  flex-wrap: wrap;
  align-items: baseline;
  justify-content: space-between;
  gap: var(--gap-1) var(--gap-3);
  flex-shrink: 0;
}
/* D2：弹窗里最大的字是当前价 */
.minute-head__price {
  font-size: var(--fs-tape);
  font-weight: 700;
  line-height: 1.05;
  letter-spacing: 0;
  font-variant-numeric: tabular-nums;
}
.minute-head__pct {
  margin-left: var(--gap-2);
  font-size: var(--fs-title);
  font-weight: 700;
}
.minute-head__meta {
  display: flex;
  flex-wrap: wrap;
  gap: var(--gap-1) var(--gap-3);
  font-size: var(--fs-aux);
  font-variant-numeric: tabular-nums;
}
.minute-stage {
  position: relative;
  flex: 1 1 auto;
  min-height: 0;
  border: 1px solid var(--rule);
  border-radius: var(--radius);
  background: var(--sheet);
  overflow: hidden;
}
/* 有数据时才占高度；空 / 报错时舞台跟着 el-empty 缩到内容高 */
.minute-stage--charted {
  height: 55vh;
  max-height: 26rem;
}
.minute-chart {
  width: 100%;
  height: 100%;
}
.tape-load {
  display: grid;
  place-content: center;
  gap: var(--gap-2);
  padding: var(--gap-4);
  text-align: center;
}
.tape-load__track {
  position: relative;
  width: min(420px, 88%);
  height: 3px;
  margin: 0 auto;
  border-radius: 999px;
  background: var(--rule);
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
  font-size: var(--fs-aux);
  color: var(--mist);
}
.tape-load__slots {
  display: flex;
  justify-content: space-between;
  width: min(420px, 88%);
  margin: 0 auto;
  font: var(--fs-kicker) / 1 var(--mono);
  font-variant-numeric: tabular-nums;
  color: var(--mist);
  letter-spacing: 0.04em;
}
.tone-up {
  color: var(--up);
}
.tone-down {
  color: var(--down);
}
/* 均价线不是涨跌语义，用状态橙（D1：红绿只留给涨跌） */
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
