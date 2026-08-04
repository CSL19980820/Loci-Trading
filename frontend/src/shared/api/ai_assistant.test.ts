import { afterEach, describe, expect, it, vi } from 'vitest'

import { streamAiRunEvents } from './ai_assistant'

describe('streamAiRunEvents', () => {
  afterEach(() => vi.unstubAllGlobals())

  it('uses the dedicated SSE path and parses persisted event frames', async () => {
    const fetchMock = vi.fn().mockResolvedValue(new Response(
      new ReadableStream<Uint8Array>({
        start(controller) {
          controller.enqueue(new TextEncoder().encode(
            'id: AIE-2\nevent: token\ndata: {"delta":"流式内容"}\n\n',
          ))
          controller.close()
        },
      }),
      { headers: { 'content-type': 'text/event-stream' } },
    ))
    vi.stubGlobal('fetch', fetchMock)
    const events: Array<{ id?: string | number; type: string; data: Record<string, unknown> }> = []

    const streamed = await streamAiRunEvents('run-1', 'AIE-1', (event) => events.push(event), new AbortController().signal)

    expect(streamed).toBe(true)
    expect(fetchMock).toHaveBeenCalledWith(
      expect.stringContaining('/ai/runs/run-1/events/stream?after=AIE-1'),
      expect.objectContaining({ headers: expect.objectContaining({ 'Last-Event-ID': 'AIE-1' }) }),
    )
    expect(events).toEqual([{ id: 'AIE-2', type: 'token', data: { delta: '流式内容' } }])
  })

  it('returns false for a non-SSE response so the host can poll', async () => {
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue(new Response('{}', {
      headers: { 'content-type': 'application/json' },
    })))

    expect(await streamAiRunEvents('run-1', undefined, () => undefined, new AbortController().signal)).toBe(false)
  })
})
