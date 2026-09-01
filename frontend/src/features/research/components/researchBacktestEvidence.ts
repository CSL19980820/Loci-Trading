import type { ResearchBacktestRun } from '@/shared/types/quant-research'

export type ProvenanceEntry = { key: string; value: string }
export type SourceEvidenceRow = {
  id: string
  kind: string
  sourceId: string
  state: string
  sourceUrl: string
  detail: string
}

type EvidenceEntry = { kind: string; item: unknown }

export function printable(value: unknown): string {
  if (value === null || value === undefined || value === '') return '未提供'
  if (typeof value === 'object') return JSON.stringify(value)
  return String(value)
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return value !== null && typeof value === 'object' && !Array.isArray(value)
}

function safeSourceUrl(value: unknown): string {
  if (typeof value !== 'string') return ''
  try {
    const url = new URL(value)
    return url.protocol === 'https:' || url.protocol === 'http:' ? url.toString() : ''
  } catch {
    return ''
  }
}

function recordText(record: Record<string, unknown>, key: string): string {
  const value = record[key]
  return typeof value === 'string' || typeof value === 'number' ? String(value) : ''
}

export function temporalMembership(run: ResearchBacktestRun | null): Record<string, unknown> {
  if (!run) return {}
  const fromSnapshot = run.data_snapshot?.temporal_membership
  if (isRecord(fromSnapshot)) return fromSnapshot
  const fromFunnel = run.universe_funnel?.temporal_membership
  return isRecord(fromFunnel) ? fromFunnel : {}
}

export function provenanceEntries(run: ResearchBacktestRun | null): ProvenanceEntry[] {
  if (!run) return []
  const membership = temporalMembership(run)
  return [
    ['input_sha256', run.input_sha256],
    ['frozen_input_sha256', run.data_snapshot?.frozen_input_sha256],
    ['market_revision', run.market_revision],
    ['strategy_revision', run.strategy_revision],
    ['requested_as_of', run.requested_as_of],
    ['actual_as_of', run.actual_as_of],
    ['temporal_membership.universe_id', recordText(membership, 'universe_id')],
    ['temporal_membership.as_of', recordText(membership, 'as_of')],
    ['temporal_membership.available_at', recordText(membership, 'available_at')],
    ['temporal_membership.source_id', recordText(membership, 'source_id')],
    ['temporal_membership.source_url', recordText(membership, 'source_url')],
    ['temporal_membership.snapshot_revision', recordText(membership, 'snapshot_revision')],
    ['temporal_membership.fetched_at', recordText(membership, 'fetched_at')],
    ['temporal_membership.payload_sha256', recordText(membership, 'payload_sha256')],
    ['temporal_membership.parser_revision', recordText(membership, 'parser_revision')],
  ].filter(([, value]) => value !== null && value !== undefined && value !== '')
    .map(([key, value]) => ({ key: String(key), value: printable(value) }))
}

export function strictPitRequested(run: ResearchBacktestRun | null): boolean {
  return run?.validation?.strict_pit === true
}

export function isExploratoryRun(run: ResearchBacktestRun | null): boolean {
  if (!run) return false
  const membership = temporalMembership(run)
  return !strictPitRequested(run)
    || run.validation?.status === 'degraded'
    || membership.degraded === true
    || membership.survivorship_bias === true
}

/** el-alert 标题：≤20 字、只报当前真实风险；完整口径由 runEvidenceDescription 走 tooltip。 */
export function runEvidenceTitle(run: ResearchBacktestRun | null): string {
  return isExploratoryRun(run) ? '降级 / 探索性 run，不能作为证据' : '严格 PIT 证据门禁'
}

export function runEvidenceDescription(run: ResearchBacktestRun | null): string {
  if (isExploratoryRun(run)) {
    return '该 run 未声明并通过严格 PIT 门禁，或后端已标记为 degraded。它只能用于探索，不能作为假设通过、已核验证据或生产默认的依据。'
  }
  return '该 run 请求了严格 PIT；仍以本页冻结输入、来源回执、验证结果和人工签署状态为准，缺任一项不得视为通过。'
}

function evidenceRows(record: Record<string, unknown>, key: 'sources' | 'receipts' | 'attempts'): unknown[] {
  const entries = record[key]
  return Array.isArray(entries) ? entries : []
}

function evidenceKindLabel(kind: string): string {
  if (kind === 'sources') return '来源'
  if (kind === 'receipts') return '路由回执'
  if (kind === 'attempts') return '来源尝试'
  return kind
}

export function sourceEvidenceRows(run: ResearchBacktestRun | null): SourceEvidenceRow[] {
  if (!run) return []
  const records: EvidenceEntry[] = run.source_evidence.flatMap((item): EvidenceEntry[] => {
    if (!isRecord(item)) return [{ kind: '未识别回执', item }]
    const nested = (['sources', 'receipts', 'attempts'] as const).flatMap((key) =>
      evidenceRows(item, key).map((entry) => ({ kind: key, item: entry })))
    return nested.length ? nested : [{ kind: '来源摘要', item }]
  })
  return records.map(({ kind, item }, index) => {
    const record = isRecord(item) ? item : {}
    const sourceId = recordText(record, 'source_id')
      || recordText(record, 'selected_source')
      || recordText(record, 'id')
      || `来源 ${index + 1}`
    return {
      id: `${kind}:${sourceId}:${index}`,
      kind: evidenceKindLabel(kind),
      sourceId,
      state: recordText(record, 'state') || (record.unresolved === true ? 'unresolved' : '未提供'),
      sourceUrl: safeSourceUrl(record.source_url ?? record.url),
      detail: printable(item),
    }
  })
}

export function sourceEvidenceIssues(run: ResearchBacktestRun | null): string[] {
  if (!run) return []
  return run.source_evidence.flatMap((item) => {
    if (!isRecord(item)) return []
    const issues: string[] = []
    const list = (key: string) => Array.isArray(item[key]) ? item[key].map(String).filter(Boolean) : []
    const unresolved = list('unresolved_codes')
    const unparsed = list('unparsed_codes')
    if (item.attempts_not_observed === true) issues.push('来源 attempt 未观测')
    if (unresolved.length) issues.push(`未解析代码：${unresolved.join('、')}`)
    if (unparsed.length) issues.push(`无法标准化代码：${unparsed.join('、')}`)
    const invalid = item.invalid_ohlc_rows
    if (typeof invalid === 'number' && invalid > 0) issues.push(`无效 OHLC：${invalid} 条`)
    evidenceRows(item, 'sources').forEach((entry) => {
      if (!isRecord(entry) || entry.state !== 'failed') return
      issues.push(`来源失败：${recordText(entry, 'source_id') || '未命名来源'}${recordText(entry, 'error') ? `（${recordText(entry, 'error')}）` : ''}`)
    })
    evidenceRows(item, 'receipts').forEach((entry) => {
      if (!isRecord(entry) || !entry.error) return
      issues.push(`回执错误：${recordText(entry, 'code') || recordText(entry, 'receipt_id') || '未命名回执'}（${recordText(entry, 'error')}）`)
    })
    evidenceRows(item, 'attempts').forEach((entry) => {
      if (!isRecord(entry) || !entry.error) return
      issues.push(`尝试错误：${recordText(entry, 'source_id') || '未命名来源'}（${recordText(entry, 'error')}）`)
    })
    return [...new Set(issues)]
  })
}
