/**
 * AssistantHost 运行循环 · waiting_user（HITL）与中止收口。
 * 共享 mock / fixture 在 `AssistantHost.test.helpers.ts`（`vi.mock` 也在那里，模块级提升）。
 */
import { describe, expect, it } from 'vitest'
import { flushPromises } from '@vue/test-utils'

import {
  aiRun,
  api,
  deferred,
  mountAssistantHost,
  primeAssistantReady,
  primeNewSession,
  sessionDetail,
  setupAfterEach,
  transcriptPanel,
} from './AssistantHost.test.helpers'

describe('AssistantHost run · 等待回复与中止', () => {
  setupAfterEach()

  it('does not let an old cancellation response finish a newer run', async () => {
    const cancelled = deferred<{ id: string; session_id: string; status: 'cancelled' }>()
    const streamEvents = new Map<string, (event: { type: string; data: Record<string, unknown> }) => void>()
    primeNewSession()
    api.sendAiMessage.mockResolvedValueOnce({ run_id: 'run-1' }).mockResolvedValueOnce({ run_id: 'run-2' })
    api.cancelAiRun.mockReturnValue(cancelled.promise)
    api.streamAiRunEvents.mockImplementation((id, _after, onEvent) => {
      streamEvents.set(id, onEvent)
      return new Promise<boolean>(() => undefined)
    })
    const wrapper = mountAssistantHost({ AssistantPanel: transcriptPanel({ cancel: true }) })

    await wrapper.get('[data-open]').trigger('click')
    await flushPromises()
    await wrapper.get('[data-send]').trigger('click')
    await flushPromises()
    await wrapper.get('[data-cancel]').trigger('click')
    streamEvents.get('run-1')?.({ type: 'done', data: {} })
    await flushPromises()
    await wrapper.get('[data-send]').trigger('click')
    await flushPromises()
    cancelled.resolve({ id: 'run-1', session_id: 'session-1', status: 'cancelled' })
    await flushPromises()

    expect(wrapper.get('[data-panel]').text()).toContain(':streaming')
    expect(wrapper.get('[data-panel]').text()).not.toContain('已中止')
    wrapper.unmount()
  })

  it('restores waiting_user from session detail and passes waiting-user to the panel', async () => {
    primeAssistantReady([{ id: 'session-wait', title: '等待回复', status: 'waiting_user' }])
    api.getAiSession.mockResolvedValue(sessionDetail({
      id: 'session-wait',
      title: '等待回复',
      status: 'waiting_user',
      messages: [{ id: 'm1', role: 'assistant', content: '请确认？', status: 'done' }],
      active_run: {
        id: 'run-wait',
        session_id: 'session-wait',
        status: 'waiting_user',
        pending_ask: { prompt: '是否提交潜龙精选？', options: ['提交', '再看看'] },
      },
    }))
    const wrapper = mountAssistantHost({
      AssistantPanel: {
        props: ['waitingUser', 'busy', 'messages'],
        template: '<div data-panel>waiting={{ waitingUser }} busy={{ busy }} hitl={{ messages.at(-1)?.hitl?.options?.join(",") }}</div>',
      },
    })

    await wrapper.get('[data-open]').trigger('click')
    await flushPromises()

    expect(wrapper.get('[data-panel]').text()).toContain('waiting=true')
    expect(wrapper.get('[data-panel]').text()).toContain('busy=false')
    expect(wrapper.get('[data-panel]').text()).toContain('hitl=提交,再看看')
    expect(api.streamAiRunEvents).not.toHaveBeenCalled()
    expect(api.getAiRunEvents).not.toHaveBeenCalled()
    wrapper.unmount()
  })

  it('does not mark the assistant as failed when getAiRun reports waiting_user', async () => {
    primeNewSession()
    api.sendAiMessage.mockResolvedValue({ run_id: 'run-1' })
    api.streamAiRunEvents.mockResolvedValue(true)
    api.getAiRun.mockResolvedValue(aiRun({ status: 'waiting_user' }))
    api.getAiSession.mockResolvedValue(sessionDetail({ status: 'waiting_user' }))
    const wrapper = mountAssistantHost({
      AssistantPanel: transcriptPanel({
        props: ['waitingUser', 'error'],
        lead: 'waiting={{ waitingUser }} {{ error }} ',
      }),
    })

    await wrapper.get('[data-open]').trigger('click')
    await flushPromises()
    await wrapper.get('[data-send]').trigger('click')
    await flushPromises()

    expect(wrapper.get('[data-panel]').text()).toContain('waiting=true')
    expect(wrapper.get('[data-panel]').text()).not.toContain('助手运行失败')
    expect(wrapper.get('[data-panel]').text()).not.toContain(':error')
    wrapper.unmount()
  })

  it('maps cancel responses that still report waiting_user to cancelled', async () => {
    primeNewSession()
    api.sendAiMessage.mockResolvedValue({ run_id: 'run-1' })
    api.streamAiRunEvents.mockImplementation((_id, _after, onEvent) => {
      onEvent({ type: 'waiting_user', data: { prompt: '确认？' } })
      return Promise.resolve(false)
    })
    api.cancelAiRun.mockResolvedValue(aiRun({ status: 'waiting_user' }))
    api.getAiSession.mockResolvedValue(sessionDetail({
      status: 'cancelled',
      messages: [
        { id: 'u1', role: 'user', content: '测试', status: 'done' },
        { id: 'a1', role: 'assistant', content: '确认？', status: 'cancelled' },
      ],
    }))
    const wrapper = mountAssistantHost({
      AssistantPanel: transcriptPanel({
        props: ['waitingUser'],
        lead: 'waiting={{ waitingUser }} ',
        cancel: true,
      }),
    })

    await wrapper.get('[data-open]').trigger('click')
    await flushPromises()
    await wrapper.get('[data-send]').trigger('click')
    await flushPromises()
    expect(wrapper.get('[data-panel]').text()).toContain('waiting=true')

    await wrapper.get('[data-cancel]').trigger('click')
    await flushPromises()

    expect(wrapper.get('[data-panel]').text()).toContain('waiting=false')
    expect(wrapper.get('[data-panel]').text()).toMatch(/确认？:cancelled|已中止:cancelled/)
    wrapper.unmount()
  })

  it('force-finishes locally when cancel API fails so the next send is not blocked', async () => {
    primeNewSession()
    api.sendAiMessage
      .mockResolvedValueOnce({ run_id: 'run-1' })
      .mockResolvedValueOnce({ run_id: 'run-2' })
    api.streamAiRunEvents.mockImplementation((id, _after, onEvent) => {
      if (id === 'run-2') {
        onEvent({ type: 'token', data: { delta: '继续记账' } })
        onEvent({ type: 'done', data: {} })
        return Promise.resolve(true)
      }
      return new Promise<boolean>(() => undefined)
    })
    api.cancelAiRun.mockRejectedValue(new Error('cancel unavailable'))
    api.getAiRun.mockResolvedValue(aiRun({ id: 'run-2' }))
    api.getAiSession.mockImplementation(async () => sessionDetail({
      messages: [
        { id: 'u1', role: 'user', content: '继续', status: 'done' },
        { id: 'a1', role: 'assistant', content: '已中止', status: 'cancelled' },
      ],
    }))

    const wrapper = mountAssistantHost({
      AssistantPanel: transcriptPanel({
        props: ['error', 'busy'],
        lead: 'busy={{ busy }} error={{ error }} ',
        sendText: '继续',
        cancel: true,
      }),
    })

    await wrapper.get('[data-open]').trigger('click')
    await flushPromises()
    await wrapper.get('[data-send]').trigger('click')
    await flushPromises()
    expect(wrapper.get('[data-panel]').text()).toContain('busy=true')

    await wrapper.get('[data-cancel]').trigger('click')
    await flushPromises()
    expect(wrapper.get('[data-panel]').text()).toContain('busy=false')
    expect(wrapper.get('[data-panel]').text()).toMatch(/已中止/)

    api.getAiSession.mockResolvedValue(sessionDetail({
      status: 'done',
      messages: [
        { id: 'u2', role: 'user', content: '继续', status: 'done' },
        { id: 'a2', role: 'assistant', content: '继续记账', status: 'done' },
      ],
    }))
    await wrapper.get('[data-send]').trigger('click')
    await flushPromises()
    expect(wrapper.get('[data-panel]').text()).toContain('继续记账')
    expect(api.sendAiMessage).toHaveBeenCalledTimes(2)
    wrapper.unmount()
  })
})
