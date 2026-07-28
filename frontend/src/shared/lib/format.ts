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

/** 裁决口径统一成中文展示。 */
export function decisionLabel(decision: string | null | undefined): string {
  if (!decision) return '—'
  const key = decision.trim().toLowerCase()
  return (
    {
      select: '精选',
      selected: '精选',
      core: '精选',
      buy: '买入',
      reject: '落选',
      rejected: '落选',
      drop: '落选',
      剔除: '落选',
      watch: '观察',
      hold: '观察',
      hold_cash: '空仓观望',
      partial: '部分参与',
    }[key] ?? decision.trim()
  )
}

export function toneClass(value: number | null | undefined): string {
  if (value === null || value === undefined) return 'tone-neutral'
  if (value > 0) return 'tone-up'
  if (value < 0) return 'tone-down'
  return 'tone-neutral'
}

/** 本地日历日（避免 toISOString 的 UTC 错日）。 */
export function localToday(): string {
  const d = new Date()
  const y = d.getFullYear()
  const m = String(d.getMonth() + 1).padStart(2, '0')
  const day = String(d.getDate()).padStart(2, '0')
  return `${y}-${m}-${day}`
}

const FACTOR_LABELS: Record<string, string> = {
  vol_ratio_5d: '5日量比',
  vol_ratio: '量比',
  turnover: '换手率',
  ma20: 'MA20',
  ma5: 'MA5',
  ma10: 'MA10',
  score: '评分',
  hsl: '换手%',
  zt: '涨停',
  one_word: '一字板',
  auction_ratio: '竞价比',
  open_pct: '开盘涨幅%',
  close_pct: '收盘涨幅%',
}

export function factorLabel(key: string): string {
  return FACTOR_LABELS[key] ?? key
}

export function severityLabel(value: string): string {
  return (
    {
      block: '阻断',
      error: '阻断',
      warn: '警告',
      warning: '警告',
      info: '提示',
      ok: '正常',
    }[value.toLowerCase()] ?? value
  )
}

export function entryTimingLabel(value: string): string {
  return (
    {
      open: '当日开盘',
      close: '当日收盘',
      next_open: '次日开盘',
      next_op: '次日开盘',
      W: '尾盘',
      w: '尾盘',
      '禁W': '禁尾盘',
      'D-flat': '平开',
      'd-flat': '平开',
      flat: '平开',
      hold: '持有',
      '持有': '持有',
      watch: '观望',
      '观望': '观望',
    }[value] ?? value
  )
}

/** 候选/历史里出现的战法 slug → 中文名（含旧别名）。 */
const STRATEGY_LABELS: Record<string, string> = {
  qianlong: '潜龙出海',
  'qianlong-v1': '潜龙出海·原版',
  'qianlong-close': '潜龙出海·原版',
  'qianlong-auction': '潜龙出海·竞价版',
  'lugw-sanwai': '卢高文·三外有三',
  'lugw-tianyi': '卢高文·天衣无缝',
  'lugw-daoba': '卢高文·倒拔杨柳',
  'lugw-haidi': '卢高文·海底捞月',
  'lugw-fenshou': '卢高文·分手快乐',
  'lugw-chouma': '卢高文·筹码峰突破',
}

export function strategyLabel(slug: string | null | undefined, fallbackMap?: Map<string, string>): string {
  if (!slug) return '—'
  if (fallbackMap?.has(slug)) return fallbackMap.get(slug) || slug
  if (STRATEGY_LABELS[slug]) return STRATEGY_LABELS[slug]
  // 潜龙旧版规则版本常见写法
  if (slug.startsWith('qianlong')) return '潜龙出海'
  if (slug.startsWith('lugw')) return '卢高文'
  return slug
}

export function timingLabel(value: string | null | undefined): string {
  if (!value) return '—'
  return entryTimingLabel(String(value).trim())
}

export function dialogWidth(): string {
  if (typeof window !== 'undefined' && window.innerWidth <= 640) return '92vw'
  return '36rem'
}