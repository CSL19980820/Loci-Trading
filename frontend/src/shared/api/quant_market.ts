/** 行情：覆盖率 / 实时条 / 看板 / K 线 / 同步 / 引导 / 股票池 / 体检。 */
import { quantRequest, query } from '@/shared/api/quant_client'
import type {
  AkshareBatchProbeResult,
  AkshareCatalog,
  AkshareCatalogProbeResult,
  AkshareCatalogSource,
  AkshareVersionInfo,
  Capabilities,
  Instrument,
  MarketBoard,
  MarketCoverage,
  QuoteSeries,
  UniverseFunnel,
  UniversePreset,
  UniverseSpec,
  UniverseStats,
} from '@/shared/types/quant'

export function getCapabilities(): Promise<Capabilities> {
  return quantRequest<Capabilities>('/capabilities')
}

export function getMarketCoverage(): Promise<MarketCoverage> {
  return quantRequest<MarketCoverage>('/market/coverage')
}

export interface LiveTapeItem {
  code: string
  label: string
  symbol?: string
  kind: 'index' | 'position' | 'watch'
  name?: string
  price: number | null
  pct: number | null
  change?: number | null
  pnl_pct?: number | null
  market_value?: number | null
  shares?: number
  cost?: number
  trade_time?: string
  source?: string
  ok?: boolean
}

export interface LiveTape {
  as_of: string
  source: string
  error: string
  title: string
  indices: LiveTapeItem[]
  watches: LiveTapeItem[]
  items: LiveTapeItem[]
}

export function getLiveTape(refresh = false): Promise<LiveTape> {
  return quantRequest<LiveTape>(`/market/live-tape${refresh ? '?refresh=true' : ''}`)
}

export function searchInstruments(q: string, limit = 20): Promise<Instrument[]> {
  return quantRequest<Instrument[]>(`/market/search${query({ q, limit })}`)
}

export function getMarketBoard(options: {
  q?: string
  page?: number
  page_size?: number
  live?: boolean
  /** 兼容旧 GET persist；轮询请保持 false，显式落盘用 persistMarketBoardSpot */
  persist?: boolean
  instrument_type?: string
  status?: string
  industry?: string
  sort?: string
  turnover_min?: number
  /** 逗号分隔或数组；指定时按码叠价，忽略榜单分页宇宙 */
  codes?: string | string[]
} = {}): Promise<MarketBoard> {
  const live = options.live === true ? 'true' : 'false'
  const persist = options.persist === true ? 'true' : 'false'
  const codes = Array.isArray(options.codes)
    ? options.codes.filter(Boolean).join(',')
    : options.codes
  return quantRequest(
    `/market/board${query({
      q: options.q,
      page: options.page,
      page_size: options.page_size,
      live,
      persist,
      instrument_type: options.instrument_type,
      status: options.status,
      industry: options.industry,
      sort: options.sort,
      turnover_min: options.turnover_min,
      codes,
    })}`,
  )
}

/** 显式落盘当日 spot + 热库镜像；与 live 轮询解耦，需写鉴权（本地桌面默认可写）。 */
export function persistMarketBoardSpot(payload: {
  codes?: string[]
  q?: string
  page?: number
  page_size?: number
  instrument_type?: string
  status?: string
  industry?: string
  sort?: string
  turnover_min?: number | null
} = {}): Promise<{
  ok: boolean
  written: number
  codes: string[]
  as_of: string
  mirrored?: Record<string, unknown>
}> {
  const body: Record<string, unknown> = {}
  if (payload.codes?.length) body.codes = payload.codes.filter(Boolean)
  if (payload.q) body.q = payload.q
  if (payload.page != null) body.page = payload.page
  if (payload.page_size != null) body.page_size = payload.page_size
  if (payload.instrument_type) body.instrument_type = payload.instrument_type
  if (payload.status) body.status = payload.status
  if (payload.industry) body.industry = payload.industry
  if (payload.sort) body.sort = payload.sort
  if (payload.turnover_min != null) body.turnover_min = payload.turnover_min
  return quantRequest('/market/board/spot', {
    method: 'POST',
    body: JSON.stringify(body),
  })
}

export function getMarketIndustries(): Promise<{ items: string[]; total: number }> {
  return quantRequest('/market/industries')
}

export function getQuotes(
  code: string,
  options: {
    start?: string
    end?: string
    adjust?: 'qfq' | 'hfq' | 'none'
    limit?: number
  } = {},
): Promise<QuoteSeries> {
  const path = `/market/quotes/${encodeURIComponent(code)}`
  return quantRequest<QuoteSeries>(`${path}${query(options)}`)
}

