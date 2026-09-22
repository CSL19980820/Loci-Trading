
import { toast } from 'vue-sonner'
/**
 * 研究回测的提交与轮询状态机。
 *
 * 这块必须整块拆走：提交 → 轮询 job → 完成后重读 run 与工作流 → 回放比对，全程靠
 * 两个序号防串（readSequence 挡详情竞态，pollSequence 挡「上一次提交的轮询」把新
 * 任务的状态盖回去），并且要跟 KeepAlive 的激活/离开挂钩——离开这屏必须停表，
 * 回来时若任务还没终态才续上。这些不变量散在页面里没人看得住。
 *
 * 面板那边留下的是展示：指标分组、战法下拉文案、证据与 artifact 的摆法。
 */
import { computed, onActivated, onDeactivated, onUnmounted, ref, watch } from 'vue'


import { getStrategies } from '@/shared/api/quant'
import {
  getResearchBacktestJob,
  getResearchBacktestRun,
  getResearchWorkflow,
  listResearchBacktestRuns,
  replayResearchBacktestRun,
  submitResearchBacktestJob,
} from '@/shared/api/quant_research'
import type { StrategyInfo } from '@/shared/types/quant'
import type { BacktestExecutionConfig, StrategyBacktestTemplate } from '@/shared/types/backtest-config'
import type {
  ResearchBacktestJob,
  ResearchBacktestPublicationResult,
  ResearchBacktestRun,
  ResearchReplayResult,
  ResearchWorkflow,
} from '@/shared/types/quant-research'

import { validateResearchBacktestForm } from './researchBacktestForm'
import { summarizeReplayComparison } from './researchReplayComparison'

