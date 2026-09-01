<script setup lang="ts">
import * as echarts from 'echarts/core'
import { BarChart, CandlestickChart, LineChart } from 'echarts/charts'
import {
  DataZoomComponent,
  GridComponent,
  LegendComponent,
  MarkPointComponent,
  TooltipComponent,
} from 'echarts/components'
import { CanvasRenderer } from 'echarts/renderers'
import { computed, onBeforeUnmount, onMounted, ref, watch } from 'vue'

import type { ChartPrepResult } from '@/shared/lib/chartPrep'
import {
  DEFAULT_MA_PERIODS,
  type IndicatorKind,
  type KlineHoverPayload,
} from '@/shared/lib/klineConfig'
import type { KPeriod, OhlcBar } from '@/shared/lib/indicators'
import { buildKlineOption } from '@/shared/lib/klineChartOption'
import type { StrategySignalMark } from '@/shared/lib/klineStrategyMarks'
import { resolveKlineDblclickIndex } from '@/shared/lib/klineDblclick'
import { useChartTheme } from '@/shared/lib/useChartTheme'
import { prepChartOffthread } from '@/shared/lib/useChartPrep'

echarts.use([
  CandlestickChart,
  LineChart,
  BarChart,
  GridComponent,
  TooltipComponent,
  LegendComponent,
  DataZoomComponent,
  MarkPointComponent,
  CanvasRenderer,
])

export type KlineBarDblclickPayload = {
  tradeDate: string
  bar: OhlcBar
  prevClose: number | null
  index: number
}

const props = withDefaults(
  defineProps<{
    bars: OhlcBar[]
    period?: KPeriod
    indicator?: IndicatorKind
    maPeriods?: number[]
    /** 默认可见根数（数据更长时 dataZoom 只展示最近 N 根） */
    visibleBars?: number
    title?: string
    /** 涨跌停判定用 */
    stockCode?: string
    stockName?: string
    /** 库内还有更早 K 线可加载 */
    hasMoreHistory?: boolean
    /** 锚定到该交易日（日 K） */
    focusDate?: string
    /** 策略选股信号标注 */
    strategySignals?: StrategySignalMark[]
  }>(),
  {
    period: 'day',
    indicator: 'macd',
    maPeriods: () => [...DEFAULT_MA_PERIODS],
    visibleBars: 60,
    title: '',
    stockCode: '',
    stockName: '',
    hasMoreHistory: false,
    focusDate: '',
    strategySignals: () => [],
  },
)

const emit = defineEmits<{
  hover: [KlineHoverPayload | null]
  needHistory: []
  barDblclick: [KlineBarDblclickPayload]
}>()

const rootEl = ref<HTMLElement | null>(null)
const chartEl = ref<HTMLElement | null>(null)
const { tokens } = useChartTheme()
let chart: echarts.ECharts | null = null
let resizeObs: ResizeObserver | null = null
let zoomStart = 0
let zoomEnd = 100
let latestPrep: ChartPrepResult | null = null
let renderSeq = 0
let historyEmitAt = 0
let keepZoomNext = false
/** code|date，避免换票但同日时不再锚定 */
let lastFocusedKey = ''
/** 轴指示器最新索引；双击空白处时用它对齐左侧锁定 K 线 */
let lastHoverIndex = -1

const LABEL_VISIBLE_MAX = 90

const ariaLabel = computed(() => {
  const p = { day: '日K', week: '周K', month: '月K' }[props.period]
  const ind = { macd: 'MACD', kdj: 'KDJ' }[props.indicator]
  return `${p} · ${ind}`
})

function at(series: Array<number | null> | undefined, i: number): number | null {
  if (!series) return null
  const v = series[i]
  return v == null || Number.isNaN(Number(v)) ? null : Number(v)
}

function visibleCountOf(n: number): number {
  return Math.max(1, Math.round((n * (zoomEnd - zoomStart)) / 100))
}

function shouldShowBarLabels(n: number): boolean {
  return n > 0 && visibleCountOf(n) <= LABEL_VISIBLE_MAX
}

function defaultZoom(n: number): { start: number; end: number } {
  const vis = Math.max(20, props.visibleBars)
  if (n <= vis) return { start: 0, end: 100 }
  return { start: Math.max(0, 100 - (vis / n) * 100), end: 100 }
}

function zoomAroundIndex(idx: number, n: number): { start: number; end: number } {
  const vis = Math.max(20, props.visibleBars)
  if (n <= vis) return { start: 0, end: 100 }
  const windowPct = (vis / n) * 100
  const centerPct = n <= 1 ? 50 : (idx / (n - 1)) * 100
  let start = centerPct - windowPct * 0.55
  let end = start + windowPct
  if (start < 0) {
    start = 0
    end = windowPct
  }
  if (end > 100) {
    end = 100
    start = Math.max(0, 100 - windowPct)
  }
  return { start, end }
}

