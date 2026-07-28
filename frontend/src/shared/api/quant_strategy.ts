/** 策略：选股 / 回测 / 分析 / 转换 / 档案 / 审计 / 洞察。 */
import { quantRequest, query } from '@/shared/api/quant_client'
import { getJobRuns } from '@/shared/api/quant_ops'
import type {
  AnalysisStarted,
  BacktestResult,
  JobRun,
  ScreenHistory,
  ScreenResult,
  ScreenTodayResult,
  StrategyInfo,
  StrategyJob,
  StrategyJobConfig,
  UniverseSpec,
} from '@/shared/types/quant'

export function getStrategies(): Promise<StrategyInfo[]> {
  return quantRequest<StrategyInfo[]>('/strategies')
}

export function runScreen(payload: {
  strategy: string
  date?: string
  codes?: string[]
  params?: Record<string, unknown>
  universe?: UniverseSpec
}): Promise<ScreenResult> {
  return quantRequest<ScreenResult>('/strategies/screen', {
    method: 'POST',
    body: JSON.stringify(payload),
  })
}

export function runBacktest(payload: {
  strategy: string
  start?: string
  end?: string
  hold_days?: number
  stop_loss_pct?: number | null
  take_profit_pct?: number | null
  benchmark?: string | null
  codes?: string[]
  params?: Record<string, unknown>
  universe?: UniverseSpec
  include_trades?: boolean
}): Promise<BacktestResult> {
  return quantRequest<BacktestResult>('/backtest', {
    method: 'POST',
    body: JSON.stringify(payload),
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

/** 轮询直到任务结束。分析任务是分钟级的，间隔取 3 秒足够。 */
export async function awaitJobResult(
  jobId: string,
  { intervalMs = 3000, timeoutMs = 900_000 }: { intervalMs?: number; timeoutMs?: number } = {},
): Promise<JobRun> {
  const deadline = Date.now() + timeoutMs
  for (;;) {
    const runs = await getJobRuns({ job_id: jobId, limit: 3 })
    const done = runs.find((run) => run.status === 'success' || run.status === 'failed')
    if (done) return done
    if (Date.now() > deadline) throw new Error('分析任务超时；可到设置页查看执行历史')
    await new Promise((resolve) => setTimeout(resolve, intervalMs))
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
  entry_timing: 'open' | 'next_open'
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
}): Promise<ScreenHistory> {
  return quantRequest(`/screen/history${query(options)}`)
}

export function getScreenToday(options: {
  strategy: string
  force_sync?: boolean
}): Promise<ScreenTodayResult> {
  return quantRequest(
    `/screen/today${query({
      strategy: options.strategy,
      force_sync: options.force_sync ? 'true' : undefined,
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
