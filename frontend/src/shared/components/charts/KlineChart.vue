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
import type { KPeriod, OhlcBar } from '@/shared/lib/indicators'
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

export type IndicatorKind = 'macd' | 'kdj' | 'none'

const props = withDefaults(
  defineProps<{
    bars: OhlcBar[]
    period?: KPeriod
    indicator?: IndicatorKind
    maPeriods?: number[]
    title?: string
  }>(),
  {
    period: 'day',
    indicator: 'macd',
    maPeriods: () => [5, 10, 20],
    title: '',
  },
)

const rootEl = ref<HTMLElement | null>(null)
const chartEl = ref<HTMLElement | null>(null)
const hoverLine = ref('')
let chart: echarts.ECharts | null = null
let resizeObs: ResizeObserver | null = null
/** dataZoom 可见区间，用于决定是否在 K 线上标收盘价 */
let zoomStart = 0
let zoomEnd = 100
let latestPrep: ChartPrepResult | null = null
let renderSeq = 0

const ariaLabel = computed(() => {
  const p = { day: '日K', week: '周K', month: '月K' }[props.period]
  const ind = { macd: 'MACD', kdj: 'KDJ', none: '无副图' }[props.indicator]
  return `${p} · ${ind}`
})

const MA_COLORS = ['#c41e3a', '#2563eb', '#d97706', '#7c3aed']

function fmtPx(v: unknown): string {
  const n = Number(v)
  if (!Number.isFinite(n)) return '—'
  return n.toFixed(2)
}

function fmtVol(v: unknown): string {
  const n = Number(v)
  if (!Number.isFinite(n)) return '—'
  if (Math.abs(n) >= 1e8) return `${(n / 1e8).toFixed(2)}亿`
  if (Math.abs(n) >= 1e4) return `${(n / 1e4).toFixed(1)}万`
  return n.toFixed(0)
}

function fmtInd(v: unknown): string {
  const n = Number(v)
  if (!Number.isFinite(n)) return '—'
  return n.toFixed(3)
}

