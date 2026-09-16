/** ECharts option for intraday (分时) + VOL.
 *
 * 视觉对齐主流 A 股分时：价格线固定蓝、均价琥珀；
 * 红/绿只用于涨跌标点与成交量柱，不整条线染涨跌色。
 */
import type { MinuteBar } from '@/shared/api/quant_market'
import { readChartTokens, withAlpha, type ChartTokens } from '@/shared/lib/chartTokens'
import { compactNumber } from '@/shared/lib/format'

function fmtPx(v: unknown): string {
  const n = Number(v)
  if (!Number.isFinite(n)) return '—'
  return n.toFixed(2)
}

/** 相对昨收涨跌幅；无昨收时返回空串。 */
export function formatMinutePct(price: number, prevClose: number | null): string {
  if (!Number.isFinite(price) || prevClose == null || !Number.isFinite(prevClose) || prevClose === 0) {
    return ''
  }
  const pct = ((price - prevClose) / prevClose) * 100
  const sign = pct > 0 ? '+' : ''
  return `${sign}${pct.toFixed(2)}%`
}

/** 「63.60 +4.95%」；无比例时仅价格。 */
export function formatMinutePxPct(price: number, prevClose: number | null): string {
  const pct = formatMinutePct(price, prevClose)
  return pct ? `${fmtPx(price)} ${pct}` : fmtPx(price)
}

function fmtVol(v: unknown): string {
  return compactNumber(v)
}

function timeLabel(dt: string): string {
  const m = String(dt).match(/(\d{2}:\d{2})/)
  return m?.[1] ?? String(dt).slice(11, 16)
}

export type MinuteDayStats = {
  high: number
  low: number
  avg: number | null
  highIndex: number
  lowIndex: number
}

/** 均价相对现价偏离过大时视为脏数据（如未按「手」换算的约 100×）。 */
export function saneMinuteAvg(avg: number, refPrice: number): number | null {
  if (!Number.isFinite(avg) || !Number.isFinite(refPrice) || refPrice <= 0) return null
  let value = avg
  const ratio = value / refPrice
  if (ratio > 20) value = value / 100
  const ratio2 = value / refPrice
  if (ratio2 <= 0.2 || ratio2 >= 5) return null
  return value
}

/** 分时最高/最低（优先用 bar high/low）与末日均价。 */
export function computeMinuteDayStats(bars: MinuteBar[]): MinuteDayStats | null {
  if (!bars.length) return null
  let high = -Infinity
  let low = Infinity
  let highIndex = 0
  let lowIndex = 0
  let lastAvg: number | null = null
  for (let i = 0; i < bars.length; i++) {
    const bar = bars[i]
    const h = Number(bar.high ?? bar.close)
    const l = Number(bar.low ?? bar.close)
    if (Number.isFinite(h) && h >= high) {
      high = h
      highIndex = i
    }
    if (Number.isFinite(l) && l <= low) {
      low = l
      lowIndex = i
    }
    const close = Number(bar.close)
    const a = saneMinuteAvg(Number(bar.avg_price), close)
    if (a != null) lastAvg = a
  }
  if (!Number.isFinite(high) || !Number.isFinite(low)) return null
  return { high, low, avg: lastAvg, highIndex, lowIndex }
}

/**
 * A 股分时 Y 轴：以昨收为中轴对称扩展。
 * 一字板/极窄振幅时若交给 ECharts scale:true，会把浮点噪声放成满屏锯齿。
 */
