/** 策略：选股 / 回测 / 分析 / 转换 / 档案 / 审计 / 洞察。 */
import { abortableSleep, quantRequest, query, toAbortError } from '@/shared/api/quant_client'
import { getJobRuns } from '@/shared/api/quant_ops'
import type {
  AnalysisStarted,
  BacktestResult,
  HorizonBacktestResult,
  JobRun,
  ScreenSkillDetail,
  ScreenSkillCatalog,
  ScreenSkillGenerateRequest,
  ScreenSkillGenerateResponse,
  ScreenHistory,
  ScreenSkillPreviewResponse,
  ScreenResult,
  ScreenTodayResult,
  EntryTiming,
  StrategyInfo,
  StrategyJob,
  StrategyJobConfig,
  ScreenSkillUpsertPayload,
  ScreenSkillPreviewRun,
  UniverseSpec,
} from '@/shared/types/quant'
import type { StrategyVersion, StrategyVersionRollbackResult } from '@/shared/types/quant'

export function getStrategies(): Promise<StrategyInfo[]> {
  return quantRequest<StrategyInfo[]>('/strategies')
}

export function getStrategyVersions(slug: string): Promise<StrategyVersion[]> {
  return quantRequest<StrategyVersion[]>(`/strategies/${encodeURIComponent(slug)}/versions`)
}

export function rollbackStrategyVersion(slug: string, version: string): Promise<StrategyVersionRollbackResult> {
  return quantRequest<StrategyVersionRollbackResult>(`/strategies/${encodeURIComponent(slug)}/rollback`, {
    method: 'POST',
    body: JSON.stringify({ version }),
  })
}

export function deleteStrategyVersion(slug: string, version: string): Promise<{ removed: boolean }> {
  return quantRequest(`/strategies/${encodeURIComponent(slug)}/versions/${encodeURIComponent(version)}`, {
    method: 'DELETE',
  })
}

export function getScreenSkills(): Promise<StrategyInfo[]> {
  return quantRequest<StrategyInfo[]>('/screen-skills')
}

export function getScreenSkillCatalog(): Promise<ScreenSkillCatalog> {
  return quantRequest<ScreenSkillCatalog>('/screen-skills/catalog')
}

export function getScreenSkill(slug: string): Promise<ScreenSkillDetail> {
  return quantRequest<ScreenSkillDetail>(`/screen-skills/${encodeURIComponent(slug)}`)
}

export function previewScreenSkill(payload: ScreenSkillUpsertPayload & {
  run?: ScreenSkillPreviewRun
}): Promise<ScreenSkillPreviewResponse> {
  return quantRequest<ScreenSkillPreviewResponse>('/screen-skills/preview', {
    method: 'POST',
    body: JSON.stringify(payload),
  })
}

export function createScreenSkill(payload: ScreenSkillUpsertPayload): Promise<ScreenSkillDetail> {
  return quantRequest<ScreenSkillDetail>('/screen-skills', {
    method: 'POST',
    body: JSON.stringify(payload),
  })
}

export function updateScreenSkill(
  slug: string,
  payload: ScreenSkillUpsertPayload & { expected_revision: string },
): Promise<ScreenSkillDetail> {
  return quantRequest<ScreenSkillDetail>(`/screen-skills/${encodeURIComponent(slug)}`, {
    method: 'PUT',
    body: JSON.stringify(payload),
  })
}

export function deleteScreenSkill(
  slug: string,
  expectedRevision: string,
): Promise<{ removed: boolean; archived?: boolean }> {
  return quantRequest(`/screen-skills/${encodeURIComponent(slug)}`, {
    method: 'DELETE',
    body: JSON.stringify({ expected_revision: expectedRevision }),
  })
}

export function generateScreenSkill(
  payload: ScreenSkillGenerateRequest,
): Promise<ScreenSkillGenerateResponse> {
  return quantRequest<ScreenSkillGenerateResponse>('/screen-skills/generate', {
    method: 'POST',
    body: JSON.stringify(payload),
  })
}

export function runScreen(payload: {
  strategy: string
  date?: string
  codes?: string[]
  params?: Record<string, unknown>
  universe?: UniverseSpec
  record_candidates?: boolean
  top_n?: number
  pool_id?: string
  skip_health_check?: boolean
}): Promise<ScreenResult> {
  return quantRequest<ScreenResult>('/strategies/screen', {
    method: 'POST',
    body: JSON.stringify(payload),
  })
}

