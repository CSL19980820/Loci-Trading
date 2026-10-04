/** 运维共享能力：告警规则与显式分享打包。 */
import { quantRequest } from '@/shared/api/quant_client'

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
