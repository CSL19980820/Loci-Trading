import { formatApiDetail } from '@/shared/lib/errors'
import { apiRequest } from '@/shared/api/palace'
import type {
  AiAssistantProfile,
  AiMemoryItem,
  AiRun,
  AiRunEvent,
  AiRunEventsPage,
  AiSessionBatchResult,
  AiSessionDetail,
  AiSessionSummary,
  AiToolsCatalog,
} from '@/shared/types/ai_assistant'

const API_ROOT = '/api'

export function createAiSession(payload: {
  title?: string
  provider?: string
  model?: string
} = {}): Promise<AiSessionDetail> {
  return apiRequest<AiSessionDetail>('/ai/sessions', { method: 'POST', body: JSON.stringify(payload) })
}

export function listAiSessions(opts: { archivedOnly?: boolean; includeArchived?: boolean } = {}): Promise<AiSessionSummary[]> {
  const params = new URLSearchParams()
  if (opts.archivedOnly) params.set('archived_only', 'true')
  if (opts.includeArchived) params.set('include_archived', 'true')
  const suffix = params.toString()
  return apiRequest<AiSessionSummary[]>(`/ai/sessions${suffix ? `?${suffix}` : ''}`)
}

export function getAiSession(id: string): Promise<AiSessionDetail> {
  return apiRequest<AiSessionDetail>(`/ai/sessions/${encodeURIComponent(id)}`)
}

export function patchAiSession(id: string, payload: { title?: string; archived?: boolean }): Promise<AiSessionDetail> {
  return apiRequest<AiSessionDetail>(`/ai/sessions/${encodeURIComponent(id)}`, {
    method: 'PATCH',
    body: JSON.stringify(payload),
  })
}

export function deleteAiSession(id: string): Promise<void> {
  return apiRequest<void>(`/ai/sessions/${encodeURIComponent(id)}`, { method: 'DELETE' })
}

export function batchAiSessions(action: 'archive' | 'unarchive' | 'delete', ids: string[]): Promise<AiSessionBatchResult> {
  return apiRequest<AiSessionBatchResult>('/ai/sessions/batch', {
    method: 'POST',
    body: JSON.stringify({ action, ids }),
  })
}

export function getAiProfile(): Promise<AiAssistantProfile> {
  return apiRequest<AiAssistantProfile>('/ai/profile')
}

export function putAiProfile(payload: Partial<AiAssistantProfile>): Promise<AiAssistantProfile> {
  return apiRequest<AiAssistantProfile>('/ai/profile', {
    method: 'PUT',
    body: JSON.stringify(payload),
  })
}

export function resetAiProfileDefaults(): Promise<AiAssistantProfile> {
  return apiRequest<AiAssistantProfile>('/ai/profile/reset-defaults', { method: 'POST' })
}

export function listAiMemories(target?: 'user' | 'memory'): Promise<AiMemoryItem[]> {
  const params = new URLSearchParams()
  if (target) params.set('target', target)
  const suffix = params.toString()
  return apiRequest<AiMemoryItem[]>(`/ai/memories${suffix ? `?${suffix}` : ''}`)
}

export function putAiMemoryDocument(payload: {
  target: 'user' | 'memory'
  content: string
}): Promise<{ target: string; content: string; usage: number; item: AiMemoryItem | null }> {
  return apiRequest('/ai/memories/document', {
    method: 'PUT',
    body: JSON.stringify(payload),
  })
}

export function createAiMemory(payload: { target: 'user' | 'memory'; content: string }): Promise<AiMemoryItem> {
  return apiRequest<AiMemoryItem>('/ai/memories', { method: 'POST', body: JSON.stringify(payload) })
}

export function patchAiMemory(
  id: string,
  payload: { target?: 'user' | 'memory'; content?: string },
): Promise<AiMemoryItem> {
  return apiRequest<AiMemoryItem>(`/ai/memories/${encodeURIComponent(id)}`, {
    method: 'PATCH',
    body: JSON.stringify(payload),
  })
}

export function deleteAiMemory(id: string): Promise<void> {
  return apiRequest<void>(`/ai/memories/${encodeURIComponent(id)}`, { method: 'DELETE' })
}

