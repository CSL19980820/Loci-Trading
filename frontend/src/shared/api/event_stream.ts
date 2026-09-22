import { formatApiDetail } from '@/shared/lib/errors'

export interface StreamEvent { id?: string; type: string; data: Record<string, unknown> }

/** 助手与交易员共享 SSE 解码，支持分块、多行 data 和取消订阅。 */
export async function streamEvents(
  path: string,
  onEvent: (event: StreamEvent) => void,
  signal: AbortSignal,
  after?: string,
): Promise<boolean> {
  const response = await fetch(path, {
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
