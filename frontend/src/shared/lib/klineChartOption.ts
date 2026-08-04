/** ECharts option for KlineChart (split for file size). */
import type { ChartPrepResult } from '@/shared/lib/chartPrep'
import { buildLimitMarks } from '@/shared/lib/klineLimitMarks'
import type { IndicatorKind } from '@/shared/lib/klineConfig'

const MA_COLORS = [
  '#c41e3a', '#2563eb', '#d97706', '#7c3aed', '#0f6b5c', '#0891b2', '#be185d', '#ca8a04',
]
const VOL_MA_COLORS: Record<number, string> = { 5: '#d97706', 60: '#2563eb' }
const CANDLE_UP = '#c41e3a'
const CANDLE_DOWN = '#0f6b5c'

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

export function buildKlineOption(opts: {
  prep: ChartPrepResult
  indicator: IndicatorKind
  maPeriods: number[]
  showBarLabels: boolean
  zoomStart: number
  zoomEnd: number
  stockCode: string
  stockName: string
}): Record<string, unknown> {
  const {
    prep,
    indicator,
    maPeriods,
    showBarLabels,
    zoomStart,
    zoomEnd,
    stockCode,
    stockName,
  } = opts
  const { dates, candle, volumes: volRaw, volumeMas, maLines } = prep
  const bars = prep.seriesBars
  // K 线阴阳 strictly 跟开收（ECharts color/color0）；触板只打「涨停/跌停」钉，
  // 不再把冲高回落阴线整根染红。
  const volumes = volRaw.map((v) => ({
    value: v.value,
    itemStyle: { color: v.up ? 'rgba(196,30,58,0.55)' : 'rgba(15,107,92,0.55)' },
  }))
  const n = dates.length

  // 副图常驻：主图 / 量能 / 指标 三窗
  const grids = [
    { left: 52, right: 12, top: 22, height: '46%' },
    { left: 52, right: 12, top: '52%', height: '14%' },
    { left: 52, right: 12, top: '70%', height: '18%' },
  ]

  const xAxes = grids.map((_, idx) => ({
    type: 'category' as const,
    data: dates,
    gridIndex: idx,
    boundaryGap: true,
    axisLine: { lineStyle: { color: '#c5ced9' } },
    axisLabel: {
      show: idx === grids.length - 1,
      color: '#5b6b7c',
      fontSize: 10,
      hideOverlap: true,
    },
    axisTick: { show: false },
    splitLine: { show: false },
  }))

  const yAxes: Record<string, unknown>[] = [
    {
      scale: true,
      gridIndex: 0,
      axisLabel: {
        color: '#5b6b7c',
        fontSize: 10,
        formatter: (v: number) => fmtPx(v),
      },
      splitLine: { lineStyle: { color: 'rgba(213,220,230,0.55)', type: 'dashed' } },
    },
    {
      scale: true,
      gridIndex: 1,
      axisLabel: { show: false },
      splitLine: { show: false },
      axisLine: { show: false },
      axisTick: { show: false },
    },
    {
      scale: true,
      gridIndex: 2,
      axisLabel: { color: '#5b6b7c', fontSize: 9 },
      splitLine: { lineStyle: { color: 'rgba(213,220,230,0.45)', type: 'dashed' } },
      axisLine: { show: false },
      axisTick: { show: false },
    },
  ]

  const limitMarks = buildLimitMarks(
    prep.seriesBars,
    dates,
    stockCode,
    stockName,
  )

  const series: Record<string, unknown>[] = [
    {
      name: 'K线',
      type: 'candlestick',
      data: candle,
      xAxisIndex: 0,
      yAxisIndex: 0,
      barMaxWidth: 18,
      itemStyle: {
        color: CANDLE_UP,
        color0: CANDLE_DOWN,
        borderColor: CANDLE_UP,
        borderColor0: CANDLE_DOWN,
        borderWidth: 1,
      },
      label: {
        show: showBarLabels,
        position: 'top',
        distance: 1,
        fontSize: 9,
        fontFamily: 'IBM Plex Mono, Cascadia Code, ui-monospace, monospace',
        color: '#3d4d5f',
        formatter: (p: { data?: number[] | { value?: number[] } }) => {
          const raw = p.data
          const arr = Array.isArray(raw) ? raw : raw?.value
          return fmtPx(arr?.[1])
        },
      },
      markPoint: {
        symbol: 'rect',
        symbolSize: [44, 16],
        data: [...limitMarks],
      },
    },
    {
      name: '成交量',
      type: 'bar',
      data: volumes,
      xAxisIndex: 1,
      yAxisIndex: 1,
      barMaxWidth: 14,
      tooltip: { valueFormatter: (v: number) => fmtVol(v) },
    },
  ]

  for (const vm of volumeMas) {
    series.push({
      name: `量MA${vm.period}`,
      type: 'line',
      data: vm.data,
      xAxisIndex: 1,
      yAxisIndex: 1,
      showSymbol: false,
      lineStyle: { width: 1.1, color: VOL_MA_COLORS[vm.period] ?? '#5b6b7c' },
      emphasis: { disabled: true },
      tooltip: { valueFormatter: (v: number) => fmtVol(v) },
    })
  }

  maPeriods.forEach((period, idx) => {
    const line = maLines.find((m) => m.period === period)
    series.push({
      name: `MA${period}`,
      type: 'line',
      data: line?.data ?? [],
      xAxisIndex: 0,
      yAxisIndex: 0,
      showSymbol: false,
      lineStyle: { width: 1, color: MA_COLORS[idx % MA_COLORS.length] },
      emphasis: { disabled: true },
      tooltip: { valueFormatter: (v: number) => fmtPx(v) },
    })
  })

  if (indicator === 'macd' && prep.macd) {
    const m = prep.macd
    series.push(
      {
        name: 'DIF',
        type: 'line',
        data: m.dif,
        xAxisIndex: 2,
        yAxisIndex: 2,
        showSymbol: false,
        lineStyle: { width: 1, color: '#2563eb' },
        tooltip: { valueFormatter: (v: number) => fmtInd(v) },
      },
      {
        name: 'DEA',
        type: 'line',
        data: m.dea,
        xAxisIndex: 2,
        yAxisIndex: 2,
        showSymbol: false,
        lineStyle: { width: 1, color: '#d97706' },
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
        barMaxWidth: 8,
        tooltip: { valueFormatter: (v: number) => fmtInd(v) },
      },
    )
  } else if (indicator === 'kdj' && prep.kdj) {
    const k = prep.kdj
    series.push(
      {
        name: 'K',
        type: 'line',
        data: k.k,
        xAxisIndex: 2,
        yAxisIndex: 2,
        showSymbol: false,
        lineStyle: { width: 1, color: '#2563eb' },
        tooltip: { valueFormatter: (v: number) => fmtInd(v) },
      },
      {
        name: 'D',
        type: 'line',
        data: k.d,
        xAxisIndex: 2,
        yAxisIndex: 2,
        showSymbol: false,
        lineStyle: { width: 1, color: '#d97706' },
        tooltip: { valueFormatter: (v: number) => fmtInd(v) },
      },
      {
        name: 'J',
        type: 'line',
        data: k.j,
        xAxisIndex: 2,
        yAxisIndex: 2,
        showSymbol: false,
        lineStyle: { width: 1, color: '#c41e3a' },
        tooltip: { valueFormatter: (v: number) => fmtInd(v) },
      },
    )
  }

  const legendData = [
    ...maPeriods.map((p) => `MA${p}`),
    '量MA5',
    '量MA60',
    ...(indicator === 'macd' ? ['DIF', 'DEA', 'MACD'] : ['K', 'D', 'J']),
  ]

  return {
    animation: false,
    backgroundColor: 'transparent',
    legend: {
      show: false,
      data: legendData,
    },
    tooltip: {
      trigger: 'axis',
      axisPointer: { type: 'cross', snap: true, label: { show: true } },
      formatter: () => '',
      backgroundColor: 'transparent',
      borderWidth: 0,
      padding: 0,
      extraCssText: 'display:none;pointer-events:none;',
    },
    axisPointer: {
      link: [{ xAxisIndex: 'all' }],
      snap: true,
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
        xAxisIndex: [0, 1, 2],
        // 禁止 filter：默认 filter 会裁掉窗口外点，使 dataIndex 变成相对下标，
        // 双击分时会错指到更早的 K 线（如点 2026 却打开 2025）。
        filterMode: 'none',
        start: zoomStart,
        end: zoomEnd,
        zoomOnMouseWheel: true,
        moveOnMouseMove: true,
        preventDefaultMouseMove: true,
      },
      {
        type: 'slider',
        xAxisIndex: [0, 1, 2],
        filterMode: 'none',
        height: 14,
        bottom: 2,
        borderColor: '#d5dce6',
        fillerColor: 'rgba(196,30,58,0.1)',
        handleStyle: { color: '#c41e3a' },
        textStyle: { color: '#5b6b7c', fontSize: 9 },
        start: zoomStart,
        end: zoomEnd,
      },
    ],
    series,
  }
}

