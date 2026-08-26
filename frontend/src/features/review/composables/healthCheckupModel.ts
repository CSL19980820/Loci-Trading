/**
 * 数据体检：目录、分数回退、报告归一与清单行映射（无 Vue 状态）。
 */
import type {
  HealthCatalogItem,
  HealthFinding,
  HealthRepairPlan,
  MarketHealthReport,
} from '@/shared/api/quant'

export type HealthPhase = 'idle' | 'scanning' | 'result' | 'repairing' | 'healthy'

export type CheckRowStatus = 'pending' | 'running' | 'ok' | 'warn' | 'block'

export type HealthCheckRow = {
  id: string
  label: string
  group: string
  status: CheckRowStatus
  message: string
  hint: string
  remediation: HealthFinding['remediation']
  /** 真正能由体检页自动执行的修复（同步/回填），不是「去运维看看」 */
  autoFixable: boolean
  /** 人工处理时跳转的前端路由 */
  manualRoute: string | null
}

export type ProgressSnap = {
  percent: number
  message: string
  detail: string
  status: string
}

export const FALLBACK_CATALOG_CORE: HealthCatalogItem[] = [
  { id: 'empty_store', label: '仓内是否有日 K', group: '仓体' },
  { id: 'staleness', label: '最新日是否落后', group: '时效' },
  { id: 'coverage', label: '当日覆盖率', group: '覆盖' },
  { id: 'turnover', label: '换手率完整度', group: '质量' },
  { id: 'zero_amount', label: '成交额异常比', group: '质量' },
  { id: 'factor_age', label: '复权因子时效', group: '因子' },
  { id: 'failed_codes', label: '同步失败标的', group: '覆盖' },
]

export const FALLBACK_CATALOG: HealthCatalogItem[] = [
  ...FALLBACK_CATALOG_CORE,
  { id: 'lane_required_not_empty', label: '必需线路未关空', group: '线路' },
  { id: 'lane_hist_daily_alive', label: '日 K 源连通', group: '线路' },
  { id: 'lane_spot_alive', label: '现价源连通', group: '线路' },
  { id: 'lane_adjust_factor_alive', label: '复权因子源连通', group: '线路' },
  { id: 'lane_instruments_alive', label: '证券列表源连通', group: '线路' },
  { id: 'session_backfill', label: '是否需要补数', group: '时效' },
  { id: 'capabilities_runtime', label: '运行时依赖', group: '运行时' },
  { id: 'schema_version', label: '库结构版本', group: '存储' },
  { id: 'db_size_warn', label: '行情库体积', group: '存储' },
  { id: 'ohlc_reject_rate', label: '坏 OHLC 拒绝比', group: '回执' },
  { id: 'source_evidence_gap', label: '来源证据缺口', group: '回执' },
  { id: 'race_fallback_rate', label: '竞速回退占比', group: '回执' },
  { id: 'job_sync_stale', label: '同步 Job 时效', group: '运维' },
]

export const CORE_CHECK_IDS = new Set(FALLBACK_CATALOG_CORE.map((row) => row.id))

const NETWORK_CHECK_IDS = new Set([
  'lane_hist_daily_alive',
  'lane_spot_alive',
  'lane_adjust_factor_alive',
  'lane_instruments_alive',
])

export function catalogForMode(includeNetwork: boolean): HealthCatalogItem[] {
  if (includeNetwork) return [...FALLBACK_CATALOG]
  return FALLBACK_CATALOG.filter((row) => !NETWORK_CHECK_IDS.has(row.id))
}

