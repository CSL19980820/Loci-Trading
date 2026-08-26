/**
 * useHealthCheckup：目录行映射 + 体检分回退。
 */
import { describe, expect, it } from 'vitest'

import {
  computeSealGrade,
  computeSealScore,
  normalizeHealthReport,
} from '@/features/review/composables/useHealthCheckup'
import type { HealthCatalogItem, HealthFinding, MarketHealthReport } from '@/shared/api/quant'

type CheckRowStatus = 'pending' | 'running' | 'ok' | 'warn' | 'block'

function findingMap(findings: HealthFinding[]): Map<string, HealthFinding> {
  const map = new Map<string, HealthFinding>()
  for (const f of findings) map.set(f.check, f)
  return map
}

function rowsFromCatalog(
  catalog: HealthCatalogItem[],
  findings: HealthFinding[],
  revealed: Set<string>,
  runningId: string | null,
): { id: string; status: CheckRowStatus }[] {
  const byId = findingMap(findings)
  const rows: { id: string; status: CheckRowStatus }[] = []
  for (const item of catalog) {
    const f = byId.get(item.id)
    if (!f && revealed.has(item.id) && item.id !== 'empty_store' && byId.has('empty_store')) {
      continue
    }
    let status: CheckRowStatus = 'pending'
    if (runningId === item.id) status = 'running'
    else if (revealed.has(item.id) && f) {
      status = f.severity === 'block' ? 'block' : f.severity === 'warn' ? 'warn' : 'ok'
    } else if (revealed.has(item.id) && !f) {
      status = 'ok'
    }
    rows.push({ id: item.id, status })
  }
  return rows
}

describe('seal score', () => {
  it('applies block/warn penalties', () => {
    expect(computeSealScore(0, 0)).toBe(100)
    expect(computeSealScore(0, 1)).toBe(92)
    expect(computeSealScore(2, 1)).toBe(42)
    expect(computeSealGrade(92)).toBe('优')
    expect(computeSealGrade(42)).toBe('差')
  })
})

describe('normalizeHealthReport', () => {
  it('fills score and repair_plan when backend omits them', () => {
    const raw = {
      trade_date: '2026-07-30',
      blocked: false,
      reason: '数据体检通过（1 项提示）',
      checked_at: '2026-07-30T22:32:13',
      findings: [{ check: 'turnover', severity: 'warn', message: '缺换手' }],
      block_count: 0,
      warn_count: 1,
    } as MarketHealthReport
    const next = normalizeHealthReport(raw)
    expect(next.score).toBe(92)
    expect(next.grade).toBe('优')
    expect(next.repair_plan.needs_turnover_repair).toBe(true)
    expect(next.findings[0]?.remediation?.action).toBe('repair_turnover')
  })

  it('does not map job_sync_stale into one-click bootstrap', () => {
    const raw = {
      trade_date: '2026-08-07',
      blocked: false,
      reason: '数据体检通过（2 项提示）',
      findings: [
        {
          check: 'turnover',
          severity: 'warn',
          message: '缺换手',
          remediation: { action: 'repair_turnover', label: '回填换手率' },
        },
        {
          check: 'job_sync_stale',
          severity: 'warn',
          message: '同步过久',
          // 旧后端曾把 Job 时效标成 sync，导致一键全量 bootstrap 卡死
          remediation: { action: 'sync', label: '手跑同步 Job' },
        },
      ],
      block_count: 0,
      warn_count: 2,
      repair_plan: {
        actions: ['sync', 'repair_turnover'],
        primary_action: 'sync',
        with_factors: true,
        needs_bootstrap: true,
        needs_turnover_repair: true,
        labels: ['手跑同步 Job', '回填换手率'],
        check_ids: ['job_sync_stale', 'turnover'],
      },
    } as MarketHealthReport
    const next = normalizeHealthReport(raw)
    expect(next.repair_plan.needs_bootstrap).toBe(false)
    expect(next.repair_plan.needs_turnover_repair).toBe(true)
    expect(next.repair_plan.actions).toEqual(['repair_turnover'])
  })
})

describe('health checkup row reveal', () => {
  const catalog: HealthCatalogItem[] = [
    { id: 'staleness', label: '时效', group: '时效' },
    { id: 'coverage', label: '覆盖', group: '覆盖' },
    { id: 'factor_age', label: '因子', group: '因子' },
  ]

  it('keeps pending until revealed', () => {
    const findings: HealthFinding[] = [
      { check: 'staleness', severity: 'block', message: '落后' },
      { check: 'coverage', severity: 'ok', message: 'ok' },
    ]
    const rows = rowsFromCatalog(catalog, findings, new Set(), 'staleness')
    expect(rows.find((r) => r.id === 'staleness')?.status).toBe('running')
    expect(rows.find((r) => r.id === 'coverage')?.status).toBe('pending')
  })

  it('maps severity after reveal', () => {
    const findings: HealthFinding[] = [
      { check: 'staleness', severity: 'block', message: '落后' },
      { check: 'factor_age', severity: 'warn', message: '旧' },
    ]
    const revealed = new Set(['staleness', 'coverage', 'factor_age'])
    const rows = rowsFromCatalog(catalog, findings, revealed, null)
    expect(rows.find((r) => r.id === 'staleness')?.status).toBe('block')
    expect(rows.find((r) => r.id === 'coverage')?.status).toBe('ok')
    expect(rows.find((r) => r.id === 'factor_age')?.status).toBe('warn')
  })
})
