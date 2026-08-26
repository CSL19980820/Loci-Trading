/** 运维：纸面量化舱 / 告警规则 / 分享打包。 */
import { quantRequest } from '@/shared/api/quant_client'

export interface PaperCabinStyle {
  style_md?: string
  revision?: number
  watch_hints?: string[]
  buy_rules?: Record<string, unknown>
}

export interface PaperMemoryGraph {
  summary?: string
  stats?: Record<string, unknown>
  nodes?: Array<Record<string, unknown>>
  edges?: Array<Record<string, unknown>>
}

export interface PaperCabinDetail {
  cabin: Record<string, unknown>
  positions: Array<Record<string, unknown>>
  fills: Array<Record<string, unknown>>
  monitor_runs: Array<Record<string, unknown>>
  nextday_plan: Record<string, unknown> | null
  unified_pool?: UnifiedMonitorPool
  style?: PaperCabinStyle
  lessons?: Array<Record<string, unknown>>
  memory_graph?: PaperMemoryGraph
}

export interface UnifiedMonitorPool {
  slug: string
  trade_date: string
  updated_at: string
  source: string
  limits: {
    initial_capital: number
    max_layers: number
    max_positions: number
    max_observe: number
    max_total: number
  }
  counts: { positions: number; observe: number; total: number }
  items: Array<Record<string, unknown>>
}

export function getPaperCabin(slug: string): Promise<PaperCabinDetail> {
  return quantRequest(`/ops/paper-cabins/${encodeURIComponent(slug)}`)
}

export function getUnifiedMonitorPool(slug: string): Promise<UnifiedMonitorPool> {
  return quantRequest(`/ops/paper-cabins/${encodeURIComponent(slug)}/unified-pool`)
}

export function savePaperCabinConfig(
  slug: string,
  payload: Record<string, unknown>,
): Promise<Record<string, unknown>> {
  return quantRequest(`/ops/paper-cabins/${encodeURIComponent(slug)}/config`, {
    method: 'PUT',
    body: JSON.stringify(payload),
  })
}

export function savePaperStyle(
  slug: string,
  payload: {
    style_md: string
    watch_hints?: string[]
    buy_rules?: Record<string, unknown>
  },
): Promise<Record<string, unknown>> {
  return quantRequest(`/ops/paper-cabins/${encodeURIComponent(slug)}/style`, {
    method: 'PUT',
    body: JSON.stringify(payload),
  })
}

export function absorbPaperStyle(slug: string): Promise<Record<string, unknown>> {
  return quantRequest(`/ops/paper-cabins/${encodeURIComponent(slug)}/style/absorb`, {
    method: 'POST',
  })
}

export function explorePaperMemory(
  slug: string,
  q = '',
): Promise<PaperMemoryGraph> {
  const query = q ? `?q=${encodeURIComponent(q)}` : ''
  return quantRequest(`/ops/paper-cabins/${encodeURIComponent(slug)}/memory/explore${query}`)
}

export function rebuildPaperMemory(slug: string): Promise<Record<string, unknown>> {
  return quantRequest(`/ops/paper-cabins/${encodeURIComponent(slug)}/memory/rebuild`, {
    method: 'POST',
  })
}

export function runPaperMonitor(slug: string): Promise<Record<string, unknown>> {
  return quantRequest(`/ops/paper-cabins/${encodeURIComponent(slug)}/monitor`, {
    method: 'POST',
  })
}

export function runPaperEod(slug: string): Promise<Record<string, unknown>> {
  return quantRequest(`/ops/paper-cabins/${encodeURIComponent(slug)}/eod`, { method: 'POST' })
}

export function listAlertRules(): Promise<Array<Record<string, unknown>>> {
  return quantRequest('/ops/alert-rules')
}

export function saveAlertRule(payload: Record<string, unknown>): Promise<Record<string, unknown>> {
  return quantRequest('/ops/alert-rules', { method: 'PUT', body: JSON.stringify(payload) })
}

export function deleteAlertRule(ruleId: string): Promise<{ ok: boolean }> {
  return quantRequest(`/ops/alert-rules/${encodeURIComponent(ruleId)}`, { method: 'DELETE' })
}

export function scanAlertRules(dryRun = false): Promise<Record<string, unknown>> {
  return quantRequest(`/ops/alert-rules/scan?dry_run=${dryRun ? 'true' : 'false'}`, {
    method: 'POST',
  })
}

export type SharePackOption = {
  id: string
  label: string
  description: string
  default: boolean
  available: boolean
  bytes: number
}

export type SharePackStatus = {
  version: string
  released_at: string
  summary: string
  can_pack: boolean
  reason: string
  bundle_root: string | null
  runtime_bytes: number
  options: SharePackOption[]
}

export function getSharePackStatus(): Promise<SharePackStatus> {
  return quantRequest<SharePackStatus>('/ops/share-pack/status')
}

/** POST 生成加密 zip 并触发浏览器下载。 */
export interface SharePackResult {
  filename: string
  /** false = 勾了「包含我的密钥与个人记录」，包里是原样数据 */
  sanitized: boolean
  /** 抹掉的密钥/个人记录处数 */
  sanitizeCount: number
}

export async function downloadSharePack(
  include: string[],
  password: string,
): Promise<SharePackResult> {
  const response = await fetch('/api/ops/share-pack', {
    method: 'POST',
    credentials: 'same-origin',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ include, password }),
  })
  if (!response.ok) {
    const body: unknown = await response.json().catch(() => null)
    const detail =
      typeof body === 'object' && body !== null && 'detail' in body
        ? String((body as { detail: unknown }).detail)
        : `打包失败（${response.status}）`
    throw new Error(detail)
  }
  const disposition = response.headers.get('content-disposition') || ''
  const matched = /filename\*?=(?:UTF-8''|")?([^\";]+)/i.exec(disposition)
  const filename = matched
    ? decodeURIComponent(matched[1]!.replace(/"/g, '').trim())
    : 'Loci-share.zip'
  const blob = await response.blob()
  const url = URL.createObjectURL(blob)
  const anchor = document.createElement('a')
  anchor.href = url
  anchor.download = filename
  anchor.click()
  URL.revokeObjectURL(url)
  return {
    filename,
    sanitized: response.headers.get('x-loci-sanitized') !== '0',
    sanitizeCount: Number(response.headers.get('x-loci-sanitize-count') || 0),
  }
}
