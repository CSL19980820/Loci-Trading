/** 量化能力的接口封装。
 *
 * 与 palace.ts 共用同一套 fetch 约定（凭据、重试、错误契约），
 * 但单独成文件：这些接口在依赖缺失时会整体 503，调用方需要能一眼分辨
 * "功能没装"和"这次请求失败了"。
 */
import { apiRequest } from '@/api/palace'
import type {
  BacktestResult,
  Capabilities,
  Instrument,
  Job,
  JobKind,
  JobRun,
  LlmProvider,
  MarketCoverage,
  QuoteSeries,
  ScheduleStatus,
  ScreenResult,
  Skill,
  StrategyInfo,
} from '@/types/quant'

/** 依赖缺失导致的功能不可用。与普通请求失败区分开，便于界面给出不同引导。 */
export class CapabilityUnavailableError extends Error {
  constructor(message: string) {
    super(message)
    this.name = 'CapabilityUnavailableError'
  }
}

async function quantRequest<T>(path: string, init?: RequestInit): Promise<T> {
  try {
    return await apiRequest<T>(path, init)
  } catch (caught: unknown) {
    const error = caught as Error & { status?: number }
    if (error.status === 503) {
      throw new CapabilityUnavailableError(error.message)
    }
    throw caught
  }
}

function query(params: Record<string, string | number | undefined>): string {
  const search = new URLSearchParams()
  for (const [key, value] of Object.entries(params)) {
    if (value !== undefined && value !== '') search.set(key, String(value))
  }
  const text = search.toString()
  return text ? `?${text}` : ''
}

// ---- 能力探测 -------------------------------------------------------

export function getCapabilities(): Promise<Capabilities> {
  return quantRequest<Capabilities>('/capabilities')
}

// ---- 行情 -----------------------------------------------------------

export function getMarketCoverage(): Promise<MarketCoverage> {
  return quantRequest<MarketCoverage>('/market/coverage')
}

export function searchInstruments(q: string, limit = 20): Promise<Instrument[]> {
  return quantRequest<Instrument[]>(`/market/search${query({ q, limit })}`)
}

export function getQuotes(
  code: string,
  options: { start?: string; end?: string; adjust?: 'qfq' | 'hfq' | 'none' } = {},
): Promise<QuoteSeries> {
  const path = `/market/quotes/${encodeURIComponent(code)}`
  return quantRequest<QuoteSeries>(`${path}${query(options)}`)
}

export function syncMarket(payload: {
  codes?: string[]
  limit?: number
  workers?: number
  interval?: number
  force?: boolean
  refresh_instruments?: boolean
}): Promise<Record<string, unknown>> {
  return quantRequest('/market/sync', { method: 'POST', body: JSON.stringify(payload) })
}

// ---- 策略与回测 -----------------------------------------------------

export function getStrategies(): Promise<StrategyInfo[]> {
  return quantRequest<StrategyInfo[]>('/strategies')
}

export function runScreen(payload: {
  strategy: string
  date?: string
  codes?: string[]
  params?: Record<string, unknown>
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
  include_trades?: boolean
}): Promise<BacktestResult> {
  return quantRequest<BacktestResult>('/backtest', {
    method: 'POST',
    body: JSON.stringify(payload),
  })
}

// ---- 技能包 ---------------------------------------------------------

export function getSkills(): Promise<Skill[]> {
  return quantRequest<Skill[]>('/skills')
}

export function getSkill(slug: string): Promise<Skill> {
  return quantRequest<Skill>(`/skills/${encodeURIComponent(slug)}`)
}

/** 上传安装。multipart 不能设 Content-Type，浏览器要自己带 boundary。 */
export function installSkill(file: File): Promise<Skill> {
  const form = new FormData()
  form.append('file', file)
  return quantRequest<Skill>('/skills', { method: 'POST', body: form })
}

export function removeSkill(slug: string): Promise<{ removed: boolean }> {
  return quantRequest(`/skills/${encodeURIComponent(slug)}`, { method: 'DELETE' })
}