export function getScreenRunStatus(): Promise<import('@/shared/types/quant').ScreenRunStatus> {
  return quantRequest('/screen/run')
}

export function startScreenRun(payload: {
  strategy: string
  date?: string
  start?: string
  end?: string
  codes?: string[]
  params?: Record<string, unknown>
  universe?: UniverseSpec
  record_candidates?: boolean
  top_n?: number
  pool_id?: string
  skip_health_check?: boolean
}): Promise<import('@/shared/types/quant').ScreenRunStatus> {
  return quantRequest('/screen/run', {
    method: 'POST',
    body: JSON.stringify({ record_candidates: true, ...payload }),
  })
}

export function runBacktest(payload: {
  strategy: string
  start?: string
  end?: string
  mode?: 'trade' | 'horizon'
  horizons?: number[]
  hold_days?: number
  stop_loss_pct?: number | null
  take_profit_pct?: number | null
  commission_bps?: number
  stamp_duty_bps?: number
  slippage_bps?: number
  benchmark?: string | null
  codes?: string[]
  params?: Record<string, unknown>
  universe?: UniverseSpec
  include_trades?: boolean
  include_events?: boolean
}): Promise<BacktestResult> {
  return quantRequest<BacktestResult>('/backtest', {
    method: 'POST',
    body: JSON.stringify(payload),
  })
}

export function runHorizonBacktest(payload: {
  strategy: string
  start: string
  end: string
  horizons?: number[]
  codes?: string[]
  params?: Record<string, unknown>
  universe?: UniverseSpec
  include_events?: boolean
}): Promise<HorizonBacktestResult> {
  return quantRequest<HorizonBacktestResult>('/backtest', {
    method: 'POST',
    body: JSON.stringify({ ...payload, mode: 'horizon' }),
  })
}

export function startAnalysis(
  kind: 'compare' | 'optimize',
  payload: {
    strategy?: string
    strategies?: string[]
    start?: string
    end?: string
    holds?: number[]
    targets?: number[]
    stops?: number[]
    stop_loss_pct?: number
    benchmark?: string
  },
): Promise<AnalysisStarted> {
  return quantRequest(`/analysis/${kind}`, { method: 'POST', body: JSON.stringify(payload) })
}

/**
 * 轮询直到任务结束。分析任务是分钟级的，间隔取 3 秒足够。
 *
 * `signal` 不是可选的礼貌参数：3s × 900s 上限 = 最多 300 次 `getJobRuns`，
 * 调用方（组件）卸载后若不能取消，这个循环会自己跑满 15 分钟。
 * 组件里请用 `onUnmounted(() => controller.abort())` 接上。
 */
export async function awaitJobResult(
  jobId: string,
  {
    intervalMs = 3000,
    timeoutMs = 900_000,
    signal,
  }: { intervalMs?: number; timeoutMs?: number; signal?: AbortSignal } = {},
): Promise<JobRun> {
  const deadline = Date.now() + timeoutMs
  for (;;) {
    if (signal?.aborted) throw toAbortError(signal.reason)
    const runs = await getJobRuns({ job_id: jobId, limit: 3 }, signal)
    const done = runs.find((run) => run.status === 'success' || run.status === 'failed')
    if (done) return done
    if (Date.now() > deadline) throw new Error('分析任务超时；可到设置页查看执行历史')
    await abortableSleep(intervalMs, signal)
  }
}

export function listCustomStrategies(): Promise<{ slug: string; name: string; file: string }[]> {
  return quantRequest('/strategies/custom')
}

export function convertStrategy(payload: {
  source: string
  source_type: 'tdx' | 'description'
  slug: string
  name: string
  provider: string
  model?: string
  thinking?: string
  entry_timing: EntryTiming
  dry_run?: boolean
}): Promise<{
  status: 'ok' | 'preview' | 'issues' | 'syntax_error' | 'load_error'
  code: string
  slug: string
  issues?: string[]
  error?: string
  file?: string
  registered?: boolean
}> {
  return quantRequest('/strategies/convert', {
    method: 'POST',
    body: JSON.stringify(payload),
  })
}

