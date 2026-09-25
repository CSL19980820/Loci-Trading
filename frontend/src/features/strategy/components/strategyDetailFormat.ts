import type { StrategyInfo, StrategyVersion, UniverseSpec } from '@/shared/types/quant'

export type ScheduleMode = 'off' | 'once' | 'interval'
export type BoardId = 'main' | 'chi_next' | 'star' | 'bse'

export const FIELD_LABELS: Record<string, string> = {
  open: '开盘价',
  high: '最高价',
  low: '最低价',
  close: '收盘价',
  volume: '成交量',
  turnover: '换手率',
}

export const PARAM_LABELS: Record<string, string> = {
  concentration: '集中度',
  low_ratio: '低位比例',
  volume_boost: '放量倍数',
  chip_bins: '筹码档位',
  death_lookback: '死叉回看',
  below_window: '白线下窗口',
  below_min: '白下最少天',
  price_min: '最低价',
  vol_boost: '放量倍数',
  hold_ratio: '站稳比例',
  turnover_min: '换手下限',
  turnover_max: '换手上限',
}

export const BOARD_OPTIONS: { id: BoardId; label: string }[] = [
  { id: 'main', label: '主板' },
  { id: 'chi_next', label: '创业板' },
  { id: 'star', label: '科创板' },
  { id: 'bse', label: '北交所' },
]

export const HOUR_OPTS = Array.from({ length: 24 }, (_, i) => i)
export const MINUTE_OPTS = Array.from({ length: 12 }, (_, i) => i * 5)
export const INTERVAL_OPTS = [5, 10, 15, 30, 60]

export function pad(n: number): string {
  return String(n).padStart(2, '0')
}

export function formatPercent(value: number | null | undefined): string {
  return typeof value === 'number' ? `${value.toFixed(2)}%` : '—'
}

export function formatProfitFactor(value: number | null | undefined): string {
  if (value === Infinity) return '∞'
  return typeof value === 'number' ? value.toFixed(2) : '—'
}

export function formatBacktestValue(key: string, value: unknown): string {
  if (key === 'universe' && value && typeof value === 'object' && !Array.isArray(value)) {
    const universe = value as UniverseSpec
    const boards = (universe.boards ?? []).map(
      (board) => BOARD_OPTIONS.find((option) => option.id === board)?.label ?? board,
    )
    const parts = boards.length ? [boards.join('、')] : []
    if (universe.exclude_st === false) parts.push('含 ST')
    else if (universe.exclude_st === true) parts.push('剔除 ST')
    if (!parts.length && universe.preset) parts.push(String(universe.preset))
    return parts.join('，') || '—'
  }
  if (Array.isArray(value)) return value.join('、')
  if (value && typeof value === 'object') return JSON.stringify(value)
  return String(value)
}

const BACKTEST_LABELS: Record<string, string> = {
  start: '起始', end: '结束', hold_days: '持有', stop_loss_pct: '止损',
  take_profit_pct: '止盈', benchmark: '基准', entry_timing: '入场', mode: '模式', universe: '股票池',
}

/** 回测口径拆成「标签 · 值」对，给详情页排成小格子 */
export function backtestConfigEntries(
  config: Record<string, unknown> | null | undefined,
): { key: string; label: string; value: string }[] {
  if (!config) return []
  return Object.entries(config)
    .filter(([, value]) => value != null && value !== '')
    .map(([key, value]) => ({ key, label: BACKTEST_LABELS[key] || key, value: formatBacktestValue(key, value) }))
}

export function buildPreview(
  mode: 'once' | 'interval',
  hour: number,
  minute: number,
  every: number,
  startH: number,
  startM: number,
  endH: number,
  endM: number,
): string[] {
  const now = new Date()
  const day = `${now.getFullYear()}-${pad(now.getMonth() + 1)}-${pad(now.getDate())}`
  if (mode === 'once') return [`${day} ${pad(hour)}:${pad(minute)}`]
  const start = startH * 60 + startM
  const end = endH * 60 + endM
  const out: string[] = []
  for (let t = start; t <= end && out.length < 5; t += every) {
    out.push(`${day} ${pad(Math.floor(t / 60))}:${pad(t % 60)}`)
  }
  return out
}

export function isActiveVersion(version: StrategyVersion, currentVersion?: string): boolean {
  return version.is_active === true || String(version.version) === currentVersion
}

export function strategySourceLabel(strategy: StrategyInfo | null | undefined): string {
  const kind = strategy?.source_kind
  if (kind === 'builtin') return '内置'
  if (kind === 'formula') return '公式'
  return kind || '—'
}

export function strategyEntryLabel(strategy: StrategyInfo | null | undefined): string {
  const v = strategy?.entry_timing
  if (v === 'open') return '当日开盘'
  if (v === 'next_dip') return '次日低吸'
  if (v === 'close') return '当日收盘'
  return '次日开盘'
}

export function strategyRevisionLabel(strategy: StrategyInfo | null | undefined): string {
  const raw = String(strategy?.strategy_revision || '').trim()
  const kind = strategy?.source_kind
  if (!raw) return '—'
  if (kind === 'builtin' || raw.startsWith('builtin:')) return '内置'
  if (/^[0-9a-f]{8,}$/i.test(raw)) return `公式 · ${raw.slice(0, 8)}`
  return raw.slice(0, 12)
}

export function strategyParamRows(strategy: StrategyInfo | null | undefined) {
  return Object.entries(strategy?.params ?? {}).map(([key, value]) => ({
    key,
    label: PARAM_LABELS[key] || key,
    value: String(value),
  }))
}

export function strategyFieldRows(strategy: StrategyInfo | null | undefined) {
  return (strategy?.required_fields ?? []).map((key) => ({
    key,
    label: FIELD_LABELS[key] || key,
  }))
}
