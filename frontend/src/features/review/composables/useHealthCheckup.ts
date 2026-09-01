/**
 * 数据体检状态机：idle → scanning → result|healthy → repairing → 复检。
 * 分数/门禁以后端报告为准；扫描回放仅 UI。纯函数（汇总/分级/文案/进度）在 `healthCheckupLogic.ts`。
 */
import { computed, onUnmounted, ref, shallowRef } from 'vue'

import {
  buildRepairPlanFromFindings,
  catalogForMode,
  idleSkeletonFromCatalog,
  isAutoRepairAction,
  normalizeHealthReport,
  rowsFromCatalog,
  type HealthCheckRow,
  type HealthPhase,
  type ProgressSnap,
} from '@/features/review/composables/healthCheckupModel'
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
} from '@/features/review/composables/healthCheckupLogic'
import {
  getMarketBootstrap,
  getMarketHealth,
  repairMarketTurnover,
  startMarketBootstrap,
  type HealthFinding,
  type HealthRepairPlan,
  type MarketHealthReport,
} from '@/shared/api/quant'
import { useMarketSyncGate } from '@/shared/composables/useMarketSyncGate'
import { toErrorMessage } from '@/shared/lib/errors'
import { ElMessage } from 'element-plus'

export type {
  CheckRowStatus,
  HealthCheckRow,
  HealthPhase,
  ProgressSnap,
} from '@/features/review/composables/healthCheckupModel'
export {
  computeSealGrade,
  computeSealScore,
  normalizeHealthReport,
} from '@/features/review/composables/healthCheckupModel'

function sleep(ms: number): Promise<void> {
  return new Promise((resolve) => {
    window.setTimeout(resolve, ms)
  })
}

function prefersReducedMotion(): boolean {
  return window.matchMedia('(prefers-reduced-motion: reduce)').matches
}

