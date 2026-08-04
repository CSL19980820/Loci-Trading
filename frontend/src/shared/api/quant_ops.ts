/** 运维：技能 / 任务 / 企微 / 数据目录 / 线路 / LLM / MCP。 */
import { quantRequest, query } from '@/shared/api/quant_client'
import type {
  Job,
  JobKind,
  JobRun,
  LanesCatalog,
  LanePolicy,
  LanePolicyPayload,
  LaneProbeResponse,
  LaneSpeedTestResponse,
  AkshareCatalog,
  AkshareCatalogProbeResult,
  AkshareCatalogSource,
  AkshareBatchProbeResult,
  AkshareVersionInfo,
  LlmModel,
  LlmProvider,
  MarketSyncSettings,
  McpServer,
  ScheduleStatus,
  Skill,
  SkillJob,
  SkillJobConfig,
  WecomSettings,
} from '@/shared/types/quant'

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

export function getSkillJob(slug: string): Promise<SkillJob> {
  return quantRequest<SkillJob>(`/skills/${encodeURIComponent(slug)}/job`)
}

export function upsertSkillJob(slug: string, payload: SkillJobConfig): Promise<SkillJob> {
  return quantRequest<SkillJob>(`/skills/${encodeURIComponent(slug)}/job`, {
    method: 'PUT',
    body: JSON.stringify(payload),
  })
}

export function unbindSkillJob(slug: string): Promise<{ removed: boolean }> {
  return quantRequest(`/skills/${encodeURIComponent(slug)}/job`, { method: 'DELETE' })
}

export interface SkillRunAsk {
  prompt?: string
  options?: string[]
}

export interface SkillRun {
  id: string
  skill: string
  provider: string
  status: 'running' | 'waiting_user' | 'done' | 'error'
  created_at?: string
  updated_at?: string
  pending_ask?: SkillRunAsk
  subagents?: Array<{ id?: string; ok?: boolean; kind?: string }>
  error?: string
  result?: {
    output?: string
    stopped_reason?: string
    tool_trace?: string
    rounds?: number
    model?: string
  }
}

export function startSkillRun(
  slug: string,
  payload: {
    provider: string
    model?: string
    config?: Record<string, unknown>
    background?: boolean
  },
): Promise<{ run: SkillRun; result?: SkillRun['result'] }> {
  return quantRequest(`/skills/${encodeURIComponent(slug)}/runs`, {
    method: 'POST',
    body: JSON.stringify(payload),
  })
}

export function getSkillRun(runId: string): Promise<SkillRun> {
  return quantRequest(`/skill-runs/${encodeURIComponent(runId)}`)
}

export function replySkillRun(
  runId: string,
  reply: string,
  background = true,
): Promise<{ run: SkillRun; result?: SkillRun['result'] }> {
  return quantRequest(`/skill-runs/${encodeURIComponent(runId)}/reply`, {
    method: 'POST',
    body: JSON.stringify({ reply, background }),
  })
}

export function getSkillRunEvents(
  runId: string,
  after = 0,
): Promise<{ run_id: string; events: Array<Record<string, unknown>>; next_after: number }> {
  return quantRequest(`/skill-runs/${encodeURIComponent(runId)}/events${query({ after })}`)
}

export function generateSkillMd(payload: {
  description: string
  slug: string
  name: string
  provider: string
  model?: string
  thinking?: string
  context_hints?: string[]
}): Promise<{ slug: string; name: string; skill_md: string }> {
  return quantRequest('/skills/generate', {
    method: 'POST',
    body: JSON.stringify(payload),
  })
}

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

export function getJobRuns(options: { job_id?: string; run_id?: string; status?: string; limit?: number } = {}): Promise<
  JobRun[]
> {
  return quantRequest<JobRun[]>(`/jobs/runs${query(options)}`)
}

export function batchDeleteJobRuns(ids: string[]): Promise<{ removed: number }> {
  return quantRequest('/jobs/runs/batch-delete', {
    method: 'POST',
    body: JSON.stringify({ ids }),
  })
}

export function getScheduleStatus(): Promise<ScheduleStatus> {
  return quantRequest<ScheduleStatus>('/jobs/schedule')
}

export function getWecomSettings(): Promise<WecomSettings> {
  return quantRequest('/ops/settings/wecom')
}