/** 实时分钟线（不落库）。 */
export interface MinuteBar {
  datetime: string
  open?: number | null
  high?: number | null
  low?: number | null
  close?: number | null
  volume?: number | null
  amount?: number | null
  avg_price?: number | null
}

export interface MinuteSeries {
  code: string
  name: string
  trade_date: string
  period: string
  /** 与日 K 对齐的复权口径；源仍是不复权，服务端用因子缩放 */
  adjust?: 'qfq' | 'hfq' | 'none'
  source: string
  /** 与 bars 同口径的昨收（已按 adjust 缩放） */
  prev_close?: number | null
  rows: number
  bars: MinuteBar[]
}

export function getMinuteBars(
  code: string,
  options: {
    date?: string
    period?: string
    days?: number
    adjust?: 'qfq' | 'hfq' | 'none'
  } = {},
): Promise<MinuteSeries> {
  const path = `/market/minute/${encodeURIComponent(code)}`
  return quantRequest<MinuteSeries>(
    `${path}${query({
      date: options.date,
      period: options.period ?? '1',
      days: options.days,
      adjust: options.adjust ?? 'none',
    })}`,
  )
}

export function syncMarket(payload: {
  codes?: string[]
  limit?: number
  workers?: number
  interval?: number
  force?: boolean
  refresh_instruments?: boolean
  with_factors?: boolean
}): Promise<Record<string, unknown>> {
  return quantRequest('/market/sync', { method: 'POST', body: JSON.stringify(payload) })
}

export interface MarketBootstrapStatus {
  status: 'idle' | 'running' | 'done' | 'error'
  phase: string
  done: number
  total: number
  percent: number
  code: string
  message: string
  needed?: boolean
  backfill_kind?: string
  coverage?: MarketCoverage
  session?: import('@/shared/lib/marketSession').MarketSession
  report?: Record<string, unknown> | null
}

export function getMarketSession(): Promise<import('@/shared/lib/marketSession').MarketSession> {
  return quantRequest('/market/session')
}

export function getMarketBootstrap(): Promise<MarketBootstrapStatus> {
  return quantRequest<MarketBootstrapStatus>('/market/bootstrap')
}

export function startMarketBootstrap(payload: {
  workers?: number
  interval?: number
  limit?: number
  with_factors?: boolean
} = {}): Promise<MarketBootstrapStatus> {
  return quantRequest<MarketBootstrapStatus>('/market/bootstrap', {
    method: 'POST',
    body: JSON.stringify(payload),
  })
}

export function getUniversePresets(): Promise<UniversePreset[]> {
  return quantRequest<UniversePreset[]>('/universe/presets')
}

export function getUniverseStats(): Promise<UniverseStats> {
  return quantRequest<UniverseStats>('/universe/stats')
}

export function previewUniverse(payload: UniverseSpec): Promise<{
  universe: UniverseSpec
  universe_funnel: UniverseFunnel
  code_count: number
}> {
  return quantRequest('/universe/preview', {
    method: 'POST',
    body: JSON.stringify(payload),
  })
}

export type HealthSeverity = 'block' | 'warn' | 'ok'

export type HealthRemediation = {
  action: string
  label: string
  hint?: string
}

export type HealthFinding = {
  check: string
  severity: HealthSeverity
  message: string
  observed?: unknown
  threshold?: unknown
  remediation?: HealthRemediation | null
}

export type HealthCatalogItem = {
  id: string
  label: string
  group: string
}

export type HealthRepairPlan = {
  actions: string[]
  primary_action: string | null
  with_factors: boolean
  needs_bootstrap: boolean
  needs_turnover_repair: boolean
  labels: string[]
  check_ids: string[]
}

export type MarketHealthReport = {
  trade_date: string
  blocked: boolean
  reason: string
  checked_at: string
  include_network?: boolean
  findings: HealthFinding[]
  block_count: number
  warn_count: number
  score: number
  grade: string
  repair_plan: HealthRepairPlan
  catalog: HealthCatalogItem[]
}

export function getMarketHealth(options?: {
  date?: string
  include_ok?: boolean
  include_network?: boolean
  signal?: AbortSignal
}): Promise<MarketHealthReport> {
  const date = options?.date
  const include_ok = options?.include_ok ? 'true' : undefined
  const include_network = options?.include_network ? 'true' : undefined
  const init = options?.signal ? { signal: options.signal } : undefined
  return quantRequest(`/market/health${query({ date, include_ok, include_network })}`, init)
}

/** 用 as-of 流通股本回填缺换手率（体检「回填换手率」）。 */
export function repairMarketTurnover(since?: string): Promise<{
  ok: boolean
  updated: number
  skipped: number
  dates_scanned: number
}> {
  return quantRequest(`/market/repair/turnover${query({ since })}`, { method: 'POST' })
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