function buildOption(prep: ChartPrepResult) {
  const { dates, candle, volumes: volRaw, maLines, seriesBars } = prep
  const volumes = volRaw.map((v) => ({
    value: v.value,
    itemStyle: { color: v.up ? 'rgba(196,30,58,0.55)' : 'rgba(15,107,92,0.55)' },
  }))
  const n = dates.length
  const visibleCount = Math.max(1, Math.round((n * (zoomEnd - zoomStart)) / 100))
  const showBarLabels = visibleCount <= 48 && n > 0

  const showInd = props.indicator !== 'none'
  const grids = showInd
    ? [
        { left: 56, right: 16, top: 28, height: '46%' },
        { left: 56, right: 16, top: '56%', height: '12%' },
        { left: 56, right: 16, top: '72%', height: '16%' },
      ]
    : [
        { left: 56, right: 16, top: 28, height: '62%' },
        { left: 56, right: 16, top: '74%', height: '16%' },
      ]

  const xAxes = grids.map((_, idx) => ({
    type: 'category' as const,
    data: dates,
    gridIndex: idx,
    boundaryGap: true,
    axisLine: { lineStyle: { color: '#c5ced9' } },
    axisLabel: { show: idx === grids.length - 1, color: '#5b6b7c', fontSize: 11 },
    axisTick: { show: false },
    splitLine: { show: false },
  }))

  const yAxes: Record<string, unknown>[] = [
    {
      scale: true,
      gridIndex: 0,
      axisLabel: {
        color: '#5b6b7c',
        fontSize: 11,
        formatter: (v: number) => fmtPx(v),
      },
      splitLine: { lineStyle: { color: '#e8edf3' } },
    },
    {
      scale: true,
      gridIndex: 1,
      axisLabel: { show: false },
      splitLine: { show: false },
      axisLine: { show: false },
      axisTick: { show: false },
    },
  ]
  if (showInd) {
    yAxes.push({
      scale: true,
      gridIndex: 2,
      axisLabel: { color: '#5b6b7c', fontSize: 10 },
      splitLine: { lineStyle: { color: '#e8edf3' } },
      axisLine: { show: false },
      axisTick: { show: false },
    })
  }

  const lastIdx = n - 1
  const lastClose = lastIdx >= 0 ? candle[lastIdx]?.[1] : null

  const series: Record<string, unknown>[] = [
    {
      name: 'K线',
      type: 'candlestick',
      data: candle,
      xAxisIndex: 0,
      yAxisIndex: 0,
      itemStyle: {
        color: '#c41e3a',
        color0: '#0f6b5c',
        borderColor: '#c41e3a',
        borderColor0: '#0f6b5c',
      },
      label: {
        show: showBarLabels,
        position: 'top',
        distance: 2,
        fontSize: 10,
        color: '#5b6b7c',
        formatter: (p: { data?: number[] }) => fmtPx(p.data?.[1]),
      },
      markPoint:
        lastClose != null
          ? {
              symbol: 'pin',
              symbolSize: 42,
              data: [
                {
                  name: '收',
                  coord: [dates[lastIdx], lastClose],
                  value: lastClose,
                  itemStyle: { color: '#c41e3a' },
                  label: {
                    formatter: () => fmtPx(lastClose),
                    color: '#fff',
                    fontSize: 10,
                  },
                },
              ],
            }
          : undefined,
    },
    {
      name: '成交量',
      type: 'bar',
      data: volumes,
      xAxisIndex: 1,
      yAxisIndex: 1,
      barMaxWidth: 8,
      tooltip: { valueFormatter: (v: number) => fmtVol(v) },
    },
  ]

  props.maPeriods.forEach((period, idx) => {
    const line = maLines.find((m) => m.period === period)
    series.push({
      name: `MA${period}`,
      type: 'line',
      data: line?.data ?? [],
      xAxisIndex: 0,
      yAxisIndex: 0,
      showSymbol: false,
      lineStyle: { width: 1.2, color: MA_COLORS[idx % MA_COLORS.length] },
      emphasis: { disabled: true },
      tooltip: { valueFormatter: (v: number) => fmtPx(v) },
    })
  })

  if (props.indicator === 'macd' && prep.macd) {
    const m = prep.macd
    series.push(
      {
        name: 'DIF',
        type: 'line',
        data: m.dif,
        xAxisIndex: 2,
        yAxisIndex: 2,
        showSymbol: false,
        lineStyle: { width: 1.2, color: '#2563eb' },
        tooltip: { valueFormatter: (v: number) => fmtInd(v) },
      },
      {
        name: 'DEA',
        type: 'line',
        data: m.dea,
        xAxisIndex: 2,
        yAxisIndex: 2,
        showSymbol: false,
        lineStyle: { width: 1.2, color: '#d97706' },
        tooltip: { valueFormatter: (v: number) => fmtInd(v) },
      },
      {
        name: 'MACD',
        type: 'bar',
        data: m.hist.map((v) => ({
          value: v,
          itemStyle: {
            color: v !== null && v >= 0 ? 'rgba(196,30,58,0.7)' : 'rgba(15,107,92,0.7)',
          },
        })),
        xAxisIndex: 2,
        yAxisIndex: 2,
        barMaxWidth: 6,
        tooltip: { valueFormatter: (v: number) => fmtInd(v) },
      },
    )
  } else if (props.indicator === 'kdj' && prep.kdj) {
    const k = prep.kdj
    series.push(
      {
        name: 'K',
        type: 'line',
        data: k.k,
        xAxisIndex: 2,
        yAxisIndex: 2,
        showSymbol: false,
        lineStyle: { width: 1.2, color: '#2563eb' },
        tooltip: { valueFormatter: (v: number) => fmtInd(v) },
      },
      {
        name: 'D',
        type: 'line',
        data: k.d,
        xAxisIndex: 2,
        yAxisIndex: 2,
        showSymbol: false,
        lineStyle: { width: 1.2, color: '#d97706' },
        tooltip: { valueFormatter: (v: number) => fmtInd(v) },
      },
      {
        name: 'J',
        type: 'line',
        data: k.j,
        xAxisIndex: 2,
        yAxisIndex: 2,
        showSymbol: false,
        lineStyle: { width: 1.2, color: '#c41e3a' },
        tooltip: { valueFormatter: (v: number) => fmtInd(v) },
      },
    )
  }

  const legendData = [
    ...props.maPeriods.map((p) => `MA${p}`),
    ...(props.indicator === 'macd' ? ['DIF', 'DEA', 'MACD'] : []),
    ...(props.indicator === 'kdj' ? ['K', 'D', 'J'] : []),
  ]

  return {
    animation: false,
    backgroundColor: 'transparent',
    legend: {
      top: 2,
      left: 56,
      itemWidth: 12,
      itemHeight: 8,
      textStyle: { color: '#5b6b7c', fontSize: 11 },
      data: legendData,
    },
    tooltip: {
      trigger: 'axis',
      axisPointer: { type: 'cross' },
      backgroundColor: 'rgba(247,249,252,0.97)',
      borderColor: '#d5dce6',
      borderWidth: 1,
      padding: [8, 10],
      textStyle: { color: '#142033', fontSize: 12 },
      extraCssText: 'box-shadow:0 4px 14px rgba(20,32,51,0.08);max-width:240px;',
      formatter: (params: unknown) => {
        const list = Array.isArray(params) ? params : [params]
        if (!list.length) return ''
        const idx = Number((list[0] as { dataIndex?: number }).dataIndex ?? -1)
        if (idx < 0 || idx >= seriesBars.length) return ''
        const bar = seriesBars[idx]
        const open = Number(bar.open ?? 0)
        const close = Number(bar.close ?? 0)
        const high = Number(bar.high ?? 0)
        const low = Number(bar.low ?? 0)
        const prev = idx > 0 ? Number(seriesBars[idx - 1].close ?? 0) : open
        const chg = prev ? ((close - prev) / prev) * 100 : 0
        const chgColor = chg > 0 ? '#c41e3a' : chg < 0 ? '#0f6b5c' : '#5b6b7c'

        const byName = new Map<string, number | null>()
        for (const raw of list) {
          const p = raw as { seriesName?: string; value?: unknown; data?: unknown }
          const name = p.seriesName || ''
          if (name === 'K线' || name === '成交量') continue
          let v: unknown = p.value
          if (v && typeof v === 'object' && 'value' in (v as object)) {
            v = (v as { value: unknown }).value
          }
          byName.set(name, v == null || v === '-' ? null : Number(v))
        }

        const rows: string[] = [
          `<div style="font-weight:600;margin-bottom:6px">${bar.trade_date}</div>`,
          `<div style="display:grid;grid-template-columns:3.2em 1fr;gap:2px 8px;font-variant-numeric:tabular-nums">`,
          `<span style="color:#5b6b7c">开</span><span>${fmtPx(open)}</span>`,
          `<span style="color:#5b6b7c">高</span><span>${fmtPx(high)}</span>`,
          `<span style="color:#5b6b7c">低</span><span>${fmtPx(low)}</span>`,
          `<span style="color:#5b6b7c">收</span><span style="color:${chgColor};font-weight:600">${fmtPx(close)}</span>`,
          `<span style="color:#5b6b7c">涨跌</span><span style="color:${chgColor}">${chg > 0 ? '+' : ''}${chg.toFixed(2)}%</span>`,
          `<span style="color:#5b6b7c">量</span><span>${fmtVol(bar.volume)}</span>`,
        ]

        for (const [name, val] of byName) {
          if (val == null || Number.isNaN(val)) continue
          const isMa = name.startsWith('MA')
          rows.push(
            `<span style="color:#5b6b7c">${name}</span><span>${isMa ? fmtPx(val) : fmtInd(val)}</span>`,
          )
        }
        rows.push('</div>')
        return rows.join('')
      },
    },
    axisPointer: {
      link: [{ xAxisIndex: 'all' }],
      label: {
        backgroundColor: '#5b6b7c',
        formatter: (params: { axisDimension?: string; value?: unknown }) => {
          if (params.axisDimension === 'y') return fmtPx(params.value)
          return String(params.value ?? '')
        },
      },
    },
    grid: grids,
    xAxis: xAxes,
    yAxis: yAxes,
    dataZoom: [
      {
        type: 'inside',
        xAxisIndex: grids.map((_, i) => i),
        start: zoomStart || (dates.length > 120 ? Math.max(0, 100 - (120 / dates.length) * 100) : 0),
        end: zoomEnd || 100,
      },
      {
        type: 'slider',
        xAxisIndex: grids.map((_, i) => i),
        height: 18,
        bottom: 4,
        borderColor: '#d5dce6',
        fillerColor: 'rgba(196,30,58,0.12)',
        handleStyle: { color: '#c41e3a' },
        textStyle: { color: '#5b6b7c', fontSize: 10 },
        start: zoomStart || (dates.length > 120 ? Math.max(0, 100 - (120 / dates.length) * 100) : 0),
        end: zoomEnd || 100,
      },
    ],
    series,
  }
}