export function computeMinutePriceAxis(
  bars: MinuteBar[],
  prevClose: number | null,
): { min: number; max: number } | null {
  const prices: number[] = []
  for (const bar of bars) {
    for (const raw of [bar.close, bar.high, bar.low]) {
      const n = Number(raw ?? bar.close)
      if (Number.isFinite(n)) prices.push(n)
    }
    const avg = saneMinuteAvg(Number(bar.avg_price), Number(bar.close))
    if (avg != null) prices.push(avg)
  }
  if (!prices.length) return null

  const dataMin = Math.min(...prices)
  const dataMax = Math.max(...prices)
  if (prevClose != null && Number.isFinite(prevClose) && prevClose > 0) {
    const pad = Math.max(
      Math.abs(dataMax - prevClose),
      Math.abs(dataMin - prevClose),
      prevClose * 0.01,
      0.01,
    )
    return { min: prevClose - pad, max: prevClose + pad }
  }
  const mid = (dataMin + dataMax) / 2 || 1
  const half = Math.max((dataMax - dataMin) / 2, Math.abs(mid) * 0.01, 0.01)
  return { min: mid - half, max: mid + half }
}

function markLabel(text: string, bg: string): Record<string, unknown> {
  return {
    show: true,
    formatter: () => text,
    color: '#fff',
    backgroundColor: bg,
    padding: [3, 6],
    borderRadius: 2,
    fontSize: 10,
    fontWeight: 600,
  }
}