// ---- 定时任务 -------------------------------------------------------

export function getJobs(): Promise<Job[]> {
  return quantRequest<Job[]>('/jobs')
}

export function createJob(payload: {
  name: string
  kind: JobKind
  cron?: string
  config?: Record<string, unknown>
  enabled?: boolean
}): Promise<Job> {
  return quantRequest<Job>('/jobs', { method: 'POST', body: JSON.stringify(payload) })
}

export function updateJob(
  id: string,
  payload: { name?: string; cron?: string; config?: Record<string, unknown>; enabled?: boolean },
): Promise<Job> {
  return quantRequest<Job>(`/jobs/${encodeURIComponent(id)}`, {
    method: 'PATCH',
    body: JSON.stringify(payload),
  })
}

export function deleteJob(id: string): Promise<{ removed: boolean }> {
  return quantRequest(`/jobs/${encodeURIComponent(id)}`, { method: 'DELETE' })
}

export function runJob(id: string): Promise<{ run_id: string; status: string; error?: string }> {
  return quantRequest(`/jobs/${encodeURIComponent(id)}/run`, { method: 'POST' })
}

export function getJobRuns(options: { job_id?: string; status?: string; limit?: number } = {}): Promise<
  JobRun[]
> {
  return quantRequest<JobRun[]>(`/jobs/runs${query(options)}`)
}

export function getScheduleStatus(): Promise<ScheduleStatus> {
  return quantRequest<ScheduleStatus>('/jobs/schedule')
}

// ---- LLM 供应商 -----------------------------------------------------

export function getProviders(): Promise<LlmProvider[]> {
  return quantRequest<LlmProvider[]>('/providers')
}

export function saveProvider(payload: {
  name: string
  base_url: string
  api_key?: string
  protocol?: 'openai_compatible' | 'anthropic'
  model?: string
  proxy_url?: string
  note?: string
  validate_key?: boolean
  discover_models?: boolean
}): Promise<LlmProvider> {
  return quantRequest<LlmProvider>('/providers', {
    method: 'POST',
    body: JSON.stringify(payload),
  })
}

export function refreshProviderModels(name: string): Promise<{ models: string[]; count: number }> {
  return quantRequest(`/providers/${encodeURIComponent(name)}/models`, { method: 'POST' })
}

export function deleteProvider(name: string): Promise<{ removed: boolean }> {
  return quantRequest(`/providers/${encodeURIComponent(name)}`, { method: 'DELETE' })
}

// ---- 复盘 -----------------------------------------------------------

export function getEquityCurve(options: { start?: string; end?: string; benchmarks?: string } = {}) {
  return quantRequest<import('@/types/quant').EquityCurve>(`/review/equity${query(options)}`)
}

export function getRoundTrips(code?: string) {
  return quantRequest<{
    trips: import('@/types/quant').RoundTrip[]
    summary: import('@/types/quant').RoundTripSummary
  }>(`/review/trips${query({ code })}`)
}

export function getCandidateOutcomes(limit = 300) {
  return quantRequest<{
    outcomes: import('@/types/quant').CandidateOutcome[]
    summary: import('@/types/quant').CandidateSummary
  }>(`/review/candidates${query({ limit })}`)
}

export function getPlanOutcomes() {
  return quantRequest<import('@/types/quant').PlanOutcome[]>('/review/plans')
}

export function getPositionsAsOf(date?: string) {
  return quantRequest<{ code: string; name: string; shares: number; cost: number; cost_value: number }[]>(
    `/review/positions${query({ date })}`,
  )
}

// ---- 分析任务（异步）------------------------------------------------

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
): Promise<import('@/types/quant').AnalysisStarted> {
  return quantRequest(`/analysis/${kind}`, { method: 'POST', body: JSON.stringify(payload) })
}