export function saveConvertedStrategy(payload: {
  code: string
  slug: string
}): Promise<{ slug: string; file: string; registered: boolean }> {
  return quantRequest('/strategies/convert/save', {
    method: 'POST',
    body: JSON.stringify(payload),
  })
}

export function deleteCustomStrategy(slug: string): Promise<{ removed: boolean }> {
  return quantRequest(`/strategies/custom/${encodeURIComponent(slug)}`, { method: 'DELETE' })
}

export function getStrategyJob(slug: string): Promise<StrategyJob> {
  return quantRequest(`/strategies/${encodeURIComponent(slug)}/job`)
}

export function upsertStrategyJob(slug: string, payload: StrategyJobConfig): Promise<StrategyJob> {
  return quantRequest(`/strategies/${encodeURIComponent(slug)}/job`, {
    method: 'PUT',
    body: JSON.stringify(payload),
  })
}

export function unbindStrategyJob(slug: string): Promise<{ removed: boolean }> {
  return quantRequest(`/strategies/${encodeURIComponent(slug)}/job`, { method: 'DELETE' })
}

export function getScreenHistory(options: {
  strategy: string
  start?: string
  end?: string
  limit?: number
  /** 默认 true（后端默认）；false 时含区间回填审计 */
  live_only?: boolean
}): Promise<ScreenHistory> {
  return quantRequest(
    `/screen/history${query({
      strategy: options.strategy,
      start: options.start,
      end: options.end,
      limit: options.limit,
      live_only:
        options.live_only === undefined
          ? undefined
          : options.live_only
            ? 'true'
            : 'false',
    })}`,
  )
}

export function getScreenHistoryBatch(options: {
  strategies: string[]
  start?: string
  end?: string
  limit?: number
  live_only?: boolean
}): Promise<{ strategies: string[]; histories: ScreenHistory[] }> {
  const strategies = options.strategies.map((s) => s.trim()).filter(Boolean).slice(0, 32)
  return quantRequest(
    `/screen/history/batch${query({
      strategies: strategies.join(','),
      start: options.start,
      end: options.end,
      limit: options.limit,
      live_only:
        options.live_only === undefined
          ? undefined
          : options.live_only
            ? 'true'
            : 'false',
    })}`,
  )
}

export function getScreenToday(options: {
  strategy: string
  force_sync?: boolean
  date?: string
  record_candidates?: boolean
  top_n?: number
}): Promise<ScreenTodayResult> {
  return quantRequest(
    `/screen/today${query({
      strategy: options.strategy,
      force_sync: options.force_sync ? 'true' : undefined,
      date: options.date,
      record_candidates: options.record_candidates === false ? 'false' : undefined,
      top_n: options.top_n,
    })}`,
  )
}

export function getDecay(options: { window?: number; baseline?: number } = {}): Promise<Record<string, unknown>[]> {
  return quantRequest(`/insights/decay${query(options)}`)
}

export function getOverlap(days?: number): Promise<Record<string, unknown>[]> {
  return quantRequest(`/insights/overlap${query({ days })}`)
}

export function getStrategyDoc(slug: string): Promise<Record<string, unknown>> {
  return quantRequest(`/strategies/${encodeURIComponent(slug)}/doc`)
}

export function upsertStrategyDoc(slug: string, payload: Record<string, string>): Promise<Record<string, unknown>> {
  return quantRequest(`/strategies/${encodeURIComponent(slug)}/doc`, {
    method: 'PUT',
    body: JSON.stringify(payload),
  })
}

export function auditStrategy(slug: string): Promise<Record<string, unknown>> {
  return quantRequest(`/strategies/${encodeURIComponent(slug)}/audit`)
}

export function listAiJudgments(strategyTag: string, limit = 100): Promise<Record<string, unknown>[]> {
  return quantRequest(`/ai/judgments/${encodeURIComponent(strategyTag)}${query({ limit })}`)
}

export function createAiJudgment(payload: {
  strategy_tag: string
  decision: 'buy' | 'hold_cash' | 'partial'
  top_codes?: string[]
  reason?: string
  occurred_on?: string
}): Promise<{ id: string }> {
  return quantRequest('/ai/judgments', { method: 'POST', body: JSON.stringify(payload) })
}