function findFocusIndex(prep: ChartPrepResult): number {
  const d = String(props.focusDate || '').trim()
  if (!d || props.period !== 'day') return -1
  const byDate = prep.dates.indexOf(d)
  if (byDate >= 0) return byDate
  return prep.seriesBars.findIndex((b) => String(b.trade_date || '').slice(0, 10) === d)
}

function buildOption(prep: ChartPrepResult) {
  return buildKlineOption({
    prep,
    indicator: props.indicator,
    maPeriods: props.maPeriods,
    showBarLabels: shouldShowBarLabels(prep.dates.length),
    zoomStart,
    zoomEnd,
    stockCode: props.stockCode,
    stockName: props.stockName,
    strategySignals: props.strategySignals,
    tokens: tokens.value,
  })
}

function buildHover(dataIndex: number): KlineHoverPayload | null {
  const prep = latestPrep
  if (!prep?.seriesBars || dataIndex < 0 || dataIndex >= prep.seriesBars.length) return null
  const bar = prep.seriesBars[dataIndex]
  const prevClose = dataIndex > 0 ? Number(prep.seriesBars[dataIndex - 1].close ?? NaN) : null
  return {
    bar,
    prevClose: prevClose != null && Number.isFinite(prevClose) ? prevClose : null,
    index: dataIndex,
    ma: props.maPeriods.map((period) => ({
      period,
      value: at(prep.maLines.find((m) => m.period === period)?.data, dataIndex),
    })),
    volume: bar.volume == null ? null : Number(bar.volume),
    volumeMa: prep.volumeMas.map((m) => ({
      period: m.period,
      value: at(m.data, dataIndex),
    })),
    macd: prep.macd
      ? {
          dif: at(prep.macd.dif, dataIndex),
          dea: at(prep.macd.dea, dataIndex),
          hist: at(prep.macd.hist, dataIndex),
        }
      : null,
    kdj: prep.kdj
      ? {
          k: at(prep.kdj.k, dataIndex),
          d: at(prep.kdj.d, dataIndex),
          j: at(prep.kdj.j, dataIndex),
        }
      : null,
  }
}

function emitHover(dataIndex: number): void {
  lastHoverIndex = dataIndex
  emit('hover', buildHover(dataIndex))
}

function resolveAxisIndex(value: unknown): number {
  if (typeof value === 'number' && Number.isFinite(value)) return Math.round(value)
  if (typeof value === 'string' && latestPrep) {
    return latestPrep.dates.indexOf(value)
  }
  return -1
}

function patchBarLabels(): void {
  if (!chart || !latestPrep) return
  const show = shouldShowBarLabels(latestPrep.dates.length)
  chart.setOption(
    {
      series: [{ name: 'K线', label: { show } }],
    },
    { lazyUpdate: true },
  )
}

function bindChartEvents(): void {
  if (!chart) return
  chart.off('datazoom')
  chart.off('updateAxisPointer')
  chart.off('globalout')
  chart.off('dblclick')
  chart.on('datazoom', (raw: unknown) => {
    const ev = raw as { start?: number; end?: number; batch?: Array<{ start?: number; end?: number }> }
    const batch = ev.batch?.[0]
    const start = batch?.start ?? ev.start
    const end = batch?.end ?? ev.end
    if (typeof start === 'number') zoomStart = start
    if (typeof end === 'number') zoomEnd = end
    patchBarLabels()
    if (
      props.hasMoreHistory &&
      typeof start === 'number' &&
      start <= 4 &&
      Date.now() - historyEmitAt > 900
    ) {
      historyEmitAt = Date.now()
      emit('needHistory')
    }
  })
  chart.on('updateAxisPointer', (raw: unknown) => {
    const ev = raw as { axesInfo?: Array<{ value?: unknown; axisDim?: string }> }
    const xInfo = ev.axesInfo?.find((a) => a.axisDim === 'x') ?? ev.axesInfo?.[0]
    const idx = resolveAxisIndex(xInfo?.value)
    if (idx >= 0) emitHover(idx)
  })
  chart.on('globalout', () => {
    if (latestPrep?.seriesBars.length) emitHover(latestPrep.seriesBars.length - 1)
  })
  chart.on('dblclick', (raw: unknown) => {
    if (props.period !== 'day' || !latestPrep) return
    const ev = raw as { dataIndex?: number; name?: string }
    const idx = resolveKlineDblclickIndex({
      dates: latestPrep.dates,
      name: ev.name,
      dataIndex: ev.dataIndex,
      hoverIndex: lastHoverIndex,
    })
    if (idx < 0) return
    const bar = latestPrep.seriesBars[idx]
    if (!bar) return
    const tradeDate = String(bar.trade_date || latestPrep.dates[idx] || '').slice(0, 10)
    if (!/^\d{4}-\d{2}-\d{2}$/.test(tradeDate)) return
    const prev = idx > 0 ? Number(latestPrep.seriesBars[idx - 1]?.close ?? NaN) : null
    emit('barDblclick', {
      tradeDate,
      bar,
      prevClose: prev != null && Number.isFinite(prev) ? prev : null,
      index: idx,
    })
  })
}