export function buildMinuteOption(opts: {
  bars: MinuteBar[]
  prevClose: number | null
  /** 主题 token 快照；不传则即时读取 */
  tokens?: ChartTokens
}): Record<string, unknown> {
  const { bars, prevClose } = opts
  const t = opts.tokens ?? readChartTokens()
  const UP = t.up
  const DOWN = t.down
  const LINE = t.info
  const AVG = t.warn
  const times = bars.map((b) => timeLabel(String(b.datetime || '')))
  const closes = bars.map((b) => Number(b.close))
  const avgs = bars.map((b) => saneMinuteAvg(Number(b.avg_price), Number(b.close)))
  const volumes = bars.map((b, i) => {
    const v = Number(b.volume)
    const c = Number(b.close)
    const prev = i > 0 ? Number(bars[i - 1]?.close) : prevClose
    const up = prev != null && Number.isFinite(prev) ? c >= prev : true
    return {
      value: Number.isFinite(v) ? v : 0,
      itemStyle: { color: up ? 'rgba(196,30,58,0.55)' : 'rgba(18,138,110,0.55)' },
    }
  })
  const last = closes.length ? closes[closes.length - 1] : null
  const lastTone =
    last != null && prevClose != null && Number.isFinite(prevClose)
      ? last >= prevClose
        ? UP
        : DOWN
      : LINE
  const stats = computeMinuteDayStats(bars)
  const priceAxis = computeMinutePriceAxis(bars, prevClose)
  const lastAvg = stats?.avg ?? null
  const lastTime = times.length ? times[times.length - 1] : ''
  // 一字板高低重合时只保留「现」，避免高低标点叠成一团
  const flatSession =
    stats != null && Math.abs(stats.high - stats.low) < 1e-6

  const priceMarks: Array<Record<string, unknown>> = []
  if (stats && !flatSession) {
    priceMarks.push({
      name: '高',
      coord: [times[stats.highIndex], stats.high],
      symbol: 'triangle',
      symbolSize: 10,
      symbolRotate: 180,
      itemStyle: { color: UP },
      label: {
        ...markLabel(`高 ${formatMinutePxPct(stats.high, prevClose)}`, UP),
        position: 'top',
        distance: 6,
      },
    })
    priceMarks.push({
      name: '低',
      coord: [times[stats.lowIndex], stats.low],
      symbol: 'triangle',
      symbolSize: 10,
      itemStyle: { color: DOWN },
      label: {
        ...markLabel(`低 ${formatMinutePxPct(stats.low, prevClose)}`, DOWN),
        position: 'bottom',
        distance: 6,
      },
    })
  }
  if (last != null && lastTime) {
    priceMarks.push({
      name: '现',
      coord: [lastTime, last],
      symbol: 'circle',
      symbolSize: 6,
      itemStyle: { color: lastTone },
      label: {
        ...markLabel(formatMinutePxPct(last, prevClose), lastTone),
        position: 'right',
        distance: 8,
      },
    })
  }

  return {
    animation: false,
    axisPointer: { link: [{ xAxisIndex: 'all' }] },
    tooltip: {
      trigger: 'axis',
      axisPointer: { type: 'cross' },
      formatter: (params: unknown) => {
        const list = Array.isArray(params) ? params : []
        const idx = Number((list[0] as { dataIndex?: number })?.dataIndex ?? -1)
        const bar = idx >= 0 ? bars[idx] : null
        if (!bar) return ''
        const c = Number(bar.close)
        const avg = saneMinuteAvg(Number(bar.avg_price), c)
        const avgLine =
          avg != null
            ? `均 ${formatMinutePxPct(avg, prevClose)}`
            : '均 —'
        return [
          timeLabel(String(bar.datetime)),
          `价 ${formatMinutePxPct(c, prevClose)}`,
          avgLine,
          `量 ${fmtVol(bar.volume)}`,
        ].join('<br/>')
      },
    },
    grid: [
      { left: 52, right: 72, top: 28, height: '58%' },
      { left: 52, right: 72, top: '74%', height: '16%' },
    ],
    xAxis: [
      {
        type: 'category',
        data: times,
        gridIndex: 0,
        boundaryGap: false,
        axisLabel: { show: false },
        axisTick: { show: false },
        axisLine: { lineStyle: { color: t.rule } },
        splitLine: { show: false },
      },
      {
        type: 'category',
        data: times,
        gridIndex: 1,
        boundaryGap: false,
        axisLabel: {
          color: t.mist,
          fontSize: 10,
          interval: (_: number, value: string) =>
            value === '09:30' || value === '11:30' || value === '13:00' || value === '15:00',
        },
        axisTick: { show: false },
        axisLine: { lineStyle: { color: t.rule } },
      },
    ],
    yAxis: [
      {
        scale: true,
        gridIndex: 0,
        min: priceAxis?.min,
        max: priceAxis?.max,
        axisLabel: { color: t.mist, fontSize: 10, fontFamily: t.mono, formatter: (v: number) => fmtPx(v) },
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
    ],
    series: [
      {
        name: '分时',
        type: 'line',
        data: closes,
        xAxisIndex: 0,
        yAxisIndex: 0,
        showSymbol: false,
        lineStyle: { width: 1.5, color: LINE },
        areaStyle: {
          color: {
            type: 'linear',
            x: 0,
            y: 0,
            x2: 0,
            y2: 1,
            colorStops: [
              { offset: 0, color: withAlpha(LINE, 0.16) },
              { offset: 1, color: withAlpha(LINE, 0) },
            ],
          },
        },
        markLine:
          prevClose != null && Number.isFinite(prevClose)
            ? {
                silent: true,
                symbol: 'none',
                lineStyle: { type: 'dashed', width: 1, color: t.mist },
                label: {
                  position: 'end',
                  formatter: () => fmtPx(prevClose),
                  color: t.mist,
                  fontSize: 10,
                },
                data: [{ yAxis: prevClose }],
              }
            : undefined,
        markPoint: priceMarks.length
          ? {
              silent: true,
              data: priceMarks,
            }
          : undefined,
      },
      {
        name: '均价',
        type: 'line',
        data: avgs,
        xAxisIndex: 0,
        yAxisIndex: 0,
        showSymbol: false,
        lineStyle: { width: 1.15, color: AVG },
        markPoint:
          lastAvg != null && lastTime
            ? {
                silent: true,
                data: [
                  {
                    name: '均',
                    coord: [lastTime, lastAvg],
                    symbol: 'circle',
                    symbolSize: 5,
                    itemStyle: { color: AVG },
                    label: {
                      ...markLabel(`均 ${formatMinutePxPct(lastAvg, prevClose)}`, AVG),
                      position: 'left',
                      distance: 8,
                    },
                  },
                ],
              }
            : undefined,
      },
      {
        name: '成交量（股）',
        type: 'bar',
        data: volumes,
        xAxisIndex: 1,
        yAxisIndex: 1,
        barMaxWidth: 4,
        tooltip: { valueFormatter: (v: number) => fmtVol(v) },
      },
    ],
  }
}
