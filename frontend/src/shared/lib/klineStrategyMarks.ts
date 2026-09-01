/**
 * K 线策略选股信号 markPoint 数据构建。
 */
import type { OhlcBar } from '@/shared/lib/indicators'
import type { ChartTokens } from '@/shared/lib/chartTokens'
import { readChartTokens } from '@/shared/lib/chartTokens'
import { strategyLabel } from '@/shared/lib/format'

export type StrategySignalMark = {
  date: string
  strategyName: string
  strategySlug?: string
  decision?: string
  reason?: string
  score?: number | null
}

export function buildStrategySignalMarks(
  bars: OhlcBar[],
  dates: string[],
  signals: StrategySignalMark[],
  tokens?: ChartTokens,
): Array<Record<string, unknown>> {
  const t = tokens ?? readChartTokens()
  if (!signals.length || !bars.length || !dates.length) return []

  const dateToBarIndex = new Map<string, number>()
  for (let i = 0; i < dates.length; i++) {
    dateToBarIndex.set(dates[i], i)
  }

  // 同一日可能触发多个策略，将同日的策略汇总，避免箭头图标完全重叠
  const signalsByDate = new Map<string, StrategySignalMark[]>()
  for (const s of signals) {
    const rawDate = String(s.date || '').slice(0, 10)
    if (!dateToBarIndex.has(rawDate)) continue
    const list = signalsByDate.get(rawDate) ?? []
    list.push(s)
    signalsByDate.set(rawDate, list)
  }

  const marks: Array<Record<string, unknown>> = []

  for (const [date, sigList] of signalsByDate.entries()) {
    const barIdx = dateToBarIndex.get(date)
    if (barIdx === undefined) continue
    const bar = bars[barIdx]
    if (!bar) continue

    // 箭头基准锚定在当根 K 线的 low 最低价下方
    const lowPrice = Number(bar.low ?? bar.close ?? bar.open)
    if (!Number.isFinite(lowPrice)) continue

    // 去重策略名拼接展示，保证全部显示为中文名
    const distinctNames = Array.from(
      new Set(
        sigList.map((s) => {
          const raw = s.strategyName || s.strategySlug || '选股'
          return strategyLabel(raw)
        }),
      ),
    )
    const labelText = distinctNames.join(' + ')

    // 提示详情
    const fullReasons = sigList
      .map((s) => {
        const raw = s.strategyName || s.strategySlug || '战法'
        const name = strategyLabel(raw)
        return `${name}${s.reason ? `: ${s.reason}` : ''}`
      })
      .join('\n')

    // 箭头颜色：使用醒目的金黄色 / 琥珀重点强调色
    const markColor = t.warn || '#f59e0b'
    const markBorderColor = 'rgba(245, 158, 11, 0.3)'

    marks.push({
      name: `策略信号: ${labelText}`,
      coord: [date, lowPrice],
      value: labelText,
      symbol: 'path://M12 2L2 22h20L12 2z', // 向上粗箭头
      symbolSize: [14, 14],
      symbolOffset: [0, 22],
      itemStyle: {
        color: markColor,
        borderColor: markBorderColor,
        borderWidth: 1,
        shadowBlur: 4,
        shadowColor: markColor,
      },
      label: {
        show: true,
        position: 'bottom',
        distance: 4,
        formatter: (params: { value?: unknown }) => `▲ ${String(params.value ?? '')}`,
        color: markColor,
        fontSize: 10,
        fontWeight: 600,
        fontFamily: t.mono,
        backgroundColor: 'rgba(15, 23, 42, 0.85)',
        borderColor: markColor,
        borderWidth: 1,
        borderRadius: 3,
        padding: [2, 4],
      },
      tooltip: {
        formatter: () =>
          `<div style="font-size:12px;padding:2px 4px;"><strong>[${date}] 选入策略</strong><br/>${fullReasons.replace(/\n/g, '<br/>')}</div>`,
      },
    })
  }

  return marks
}