async function render(opts: { keepZoom?: boolean; prevBarCount?: number } = {}): Promise<void> {
  if (!chartEl.value) return
  if (!chart) {
    chart = echarts.init(chartEl.value, undefined, { renderer: 'canvas' })
    bindChartEvents()
  }
  if (!props.bars.length) {
    chart.clear()
    latestPrep = null
    lastHoverIndex = -1
    emit('hover', null)
    return
  }
  const my = ++renderSeq
  const prep = await prepChartOffthread({
    bars: props.bars,
    period: props.period,
    maPeriods: props.maPeriods,
    indicator: props.indicator,
  })
  if (my !== renderSeq) return
  latestPrep = prep
  const focusIdx = findFocusIndex(prep)
  const focusDate = String(props.focusDate || '').trim()
  const focusKey = focusDate ? `${props.stockCode}|${focusDate}` : ''
  const shouldFocus = focusIdx >= 0 && focusKey !== lastFocusedKey
  const preserveZoom = keepZoomNext || opts.keepZoom
  keepZoomNext = false
  if (shouldFocus) {
    const z = zoomAroundIndex(focusIdx, prep.dates.length)
    zoomStart = z.start
    zoomEnd = z.end
    lastFocusedKey = focusKey
  } else if (!preserveZoom) {
    const z = defaultZoom(prep.dates.length)
    zoomStart = z.start
    zoomEnd = z.end
  } else if (
    opts.prevBarCount != null &&
    opts.prevBarCount > 0 &&
    prep.dates.length > opts.prevBarCount
  ) {
    const added = prep.dates.length - opts.prevBarCount
    const shift = (added / prep.dates.length) * 100
    zoomStart = Math.min(99, zoomStart * (opts.prevBarCount / prep.dates.length) + shift)
    zoomEnd = Math.min(100, zoomEnd * (opts.prevBarCount / prep.dates.length) + shift)
  }
  if (focusDate && focusIdx < 0 && props.hasMoreHistory && Date.now() - historyEmitAt > 400) {
    historyEmitAt = Date.now()
    emit('needHistory')
  }
  chart.setOption(buildOption(prep) as echarts.EChartsCoreOption, { notMerge: true })
  if (focusIdx >= 0) emitHover(focusIdx)
  else if (prep.seriesBars.length) emitHover(prep.seriesBars.length - 1)
}

onMounted(() => {
  void render()
  if (rootEl.value) {
    resizeObs = new ResizeObserver(() => chart?.resize())
    resizeObs.observe(rootEl.value)
  }
})

onBeforeUnmount(() => {
  renderSeq += 1
  resizeObs?.disconnect()
  chart?.dispose()
  chart = null
})

let prevBarLen = 0
watch(
  () =>
    [
      props.bars,
      props.period,
      props.indicator,
      props.maPeriods,
      props.visibleBars,
      props.focusDate,
      props.strategySignals,
      // canvas 颜色是 setOption 时的快照，主题变了必须重绘，否则深色下仍是浅色档轴线
      tokens.value,
    ] as const,
  () => {
    const len = props.bars.length
    const grew = len > prevBarLen && prevBarLen > 0
    const prev = prevBarLen
    prevBarLen = len
    const nextFocusKey = props.focusDate
      ? `${props.stockCode}|${String(props.focusDate).trim()}`
      : ''
    const focusChanged = nextFocusKey !== lastFocusedKey
    void render(
      grew && !focusChanged ? { keepZoom: true, prevBarCount: prev } : {},
    )
  },
  { deep: true },
)
</script>

<template>
  <div class="kline-chart" ref="rootEl">
    <div ref="chartEl" class="kline-chart__canvas" role="img" :aria-label="ariaLabel" />
  </div>
</template>

<style scoped>
.kline-chart {
  width: 100%;
  height: 100%;
  min-height: 0;
  flex: 1 1 auto;
  display: flex;
  flex-direction: column;
}

.kline-chart__canvas {
  flex: 1 1 auto;
  min-height: 360px;
  width: 100%;
  height: 100%;
}
</style>