export function saveWecomSettings(payload: {
  url?: string | null
  screen_template?: WecomSettings['screen_template']
}): Promise<WecomSettings> {
  return quantRequest('/ops/settings/wecom', {
    method: 'PUT',
    body: JSON.stringify(payload),
  })
}

export function testWecomSettings(): Promise<{ ok: boolean }> {
  return quantRequest('/ops/settings/wecom/test', { method: 'POST' })
}

export function getMarketSyncSettings(): Promise<MarketSyncSettings> {
  return quantRequest('/ops/market-sync')
}

export function saveMarketSyncSettings(
  payload: Omit<MarketSyncSettings, 'intraday_job' | 'eod_job'>,
): Promise<MarketSyncSettings> {
  return quantRequest('/ops/market-sync', {
    method: 'PUT',
    body: JSON.stringify(payload),
  })
}

export interface DataLocationInfo {
  data_dir: string
  default_dir: string
  install_dir: string
  config_path: string
  market_db: string
  market_bytes: number
  needed_bootstrap: boolean
  setup_done: boolean
  /** 未确认过数据目录，或目录已不存在时为 true，前端强制弹初始化向导 */
  needs_setup: boolean
  discovered_dirs: Array<{
    path: string
    market_bytes: number
    source: string
    label: string
  }>
  restart_required?: boolean
  pending_data_dir?: string
  message?: string
}

export function getDataLocation(): Promise<DataLocationInfo> {
  return quantRequest('/ops/data-location')
}

export function saveDataLocation(payload: {
  data_dir: string
  setup_done?: boolean
}): Promise<DataLocationInfo> {
  return quantRequest('/ops/data-location', {
    method: 'POST',
    body: JSON.stringify(payload),
  })
}

export function createDesktopShortcut(): Promise<{
  ok: boolean
  shortcut: string
  target: string
  workdir: string
  desktop: string
}> {
  return quantRequest('/ops/desktop-shortcut', { method: 'POST' })
}

export type DesktopPrefs = {
  minimize_to_tray: boolean
}

export function getDesktopPrefs(): Promise<DesktopPrefs> {
  return quantRequest('/ops/desktop-prefs')
}

export function saveDesktopPrefs(payload: Partial<DesktopPrefs>): Promise<DesktopPrefs> {
  return quantRequest('/ops/desktop-prefs', {
    method: 'PUT',
    body: JSON.stringify(payload),
  })
}

export function fetchLanesCatalog(): Promise<LanesCatalog> {
  return quantRequest<LanesCatalog>('/ops/lanes')
}

export function probeLanes(
  lane?: string | null,
  adapterId?: string | null,
  options: { code?: string; runs?: 1 | 2 | 3 } = {},
): Promise<LaneProbeResponse> {
  const payload: { lane: string | null; code?: string; runs?: 1 | 2 | 3; adapter_id?: string } = {
    lane: lane ?? null,
    code: options.code,
    runs: options.runs,
  }
  if (adapterId) payload.adapter_id = adapterId
  return quantRequest<LaneProbeResponse>('/ops/lanes/probe', {
    method: 'POST',
    body: JSON.stringify(payload),
  })
}

export function speedtestLane(
  lane: string,
  code = '600519',
  runs?: 1 | 2 | 3,
): Promise<LaneSpeedTestResponse> {
  return quantRequest<LaneSpeedTestResponse>('/ops/lanes/speedtest', {
    method: 'POST',
    body: JSON.stringify({ lane, code, runs }),
  })
}

export function saveLanePolicy(lane: string, payload: LanePolicyPayload): Promise<LanePolicy> {
  return quantRequest(`/ops/lanes/${encodeURIComponent(lane)}/policy`, {
    method: 'PUT',
    body: JSON.stringify(payload),
  })
}

export function getAkshareCatalog(
  filters: { q?: string; category?: string; source?: string } = {},
): Promise<AkshareCatalog> {
  const query = new URLSearchParams()
  if (filters.q) query.set('q', filters.q)
  if (filters.category) query.set('category', filters.category)
  if (filters.source) query.set('source', filters.source)
  const search = query.toString()
  const suffix = search ? `?${search}` : ''
  return quantRequest<AkshareCatalog>(`/market/akshare/catalog${suffix}`)
}

/** 只要每个来源挂了多少接口。整份目录几千条，货架列表不该为一个数字全量拉。 */
export function getAkshareSources(): Promise<{
  sources: AkshareCatalogSource[]
  total?: number
  akshare_version?: string
}> {
  return quantRequest('/market/akshare/sources')
}

