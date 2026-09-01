/**
 * healthCheckupLogic：体检结果汇总 / 分级 / 文案与进度映射（纯函数）。
 */
import { describe, expect, it } from 'vitest'

import {
  bootstrapDoneMessage,
  bootstrapProgressDetail,
  checkupHeadline,
  checkupSubtitle,
  effectiveCatalog,
  isInstrumentsStalled,
  INSTRUMENTS_STALL_MESSAGE,
  phaseForReport,
  planForFindingAction,
  planIsActionable,
  resolveSealGrade,
  resolveSealScore,
  revealProgressSnap,
  revealSequence,
  scanHeartbeatSnap,
  softBootstrapPercent,
} from './healthCheckupLogic'
import type {
  HealthFinding,
  HealthRepairPlan,
  MarketBootstrapStatus,
  MarketHealthReport,
} from '@/shared/api/quant'

const EMPTY_PLAN: HealthRepairPlan = {
  actions: [],
  primary_action: null,
  with_factors: false,
  needs_bootstrap: false,
  needs_turnover_repair: false,
  labels: [],
  check_ids: [],
}

function report(overrides: Partial<MarketHealthReport> = {}): MarketHealthReport {
  return {
    trade_date: '2026-08-26',
    blocked: false,
    reason: '',
    checked_at: '08-27 09:00',
    findings: [],
    block_count: 0,
    warn_count: 0,
    score: 100,
    grade: '优',
    repair_plan: EMPTY_PLAN,
    catalog: [],
    ...overrides,
  }
}

function finding(overrides: Partial<HealthFinding> & { check: string }): HealthFinding {
  return { severity: 'block', message: '', ...overrides }
}

function bootstrapSnap(overrides: Partial<MarketBootstrapStatus> = {}): MarketBootstrapStatus {
  return {
    status: 'running',
    phase: 'daily',
    done: 0,
    total: 0,
    percent: 0,
    code: '',
    message: '',
    ...overrides,
  }
}

describe('体检分与等级', () => {
  it('后端给分就用后端的，缺失才按阻断/提示回退', () => {
    expect(resolveSealScore(report({ score: 73 }))).toBe(73)
    expect(resolveSealScore(report({ score: Number.NaN, block_count: 1, warn_count: 2 }))).toBe(59)
    expect(resolveSealScore(null)).toBeNull()
  })

  it('等级缺失时由分数回推', () => {
    expect(resolveSealGrade(report({ grade: '良' }), 95)).toBe('良')
    expect(resolveSealGrade(report({ grade: '' }), 95)).toBe('优')
    expect(resolveSealGrade(report({ grade: '' }), null)).toBe('')
    expect(resolveSealGrade(null, 95)).toBe('')
  })
})

describe('修复计划与落点', () => {
  it('没有 bootstrap / 换手回填就不算可一键修复', () => {
    expect(planIsActionable(null)).toBe(false)
    expect(planIsActionable(EMPTY_PLAN)).toBe(false)
    expect(planIsActionable({ ...EMPTY_PLAN, needs_turnover_repair: true })).toBe(true)
  })

  it('仍被阻断或还有可修项时停在 result', () => {
    expect(phaseForReport(report())).toBe('healthy')
    expect(phaseForReport(report({ blocked: true }))).toBe('result')
    expect(
      phaseForReport(report({ repair_plan: { ...EMPTY_PLAN, needs_bootstrap: true } })),
    ).toBe('result')
  })

  it('单项修复计划只带该项自己的 action 与 check', () => {
    const plan = planForFindingAction({ action: 'sync_factors', check: 'factor_stale', label: '补因子' })
    expect(plan).toEqual({
      actions: ['sync_factors'],
      primary_action: 'sync_factors',
      with_factors: true,
      needs_bootstrap: true,
      needs_turnover_repair: false,
      labels: ['补因子'],
      check_ids: ['factor_stale'],
    })
    const turnover = planForFindingAction({ action: 'repair_turnover', check: 'turnover_missing' })
    expect(turnover.needs_bootstrap).toBe(false)
    expect(turnover.needs_turnover_repair).toBe(true)
    expect(turnover.labels).toEqual(['修复'])
  })
})

describe('目录与回放顺序', () => {
  const catalog = [
    { id: 'empty_store', label: '仓内有数据', group: '仓内' },
    { id: 'staleness', label: '最新日是否落后', group: '时效' },
    { id: 'db_size_warn', label: '行情库体积', group: '存储' },
  ]

  it('空仓阻断且核心检查没往下跑时，核心项不摆出来充数', () => {
    const rows = effectiveCatalog(
      report({ catalog, findings: [finding({ check: 'empty_store' })] }),
    )
    expect(rows.map((r) => r.id)).toEqual(['empty_store', 'db_size_warn'])
  })

  it('核心检查真的跑过就展示完整目录', () => {
    const rows = effectiveCatalog(
      report({
        catalog,
        findings: [
          finding({ check: 'empty_store' }),
            finding({ check: 'staleness', severity: 'warn' }),
        ],
      }),
    )
    expect(rows.map((r) => r.id)).toEqual(['empty_store', 'staleness', 'db_size_warn'])
  })

  it('没有 empty_store 结论时不回放该行', () => {
    expect(revealSequence(catalog, []).map((r) => r.id)).toEqual(['staleness', 'db_size_warn'])
    expect(
      revealSequence(catalog, [finding({ check: 'empty_store' })]).map((r) => r.id),
       ).toEqual(['empty_store', 'staleness', 'db_size_warn'])
  })
})