const FALLBACK_REMEDIATION: Record<string, NonNullable<HealthFinding['remediation']>> = {
  empty_store: { action: 'bootstrap', label: '初始化行情', hint: '空库需先全量或补齐历史日 K' },
  staleness: { action: 'sync', label: '同步行情', hint: '库内最新日落后，增量同步即可' },
  coverage: { action: 'sync', label: '补齐当日覆盖', hint: '覆盖率不足通常是同步未跑完' },
  turnover: {
    action: 'repair_turnover',
    label: '回填换手率',
    hint: '用流通股本回填缺换手，不重拉 OHLC',
  },
  zero_amount: { action: 'sync', label: '重拉成交额', hint: '成交额异常多为源数据未就绪' },
  factor_age: {
    action: 'sync_factors',
    label: '刷新复权因子',
    hint: '复权因子过旧会导致前复权价漂移',
  },
  failed_codes: { action: 'sync', label: '重试失败标的', hint: '对失败代码再跑一轮同步' },
  lane_required_not_empty: {
    action: 'open_lanes',
    label: '检查数据源',
    hint: '必需线路被关空，到运维「数据源」重新启用',
  },
  lane_hist_daily_alive: {
    action: 'open_lanes',
    label: '检查日 K 连通',
    hint: '日 K 源全部探测失败',
  },
  lane_spot_alive: {
    action: 'open_lanes',
    label: '检查现价连通',
    hint: '现价源探测失败',
  },
  lane_adjust_factor_alive: {
    action: 'open_lanes',
    label: '检查复权源连通',
    hint: '复权因子源探测失败',
  },
  lane_instruments_alive: {
    action: 'open_lanes',
    label: '检查证券列表连通',
    hint: '证券列表源探测失败',
  },
  session_backfill: {
    action: 'bootstrap',
    label: '补齐行情',
    hint: '库内尖端落后于应覆盖交易日',
  },
  capabilities_runtime: {
    action: 'setup',
    label: '安装依赖',
    hint: '运行 setup.ps1 或 pip 安装缺失包',
  },
  schema_version: {
    action: 'restart',
    label: '重启应用',
    hint: '启动时会自动迁移 market schema',
  },
  db_size_warn: {
    action: 'cleanup',
    label: '关注磁盘',
    hint: '行情库体积偏大',
  },
  ohlc_reject_rate: {
    action: 'sync',
    label: '换源重同步',
    hint: '近次回执坏 OHLC 偏高',
  },
  source_evidence_gap: {
    action: 'sync',
    label: '全量重同步',
    hint: '大量日 K 无回执，严格研究不可用',
  },
  race_fallback_rate: {
    action: 'open_lanes',
    label: '检查主源',
    hint: '竞速常落到后备源',
  },
  job_sync_stale: {
    action: 'open_jobs',
    label: '去工坊手跑 Job',
    hint: '日终/盘中同步过久未跑或失败；勿一键全量 bootstrap',
  },
}

const ACTION_PRIORITY: Record<string, number> = {
  bootstrap: 0,
  sync_factors: 1,
  sync: 2,
  repair_turnover: 3,
}

/** 体检页可自动执行的 action；其余只给人工指引。 */
export const AUTO_REPAIR_ACTIONS = new Set([
  'bootstrap',
  'sync',
  'sync_factors',
  'repair_turnover',
])

export function isAutoRepairAction(action: string | null | undefined): boolean {
  return Boolean(action && AUTO_REPAIR_ACTIONS.has(action))
}

function manualRouteFor(action: string | null | undefined): string | null {
  if (!action || isAutoRepairAction(action)) return null
  if (action === 'open_lanes') return '/quant?tab=sources'
  if (action === 'open_jobs') return '/quant?tab=jobs'
  if (action === 'setup' || action === 'restart' || action === 'cleanup') return '/ops'
  return '/ops'
}

export function computeSealScore(blockCount: number, warnCount: number): number {
  return Math.max(0, Math.min(100, 100 - 25 * blockCount - 8 * warnCount))
}

export function computeSealGrade(score: number): string {
  if (score >= 90) return '优'
  if (score >= 70) return '良'
  if (score >= 50) return '中'
  return '差'
}

export function buildRepairPlanFromFindings(findings: HealthFinding[]): HealthRepairPlan {
  const byAction = new Map<string, NonNullable<HealthFinding['remediation']>>()
  const checkIds: string[] = []
  for (const item of findings) {
    if (item.severity === 'ok') continue
    const rem = item.remediation ?? FALLBACK_REMEDIATION[item.check] ?? null
    if (!rem || !isAutoRepairAction(rem.action)) continue
    checkIds.push(item.check)
    if (!byAction.has(rem.action)) byAction.set(rem.action, rem)
  }
  const ordered = [...byAction.values()].sort(
    (a, b) => (ACTION_PRIORITY[a.action] ?? 99) - (ACTION_PRIORITY[b.action] ?? 99),
  )
  const actions = ordered.map((r) => r.action)
  return {
    actions,
    primary_action: actions[0] ?? null,
    with_factors: actions.some((a) => a === 'sync_factors' || a === 'bootstrap' || a === 'sync'),
    needs_bootstrap: actions.some(
      (a) => a === 'bootstrap' || a === 'sync' || a === 'sync_factors',
    ),
    needs_turnover_repair: actions.includes('repair_turnover'),
    labels: ordered.map((r) => r.label),
    check_ids: checkIds,
  }
}

