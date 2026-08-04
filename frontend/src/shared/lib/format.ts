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
  const raw = decision.trim()
  const key = raw.toLowerCase()
  const mapped =
    {
      select: '精选',
      selected: '精选',
      core: '精选',
      buy: '精选',
      买入: '精选',
      高确定性: '精选',
      值得做: '精选',
      入选: '精选',
      重点: '精选',
      建仓: '精选',
      reject: '落选',
      rejected: '落选',
      drop: '落选',
      exclude: '落选',
      剔除: '落选',
      排除: '落选',
      空仓: '落选',
      watch: '观察',
      hold: '观察',
      hold_cash: '观察',
      partial: '观察',
      持仓: '观察',
      持有: '观察',
      观望: '观察',
      空仓观望: '观察',
      部分参与: '观察',
      精选: '精选',
      落选: '落选',
      观察: '观察',
    }[key] ??
    {
      买入: '精选',
      高确定性: '精选',
      值得做: '精选',
      入选: '精选',
      重点: '精选',
      建仓: '精选',
      剔除: '落选',
      排除: '落选',
      空仓: '落选',
      持仓: '观察',
      持有: '观察',
      观望: '观察',
      空仓观望: '观察',
      部分参与: '观察',
    }[raw]
  return mapped ?? raw
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
  const raw = value.trim()
  const key = raw.toLowerCase().replace(/\s+/g, '')
  return (
    {
      open: '当日开盘',
      close: '当日收盘',
      next_open: '次日开盘',
      next_dip: '次日低吸',
      next_op: '次日开盘',
      w: '尾盘',
      尾盘: '尾盘',
      禁w: '禁尾盘',
      禁尾盘: '禁尾盘',
      'd-flat': '平开',
      d_flat: '平开',
      flat: '平开',
      平开: '平开',
      'd-low': '低吸',
      d_low: '低吸',
      low: '低吸',
      低吸: '低吸',
      'd-high': '高开回踩',
      d_high: '高开回踩',
      high: '高开回踩',
      高开回踩: '高开回踩',
      hold: '持有',
      持有: '持有',
      watch: '观望',
      观望: '观望',
      auction: '竞价',
      竞价: '竞价',
      // 保留原大小写键（兼容未 lower 的直接查）
      W: '尾盘',
      '禁W': '禁尾盘',
      'D-flat': '平开',
      'D-low': '低吸',
      'D-high': '高开回踩',
    }[key] ??
    {
      W: '尾盘',
      '禁W': '禁尾盘',
      'D-flat': '平开',
      'D-low': '低吸',
      'D-high': '高开回踩',
    }[raw] ??
    raw
  )
}

/** 候选/历史里出现的战法 slug → 中文名（含旧别名）。 */
const STRATEGY_LABELS: Record<string, string> = {
  潜龙: '潜龙出海',
  qianlong: '潜龙出海',
  'qianlong-v1': '潜龙出海',
  'qianlong-close': '潜龙出海',
  'qianlong-close-v2': '潜龙出海（优化版）',
  'qianlong-close-v3': '潜龙出海（V3）',
  'qianlong-tail-v1': '潜龙尾盘（V1）',
  'sanyuan-tail-v1': '三源尾盘共振',
  'qianlong-auction': '潜龙出海',
  潜龙出海: '潜龙出海',
  '潜龙出海·原版': '潜龙出海',
  '潜龙出海·竞价版': '潜龙出海',
  三外有三: '三外有三',
  天衣无缝: '天衣无缝',
  倒拔杨柳: '倒拔杨柳',
  海底捞月: '海底捞月',
  分手快乐: '分手快乐',
  筹码峰突破: '筹码峰突破',
  '卢高文·三外有三': '三外有三',
  '卢高文·天衣无缝': '天衣无缝',
  '卢高文·倒拔杨柳': '倒拔杨柳',
  '卢高文·海底捞月': '海底捞月',
  '卢高文·分手快乐': '分手快乐',
  '卢高文·筹码峰突破': '筹码峰突破',
  'lugw-sanwai': '三外有三',
  'lugw-tianyi': '天衣无缝',
  'lugw-daoba': '倒拔杨柳',
  'lugw-haidi': '海底捞月',
  'lugw-fenshou': '分手快乐',
  'lugw-chouma': '筹码峰突破',
}

export function strategyLabel(slug: string | null | undefined, fallbackMap?: Map<string, string>): string {
  if (!slug) return '—'
  if (fallbackMap?.has(slug)) return fallbackMap.get(slug) || slug
  if (STRATEGY_LABELS[slug]) return STRATEGY_LABELS[slug]
  // 潜龙旧版规则版本常见写法
  if (slug.startsWith('qianlong') || slug.includes('潜龙')) return '潜龙出海'
  if (slug.startsWith('lugw') || slug.includes('卢高文')) {
    if (slug.includes('sanwai') || slug.includes('三外')) return '三外有三'
    if (slug.includes('haidi') || slug.includes('海底')) return '海底捞月'
    if (slug.includes('chouma') || slug.includes('筹码')) return '筹码峰突破'
    if (slug.includes('tianyi') || slug.includes('天衣')) return '天衣无缝'
    if (slug.includes('daoba') || slug.includes('倒拔')) return '倒拔杨柳'
    if (slug.includes('fenshou') || slug.includes('分手')) return '分手快乐'
  }
  return slug
}

export function timingLabel(value: string | null | undefined): string {
  if (!value) return '—'
  return entryTimingLabel(String(value).trim())
}

export function dialogWidth(): string {
  return 'min(36rem, 92vw)'
}
