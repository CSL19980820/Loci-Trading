/**
 * 数据体检纯逻辑（无 Vue 状态、无 IO）：结果汇总 / 分级 / 文案与进度映射。
 * 目录与报告归一在 `healthCheckupModel.ts`；反应式编排与取消链路在 `useHealthCheckup.ts`。
 */
import {
  CORE_CHECK_IDS,
  catalogForMode,
  computeSealGrade,
  computeSealScore,
  type HealthPhase,
  type ProgressSnap,
} from '@/features/review/composables/healthCheckupModel'
import type {
  HealthCatalogItem,
  HealthFinding,
  HealthRepairPlan,
  MarketBootstrapStatus,
  MarketHealthReport,
} from '@/shared/api/quant'

/** 体检分：后端给了就认后端的，缺失才按阻断/提示条数回退。 */
export function resolveSealScore(report: MarketHealthReport | null): number | null {
  if (!report) return null
  if (typeof report.score === 'number' && !Number.isNaN(report.score)) return report.score
  return computeSealScore(report.block_count ?? 0, report.warn_count ?? 0)
}

/** 等级同样以后端为准；没有等级时由分数回推。 */
export function resolveSealGrade(report: MarketHealthReport | null, score: number | null): string {
  if (!report) return ''
  if (report.grade) return report.grade
  return score == null ? '' : computeSealGrade(score)
}

/** 一键修复是否真有可执行动作。 */
export function planIsActionable(plan: HealthRepairPlan | null | undefined): boolean {
  return Boolean(plan?.needs_bootstrap || plan?.needs_turnover_repair)
}

/** 报告收口后的落点：仍被阻断或还有可修项就停在 result，否则 healthy。 */
export function phaseForReport(report: MarketHealthReport): HealthPhase {
  return report.blocked || planIsActionable(report.repair_plan) ? 'result' : 'healthy'
}

/**
 * 本次可展示的检查目录。
 * `empty_store` 阻断且核心检查没往下跑时，核心项其实没体检过，不能摆出来充数。
 */
export function effectiveCatalog(report: MarketHealthReport): HealthCatalogItem[] {
  const catalog = report.catalog?.length
    ? report.catalog
    : catalogForMode(Boolean(report.include_network))
  const emptyBlocked = report.findings.some(
    (f) => f.check === 'empty_store' && f.severity === 'block',
  )
  const coreRanBeyondEmpty = report.findings.some(
    (f) => CORE_CHECK_IDS.has(f.check) && f.check !== 'empty_store',
  )
  if (!emptyBlocked || coreRanBeyondEmpty) return catalog
  return catalog.filter((c) => c.id === 'empty_store' || !CORE_CHECK_IDS.has(c.id))
}

/** 扫描回放顺序：后端没给 `empty_store` 结论时不回放该行。 */
export function revealSequence(
  catalog: HealthCatalogItem[],
  findings: HealthFinding[],
): HealthCatalogItem[] {
  const hasEmptyStore = findings.some((f) => f.check === 'empty_store')
  return catalog.filter((c) => c.id !== 'empty_store' || hasEmptyStore)
}

export function checkupHeadline(phase: HealthPhase, issueCount: number): string {
  if (phase === 'idle') return '尚未体检'
  if (phase === 'scanning') return '正在核对行情仓'
  if (phase === 'repairing') return '正在修复'
  if (phase === 'healthy') return '行情仓可安全选股'
  return issueCount > 0 ? `发现 ${issueCount} 项问题` : '体检完成'
}

/** 副标题：扫描/修复期跟进度走，收口后是「通过 / 阻断」读数。 */
export function checkupSubtitle(input: {
  phase: HealthPhase
  progress: ProgressSnap | null
  report: MarketHealthReport | null
  idleCount: number
}): string {
  const { phase, progress, report } = input
  if (phase === 'idle') {
    return `选股前建议先扫一遍 · ${input.idleCount} 项待检 · 仓内+线路+依赖 · 只读`
  }
  if (phase === 'scanning') {
    if (progress?.message) return progress.message
    const pct = progress?.percent
    return pct != null ? `进度 ${Math.round(pct)}%` : '正在核对行情仓…'
  }
  if (phase === 'repairing') return '修好后自动复检'
  if (!report) return ''
  const trade = report.trade_date ? `交易日 ${report.trade_date}` : ''
  const checked = report.checked_at ? `上次 ${report.checked_at}` : ''
  if (!report.blocked) {
    const w = report.warn_count
    const head = w > 0 ? `通过（${w} 项提示）` : '全部通过'
    return [head, checked, trade].filter(Boolean).join(' · ')
  }
  const b = report.block_count
  const w = report.warn_count
  return [
    b > 0 ? `阻断 ${b}` : '',
    w > 0 ? `提示 ${w}` : '',
    b > 0 ? '选股将被拒绝' : '',
    trade,
  ]
    .filter(Boolean)
    .join(' · ')
}

