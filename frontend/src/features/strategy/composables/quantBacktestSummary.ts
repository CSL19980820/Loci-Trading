/** 回测面板纯函数：摘要文案 / 跳过串 / 乐观差。 */

export type HorizonStatLite = {
  n?: number
  win_rate?: number
  avg?: number
  median?: number
  close_avg?: number | null
  close_win_rate?: number | null
  sample_confidence?: string
  caution?: string
} | null

export function skippedText(skipped: Record<string, number> | undefined): string {
  if (!skipped) return ''
  return Object.entries(skipped)
    .filter(([, n]) => n > 0)
    .map(([reason, n]) => `${reason} ${n}`)
    .join(' · ')
}

/** 高点均值 − 收盘均值：正数表示高点口径更乐观。 */
export function optimismGapPct(
  highAvg: number | null | undefined,
  closeAvg: number | null | undefined,
): number | null {
  if (highAvg == null || closeAvg == null) return null
  if (!Number.isFinite(highAvg) || !Number.isFinite(closeAvg)) return null
  return Math.round((highAvg - closeAvg) * 10000) / 10000
}

import { signedPct as formatSignedPct } from '@/shared/lib/format'

export { formatSignedPct }

export function buildHorizonCompareRows(
  t1: HorizonStatLite,
  t3: HorizonStatLite,
): Array<{ key: string; label: string; t1: string; t3: string }> {
  return [
    {
      key: 'n',
      label: '样本',
      t1: t1?.n != null ? String(t1.n) : '—',
      t3: t3?.n != null ? String(t3.n) : '—',
    },
    {
      key: 'win',
      label: '胜率(高点)',
      t1: t1?.win_rate != null ? `${t1.win_rate.toFixed(1)}%` : '—',
      t3: t3?.win_rate != null ? `${t3.win_rate.toFixed(1)}%` : '—',
    },
    {
      key: 'avg',
      label: '均值(高点)',
      t1: formatSignedPct(t1?.avg),
      t3: formatSignedPct(t3?.avg),
    },
    {
      key: 'close',
      label: '均值(收盘)',
      t1: formatSignedPct(t1?.close_avg ?? null),
      t3: formatSignedPct(t3?.close_avg ?? null),
    },
    {
      key: 'gap',
      label: '乐观差',
      t1: formatSignedPct(optimismGapPct(t1?.avg, t1?.close_avg ?? null)),
      t3: formatSignedPct(optimismGapPct(t3?.avg, t3?.close_avg ?? null)),
    },
  ]
}

export function buildTradeSummaryText(input: {
  strategy: string
  range: string
  metrics: {
    trades?: number
    win_rate?: number
    avg_net_return?: number
    profit_factor?: number | null
    expectancy?: number
    avg_hold_days?: number
    caution?: string
  }
  performance?: {
    available?: boolean
    cumulative_return_pct?: number
    max_drawdown_pct?: number
    sharpe?: number | null
    cagr_pct?: number | null
  } | null
}): string {
  const m = input.metrics
  const p = input.performance
  const lines = [
    `Loci 成交回测 · ${input.strategy}`,
    `区间 ${input.range}`,
    `笔数 ${m.trades ?? 0} · 胜率 ${m.win_rate?.toFixed(1) ?? '—'}% · 均值 ${formatSignedPct(m.avg_net_return)} · 期望 ${formatSignedPct(m.expectancy)}`,
    `PF ${m.profit_factor == null ? '—' : m.profit_factor === Infinity ? '∞' : m.profit_factor.toFixed(2)} · 均持仓 ${m.avg_hold_days?.toFixed(1) ?? '—'} 日`,
  ]
  if (p?.available) {
    lines.push(
      `诊断累计 ${formatSignedPct(p.cumulative_return_pct)} · CAGR ${formatSignedPct(p.cagr_pct)} · 最大回撤 ${formatSignedPct(p.max_drawdown_pct)} · 夏普 ${p.sharpe?.toFixed(2) ?? '—'}`,
      '（顺序复利诊断曲线，非真实多仓账户净值）',
    )
  }
  if (m.caution) lines.push(m.caution)
  return lines.join('\n')
}

export function buildHorizonSummaryText(input: {
  strategy: string
  range: string
  entry: string
  t1: HorizonStatLite
  t3: HorizonStatLite
}): string {
  const row = (label: string, s: HorizonStatLite) =>
    `${label} n=${s?.n ?? 0} 胜率=${s?.win_rate?.toFixed(1) ?? '—'}% 高点=${formatSignedPct(s?.avg)} 收盘=${formatSignedPct(s?.close_avg ?? null)} 乐观差=${formatSignedPct(optimismGapPct(s?.avg, s?.close_avg ?? null))}`
  return [
    `Loci Horizon 回测 · ${input.strategy}`,
    `区间 ${input.range} · 入场 ${input.entry}`,
    row('T+1', input.t1),
    row('T+3', input.t3),
    '高点口径为乐观上沿；收盘更接近可兑现。',
  ].join('\n')
}

export const BACKTEST_PREFS_KEY = 'loci.quant-backtest.prefs.v1'

export type BacktestPrefs = {
  mode?: 'horizon' | 'trade'
  range?: [string, string] | null
  activePreset?: 30 | 90 | 180 | null
  holdDays?: number
  stopLossEnabled?: boolean
  stopLossPct?: number
  commissionBps?: number
  stampDutyBps?: number
  slippageBps?: number
}

export function loadBacktestPrefs(): BacktestPrefs {
  try {
    const raw = sessionStorage.getItem(BACKTEST_PREFS_KEY)
    if (!raw) return {}
    const parsed = JSON.parse(raw) as BacktestPrefs
    return parsed && typeof parsed === 'object' ? parsed : {}
  } catch {
    return {}
  }
}

export function saveBacktestPrefs(prefs: BacktestPrefs): void {
  try {
    sessionStorage.setItem(BACKTEST_PREFS_KEY, JSON.stringify(prefs))
  } catch {
    /* ignore quota */
  }
}