describe('标题与副标题', () => {
  it('各阶段标题固定', () => {
    expect(checkupHeadline('idle', 0)).toBe('尚未体检')
    expect(checkupHeadline('scanning', 0)).toBe('正在核对行情仓')
    expect(checkupHeadline('repairing', 3)).toBe('正在修复')
    expect(checkupHeadline('healthy', 0)).toBe('行情仓可安全选股')
    expect(checkupHeadline('result', 2)).toBe('发现 2 项问题')
    expect(checkupHeadline('result', 0)).toBe('体检完成')
  })

  it('待检态报待检项数', () => {
    expect(
      checkupSubtitle({ phase: 'idle', progress: null, report: null, idleCount: 9 }),
    ).toContain('9 项待检')
  })

  it('扫描态优先用进度文案，没有文案才退回百分比', () => {
    const base = { phase: 'scanning' as const, report: null, idleCount: 0 }
    expect(
      checkupSubtitle({
        ...base,
        progress: { percent: 40, message: '连接行情仓…', detail: '', status: 'running' },
      }),
    ).toBe('连接行情仓…')
    expect(
      checkupSubtitle({
        ...base,
        progress: { percent: 40.4, message: '', detail: '', status: 'running' },
      }),
    ).toBe('进度 40%')
    expect(checkupSubtitle({ ...base, progress: null })).toBe('正在核对行情仓…')
  })

  it('收口后按通过 / 阻断给读数', () => {
    expect(
      checkupSubtitle({ phase: 'healthy', progress: null, report: report(), idleCount: 0 }),
    ).toBe('全部通过 · 上次 08-27 09:00 · 交易日 2026-08-26')
    expect(
      checkupSubtitle({
        phase: 'result',
        progress: null,
        report: report({ blocked: true, block_count: 1, warn_count: 2 }),
        idleCount: 0,
      }),
    ).toBe('阻断 1 · 提示 2 · 选股将被拒绝 · 交易日 2026-08-26')
    expect(
      checkupSubtitle({ phase: 'repairing', progress: null, report: report(), idleCount: 0 }),
    ).toBe('修好后自动复检')
    expect(
      checkupSubtitle({ phase: 'result', progress: null, report: null, idleCount: 0 }),
    ).toBe('')
  })
})

describe('进度映射', () => {
  it('扫描心跳封顶 28%，等待秒数进 detail', () => {
    expect(scanHeartbeatSnap('连接行情仓…', 0)).toEqual({
      percent: 4,
      message: '连接行情仓…',
      detail: '',
      status: 'running',
    })
    expect(scanHeartbeatSnap('连接行情仓…', 3).detail).toBe('已等待 3s')
    expect(scanHeartbeatSnap('连接行情仓…', 600).percent).toBe(28)
  })

  it('回放进度在揭晓前后各占一档', () => {
  const item = { id: 'staleness', label: '最新日是否落后', group: '时效' }
    const before = revealProgressSnap({ item, index: 0, total: 4, tradeDate: '2026-08-26', done: false })
    const after = revealProgressSnap({ item, index: 0, total: 4, tradeDate: '', done: true })
    expect(before.percent).toBe(11)
    expect(before.message).toBe('检查 1/4 · 最新日是否落后')
       expect(before.detail).toBe('staleness · trade_date 2026-08-26')
    expect(after.percent).toBe(25)
    expect(after.detail).toBe('staleness · trade_date —')
  })

  it('bootstrap 零进度时用等待秒数给软进度', () => {
    expect(softBootstrapPercent(42, 100)).toBe(42)
    expect(softBootstrapPercent(0, 0)).toBe(1)
    expect(softBootstrapPercent(0, 45)).toBe(4)
    expect(softBootstrapPercent(0, 3600)).toBe(8)
  })

  it('instruments 阶段长时间零进展才算卡死', () => {
    expect(isInstrumentsStalled(bootstrapSnap({ phase: 'instruments' }), 179)).toBe(false)
    expect(isInstrumentsStalled(bootstrapSnap({ phase: 'instruments' }), 180)).toBe(true)
    expect(isInstrumentsStalled(bootstrapSnap({ phase: '' }), 180)).toBe(true)
    expect(isInstrumentsStalled(bootstrapSnap({ phase: 'daily' }), 900)).toBe(false)
    expect(isInstrumentsStalled(bootstrapSnap({ phase: 'instruments', percent: 3 }), 900)).toBe(false)
    expect(isInstrumentsStalled(bootstrapSnap({ phase: 'instruments', status: 'done' }), 900)).toBe(false)
    expect(INSTRUMENTS_STALL_MESSAGE).toContain('刷新证券列表超时')
  })

  it('bootstrap 明细按有值的字段拼', () => {
    expect(
      bootstrapProgressDetail(bootstrapSnap({ done: 30, total: 100, code: '600000', phase: 'daily', percent: 40 }), 9),
    ).toBe('30/100 · 当前 600000 · 阶段 daily')
    expect(bootstrapProgressDetail(bootstrapSnap({ phase: 'instruments' }), 9)).toBe(
      '阶段 instruments · 已等待 9s',
    )
    expect(bootstrapProgressDetail(bootstrapSnap({ phase: '' }), 1)).toBe('')
  })

  it('修复完成读数缺字段时补占位', () => {
    expect(bootstrapDoneMessage({ succeeded: 10, failed: 0, skipped: 2 })).toBe(
      '修复完成：成功 10 / 失败 0 / 跳过 2',
    )
    expect(bootstrapDoneMessage(null)).toBe('修复完成：成功 — / 失败 — / 跳过 —')
  })
})
