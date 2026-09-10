/**
 * 持有期（horizon）回测：不模拟卖出，只看信号后 T+N 的分布。与逐笔回测共用
 * 「命中率/均值/分位」这些词但口径不同，分文件是为了让引用处必须显式选一套。
 */

import type { EntryTiming } from './enums'

/** 极端案例标注（样本最佳/最差那一笔） */
export interface HorizonEventRef {
  code: string
  name?: string
  signal_date: string
  entry_date: string
  mark_date: string
  return_pct: number
  base_close?: number
  mark_high?: number
}

export interface HorizonPeriodRow {
  period: string
  n: number
  win_rate: number
  avg: number
}

export interface HorizonStats {
  n: number
  win_rate: number
  avg: number
  best: number
  worst: number
  median?: number
  std?: number
  avg_win?: number | null
  avg_loss?: number | null
  payoff_ratio?: number | null
  percentiles?: Record<string, number>
  distribution?: Array<{ lo: number; hi: number; n: number }>
  by_month?: HorizonPeriodRow[]
  sample_confidence?: 'low' | 'medium' | 'high' | string
  caution?: string
  mark_basis?: string
  mark_basis_note?: string
  close_n?: number
  close_avg?: number
  close_median?: number
  close_win_rate?: number
  close_best?: number
  close_worst?: number
  close_note?: string
  best_event?: HorizonEventRef | null
  worst_event?: HorizonEventRef | null
}

export interface HorizonBacktestResult {
  strategy: string
  mode: 'horizon' | string
  entry_timing: EntryTiming | string
  config: Record<string, unknown>
  horizons: {
    t1?: HorizonStats | null
    t3?: HorizonStats | null
    [key: string]: HorizonStats | null | undefined
  }
  skipped: Record<string, number>
  events?: Array<Record<string, unknown>>
}