/** 兼容旧后端：补齐 score / grade / repair_plan / remediation。 */
export function normalizeHealthReport(raw: MarketHealthReport): MarketHealthReport {
  const findings = (raw.findings ?? []).map((f) => ({
    ...f,
    // 已知项以本地 FALLBACK 为准，避免旧后端把 Job 时效等标成 sync 误触发 bootstrap
    remediation: FALLBACK_REMEDIATION[f.check] ?? f.remediation ?? null,
  }))
  const block_count =
    typeof raw.block_count === 'number'
      ? raw.block_count
      : findings.filter((f) => f.severity === 'block').length
  const warn_count =
    typeof raw.warn_count === 'number'
      ? raw.warn_count
      : findings.filter((f) => f.severity === 'warn').length
  const score =
    typeof raw.score === 'number' && !Number.isNaN(raw.score)
      ? raw.score
      : computeSealScore(block_count, warn_count)
  const grade = raw.grade || computeSealGrade(score)
  // 一键修复只认 AUTO_REPAIR_ACTIONS；后端若把 Job 时效等人工项标成 sync，
  // 会误触发全量 bootstrap 卡死在 instruments。始终按 findings 重建可执行计划。
  const repair_plan = buildRepairPlanFromFindings(findings)
  return {
    ...raw,
    findings,
    block_count,
    warn_count,
    score,
    grade,
    repair_plan,
    catalog: raw.catalog?.length ? raw.catalog : [...FALLBACK_CATALOG],
  }
}

function findingMap(findings: HealthFinding[]): Map<string, HealthFinding> {
  const map = new Map<string, HealthFinding>()
  for (const f of findings) map.set(f.check, f)
  return map
}

export function rowsFromCatalog(
  catalog: HealthCatalogItem[],
  findings: HealthFinding[],
  revealed: Set<string>,
  runningId: string | null,
): HealthCheckRow[] {
  const byId = findingMap(findings)
  const used = new Set<string>()
  const rows: HealthCheckRow[] = []

  for (const item of catalog) {
    const f = byId.get(item.id)
    if (!f && revealed.has(item.id) && item.id !== 'empty_store') {
      if (byId.has('empty_store')) continue
    }
    let status: CheckRowStatus = 'pending'
    if (runningId === item.id) status = 'running'
    else if (revealed.has(item.id) && f) {
      status = f.severity === 'block' ? 'block' : f.severity === 'warn' ? 'warn' : 'ok'
    } else if (revealed.has(item.id) && !f) {
      status = 'ok'
    }
    used.add(item.id)
    const rem = f?.remediation ?? FALLBACK_REMEDIATION[item.id] ?? null
    rows.push({
      id: item.id,
      label: item.label,
      group: item.group,
      status,
      message: f?.message ?? '',
      hint: rem?.hint ?? '',
      remediation: rem,
      autoFixable: isAutoRepairAction(rem?.action),
      manualRoute: manualRouteFor(rem?.action),
    })
  }

  for (const f of findings) {
    if (used.has(f.check)) continue
    if (!revealed.has(f.check) && runningId !== f.check) continue
    const rem = f.remediation ?? FALLBACK_REMEDIATION[f.check] ?? null
    rows.push({
      id: f.check,
      label: f.check,
      group: '其它',
      status:
        runningId === f.check
          ? 'running'
          : f.severity === 'block'
            ? 'block'
            : f.severity === 'warn'
              ? 'warn'
              : 'ok',
      message: f.message,
      hint: rem?.hint ?? '',
      remediation: rem,
      autoFixable: isAutoRepairAction(rem?.action),
      manualRoute: manualRouteFor(rem?.action),
    })
  }
  return rows
}

export function idleSkeletonFromCatalog(includeNetwork = false): HealthCheckRow[] {
  return catalogForMode(includeNetwork)
    .filter((c) => c.id !== 'empty_store')
    .map((c) => ({
      id: c.id,
      label: c.label,
      group: c.group,
      status: 'pending' as const,
      message: '',
      hint: '',
      remediation: null,
      autoFixable: false,
      manualRoute: null,
    }))
}
