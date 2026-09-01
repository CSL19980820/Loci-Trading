import type { QuoteRow } from '@/shared/api/marketStream'

export type TapeItem = {
  key: string
  code: string
  name: string
  price: number
  change: number
  pct: number
  volume: number
  amount: number
}

/**
 * 将 QuoteRow 映射到稳定的跑马灯条目。
 * key 必须保持为 `${row.code}`，即使数据刷新也绝不改变 key，避免重触发 CSS 动画或 DOM 重构。
 */
export function formatTapeItem(row: QuoteRow): TapeItem {
  return {
    key: `tape-${row.code}`,
    code: row.code,
    name: row.name || row.code,
    price: row.price,
    change: row.change,
    pct: row.pct,
    volume: row.volume,
    amount: row.amount,
  }
}

/**
 * 分桶统计涨跌分布（用于 HeatStrip）
 * 跌停 / -7% / -5% / -3% / -1% / 平 / +1% / +3% / +5% / +7% / 涨停
 */
export type HeatBucket = {
  key: string
  label: string
  count: number
  tone: 'down' | 'flat' | 'up'
}

export function computeHeatBuckets(rows: QuoteRow[]): HeatBucket[] {
  const counts = {
    limitDown: 0,
    down7: 0,
    down5: 0,
    down3: 0,
    down1: 0,
    flat: 0,
    up1: 0,
    up3: 0,
    up5: 0,
    up7: 0,
    limitUp: 0,
  }

  for (const row of rows) {
    const p = row.pct
    if (p <= -9.8) counts.limitDown++
    else if (p <= -7) counts.down7++
    else if (p <= -5) counts.down5++
    else if (p <= -3) counts.down3++
    else if (p < 0) counts.down1++
    else if (p === 0) counts.flat++
    else if (p < 3) counts.up1++
    else if (p < 5) counts.up3++
    else if (p < 7) counts.up5++
    else if (p < 9.8) counts.up7++
    else counts.limitUp++
  }

  return [
    { key: 'limitDown', label: '跌停', count: counts.limitDown, tone: 'down' },
    { key: 'down7', label: '-7%', count: counts.down7, tone: 'down' },
    { key: 'down5', label: '-5%', count: counts.down5, tone: 'down' },
    { key: 'down3', label: '-3%', count: counts.down3, tone: 'down' },
    { key: 'down1', label: '-1%', count: counts.down1, tone: 'down' },
    { key: 'flat', label: '平', count: counts.flat, tone: 'flat' },
    { key: 'up1', label: '+1%', count: counts.up1, tone: 'up' },
    { key: 'up3', label: '+3%', count: counts.up3, tone: 'up' },
    { key: 'up5', label: '+5%', count: counts.up5, tone: 'up' },
    { key: 'up7', label: '+7%', count: counts.up7, tone: 'up' },
    { key: 'limitUp', label: '涨停', count: counts.limitUp, tone: 'up' },
  ]
}
