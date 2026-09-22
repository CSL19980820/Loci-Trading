import { afterEach, expect, it, vi } from 'vitest'
import { streamEvents } from './event_stream'
import { streamAiRunEvents } from './ai_assistant'
import type { AiRunEvent } from '@/shared/types/ai_assistant'

afterEach(() => vi.unstubAllGlobals())

it('decodes split UTF-8 and SSE frames through the assistant entry point', async () => {
  const bytes = new TextEncoder().encode(': keepalive\n\nid: 7\nevent: token\ndata: {"delta":"中文片段"}\n\nevent: done\ndata: {"ok":true}\n\n')
  const fetchMock = vi.fn().mockResolvedValue(new Response(new ReadableStream({
    start(controller) {
      for (const byte of bytes) controller.enqueue(new Uint8Array([byte]))
      controller.close()
    },
  }), { headers: { 'Content-Type': 'text/event-stream' } }))
  vi.stubGlobal('fetch', fetchMock)
  const events: AiRunEvent[] = []
  const signal = new AbortController().signal
  expect(await streamAiRunEvents('run-1', '6', event => events.push(event), signal)).toBe(true)
  expect(events).toEqual([{id:'7',type:'token',data:{delta:'中文片段'}}, {id:undefined,type:'done',data:{ok:true}}])
  expect(fetchMock).toHaveBeenCalledWith('/api/ai/runs/run-1/events/stream?after=6', expect.objectContaining({signal, headers: expect.objectContaining({'Last-Event-ID':'6'})}))
})

it('allows polling fallback on non-stream responses and propagates cancellation', async () => {
  vi.stubGlobal('fetch', vi.fn().mockResolvedValue(new Response('{}', {headers:{'Content-Type':'application/json'}})))
  expect(await streamEvents('/api/example', () => {}, new AbortController().signal)).toBe(false)
  const aborted = new DOMException('Aborted', 'AbortError')
  vi.stubGlobal('fetch', vi.fn().mockRejectedValue(aborted))
  await expect(streamEvents('/api/example', () => {}, new AbortController().signal)).rejects.toBe(aborted)
})