function syncHoverStrip(dataIndex: number): void {
  const seriesBars = latestPrep?.seriesBars
  if (!seriesBars) {
    hoverLine.value = ''
    return
  }
  const bar = seriesBars[dataIndex]
  if (!bar) {
    hoverLine.value = ''
    return
  }
  const close = Number(bar.close ?? 0)
  const open = Number(bar.open ?? 0)
  const prev = dataIndex > 0 ? Number(seriesBars[dataIndex - 1].close ?? 0) : open
  const chg = prev ? ((close - prev) / prev) * 100 : 0
  hoverLine.value = [
    bar.trade_date,
    `开 ${fmtPx(bar.open)}`,
    `高 ${fmtPx(bar.high)}`,
    `低 ${fmtPx(bar.low)}`,
    `收 ${fmtPx(bar.close)}`,
    `量 ${fmtVol(bar.volume)}`,
    `${chg > 0 ? '+' : ''}${chg.toFixed(2)}%`,
  ].join('  ·  ')
}

function bindChartEvents(): void {
  if (!chart) return
  chart.off('datazoom')
  chart.off('updateAxisPointer')
  chart.on('datazoom', (raw: unknown) => {
    const ev = raw as { start?: number; end?: number; batch?: Array<{ start?: number; end?: number }> }
    const batch = ev.batch?.[0]
    const start = batch?.start ?? ev.start
    const end = batch?.end ?? ev.end
    if (typeof start === 'number') zoomStart = start
    if (typeof end === 'number') zoomEnd = end
    void render({ keepZoom: true })
  })
  chart.on('updateAxisPointer', (raw: unknown) => {
    const ev = raw as { axesInfo?: Array<{ value?: number }> }
    const idx = ev.axesInfo?.[0]?.value
    if (typeof idx === 'number') syncHoverStrip(idx)
  })
}

