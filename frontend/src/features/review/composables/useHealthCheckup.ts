/**
 * 数据体检状态机：idle → scanning → result|healthy → repairing → 复检。
 * 分数/门禁以后端报告为准；扫描回放仅 UI。
 */
import { computed, onUnmounted, ref, shallowRef } from 'vue'

import {
  getMarketBootstrap,
  getMarketHealth,
  repairMarketTurnover,
  type HealthCatalogItem,
  type HealthFinding,
  type HealthRepairPlan,
  type MarketHealthReport,
} from '@/shared/api/quant'
import { useMarketSyncGate } from '@/shared/composables/useMarketSyncGate'
import { toErrorMessage } from '@/shared/lib/errors'
import { ElMessage } from 'element-plus'

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
}

export type ProgressSnap = {
  percent: number
  message: string
  detail: string
  status: string
}

const FALLBACK_CATALOG: HealthCatalogItem[] = [
  { id: 'empty_store', label: '仓内是否有日 K', group: '仓体' },
  { id: 'staleness', label: '最新日是否落后', group: '时效' },
  { id: 'coverage', label: '当日覆盖率', group: '覆盖' },
  { id: 'turnover', label: '换手率完整度', group: '质量' },
  { id: 'zero_amount', label: '成交额异常比', group: '质量' },
  { id: 'factor_age', label: '复权因子时效', group: '因子' },
  { id: 'failed_codes', label: '同步失败标的', group: '覆盖' },
]

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
}

const ACTION_PRIORITY: Record<string, number> = {
  bootstrap: 0,
  sync_factors: 1,
  sync: 2,
  repair_turnover: 3,
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

function buildRepairPlanFromFindings(findings: HealthFinding[]): HealthRepairPlan {
  const byAction = new Map<string, NonNullable<HealthFinding['remediation']>>()
  const checkIds: string[] = []
  for (const item of findings) {
    if (item.severity === 'ok') continue
    const rem = item.remediation ?? FALLBACK_REMEDIATION[item.check] ?? null
    if (!rem) continue
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
    remediation: f.remediation ?? FALLBACK_REMEDIATION[f.check] ?? null,
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
  const rebuilt = buildRepairPlanFromFindings(findings)
  const repair_plan =
    raw.repair_plan &&
    Array.isArray(raw.repair_plan.actions) &&
    typeof raw.repair_plan.needs_bootstrap === 'boolean'
      ? raw.repair_plan
      : rebuilt
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

function sleep(ms: number): Promise<void> {
  return new Promise((resolve) => {
    window.setTimeout(resolve, ms)
  })
}

function prefersReducedMotion(): boolean {
  return window.matchMedia('(prefers-reduced-motion: reduce)').matches
}

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
): HealthCheckRow[] {
  const byId = findingMap(findings)
  const used = new Set<string>()
  const rows: HealthCheckRow[] = []

  for (const item of catalog) {
    const f = byId.get(item.id)
    // 空仓时其它检查未跑：未揭示前 pending，揭示后若无 finding 则跳过（不造假通过）
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
    })
  }
  return rows
}

