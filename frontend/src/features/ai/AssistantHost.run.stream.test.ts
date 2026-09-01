/**
 * AssistantHost 运行循环 · SSE 流与轮询回落。
 * 共享 mock / fixture 在 `AssistantHost.test.helpers.ts`（`vi.mock` 也在那里，模块级提升）。
 */
import { describe, expect, it, vi } from 'vitest'
import { flushPromises } from '@vue/test-utils'

import {
  aiRun,
  api,
  mountAssistantHost,
  primeAssistantReady,
  primeNewSession,
  sessionDetail,
  setupAfterEach,
  transcriptPanel,
} from './AssistantHost.test.helpers'

describe('AssistantHost run · 流与轮询', () => {
  setupAfterEach()

  it('does not report an error when a completed SSE run aborts its reader', async () => {
    primeNewSession()
    api.sendAiMessage.mockResolvedValue({ run_id: 'run-1' })
    api.streamAiRunEvents.mockImplementation(async (_id, _after, onEvent) => {
      onEvent({ type: 'done', data: {} })
      throw new DOMException('The operation was aborted.', 'AbortError')
    })
    const wrapper = mountAssistantHost({
      AssistantPanel: {
        props: ['error'], emits: ['send'],
        template: '<div data-panel>{{ error }}<button data-send @click="$emit(\'send\', \'测试\')" /></div>',
      },
    })

    await wrapper.get('[data-open]').trigger('click')
    await flushPromises()
    await wrapper.get('[data-send]').trigger('click')
    await flushPromises()

    expect(wrapper.find('[data-panel]').text()).not.toContain('运行事件消费失败')
    wrapper.unmount()
  })

  it('closing the panel leaves an active stream running', async () => {
    let signal: AbortSignal | undefined
    primeNewSession()
    api.sendAiMessage.mockResolvedValue({ run_id: 'run-1' })
    api.streamAiRunEvents.mockImplementation((_id, _after, _onEvent, nextSignal) => new Promise<boolean>((resolve) => {
      signal = nextSignal
      nextSignal.addEventListener('abort', () => resolve(true), { once: true })
    }))
    const wrapper = mountAssistantHost({
      AssistantPanel: {
        emits: ['send', 'close'],
        template: '<div><button data-send @click="$emit(\'send\', \'测试\')" /><button data-close @click="$emit(\'close\')" /></div>',
      },
    })

    await wrapper.get('[data-open]').trigger('click')
    await flushPromises()
    await wrapper.get('[data-send]').trigger('click')
    await flushPromises()
    await wrapper.get('[data-close]').trigger('click')

    expect(api.cancelAiRun).not.toHaveBeenCalled()
    expect(signal?.aborted).toBe(false)
    wrapper.unmount()
  })

  it('falls back to polling when the optional event stream fails', async () => {
    primeNewSession()
    api.sendAiMessage.mockResolvedValue({ run_id: 'run-1' })
    api.streamAiRunEvents.mockRejectedValue(new Error('SSE unavailable'))
    api.getAiRunEvents.mockResolvedValue({ events: [{ id: '1', type: 'token', data: { delta: '轮询成功' } }], after: '1' })
    api.getAiRun.mockResolvedValue(aiRun())
    api.getAiSession.mockResolvedValue(sessionDetail({
      status: 'done',
      messages: [
        { id: 'u1', role: 'user', content: '测试', status: 'done' },
        { id: 'a1', role: 'assistant', content: '轮询成功', status: 'done' },
      ],
    }))
    const wrapper = mountAssistantHost({
      AssistantPanel: transcriptPanel({ props: ['error'], lead: '{{ error }} ' }),
    })

    await wrapper.get('[data-open]').trigger('click')
    await flushPromises()
    await wrapper.get('[data-send]').trigger('click')
    await flushPromises()
    await flushPromises()

    expect(api.getAiRunEvents).toHaveBeenCalled()
    expect(wrapper.get('[data-panel]').text()).toContain('轮询成功:done')
    expect(wrapper.get('[data-panel]').text()).not.toContain('运行事件消费失败')
    wrapper.unmount()
  })

  it('retries a transient polling failure after SSE falls back, then uses the server terminal state', async () => {
    vi.useFakeTimers()
    primeNewSession()
    api.sendAiMessage.mockResolvedValue({ run_id: 'run-1' })
    api.streamAiRunEvents.mockRejectedValue(new Error('SSE unavailable'))
    api.getAiRunEvents
      .mockRejectedValueOnce(new Error('temporary network error'))
      .mockResolvedValueOnce({ events: [{ id: '1', type: 'token', data: { delta: '恢复成功' } }], after: '1' })
    api.getAiRun
      .mockResolvedValueOnce(aiRun({ status: 'running' }))
      .mockResolvedValueOnce(aiRun())
    api.getAiSession.mockResolvedValue(sessionDetail({
      status: 'done',
      messages: [
        { id: 'u1', role: 'user', content: '测试', status: 'done' },
        { id: 'a1', role: 'assistant', content: '恢复成功', status: 'done' },
      ],
    }))
    const wrapper = mountAssistantHost({
      AssistantPanel: transcriptPanel({ props: ['error'], lead: '{{ error }} ' }),
    })

    await wrapper.get('[data-open]').trigger('click')
    await flushPromises()
    await wrapper.get('[data-send]').trigger('click')
    await flushPromises()

    expect(api.getAiRunEvents).toHaveBeenCalledTimes(1)
    expect(wrapper.get('[data-panel]').text()).toContain(':streaming')
    expect(wrapper.get('[data-panel]').text()).not.toContain('运行事件消费失败')

    await vi.advanceTimersByTimeAsync(1_000)
    await flushPromises()

    expect(api.getAiRunEvents).toHaveBeenCalledTimes(2)
    expect(wrapper.get('[data-panel]').text()).toContain('恢复成功:done')
    expect(wrapper.get('[data-panel]').text()).not.toContain('运行事件消费失败')
    wrapper.unmount()
  })

  it('resumes a running active_run with stream/poll after selecting the session', async () => {
    primeAssistantReady([{ id: 'session-run', title: '续跑', status: 'running' }])
    api.getAiSession.mockImplementation(async () => sessionDetail({
      id: 'session-run',
      title: '续跑',
      status: 'running',
      messages: [
        { id: 'm1', role: 'user', content: '继续', status: 'done' },
        { id: 'a1', role: 'assistant', content: '', status: 'streaming' },
      ],
      active_run: { id: 'run-resume', session_id: 'session-run', status: 'running', cursor: '42' },
    }))
    api.streamAiRunEvents.mockResolvedValue(false)
    api.getAiRunEvents.mockResolvedValue({ events: [{ id: '43', type: 'token', data: { delta: '续上了' } }], after: '43' })
    api.getAiRun.mockResolvedValue(aiRun({ id: 'run-resume', session_id: 'session-run' }))
    const wrapper = mountAssistantHost({
      AssistantPanel: {
        props: ['messages'],
        template: '<div data-panel>{{ messages.map((message) => message.content).join("|") }}</div>',
      },
    })

    await wrapper.get('[data-open]').trigger('click')
    await flushPromises()
    await flushPromises()

    expect(api.streamAiRunEvents).toHaveBeenCalledWith('run-resume', undefined, expect.any(Function), expect.any(AbortSignal))
    expect(api.getAiRunEvents).toHaveBeenCalledWith('run-resume', undefined)
    expect(wrapper.get('[data-panel]').text()).toContain('续上了')
    wrapper.unmount()
  })

  it('falls back to polling when the SSE stream ends while the run is still running', async () => {
    vi.useFakeTimers()
    primeNewSession()
    api.sendAiMessage.mockResolvedValue({ run_id: 'run-1' })
    api.streamAiRunEvents.mockImplementation(async (_id, _after, onEvent) => {
      onEvent({ id: '1', type: 'tool_end', data: { call_id: 't1', name: 'ledger_positions', ok: true } })
      // 模拟 WebView/代理断流：连接结束但 run 仍在跑、done 未到
      return true
    })
    api.getAiRun
      .mockResolvedValueOnce(aiRun({ status: 'running' }))
      .mockResolvedValue(aiRun())
    api.getAiRunEvents.mockResolvedValue({
      events: [{ id: '2', type: 'done', data: { text: '断流后续上了', content: '断流后续上了' } }],
      after: '2',
    })
    api.getAiSession.mockResolvedValue(sessionDetail({
      status: 'done',
      messages: [
        { id: 'u1', role: 'user', content: '测试', status: 'done' },
        { id: 'a1', role: 'assistant', content: '断流后续上了', status: 'done' },
      ],
    }))
    const wrapper = mountAssistantHost({ AssistantPanel: transcriptPanel() })

    await wrapper.get('[data-open]').trigger('click')
    await flushPromises()
    await wrapper.get('[data-send]').trigger('click')
    await flushPromises()

    expect(api.getAiRunEvents).toHaveBeenCalled()
    await vi.advanceTimersByTimeAsync(800)
    await flushPromises()

    expect(wrapper.get('[data-panel]').text()).toContain('断流后续上了')
    wrapper.unmount()
    vi.useRealTimers()
  })
})