async function render(opts: { keepZoom?: boolean } = {}): Promise<void> {
  if (!chartEl.value) return
  if (!chart) {
    chart = echarts.init(chartEl.value, undefined, { renderer: 'canvas' })
    bindChartEvents()
  }
  if (!props.bars.length) {
    chart.clear()
    hoverLine.value = ''
    latestPrep = null
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
  if (!opts.keepZoom) {
    const n = prep.dates.length
    zoomStart = n > 120 ? Math.max(0, 100 - (120 / n) * 100) : 0
    zoomEnd = 100
  }
  chart.setOption(buildOption(prep) as echarts.EChartsCoreOption, { notMerge: true })
  if (prep.seriesBars.length) syncHoverStrip(prep.seriesBars.length - 1)
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

watch(
  () => [props.bars, props.period, props.indicator, props.maPeriods] as const,
  () => {
    void render()
  },
  { deep: true },
)
</script>

<template>
  <div class="kline-chart" ref="rootEl">
    <div v-if="hoverLine" class="kline-chart__strip mono" aria-live="polite">{{ hoverLine }}</div>
    <div ref="chartEl" class="kline-chart__canvas" role="img" :aria-label="ariaLabel" />
  </div>
</template>

<style scoped>
.kline-chart {
  width: 100%;
  min-height: 420px;
  height: min(62vh, 560px);
  display: flex;
  flex-direction: column;
  gap: 0.35rem;
}

.kline-chart__strip {
  flex-shrink: 0;
  font-size: 0.78rem;
  color: var(--ink);
  padding: 0.2rem 0.15rem;
  white-space: nowrap;
  overflow-x: auto;
  border-bottom: 1px solid var(--rule);
}

.kline-chart__canvas {
  flex: 1 1 auto;
  min-height: 0;
  width: 100%;
}

.mono {
  font-family: var(--mono);
  font-variant-numeric: tabular-nums;
}
</style>