export function useResearchBacktestJob() {
  const runs = ref<ResearchBacktestRun[]>([])
  const strategies = ref<StrategyInfo[]>([])
  const selectedRun = ref<ResearchBacktestRun | null>(null)
  const workflow = ref<ResearchWorkflow | null>(null)
  const loading = ref(false)
  const submitting = ref(false)
  const replaying = ref(false)
  const error = ref('')
  const activeJob = ref<ResearchBacktestJob | null>(null)
  const pollingFailed = ref(false)
  const replayResult = ref<ResearchReplayResult | null>(null)
  const readSequence = ref(0)
  let pollTimer: ReturnType<typeof setTimeout> | undefined
  let pollSequence = 0
  const range = ref<string[]>([])
  const trainRange = ref<string[]>([])
  const oosRange = ref<string[]>([])
  const form = ref({
    strategy: '',
    holdDays: 3,
    initialCapital: 200000,
    maxPositions: 2,
    historicalUniverseId: '',
    strictPit: false,
  })

  const selected = computed(() => strategies.value.find((item) => item.slug === form.value.strategy.trim()))
  const template = computed(() => (selected.value?.backtest_config || {}) as StrategyBacktestTemplate)
  watch(
    () => selected.value?.slug,
    () => {
      const cfg = template.value
      if (typeof cfg.hold_days === 'number') form.value.holdDays = cfg.hold_days
      if (typeof cfg.initial_capital === 'number') form.value.initialCapital = cfg.initial_capital
      if (typeof cfg.max_positions === 'number') form.value.maxPositions = cfg.max_positions
      if (cfg.start && cfg.end) range.value = [cfg.start, cfg.end]
      if (cfg.split) {
        trainRange.value = [cfg.split.train_start, cfg.split.train_end]
        oosRange.value = [cfg.split.oos_start, cfg.split.oos_end]
      }
    },
    { immediate: true },
  )

  function updateRun(next: ResearchBacktestRun): void {
    const index = runs.value.findIndex((item) => item.run_id === next.run_id)
    if (index < 0) runs.value = [next, ...runs.value]
    else runs.value.splice(index, 1, next)
  }

  function stopPolling(): void {
    pollSequence += 1
    if (pollTimer) clearTimeout(pollTimer)
    pollTimer = undefined
  }

  function schedulePoll(jobId: string, sequence: number): void {
    pollTimer = setTimeout(() => {
      void pollJob(jobId, sequence)
    }, 1500)
  }

  function retryPolling(): void {
    const jobId = activeJob.value?.id
    if (!jobId) return
    stopPolling()
    const sequence = pollSequence
    error.value = ''
    pollingFailed.value = false
    void pollJob(jobId, sequence)
  }

  async function load(): Promise<void> {
    loading.value = true
    error.value = ''
    try {
      // 战法目录问不到只是下拉变空（还能手填），不该把整块判成加载失败
      const [response, catalog] = await Promise.all([
        listResearchBacktestRuns(),
        getStrategies().catch(() => [] as StrategyInfo[]),
      ])
      runs.value = response.items
      if (catalog.length) strategies.value = catalog
    } catch (caught: unknown) {
      error.value = caught instanceof Error ? caught.message : '读取研究回测失败'
    } finally {
      loading.value = false
    }
  }

  async function selectRun(runId: string): Promise<void> {
    const sequence = ++readSequence.value
    loading.value = true
    error.value = ''
    replayResult.value = null
    try {
      const [run, nextWorkflow] = await Promise.all([
        getResearchBacktestRun(runId),
        getResearchWorkflow(runId),
      ])
      if (sequence !== readSequence.value) return
      selectedRun.value = run
      workflow.value = nextWorkflow
      updateRun(run)
    } catch (caught: unknown) {
      if (sequence === readSequence.value) {
        error.value = caught instanceof Error ? caught.message : '读取研究回测详情失败'
      }
    } finally {
      if (sequence === readSequence.value) loading.value = false
    }
  }

  async function submit(): Promise<void> {
    const validationError = validateResearchBacktestForm({
      strategy: form.value.strategy,
      range: range.value,
      trainRange: trainRange.value,
      oosRange: oosRange.value,
      historicalUniverseId: form.value.historicalUniverseId,
      strictPit: form.value.strictPit,
    })
    if (validationError) {
      error.value = validationError
      return
    }
    const hasTrain = trainRange.value.length === 2
    const hasOos = oosRange.value.length === 2
    stopPolling()
    const sequence = pollSequence
    submitting.value = true
    error.value = ''
    activeJob.value = null
    pollingFailed.value = false
    try {
      const cfg = template.value
      const backtestConfig: BacktestExecutionConfig = { hold_days: form.value.holdDays }
      const executionKeys = [
        'stop_loss_pct', 'take_profit_pct', 'commission_bps', 'stamp_duty_bps', 'slippage_bps',
        'allow_limit_up_entry', 'benchmark', 'strict_limit_prices', 'economic_returns', 'signal_dataset',
      ] as const
      for (const key of executionKeys) {
        if (cfg[key] !== undefined) Object.assign(backtestConfig, { [key]: cfg[key] })
      }
      if (cfg.valuation_end !== undefined) backtestConfig.valuation_end = range.value[1]
      const result = await submitResearchBacktestJob({
        strategy: form.value.strategy.trim(),
        start: range.value[0],
        end: range.value[1],
        backtest_config: backtestConfig,
        initial_capital: form.value.initialCapital,
        max_positions: form.value.maxPositions,
        ...(cfg.account_model !== undefined ? { account_model: cfg.account_model } : {}),
        ...(cfg.lot_size !== undefined ? { lot_size: cfg.lot_size } : {}),
        split: hasTrain && hasOos ? {
          train_start: trainRange.value[0], train_end: trainRange.value[1],
          oos_start: oosRange.value[0], oos_end: oosRange.value[1],
        } : undefined,
        historical_universe_id: form.value.historicalUniverseId.trim() || undefined,
        strict_pit: form.value.strictPit,
      })
      if (sequence !== pollSequence) return
      activeJob.value = result.job
      toast.success('研究回测任务已提交')
      void pollJob(result.job.id, sequence)
    } catch (caught: unknown) {
      if (sequence === pollSequence) {
        error.value = caught instanceof Error ? caught.message : '提交研究回测失败'
      }
    } finally {
      if (sequence === pollSequence) submitting.value = false
    }
  }

  async function pollJob(jobId: string, sequence: number): Promise<void> {
    try {
      const response = await getResearchBacktestJob(jobId)
      if (sequence !== pollSequence || activeJob.value?.id !== jobId) return
      pollingFailed.value = false
      activeJob.value = response.job
      if (response.job.status === 'completed' && response.job.run_id) {
        await load()
        if (sequence !== pollSequence || activeJob.value?.id !== jobId) return
        await selectRun(response.job.run_id)
        return
      }
      if (response.job.status === 'completed') {
        error.value = '任务已完成，但后端未返回 run id'
        return
      }
      if (response.job.status === 'failed') {
        error.value = response.job.error || '研究回测任务失败'
        return
      }
      schedulePoll(jobId, sequence)
    } catch (caught: unknown) {
      if (sequence === pollSequence && activeJob.value?.id === jobId) {
        error.value = caught instanceof Error ? caught.message : '读取研究回测任务状态失败'
        pollingFailed.value = true
      }
    }
  }

  async function replay(): Promise<void> {
    if (!selectedRun.value) return
    replaying.value = true
    error.value = ''
    try {
      const result = await replayResearchBacktestRun(selectedRun.value.run_id)
      selectedRun.value = result.run_card
      workflow.value = result.workflow
      updateRun(result.run_card)
      await selectRun(result.run_card.run_id)
      replayResult.value = result
      const summary = summarizeReplayComparison(result.comparison)
      if (summary.matches) toast.success(summary.message)
      else toast.warning(summary.message)
    } catch (caught: unknown) {
      error.value = caught instanceof Error ? caught.message : '回放失败'
    } finally {
      replaying.value = false
    }
  }

  function applyPublication(result: ResearchBacktestPublicationResult): void {
    selectedRun.value = result.run_card
    workflow.value = result.workflow
    replayResult.value = null
    updateRun(result.run_card)
  }

  function setHistoricalUniverse(universeId: string): void {
    form.value.historicalUniverseId = universeId
  }

  onDeactivated(stopPolling)
  onActivated(() => {
    const status = activeJob.value?.status
    if (status && status !== 'completed' && status !== 'failed') retryPolling()
  })
  onUnmounted(stopPolling)

  return {
    runs,
    strategies,
    selectedRun,
    workflow,
    loading,
    submitting,
    replaying,
    error,
    activeJob,
    pollingFailed,
    replayResult,
    range,
    trainRange,
    oosRange,
    form,
    load,
    selectRun,
    submit,
    replay,
    retryPolling,
    applyPublication,
    setHistoricalUniverse,
  }
}