/** 轮询直到任务结束。分析任务是分钟级的，间隔取 3 秒足够。 */
export async function awaitJobResult(
  jobId: string,
  { intervalMs = 3000, timeoutMs = 900_000 }: { intervalMs?: number; timeoutMs?: number } = {},
): Promise<import('@/types/quant').JobRun> {
  const deadline = Date.now() + timeoutMs
  for (;;) {
    const runs = await getJobRuns({ job_id: jobId, limit: 3 })
    const done = runs.find((run) => run.status === 'success' || run.status === 'failed')
    if (done) return done
    if (Date.now() > deadline) throw new Error('分析任务超时；可到运维页查看执行历史')
    await new Promise((resolve) => setTimeout(resolve, intervalMs))
  }
}

// ---- AI 策略转换器 --------------------------------------------------

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

export function generateSkillMd(payload: {
  description: string
  slug: string
  name: string
  provider: string
  model?: string
  context_hints?: string[]
}): Promise<{ slug: string; name: string; skill_md: string }> {
  return quantRequest('/skills/generate', {
    method: 'POST',
    body: JSON.stringify(payload),
  })
}

export function getMcpServers(): Promise<import('@/types/quant').McpServer[]> {
  return quantRequest('/mcp')
}

export function saveMcpServer(payload: {
  name: string
  url: string
  token?: string
  proxy_url?: string
  note?: string
  verify?: boolean
}): Promise<import('@/types/quant').McpServer> {
  return quantRequest('/mcp', { method: 'POST', body: JSON.stringify(payload) })
}

export function refreshMcpTools(name: string): Promise<{ tools: unknown[]; count: number }> {
  return quantRequest(`/mcp/${encodeURIComponent(name)}/refresh`, { method: 'POST' })
}

export function toggleMcpServer(
  name: string,
  is_active: boolean,
): Promise<import('@/types/quant').McpServer> {
  return quantRequest(`/mcp/${encodeURIComponent(name)}`, {
    method: 'PATCH',
    body: JSON.stringify({ is_active }),
  })
}

export function deleteMcpServer(name: string): Promise<{ removed: boolean }> {
  return quantRequest(`/mcp/${encodeURIComponent(name)}`, { method: 'DELETE' })
}

// ---- 策略定时选股配置 -----------------------------------------------

export function getStrategyJob(slug: string): Promise<import('@/types/quant').StrategyJob> {
  return quantRequest(`/strategies/${encodeURIComponent(slug)}/job`)
}

export function upsertStrategyJob(
  slug: string,
  payload: import('@/types/quant').StrategyJobConfig,
): Promise<import('@/types/quant').StrategyJob> {
  return quantRequest(`/strategies/${encodeURIComponent(slug)}/job`, {
    method: 'PUT',
    body: JSON.stringify(payload),
  })
}

export function unbindStrategyJob(slug: string): Promise<{ removed: boolean }> {
  return quantRequest(`/strategies/${encodeURIComponent(slug)}/job`, { method: 'DELETE' })
}

// ---- 胜率趋势 -------------------------------------------------------

export function getWinRateSummary(): Promise<import('@/types/quant').WinRateSummary[]> {
  return quantRequest('/winrate/summary')
}

export function getWinRateTrend(options: {
  granularity?: 'month' | 'week'
  tags?: string
} = {}): Promise<import('@/types/quant').WinRateTrendPoint[]> {
  return quantRequest(`/winrate/trend${query(options)}`)
}

// ---- 选股历史 + 准实时 ----------------------------------------------

export function getScreenHistory(options: {
  strategy: string
  start?: string
  end?: string
  limit?: number
}): Promise<import('@/types/quant').ScreenHistory> {
  return quantRequest(`/screen/history${query(options)}`)
}

export function getScreenToday(options: {
  strategy: string
  force_sync?: boolean
}): Promise<import('@/types/quant').ScreenTodayResult> {
  return quantRequest(`/screen/today${query({ strategy: options.strategy, force_sync: options.force_sync ? 'true' : undefined })}`)
}

// ---- 洞察层：衰减 / 重叠 / 体检 / 审计 / 策略档案 / AI判定 ----------

export function getMarketHealth(date?: string): Promise<Record<string, unknown>> {
  return quantRequest(`/market/health${query({ date })}`)
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