export function getAkshareVersion(fetchLatest = true): Promise<AkshareVersionInfo> {
  const suffix = fetchLatest ? '' : '?fetch_latest=false'
  return quantRequest(`/market/akshare/version${suffix}`)
}

export function probeAkshareCatalog(
  name: string,
  params: Record<string, unknown>,
): Promise<AkshareCatalogProbeResult> {
  return quantRequest(`/market/akshare/catalog/${encodeURIComponent(name)}/probe`, {
    method: 'POST',
    body: JSON.stringify({ params }),
  })
}

/** 一键/分页批量探测；不传 names 则按目录全量续跑。 */
export function probeAkshareCatalogBatch(payload: {
  names?: string[]
  offset?: number
  limit?: number
}): Promise<AkshareBatchProbeResult> {
  return quantRequest('/market/akshare/catalog/probe-batch', {
    method: 'POST',
    body: JSON.stringify(payload),
  })
}

/** 不传 lane 改源总开关；传 lane 只改这家在该线路上的单个工具。 */
export function patchLaneProvider(
  providerId: string,
  enabled: boolean,
  lane?: string,
): Promise<{ id: string; label: string; enabled: boolean; disabled_lanes?: string[] }> {
  return quantRequest(`/ops/lanes/providers/${encodeURIComponent(providerId)}`, {
    method: 'PATCH',
    body: JSON.stringify(lane ? { enabled, lane } : { enabled }),
  })
}

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
  is_default?: boolean
}): Promise<LlmProvider> {
  return quantRequest<LlmProvider>('/providers', {
    method: 'POST',
    body: JSON.stringify(payload),
  })
}

export function setDefaultProvider(name: string): Promise<LlmProvider> {
  return quantRequest<LlmProvider>(`/providers/${encodeURIComponent(name)}/default`, {
    method: 'POST',
  })
}

export function refreshProviderModels(name: string): Promise<{
  models: string[]
  model_catalog: LlmModel[]
  count: number
}> {
  return quantRequest(`/providers/${encodeURIComponent(name)}/models`, { method: 'POST' })
}

export function updateProviderModels(
  name: string,
  payload: {
    models: LlmModel[]
    default_model?: string | null
  },
): Promise<LlmProvider> {
  return quantRequest<LlmProvider>(`/providers/${encodeURIComponent(name)}/models`, {
    method: 'PUT',
    body: JSON.stringify(payload),
  })
}

export function testProvider(name: string): Promise<{
  ok: boolean
  provider: string
  model: string
  latency_ms: number
  preview: string
}> {
  return quantRequest(`/providers/${encodeURIComponent(name)}/test`, { method: 'POST' })
}

export function deleteProvider(name: string): Promise<{ removed: boolean }> {
  return quantRequest(`/providers/${encodeURIComponent(name)}`, { method: 'DELETE' })
}

export function getMcpServers(): Promise<McpServer[]> {
  return quantRequest('/mcp')
}

export function saveMcpServer(payload: {
  name: string
  url: string
  token?: string
  note?: string
  verify?: boolean
}): Promise<McpServer> {
  return quantRequest('/mcp', { method: 'POST', body: JSON.stringify(payload) })
}

export function refreshMcpTools(name: string): Promise<{ tools: unknown[]; count: number }> {
  return quantRequest(`/mcp/${encodeURIComponent(name)}/refresh`, { method: 'POST' })
}

export type McpProbeResult = {
  ok: boolean
  scope: 'server'
  rtt_ms: number
  error?: string
  tools_updated?: number
  tool_count?: number
  server_name?: string
  server_version?: string
  protocol_version?: string
  sample_tools?: string[]
}

export function probeMcpServer(name: string): Promise<McpProbeResult> {
  return quantRequest(`/mcp/${encodeURIComponent(name)}/probe`, {
    method: 'POST',
  })
}

export function toggleMcpServer(name: string, is_active: boolean): Promise<McpServer> {
  return quantRequest(`/mcp/${encodeURIComponent(name)}`, {
    method: 'PATCH',
    body: JSON.stringify({ is_active }),
  })
}

export function deleteMcpServer(name: string): Promise<{ removed: boolean }> {
  return quantRequest(`/mcp/${encodeURIComponent(name)}`, { method: 'DELETE' })
}
