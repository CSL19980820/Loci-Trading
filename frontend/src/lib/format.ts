export function money(value: number | null | undefined, digits = 2): string {
  if (value === null || value === undefined) return '—'
  return new Intl.NumberFormat('zh-CN', {
    style: 'currency',
    currency: 'CNY',
    maximumFractionDigits: digits,
  }).format(value)
}

export function signedMoney(value: number | null | undefined): string {
  if (value === null || value === undefined) return '—'
  const prefix = value > 0 ? '+' : ''
  return `${prefix}${money(value)}`
}

export function pct(value: number | null | undefined, digits = 2): string {
  if (value === null || value === undefined) return '—'
  const prefix = value > 0 ? '+' : ''
  return `${prefix}${value.toFixed(digits)}%`
}

export function shares(value: number): string {
  return `${value.toLocaleString('zh-CN')} 股`
}

export function shortTime(value: string): string {
  return value.replace('T', ' ').slice(0, 16)
}

export function actionLabel(action: string): string {
  return (
    {
      BUY: '买入',
      SELL: '卖出',
      OPENING: '开仓快照',
    }[action] ?? action
  )
}

export function entityLabel(type: string): string {
  return (
    {
      plan: '预案',
      candidate: '候选',
      trade: '成交',
    }[type] ?? type
  )
}

export function toneClass(value: number | null | undefined): string {
  if (value === null || value === undefined) return 'tone-neutral'
  if (value > 0) return 'tone-up'
  if (value < 0) return 'tone-down'
  return 'tone-neutral'
}