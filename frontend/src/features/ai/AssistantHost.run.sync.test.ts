/**
 * AssistantHost 运行循环 · 发送护栏与会话回填。
 * 共享 mock / fixture 在 `AssistantHost.test.helpers.ts`（`vi.mock` 也在那里，模块级提升）。
 */
import { describe, expect, it, vi } from 'vitest'
import { flushPromises } from '@vue/test-utils'

import {
  aiRun,
  api,
  deferred,
  mountAssistantHost,
  primeAssistantReady,
  primeNewSession,
  sendPanel,
  sessionDetail,
  setupAfterEach,
  transcriptPanel,
  TRANSCRIPT_ROLE_LINE,
} from './AssistantHost.test.helpers'

describe('AssistantHost run · 发送护栏与消息同步', () => {
  setupAfterEach()

  it('does not start a second run while session creation is pending', async () => {
    const creating = deferred<{ id: string; title: string; status: 'idle'; messages: [] }>()
    primeAssistantReady()
    api.createAiSession.mockReturnValue(creating.promise)
    api.sendAiMessage.mockResolvedValue({ run_id: 'run-1' })
    api.streamAiRunEvents.mockResolvedValue(false)
    api.getAiRunEvents.mockResolvedValue({ events: [], after: '0' })
    api.getAiRun.mockResolvedValue(aiRun())
    const wrapper = mountAssistantHost({ AssistantPanel: sendPanel() })

    await wrapper.get('[data-open]').trigger('click')
    await flushPromises()
    await wrapper.get('[data-send]').trigger('click')
    await wrapper.get('[data-send]').trigger('click')
    expect(api.createAiSession).toHaveBeenCalledTimes(1)

    creating.resolve({ id: 'session-1', title: '运行', status: 'idle', messages: [] })
    await flushPromises()
    expect(api.sendAiMessage).toHaveBeenCalledTimes(1)
    wrapper.unmount()
  })

  it('does not start event consumption after the host unmounts during send', async () => {
    const response = deferred<{ run_id: string }>()
    primeNewSession()
    api.sendAiMessage.mockReturnValue(response.promise)
    const wrapper = mountAssistantHost({ AssistantPanel: sendPanel() })

    await wrapper.get('[data-open]').trigger('click')
    await flushPromises()
    await wrapper.get('[data-send]').trigger('click')
    wrapper.unmount()
    response.resolve({ run_id: 'run-1' })
    await flushPromises()

    expect(api.streamAiRunEvents).not.toHaveBeenCalled()
  })

  it('clears sticky send errors on the next successful send', async () => {
    primeNewSession()
    api.sendAiMessage
      .mockRejectedValueOnce(new Error('network down'))
      .mockResolvedValueOnce({ run_id: 'run-2' })
    api.streamAiRunEvents.mockImplementation((_id, _after, onEvent) => {
      onEvent({ type: 'token', data: { delta: '补记成功' } })
      onEvent({ type: 'done', data: {} })
      return Promise.resolve(true)
    })
    api.getAiRun.mockResolvedValue(aiRun({ id: 'run-2' }))
    api.getAiSession.mockResolvedValue(sessionDetail({
      status: 'done',
      messages: [
        { id: 'u2', role: 'user', content: '补交割', status: 'done' },
        { id: 'a2', role: 'assistant', content: '补记成功', status: 'done' },
      ],
    }))

    const wrapper = mountAssistantHost({
      AssistantPanel: transcriptPanel({
        props: ['error'],
        lead: 'error={{ error }} ',
        sendText: '补交割',
      }),
    })

    await wrapper.get('[data-open]').trigger('click')
    await flushPromises()
    await wrapper.get('[data-send]').trigger('click')
    await flushPromises()
    expect(wrapper.get('[data-panel]').text()).toContain('发送失败')
    expect(wrapper.get('[data-panel]').text()).toMatch(/error=.*network down|error=.*发送消息失败/)

    await wrapper.get('[data-send]').trigger('click')
    await flushPromises()

    expect(wrapper.get('[data-panel]').text()).toContain('补记成功')
    expect(wrapper.get('[data-panel]').text()).toContain('error= ')
    expect(wrapper.get('[data-panel]').text()).not.toContain('network down')
    wrapper.unmount()
  })

  it('refetches session messages after a done-only stream so empty bubbles get server content', async () => {
    primeNewSession()
    api.sendAiMessage.mockResolvedValue({ run_id: 'run-1' })
    api.streamAiRunEvents.mockImplementation(async (_id, _after, onEvent) => {
      onEvent({ type: 'done', data: {} })
      return false
    })
    api.getAiSession.mockResolvedValue(sessionDetail({
      status: 'done',
      messages: [
        { id: 'u1', role: 'user', content: '测试', status: 'done' },
        { id: 'a1', role: 'assistant', content: '服务端落盘的完整答复', status: 'done' },
      ],
    }))
    const wrapper = mountAssistantHost({ AssistantPanel: transcriptPanel() })

    await wrapper.get('[data-open]').trigger('click')
    await flushPromises()
    await wrapper.get('[data-send]').trigger('click')
    await flushPromises()

    expect(wrapper.get('[data-panel]').text()).toContain('服务端落盘的完整答复:done')
    expect(api.getAiSession).toHaveBeenCalledWith('session-1')
    wrapper.unmount()
  })

  it('does not let a previous turn delayed sync overwrite the next optimistic turn', async () => {
    vi.useFakeTimers()
    primeNewSession()
    api.sendAiMessage
      .mockResolvedValueOnce({ run_id: 'run-1' })
      .mockResolvedValueOnce({ run_id: 'run-2' })
    const firstSync = deferred<{
      id: string
      title: string
      status: string
      messages: Array<{ id: string; role: 'user' | 'assistant'; content: string; status: string }>
    }>()
    let sessionGets = 0
    api.getAiSession.mockImplementation(async () => {
      sessionGets += 1
      if (sessionGets === 1) return firstSync.promise as never
      return sessionDetail({
        status: 'running',
        messages: [
          { id: 'u1', role: 'user', content: '第一问', status: 'done' },
          { id: 'a1', role: 'assistant', content: '第一答', status: 'done' },
          { id: 'u2', role: 'user', content: '第二问', status: 'done' },
        ],
      }) as never
    })
    api.streamAiRunEvents.mockImplementation(async (runId, _after, onEvent) => {
      if (runId === 'run-1') {
        onEvent({ type: 'done', data: { text: '第一答' } })
        return false
      }
      onEvent({ type: 'token', data: { delta: '第二' } })
      return true
    })
    api.getAiRun.mockImplementation(async (runId) => ({
      id: runId,
      session_id: 'session-1',
      status: runId === 'run-1' ? 'done' : 'running',
      provider: 'p',
      model: 'm',
    }))
    api.getAiRunEvents.mockResolvedValue({ events: [] })

    const wrapper = mountAssistantHost({
      AssistantPanel: transcriptPanel({
        props: ['busy'],
        line: TRANSCRIPT_ROLE_LINE,
        sendExpr: 'messages.some((row) => row.content === \'第一问\') ? \'第二问\' : \'第一问\'',
      }),
    })

    await wrapper.get('[data-open]').trigger('click')
    await flushPromises()
    await wrapper.get('[data-send]').trigger('click')
    await flushPromises()

    // 第二轮已发出时，第一轮延迟 sync 才回填旧 transcript
    await wrapper.get('[data-send]').trigger('click')
    await flushPromises()
    firstSync.resolve({
      id: 'session-1',
      title: '运行',
      status: 'done',
      messages: [
        { id: 'u1', role: 'user', content: '第一问', status: 'done' },
        { id: 'a1', role: 'assistant', content: '第一答', status: 'done' },
      ],
    })
    await flushPromises()
    await vi.advanceTimersByTimeAsync(500)
    await flushPromises()

    const text = wrapper.get('[data-panel]').text()
    expect(text).toContain('user:第一问')
    expect(text).toContain('assistant:第一答')
    expect(text).toContain('user:第二问')
    expect(text).toMatch(/assistant:第二/)
    wrapper.unmount()
    vi.useRealTimers()
  })
})
