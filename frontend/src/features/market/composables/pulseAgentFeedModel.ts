import type { GuardianRun, GuardianReviewSummary } from '@/shared/types/guardian'
import { statusName } from '@/features/agents/agentFormat'

export interface AgentFeedRow {
  key: string
  agentId: string
  agentName: string
  to: string
  at: string
  phaseLabel: string
  statusLabel: string
  summary: string
  failed: boolean
}

/** Legacy local datetimes mean Beijing time, not the viewing device's timezone. */
export function feedEpoch(value: string | number | null | undefined): number {
  if (typeof value === 'number') {
    const ms = Math.abs(value) < 1e12 ? value * 1000 : value
    return Number.isFinite(ms) && Math.abs(ms) <= 8.64e15 ? ms : 0
  }
  let text = String(value ?? '').trim().replace(' ', 'T')
  if (!text) return 0
  if (/^\d{4}-\d{2}-\d{2}$/.test(text)) text += 'T00:00:00'
  if (!/(?:Z|[+-]\d{2}:?\d{2})$/i.test(text)) text += '+08:00'
  const time = Date.parse(text)
  return Number.isFinite(time) ? time : 0
}
function at(...values: (string | number | null | undefined)[]): string {
  const stamp = values.map(feedEpoch).find(Boolean)
  return stamp ? new Date(stamp).toISOString() : ''
}
export const feedPhase = (phase?: string): string => ({
  premarket:'盘前计划', auction:'竞价研判', intraday:'盘中研判', closeout:'尾盘研判',
  daily:'盘后复盘', review:'盘后复盘', weekly:'周复盘',
}[phase ?? ''] ?? '研判记录')

export function guardianRunRows(runs: GuardianRun[]): AgentFeedRow[] {
  return runs.map(run => ({
    key:`guardian:run:${run.slot}`, agentId:'guardian', agentName:'天才交易员',
    to:'/agents/guardian?tab=research', at:at(run.started, run.result?.as_of),
    phaseLabel:'盘中研判', statusLabel:run.status === 'running' ? '研判中' : statusName(run.status),
    summary:(run.result?.error || run.result?.analysis || run.result?.body || run.result?.sections?.flatMap(s => s.paragraphs).join('\n') || '').trim(),
    failed:['failed','interrupted'].includes(run.status) || Boolean(run.result?.error),
  }))
}
export function guardianReportRows(reports: GuardianReviewSummary[]): AgentFeedRow[] {
  return reports.map(report => ({
    key:`guardian:report:${report.report_key || `${report.period}:${report.trade_date}`}`,
    agentId:'guardian', agentName:'天才交易员', to:'/agents/guardian?tab=reviews',
    at:at(report.started, report.created_at), phaseLabel:feedPhase(report.period),
    statusLabel:report.status === 'running' ? '研判中' : statusName(report.status),
    summary:(report.error || report.summary || '').trim(),
    failed:['failed','interrupted'].includes(report.status) || Boolean(report.error),
  }))
}
/** Limit only after all stages/sources are merged. Do not reserve slots by phase. */
export function latestAgentFeed(rows: AgentFeedRow[], limit = 16): AgentFeedRow[] {
  const unique = new Map<string, AgentFeedRow>()
  for (const row of rows) {
    const old = unique.get(row.key)
    if (!old || feedEpoch(row.at) > feedEpoch(old.at)) unique.set(row.key, row)
  }
  return [...unique.values()].sort((a,b) => feedEpoch(b.at) - feedEpoch(a.at) || a.key.localeCompare(b.key)).slice(0, Math.max(0, limit))
}