/** 等 `/market/health` 时的秒级心跳：进度封顶 28%，只是别让人以为卡死。 */
export function scanHeartbeatSnap(waitLabel: string, waitedSec: number): ProgressSnap {
  return {
    percent: Math.min(28, 4 + waitedSec * 2),
    message: waitLabel,
    detail: waitedSec > 0 ? `已等待 ${waitedSec}s` : '',
    status: 'running',
  }
}

/** 扫描回放的单项进度；`done` 表示该项已揭晓。 */
export function revealProgressSnap(input: {
  item: HealthCatalogItem
  index: number
  total: number
  tradeDate: string
  done: boolean
}): ProgressSnap {
  const step = input.done ? input.index + 1 : input.index + 0.45
  return {
    percent: Math.round((step / input.total) * 100),
    message: `检查 ${input.index + 1}/${input.total} · ${input.item.label}`,
    detail: `${input.item.id} · trade_date ${input.tradeDate || '—'}`,
    status: 'running',
  }
}

/** instruments 阶段 total=0、percent=0：用等待秒数给一点呼吸感，避免「假死」。 */
export function softBootstrapPercent(percent: number, waitedSec: number): number {
  return percent > 0 ? percent : Math.min(8, 1 + Math.floor(waitedSec / 15))
}

export const INSTRUMENTS_STALL_SECONDS = 180

export const INSTRUMENTS_STALL_MESSAGE =
  '刷新证券列表超时（已等 3 分钟）。请检查网络或到数据源页探测 instruments，再重试。'

/** 证券列表阶段长时间零进展：前端主动放弃等待，避免永久卡死。 */
export function isInstrumentsStalled(snap: MarketBootstrapStatus, waitedSec: number): boolean {
  const pct = Number(snap.percent || 0)
  return (
    (snap.status === 'running' || snap.status === 'idle') &&
    (snap.phase === 'instruments' || !snap.phase) &&
    pct <= 0 &&
    waitedSec >= INSTRUMENTS_STALL_SECONDS
  )
}

export function bootstrapProgressDetail(snap: MarketBootstrapStatus, waitedSec: number): string {
  const pct = Number(snap.percent || 0)
  return [
    snap.total ? `${snap.done}/${snap.total}` : '',
    snap.code ? `当前 ${snap.code}` : '',
    snap.phase ? `阶段 ${snap.phase}` : '',
    waitedSec >= 5 && pct <= 0 ? `已等待 ${waitedSec}s` : '',
  ]
    .filter(Boolean)
    .join(' · ')
}

export function bootstrapDoneMessage(report: Record<string, unknown> | null | undefined): string {
  const r = report || {}
  const succeeded = String(r.succeeded ?? '—')
  const failed = String(r.failed ?? '—')
  const skipped = String(r.skipped ?? '—')
  return `修复完成：成功 ${succeeded} / 失败 ${failed} / 跳过 ${skipped}`
}

/** 单项「修复」按钮的一次性计划；只在 action 已确认可自动执行时调用。 */
export function planForFindingAction(input: {
  action: string
  check: string
  label?: string
}): HealthRepairPlan {
  const { action } = input
  return {
    actions: [action],
    primary_action: action,
    with_factors: action === 'sync_factors' || action === 'sync' || action === 'bootstrap',
    needs_bootstrap: action === 'bootstrap' || action === 'sync' || action === 'sync_factors',
    needs_turnover_repair: action === 'repair_turnover',
    labels: [input.label || '修复'],
    check_ids: [input.check],
  }
}
