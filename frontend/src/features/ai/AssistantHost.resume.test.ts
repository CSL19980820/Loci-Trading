import { describe, expect, it, vi } from 'vitest'
import { flushPromises } from '@vue/test-utils'

import {
  api,
  mountAssistantHost,
  setupAfterEach,
} from './AssistantHost.test.helpers'

describe('AssistantHost HITL same-run resume', () => {
  setupAfterEach()

  it('keeps the same run_id after waiting_user reply and resumes stream from cursor', async () => {
    const streamAfter: Array<string | undefined> = []
    let firstOnEvent: ((event: { id?: string; type: string; data: Record<string, unknown> }) => void) | undefined

    api.getAiTools.mockResolvedValue({ provider_configured: true, tools: [] })
    api.listAiSessions.mockResolvedValue([])
    api.createAiSession.mockResolvedValue({ id: 'session-1', title: '运行', status: 'idle', messages: [] })
    api.sendAiMessage
      .mockResolvedValueOnce({ run_id: 'run-1' })
      .mockResolvedValueOnce({ run_id: 'run-1' })
    api.streamAiRunEvents.mockImplementation(async (id, after, onEvent) => {
      streamAfter.push(after == null ? undefined : String(after))
      if (streamAfter.length === 1) {
        firstOnEvent = onEvent
        return new Promise<boolean>(() => undefined)
      }
      onEvent({ id: 'evt-resume', type: 'token', data: { delta: '续上了' } })
      onEvent({ id: 'evt-done', type: 'done', data: { text: '续上了' } })
      return true
    })
    api.getAiRun.mockResolvedValue({ id: 'run-1', session_id: 'session-1', status: 'done' })
    api.getAiSession.mockResolvedValue({ id: 'session-1', title: '运行', status: 'idle', messages: [] })

    const wrapper = mountAssistantHost({
      AssistantPanel: {
        props: ['waitingUser', 'messages', 'busy'],
        emits: ['send'],
        template: `
          <div data-panel>
            waiting={{ waitingUser }} busy={{ busy }}
            {{ messages.map((m) => m.role + ':' + (m.content || '').slice(0, 8) + ':' + (m.status || '')).join('|') }}
            <button data-send @click="$emit('send', '首轮')" />
            <button data-reply @click="$emit('send', '确认继续')" />
          </div>
        `,
      },
    })

    await wrapper.get('[data-open]').trigger('click')
    await flushPromises()
    await wrapper.get('[data-send]').trigger('click')
    await flushPromises()

    firstOnEvent?.({ id: 'evt-wait', type: 'waiting_user', data: { prompt: '是否继续？' } })
    await flushPromises()
    expect(wrapper.get('[data-panel]').text()).toContain('waiting=true')

    await wrapper.get('[data-reply]').trigger('click')
    await flushPromises()

    expect(api.sendAiMessage).toHaveBeenCalledTimes(2)
    await expect(api.sendAiMessage.mock.results[1]?.value).resolves.toEqual({ run_id: 'run-1' })
    expect(streamAfter.length).toBeGreaterThanOrEqual(2)
    // 续跑从 waiting_user 事件 cursor 接着拉，而不是从头重放
    expect(streamAfter[1]).toBe('evt-wait')
    expect(wrapper.get('[data-panel]').text()).toContain('waiting=false')
    expect(wrapper.get('[data-panel]').text()).toContain('确认继续')
    wrapper.unmount()
  })
})