export function useHealthCheckup() {
  const phase = ref<HealthPhase>('idle')
  const error = ref('')
  const report = shallowRef<MarketHealthReport | null>(null)
  const checkRows = ref<HealthCheckRow[]>([])
  const progress = ref<ProgressSnap | null>(null)
  const repairBusy = ref('')
  const scanToken = ref(0)

  const { setSyncing } = useMarketSyncGate()

  const score = computed(() => {
    const r = report.value
    if (!r) return null
    if (typeof r.score === 'number' && !Number.isNaN(r.score)) return r.score
    return computeSealScore(r.block_count ?? 0, r.warn_count ?? 0)
  })
  const grade = computed(() => {
    const r = report.value
    if (!r) return ''
    if (r.grade) return r.grade
    const s = score.value
    return s == null ? '' : computeSealGrade(s)
  })
  const blocked = computed(() => Boolean(report.value?.blocked))
  const reason = computed(() => report.value?.reason ?? '')
  const repairPlan = computed<HealthRepairPlan | null>(
    () => report.value?.repair_plan ?? null,
  )
  const canOneClickRepair = computed(() => {
    const plan = repairPlan.value
    if (!plan) return false
    return Boolean(plan.needs_bootstrap || plan.needs_turnover_repair)
  })
  const subtitle = computed(() => {
    if (phase.value === 'idle') return '尚未体检 · 选股前建议先扫一遍'
    if (phase.value === 'scanning') return '正在盖章核对行情仓…'
    if (phase.value === 'repairing') return '正在修复 · 修好后自动复检'
    if (!report.value) return ''
    if (!report.value.blocked) {
      const w = report.value.warn_count
      return w > 0
        ? `数据体检通过（${w} 项提示）· 可以安心选股`
        : '数据体检通过 · 可以安心选股'
    }
    const b = report.value.block_count
    const w = report.value.warn_count
    const parts = [
      b > 0 ? `${b} 项阻断` : '',
      w > 0 ? `${w} 项提示` : '',
      b > 0 ? '选股将被拒绝' : '',
    ].filter(Boolean)
    return parts.join(' · ')
  })

  const issueRows = computed(() =>
    checkRows.value.filter((r) => r.status === 'block' || r.status === 'warn'),
  )
  const okRows = computed(() => checkRows.value.filter((r) => r.status === 'ok'))
  const pendingRows = computed(() =>
    checkRows.value.filter((r) => r.status === 'pending' || r.status === 'running'),
  )
  /** 有待修项（含仅提示）：主 CTA 应出一键修复。 */
  const hasRepairableIssues = computed(
    () => canOneClickRepair.value && issueRows.value.some((r) => Boolean(r.remediation)),
  )

  function applyReportRows(next: MarketHealthReport, revealedAll = true): void {
    const catalog = next.catalog?.length ? next.catalog : FALLBACK_CATALOG
    const revealed = new Set(
      revealedAll
        ? [
            ...catalog.map((c) => c.id),
            ...next.findings.map((f) => f.check),
          ]
        : [],
    )
    // 空仓：只展示 empty_store
    if (next.findings.some((f) => f.check === 'empty_store') && next.findings.length === 1) {
      checkRows.value = rowsFromCatalog(
        catalog.filter((c) => c.id === 'empty_store'),
        next.findings,
        revealed,
        null,
      )
      return
    }
    checkRows.value = rowsFromCatalog(catalog, next.findings, revealed, null)
  }

  function settlePhase(next: MarketHealthReport): void {
    const normalized = normalizeHealthReport(next)
    report.value = normalized
    applyReportRows(normalized, true)
    // 有待修项 → result（露出一键修复）；全干净 → healthy
    const plan = normalized.repair_plan
    const repairable = Boolean(plan?.needs_bootstrap || plan?.needs_turnover_repair)
    phase.value = normalized.blocked || repairable ? 'result' : 'healthy'
  }

  async function revealScan(
    next: MarketHealthReport,
    token: number,
  ): Promise<boolean> {
    const catalog = next.catalog?.length ? next.catalog : FALLBACK_CATALOG
    const byId = findingMap(next.findings)
    const emptyOnly =
      next.findings.length === 1 && next.findings[0]?.check === 'empty_store'
    const sequence = emptyOnly
      ? catalog.filter((c) => c.id === 'empty_store')
      : catalog.filter((c) => c.id !== 'empty_store' || byId.has('empty_store'))

    const revealed = new Set<string>()
    const total = Math.max(1, sequence.length)

    if (prefersReducedMotion()) {
      progress.value = {
        percent: 100,
        message: '扫描完成',
        detail: `${total}/${total}`,
        status: 'done',
      }
      return token === scanToken.value
    }

    for (let i = 0; i < sequence.length; i += 1) {
      if (token !== scanToken.value) return false
      const item = sequence[i]!
      progress.value = {
        percent: Math.round(((i + 0.45) / total) * 100),
        message: `检查 ${i + 1}/${total} · ${item.label}`,
        detail: `${item.id} · trade_date ${next.trade_date || '—'}`,
        status: 'running',
      }
      checkRows.value = rowsFromCatalog(catalog, next.findings, revealed, item.id)
      await sleep(160)
      if (token !== scanToken.value) return false
      revealed.add(item.id)
      checkRows.value = rowsFromCatalog(catalog, next.findings, revealed, null)
      progress.value = {
        percent: Math.round(((i + 1) / total) * 100),
        message: `检查 ${i + 1}/${total} · ${item.label}`,
        detail: `${item.id} · trade_date ${next.trade_date || '—'}`,
        status: 'running',
      }
      await sleep(40)
    }
    return token === scanToken.value
  }

  async function scan(): Promise<void> {
    const token = scanToken.value + 1
    scanToken.value = token
    error.value = ''
    phase.value = 'scanning'
    progress.value = {
      percent: 4,
      message: '连接行情仓…',
      detail: '',
      status: 'running',
    }
    const catalog = report.value?.catalog?.length
      ? report.value.catalog
      : FALLBACK_CATALOG
    checkRows.value = rowsFromCatalog(catalog, [], new Set(), null)

    try {
      const next = normalizeHealthReport(await getMarketHealth({ include_ok: true }))
      if (token !== scanToken.value) return
      report.value = next
      const ok = await revealScan(next, token)
      if (!ok) return
      progress.value = {
        percent: 100,
        message: '扫描完成',
        detail: next.checked_at || '',
        status: 'done',
      }
      settlePhase(next)
      window.setTimeout(() => {
        if (phase.value !== 'scanning' && phase.value !== 'repairing') {
          progress.value = null
        }
      }, 1200)
    } catch (e: unknown) {
      if (token !== scanToken.value) return
      error.value = toErrorMessage(e, '体检失败')
      phase.value = report.value ? (report.value.blocked ? 'result' : 'healthy') : 'idle'
      progress.value = null
    }
  }

  function cancelScan(): void {
    if (phase.value !== 'scanning') return
    scanToken.value += 1
    progress.value = null
    if (report.value) settlePhase(report.value)
    else {
      phase.value = 'idle'
      checkRows.value = []
    }
  }

  async function runBootstrapRepair(opts: {
    with_factors?: boolean
    label?: string
  }): Promise<void> {
    const withFactors = Boolean(opts.with_factors)
    window.dispatchEvent(
      new CustomEvent('loci:open-bootstrap', {
        detail: { with_factors: withFactors, autoStart: true },
      }),
    )
    progress.value = {
      percent: 0,
      message: opts.label || '正在启动行情修复…',
      detail: '',
      status: 'running',
    }
    setSyncing(true, opts.label || '正在修复行情', 0)
    await sleep(200)

    for (let i = 0; i < 3600; i += 1) {
      const snap = await getMarketBootstrap()
      const pct = Number(snap.percent || 0)
      const detail = [
        snap.total ? `${snap.done}/${snap.total}` : '',
        snap.code ? `当前 ${snap.code}` : '',
        snap.phase ? `阶段 ${snap.phase}` : '',
      ]
        .filter(Boolean)
        .join(' · ')
      progress.value = {
        percent: pct,
        message: snap.message || opts.label || '同步中…',
        detail,
        status: snap.status,
      }
      if (snap.status === 'running') {
        setSyncing(true, snap.message || opts.label || '正在修复行情', pct)
        await sleep(1000)
        continue
      }
      setSyncing(false)
      if (snap.status === 'error') {
        throw new Error(snap.message || '修复失败')
      }
      if (snap.status === 'done') {
        const r = snap.report || {}
        ElMessage.success(
          `修复完成：成功 ${String(r.succeeded ?? '—')} / 失败 ${String(r.failed ?? '—')} / 跳过 ${String(r.skipped ?? '—')}`,
        )
      }
      return
    }
    setSyncing(false)
    throw new Error('修复超时，请到运维页查看同步状态')
  }

  async function runTurnoverRepair(): Promise<void> {
    progress.value = {
      percent: 30,
      message: '正在回填换手率…',
      detail: 'repair_turnover',
      status: 'running',
    }
    const res = await repairMarketTurnover()
    progress.value = {
      percent: 100,
      message: `换手回填完成：更新 ${res.updated} · 跳过 ${res.skipped}`,
      detail: `dates ${res.dates_scanned}`,
      status: 'done',
    }
    ElMessage.success(`换手回填：更新 ${res.updated} 行`)
  }

  async function executePlan(plan: HealthRepairPlan, label?: string): Promise<void> {
    if (plan.needs_bootstrap) {
      await runBootstrapRepair({
        with_factors: plan.with_factors,
        label: label || plan.labels.join(' · ') || '一键修复',
      })
    }
    if (plan.needs_turnover_repair) {
      await runTurnoverRepair()
    }
  }

  async function repairAll(checkIds?: string[]): Promise<void> {
    let plan = repairPlan.value
    if (checkIds?.length && report.value) {
      const selected = report.value.findings.filter(
        (f) => checkIds.includes(f.check) && f.severity !== 'ok',
      )
      plan = buildRepairPlanFromFindings(selected)
    }
    if (!plan || (!plan.needs_bootstrap && !plan.needs_turnover_repair)) {
      ElMessage.info('没有可自动修复的项')
      return
    }
    repairBusy.value = '__all__'
    error.value = ''
    phase.value = 'repairing'
    try {
      await executePlan(plan)
      ElMessage.info('正在复检…')
      await scan()
    } catch (e: unknown) {
      error.value = toErrorMessage(e, '修复失败')
      phase.value = 'result'
      window.setTimeout(() => {
        if (phase.value !== 'repairing') progress.value = null
      }, 2500)
    } finally {
      repairBusy.value = ''
    }
  }

  async function repairFinding(finding: {
    check: string
    remediation?: HealthFinding['remediation']
  }): Promise<void> {
    const action = finding.remediation?.action
    if (!action) {
      ElMessage.info('该项暂无自动修复，请到运维页手动处理')
      return
    }
    repairBusy.value = finding.check
    error.value = ''
    phase.value = 'repairing'
    try {
      const plan: HealthRepairPlan = {
        actions: [action],
        primary_action: action,
        with_factors: action === 'sync_factors' || action === 'sync' || action === 'bootstrap',
        needs_bootstrap: action === 'bootstrap' || action === 'sync' || action === 'sync_factors',
        needs_turnover_repair: action === 'repair_turnover',
        labels: [finding.remediation?.label || '修复'],
        check_ids: [finding.check],
      }
      await executePlan(plan, finding.remediation?.label)
      await scan()
    } catch (e: unknown) {
      error.value = toErrorMessage(e, '修复失败')
      phase.value = 'result'
      window.setTimeout(() => {
        if (phase.value !== 'repairing') progress.value = null
      }, 2500)
    } finally {
      repairBusy.value = ''
    }
  }

  onUnmounted(() => {
    scanToken.value += 1
  })

  return {
    phase,
    error,
    report,
    checkRows,
    progress,
    repairBusy,
    score,
    grade,
    blocked,
    reason,
    repairPlan,
    canOneClickRepair,
    hasRepairableIssues,
    subtitle,
    issueRows,
    okRows,
    pendingRows,
    scan,
    cancelScan,
    repairAll,
    repairFinding,
  }
}