export function sendAiMessage(
  id: string,
  message: string,
  runtime: {
    provider?: string
    model?: string
    thinking?: string
    images?: string[]
    skill_slug?: string
  } = {},
): Promise<{ run_id: string }> {
  return apiRequest<{ run_id: string }>(`/ai/sessions/${encodeURIComponent(id)}/messages`, {
    method: 'POST',
    body: JSON.stringify({ message, ...runtime }),
  })
}

export function compactAiSession(id: string): Promise<{
  compacted: boolean
  tokens_before: number
  tokens_after: number
  removed?: number
  kept?: number
  method?: string
  message?: string
}> {
  return apiRequest(`/ai/sessions/${encodeURIComponent(id)}/compact`, { method: 'POST' })
}

export function getAiRun(id: string): Promise<AiRun> {
  return apiRequest<AiRun>(`/ai/runs/${encodeURIComponent(id)}`)
}

export function cancelAiRun(id: string): Promise<AiRun> {
  return apiRequest<AiRun>(`/ai/runs/${encodeURIComponent(id)}/cancel`, { method: 'POST' })
}

export function getAiTools(): Promise<AiToolsCatalog> {
  return apiRequest<AiToolsCatalog>('/ai/tools')
}

export async function getAiRunEvents(runId: string, after?: string): Promise<AiRunEventsPage> {
  const params = new URLSearchParams()
  if (after) params.set('after', after)
  const suffix = params.toString()
  return apiRequest<AiRunEventsPage>(`/ai/runs/${encodeURIComponent(runId)}/events${suffix ? `?${suffix}` : ''}`)
}

/** SSE is optional at rollout time; a JSON response lets the host fall back to polling.
 * Event types consumed by assistantRunState: think, token, tool_*, artifact, waiting_user, done.
 * Session messages may carry thinking, tool_receipts, artifacts, hitl when backend persists them.
 */
export async function streamAiRunEvents(
  runId: string,
  after: string | undefined,
  onEvent: (event: AiRunEvent) => void,
  signal: AbortSignal,
): Promise<boolean> {
  const params = new URLSearchParams()
  if (after) params.set('after', after)
  const suffix = params.toString()
  const response = await fetch(`${API_ROOT}/ai/runs/${encodeURIComponent(runId)}/events/stream${suffix ? `?${suffix}` : ''}`, {
    credentials: 'same-origin',
    headers: { Accept: 'text/event-stream', ...(after ? { 'Last-Event-ID': after } : {}) },
    signal,
  })
  if (!response.ok) {
    const body: unknown = await response.json().catch(() => null)
    const detail = body && typeof body === 'object' && 'detail' in body ? (body as { detail: unknown }).detail : null
    throw new Error(formatApiDetail(detail, response.status))
  }
  if (!response.headers.get('content-type')?.includes('text/event-stream') || !response.body) return false

  const reader = response.body.getReader()
  const decoder = new TextDecoder()
  let buffer = ''
  try {
    for (;;) {
      const { value, done } = await reader.read()
      buffer += decoder.decode(value ?? new Uint8Array(), { stream: !done })
      const frames = buffer.split(/\r?\n\r?\n/)
      buffer = frames.pop() ?? ''
      for (const frame of frames) {
        if (/^:\s*/.test(frame.trim())) continue
        const type = frame.match(/^event:\s*(.+)$/m)?.[1]?.trim() ?? 'message'
        const dataLines = [...frame.matchAll(/^data:\s?(.*)$/gm)].map((match) => match[1] ?? '')
        if (!dataLines.length) continue
        const raw = dataLines.join('\n')
        if (raw === '[DONE]') continue
        let data: unknown
        try {
          data = JSON.parse(raw)
        } catch {
          data = { value: raw }
        }
        const id = frame.match(/^id:\s*(.+)$/m)?.[1]?.trim()
        onEvent({
          id,
          type,
          data: data && typeof data === 'object' ? data as Record<string, unknown> : { value: data },
        })
      }
      if (done) return true
    }
  } finally {
    reader.releaseLock()
  }
}