export function useHealthCheckup() {
  const phase = ref<HealthPhase>('idle')
  const error = ref('')
  const report = shallowRef<MarketHealthReport | null>(null)
  const checkRows = ref<HealthCheckRow[]>([])
  const progress = ref<ProgressSnap | null>(null)
  const repairBusy = ref('')
  const scanToken = ref(0)
  const repairToken = ref(0)
  let scanAbort: AbortController | null = null
  let scanHeartbeat: number | undefined
  let repairHeartbeat: number | undefined

  const { setSyncing } = useMarketSyncGate()

  function clearScanWaiters(): void {
    if (scanHeartbeat != null) {
      window.clearInterval(scanHeartbeat)
      scanHeartbeat = undefined
    }
    if (scanAbort) {
      scanAbort.abort()
      scanAbort = null
    }
  }

  function clearRepairWaiters(): void {
    if (repairHeartbeat != null) {
      window.clearInterval(repairHeartbeat)
      repairHeartbeat = undefined
    }
  }

  const score = computed(() => resolveSealScore(report.value))
  const grade = computed(() => resolveSealGrade(report.value, score.value))
  const blocked = computed(() => Boolean(report.value?.blocked))
  const reason = computed(() => report.value?.reason ?? '')
  const repairPlan = computed<HealthRepairPlan | null>(
    () => report.value?.repair_plan ?? null,
  )
  const canOneClickRepair = computed(() => planIsActionable(repairPlan.value))
  const issueRows = computed(() =>
    checkRows.value.filter((r) => r.status === 'block' || r.status === 'warn'),
  )
  const okRows = computed(() => checkRows.value.filter((r) => r.status === 'ok'))
  const pendingRows = computed(() =>
    checkRows.value.filter((r) => r.status === 'pending' || r.status === 'running'),
  )

  const idleSkeletonRows = computed(() => idleSkeletonFromCatalog(false))

  const subtitle = computed(() =>
    checkupSubtitle({
      phase: phase.value,
      progress: progress.value,
      report: report.value,
      idleCount: idleSkeletonRows.value.length,
    }),
  )

  const headline = computed(() => checkupHeadline(phase.value, issueRows.value.length))

  const hasRepairableIssues = computed(
    () => canOneClickRepair.value && issueRows.value.some((r) => r.autoFixable),
  )

  function settlePhase(next: MarketHealthReport): void {
    const normalized = normalizeHealthReport(next)
    report.value = normalized
    const catalog = effectiveCatalog(normalized)
    const revealed = new Set([
      ...catalog.map((c) => c.id),
      ...normalized.findings.map((f) => f.check),
    ])
    checkRows.value = rowsFromCatalog(catalog, normalized.findings, revealed, null)
    phase.value = phaseForReport(normalized)
  }

  async function revealScan(next: MarketHealthReport, token: number): Promise<boolean> {
    const catalog = effectiveCatalog(next)
    const sequence = revealSequence(catalog, next.findings)
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
      const snap = { item, index: i, total, tradeDate: next.trade_date }
      progress.value = revealProgressSnap({ ...snap, done: false })
      checkRows.value = rowsFromCatalog(catalog, next.findings, revealed, item.id)
      await sleep(160)
      if (token !== scanToken.value) return false
      revealed.add(item.id)
      checkRows.value = rowsFromCatalog(catalog, next.findings, revealed, null)
      progress.value = revealProgressSnap({ ...snap, done: true })
      await sleep(40)
    }
    return token === scanToken.value
  }

  async function scan(options?: { includeNetwork?: boolean }): Promise<void> {
    const includeNetwork = Boolean(options?.includeNetwork)
    const token = scanToken.value + 1
    scanToken.value = token
    clearScanWaiters()
    error.value = ''
    phase.value = 'scanning'
    const waitLabel = includeNetwork
      ? '深度扫描：连接行情仓与数据源…'
      : '连接行情仓…'
    progress.value = {
      percent: 4,
      message: waitLabel,
      detail: '',
      status: 'running',
    }
    const catalog = report.value?.catalog?.length
      ? report.value.catalog
      : catalogForMode(includeNetwork)
    checkRows.value = rowsFromCatalog(catalog, [], new Set(), null)

    const controller = new AbortController()
    scanAbort = controller
    const startedAt = Date.now()
    scanHeartbeat = window.setInterval(() => {
      if (token !== scanToken.value) return
      const waited = Math.max(0, Math.floor((Date.now() - startedAt) / 1000))
      progress.value = scanHeartbeatSnap(waitLabel, waited)
    }, 1000)

    try {
      const next = normalizeHealthReport(
        await getMarketHealth({
          include_ok: true,
          include_network: includeNetwork,
          signal: controller.signal,
        }),
      )
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
      if (controller.signal.aborted) {
        progress.value = null
        return
      }
      error.value = toErrorMessage(e, '体检失败')
      phase.value = report.value ? (report.value.blocked ? 'result' : 'healthy') : 'idle'
      progress.value = null
    } finally {
      if (scanHeartbeat != null) {
        window.clearInterval(scanHeartbeat)
        scanHeartbeat = undefined
      }
      if (scanAbort === controller) scanAbort = null
    }
  }

  function cancelScan(): void {
    if (phase.value !== 'scanning') return
    scanToken.value += 1
    clearScanWaiters()
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
    token: number
  }): Promise<void> {
    const withFactors = Boolean(opts.with_factors)
    // 体检页自有进度条；勿再打开不可关闭的 bootstrap 模态框，否则网络挂起时整页像卡死。
    progress.value = {
      percent: 0,
      message: opts.label || '正在启动行情修复…',
      detail: '',
      status: 'running',
    }
    setSyncing(true, opts.label || '正在修复行情', 0)

    const started = await startMarketBootstrap({ with_factors: withFactors })
    if (opts.token !== repairToken.value) {
      setSyncing(false)
      return
    }
    if (started.status === 'error') {
      setSyncing(false)
      throw new Error(started.message || '启动行情修复失败')
    }

    const startedAt = Date.now()
    clearRepairWaiters()
    repairHeartbeat = window.setInterval(() => {
      if (opts.token !== repairToken.value) return
      if (phase.value !== 'repairing') return
      const cur = progress.value
      if (!cur || cur.status === 'done' || cur.status === 'error') return
      const waited = Math.max(0, Math.floor((Date.now() - startedAt) / 1000))
      if (waited < 2) return
      const softPct = softBootstrapPercent(Number(cur.percent || 0), waited)
      progress.value = {
        ...cur,
        percent: softPct,
        detail: [cur.detail, `已等待 ${waited}s`].filter(Boolean).join(' · '),
      }
      setSyncing(true, cur.message || opts.label || '正在修复行情', softPct)
    }, 1000)

    try {
      for (let i = 0; i < 3600; i += 1) {
        if (opts.token !== repairToken.value) {
          setSyncing(false)
          return
        }
        const snap = i === 0 ? started : await getMarketBootstrap()
        if (opts.token !== repairToken.value) {
          setSyncing(false)
          return
        }
        const pct = Number(snap.percent || 0)
        const waited = Math.max(0, Math.floor((Date.now() - startedAt) / 1000))
        if (isInstrumentsStalled(snap, waited)) {
          setSyncing(false)
          throw new Error(INSTRUMENTS_STALL_MESSAGE)
        }
        progress.value = {
          percent: softBootstrapPercent(pct, waited),
          message: snap.message || opts.label || '同步中…',
          detail: bootstrapProgressDetail(snap, waited),
          status: snap.status,
        }
        if (snap.status === 'running' || snap.status === 'idle') {
          // idle：刚提交尚未进入 running；继续等，不要当成功
          setSyncing(true, snap.message || opts.label || '正在修复行情', pct)
          await sleep(1000)
          continue
        }
        setSyncing(false)
        if (snap.status === 'error') {
          throw new Error(snap.message || '修复失败')
        }
        if (snap.status === 'done') {
          ElMessage.success(bootstrapDoneMessage(snap.report))
          return
        }
        throw new Error(`修复状态异常：${snap.status || 'unknown'}`)
      }
      setSyncing(false)
      throw new Error('修复超时，请到运维页查看同步状态')
    } finally {
      clearRepairWaiters()
    }
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

  async function executePlan(
    plan: HealthRepairPlan,
    label: string | undefined,
    token: number,
  ): Promise<void> {
    if (plan.needs_bootstrap) {
      await runBootstrapRepair({
        with_factors: plan.with_factors,
        label: label || plan.labels.join(' · ') || '一键修复',
        token,
      })
      if (token !== repairToken.value) return
    }
    if (plan.needs_turnover_repair) {
      await runTurnoverRepair()
    }
  }

  /** 修复失败的共同收尾：留在 result 并延迟收掉进度条。 */
  function settleRepairFailure(e: unknown): void {
    error.value = toErrorMessage(e, '修复失败')
    phase.value = 'result'
    window.setTimeout(() => {
      if (phase.value !== 'repairing') progress.value = null
    }, 2500)
  }

  async function repairAll(checkIds?: string[]): Promise<void> {
    let plan = repairPlan.value
    if (checkIds?.length && report.value) {
      const selected = report.value.findings.filter(
        (f) => checkIds.includes(f.check) && f.severity !== 'ok',
      )
      plan = buildRepairPlanFromFindings(selected)
    }
    if (!plan || !planIsActionable(plan)) {
      ElMessage.info('没有可自动修复的项')
      return
    }
    const token = repairToken.value + 1
    repairToken.value = token
    repairBusy.value = '__all__'
    error.value = ''
    phase.value = 'repairing'
    try {
      await executePlan(plan, undefined, token)
      if (token !== repairToken.value) return
      ElMessage.info('正在复检…')
      await scan()
    } catch (e: unknown) {
      if (token !== repairToken.value) return
      settleRepairFailure(e)
    } finally {
      if (token === repairToken.value) {
        repairBusy.value = ''
        clearRepairWaiters()
      }
    }
  }

  async function repairFinding(finding: {
    check: string
    remediation?: HealthFinding['remediation']
    autoFixable?: boolean
  }): Promise<void> {
    const action = finding.remediation?.action
    if (!action || finding.autoFixable === false) {
      ElMessage.info(finding.remediation?.hint || '该项需人工处理，请到运维页按提示操作')
      return
    }
    if (!isAutoRepairAction(action)) {
      ElMessage.info(finding.remediation?.hint || '该项暂无自动修复，请到运维页手动处理')
      return
    }
    const token = repairToken.value + 1
    repairToken.value = token
    repairBusy.value = finding.check
    error.value = ''
    phase.value = 'repairing'
    try {
      const plan = planForFindingAction({
        action,
        check: finding.check,
        label: finding.remediation?.label,
      })
      await executePlan(plan, finding.remediation?.label, token)
      if (token !== repairToken.value) return
      ElMessage.info('正在复检…')
      await scan()
    } catch (e: unknown) {
      if (token !== repairToken.value) return
      settleRepairFailure(e)
    } finally {
      if (token === repairToken.value) {
        repairBusy.value = ''
        clearRepairWaiters()
      }
    }
  }

  function cancelRepair(): void {
    if (phase.value !== 'repairing') return
    repairToken.value += 1
    clearRepairWaiters()
    repairBusy.value = ''
    setSyncing(false)
    progress.value = null
    if (report.value) settlePhase(report.value)
    else phase.value = 'result'
    ElMessage.info('已停止等待修复进度（后台同步若已启动仍可能继续）')
  }

  onUnmounted(() => {
    scanToken.value += 1
    repairToken.value += 1
    clearScanWaiters()
    clearRepairWaiters()
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
    headline,
    subtitle,
    idleSkeletonRows,
    issueRows,
    okRows,
    pendingRows,
    scan,
    cancelScan,
    cancelRepair,
    repairAll,
    repairFinding,
  }
}
