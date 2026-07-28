<script setup lang="ts">
import {
  CandlestickSeries,
  ColorType,
  createChart,
  type IChartApi,
  type ISeriesApi,
  type CandlestickData,
  type Time,
} from 'lightweight-charts'
import { computed, onBeforeUnmount, onMounted, ref, watch } from 'vue'

import type { KPeriod, OhlcBar } from '@/shared/lib/indicators'
import { resampleOffthread } from '@/shared/lib/useChartPrep'

const props = withDefaults(
  defineProps<{
    bars: OhlcBar[]
    period?: KPeriod
  }>(),
  { period: 'day' },
)

const rootEl = ref<HTMLElement | null>(null)
const chartEl = ref<HTMLElement | null>(null)
let chart: IChartApi | null = null
let series: ISeriesApi<'Candlestick'> | null = null
let resizeObs: ResizeObserver | null = null
let renderSeq = 0

const ariaLabel = computed(() => {
  const p = { day: '日K', week: '周K', month: '月K' }[props.period]
  return `${p} · Lightweight Charts`
})

async function toCandleData(bars: OhlcBar[]): Promise<CandlestickData<Time>[]> {
  const resampled = await resampleOffthread(bars, props.period)
  const out: CandlestickData<Time>[] = []
  for (const bar of resampled) {
    const o = Number(bar.open)
    const h = Number(bar.high)
    const l = Number(bar.low)
    const c = Number(bar.close)
    if (![o, h, l, c].every((n) => Number.isFinite(n))) continue
    out.push({
      time: bar.trade_date as Time,
      open: o,
      high: h,
      low: l,
      close: c,
    })
  }
  return out
}

function applyTheme(): void {
  if (!chart) return
  const styles = getComputedStyle(document.documentElement)
  const bg = styles.getPropertyValue('--panel').trim() || '#0f1419'
  const text = styles.getPropertyValue('--ink').trim() || '#e7ecf3'
  const grid = styles.getPropertyValue('--line').trim() || '#2a3340'
  chart.applyOptions({
    layout: {
      background: { type: ColorType.Solid, color: bg },
      textColor: text,
    },
    grid: {
      vertLines: { color: grid },
      horzLines: { color: grid },
    },
  })
}

async function render(): Promise<void> {
  if (!series) return
  const my = ++renderSeq
  const data = await toCandleData(props.bars)
  if (my !== renderSeq) return
  series.setData(data)
  chart?.timeScale().fitContent()
}

function dispose(): void {
  renderSeq += 1
  resizeObs?.disconnect()
  resizeObs = null
  chart?.remove()
  chart = null
  series = null
}

function mountChart(): void {
  if (!chartEl.value) return
  dispose()
  chart = createChart(chartEl.value, {
    autoSize: true,
    rightPriceScale: { borderVisible: false },
    timeScale: { borderVisible: false, timeVisible: false },
  })
  applyTheme()
  series = chart.addSeries(CandlestickSeries, {
    upColor: '#c41e3a',
    downColor: '#16a34a',
    borderUpColor: '#c41e3a',
    borderDownColor: '#16a34a',
    wickUpColor: '#c41e3a',
    wickDownColor: '#16a34a',
  })
  void render()
  resizeObs = new ResizeObserver(() => chart?.applyOptions({}))
  if (rootEl.value) resizeObs.observe(rootEl.value)
}

onMounted(() => mountChart())
onBeforeUnmount(() => dispose())

watch(
  () => [props.bars, props.period] as const,
  () => {
    void render()
  },
  { deep: true },
)
</script>

<template>
  <div ref="rootEl" class="lw-kline" role="img" :aria-label="ariaLabel">
    <div ref="chartEl" class="lw-kline__canvas" />
  </div>
</template>

<style scoped>
.lw-kline {
  width: 100%;
  height: 100%;
  min-height: 22rem;
}
.lw-kline__canvas {
  width: 100%;
  height: 100%;
  min-height: 22rem;
}
</style>
