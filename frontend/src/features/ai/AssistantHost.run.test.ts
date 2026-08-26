import { describe, expect, it, vi } from 'vitest'
import { flushPromises } from '@vue/test-utils'

import {
  api,
  deferred,
  mountAssistantHost,
  setupAfterEach,
} from './AssistantHost.test.helpers'

describe('AssistantHost run', () => {
  setupAfterEach()

  it('does not report an error when a completed SSE run aborts its reader', async () => {
    api.getAiTools.mockResolvedValue({ provider_configured: true, tools: [] })
    api.listAiSessions.mockResolvedValue([])
    api.createAiSession.mockResolvedValue({ id: 'session-1', title: '运行', status: 'idle', messages: [] })
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
    api.getAiTools.mockResolvedValue({ provider_configured: true, tools: [] })
    api.listAiSessions.mockResolvedValue([])
    api.createAiSession.mockResolvedValue({ id: 'session-1', title: '运行', status: 'idle', messages: [] })
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

  it('does not start a second run while session creation is pending', async () => {
    const creating = deferred<{ id: string; title: string; status: 'idle'; messages: [] }>()
    api.getAiTools.mockResolvedValue({ provider_configured: true, tools: [] })
    api.listAiSessions.mockResolvedValue([])
    api.createAiSession.mockReturnValue(creating.promise)
    api.sendAiMessage.mockResolvedValue({ run_id: 'run-1' })
    api.streamAiRunEvents.mockResolvedValue(false)
    api.getAiRunEvents.mockResolvedValue({ events: [], after: '0' })
    api.getAiRun.mockResolvedValue({ id: 'run-1', session_id: 'session-1', status: 'done' })
    const wrapper = mountAssistantHost({
      AssistantPanel: {
        emits: ['send'],
        template: '<div><button data-send @click="$emit(\'send\', \'测试\')" /></div>',
      },
    })

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

  it('does not let an old cancellation response finish a newer run', async () => {
    const cancelled = deferred<{ id: string; session_id: string; status: 'cancelled' }>()
    const streamEvents = new Map<string, (event: { type: string; data: Record<string, unknown> }) => void>()
    api.getAiTools.mockResolvedValue({ provider_configured: true, tools: [] })
    api.listAiSessions.mockResolvedValue([])
    api.createAiSession.mockResolvedValue({ id: 'session-1', title: '运行', status: 'idle', messages: [] })
    api.sendAiMessage.mockResolvedValueOnce({ run_id: 'run-1' }).mockResolvedValueOnce({ run_id: 'run-2' })
    api.cancelAiRun.mockReturnValue(cancelled.promise)
    api.streamAiRunEvents.mockImplementation((id, _after, onEvent) => {
      streamEvents.set(id, onEvent)
      return new Promise<boolean>(() => undefined)
    })
    const wrapper = mountAssistantHost({
      AssistantPanel: {
        props: ['messages'], emits: ['send', 'cancel'],
        template: '<div data-panel>{{ messages.map((message) => `${message.content}:${message.status}`).join("|") }}<button data-send @click="$emit(\'send\', \'测试\')" /><button data-cancel @click="$emit(\'cancel\')" /></div>',
      },
    })

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

  it('falls back to polling when the optional event stream fails', async () => {
    api.getAiTools.mockResolvedValue({ provider_configured: true, tools: [] })
    api.listAiSessions.mockResolvedValue([])
    api.createAiSession.mockResolvedValue({ id: 'session-1', title: '运行', status: 'idle', messages: [] })
    api.sendAiMessage.mockResolvedValue({ run_id: 'run-1' })
    api.streamAiRunEvents.mockRejectedValue(new Error('SSE unavailable'))
    api.getAiRunEvents.mockResolvedValue({ events: [{ id: '1', type: 'token', data: { delta: '轮询成功' } }], after: '1' })
    api.getAiRun.mockResolvedValue({ id: 'run-1', session_id: 'session-1', status: 'done' })
    api.getAiSession.mockResolvedValue({
      id: 'session-1',
      title: '运行',
      status: 'done',
      messages: [
        { id: 'u1', role: 'user', content: '测试', status: 'done' },
        { id: 'a1', role: 'assistant', content: '轮询成功', status: 'done' },
      ],
    })
    const wrapper = mountAssistantHost({
      AssistantPanel: {
        props: ['messages', 'error'], emits: ['send'],
        template: '<div data-panel>{{ error }} {{ messages.map((message) => `${message.content}:${message.status}`).join("|") }}<button data-send @click="$emit(\'send\', \'测试\')" /></div>',
      },
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
    api.getAiTools.mockResolvedValue({ provider_configured: true, tools: [] })
    api.listAiSessions.mockResolvedValue([])
    api.createAiSession.mockResolvedValue({ id: 'session-1', title: '运行', status: 'idle', messages: [] })
    api.sendAiMessage.mockResolvedValue({ run_id: 'run-1' })
    api.streamAiRunEvents.mockRejectedValue(new Error('SSE unavailable'))
    api.getAiRunEvents
      .mockRejectedValueOnce(new Error('temporary network error'))
      .mockResolvedValueOnce({ events: [{ id: '1', type: 'token', data: { delta: '恢复成功' } }], after: '1' })
    api.getAiRun
      .mockResolvedValueOnce({ id: 'run-1', session_id: 'session-1', status: 'running' })
      .mockResolvedValueOnce({ id: 'run-1', session_id: 'session-1', status: 'done' })
    api.getAiSession.mockResolvedValue({
      id: 'session-1',
      title: '运行',
      status: 'done',
      messages: [
        { id: 'u1', role: 'user', content: '测试', status: 'done' },
        { id: 'a1', role: 'assistant', content: '恢复成功', status: 'done' },
      ],
    })
    const wrapper = mountAssistantHost({
      AssistantPanel: {
        props: ['messages', 'error'], emits: ['send'],
        template: '<div data-panel>{{ error }} {{ messages.map((message) => `${message.content}:${message.status}`).join("|") }}<button data-send @click="$emit(\'send\', \'测试\')" /></div>',
      },
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

  it('does not start event consumption after the host unmounts during send', async () => {
    const response = deferred<{ run_id: string }>()
    api.getAiTools.mockResolvedValue({ provider_configured: true, tools: [] })
    api.listAiSessions.mockResolvedValue([])
    api.createAiSession.mockResolvedValue({ id: 'session-1', title: '运行', status: 'idle', messages: [] })
    api.sendAiMessage.mockReturnValue(response.promise)
    const wrapper = mountAssistantHost({
      AssistantPanel: { emits: ['send'], template: '<button data-send @click="$emit(\'send\', \'测试\')" />' },
    })

    await wrapper.get('[data-open]').trigger('click')
    await flushPromises()
    await wrapper.get('[data-send]').trigger('click')
    wrapper.unmount()
    response.resolve({ run_id: 'run-1' })
    await flushPromises()

    expect(api.streamAiRunEvents).not.toHaveBeenCalled()
  })

  it('restores waiting_user from session detail and passes waiting-user to the panel', async () => {
    api.getAiTools.mockResolvedValue({ provider_configured: true, tools: [] })
    api.listAiSessions.mockResolvedValue([{ id: 'session-wait', title: '等待回复', status: 'waiting_user' }])
    api.getAiSession.mockResolvedValue({
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
    })
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
    api.getAiTools.mockResolvedValue({ provider_configured: true, tools: [] })
    api.listAiSessions.mockResolvedValue([])
    api.createAiSession.mockResolvedValue({ id: 'session-1', title: '运行', status: 'idle', messages: [] })
    api.sendAiMessage.mockResolvedValue({ run_id: 'run-1' })
    api.streamAiRunEvents.mockResolvedValue(true)
    api.getAiRun.mockResolvedValue({ id: 'run-1', session_id: 'session-1', status: 'waiting_user' })
    api.getAiSession.mockResolvedValue({ id: 'session-1', title: '运行', status: 'waiting_user', messages: [] })
    const wrapper = mountAssistantHost({
      AssistantPanel: {
        props: ['messages', 'waitingUser', 'error'],
        emits: ['send'],
        template: '<div data-panel>waiting={{ waitingUser }} {{ error }} {{ messages.map((message) => `${message.content}:${message.status}`).join("|") }}<button data-send @click="$emit(\'send\', \'测试\')" /></div>',
      },
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

  it('resumes a running active_run with stream/poll after selecting the session', async () => {
    api.getAiTools.mockResolvedValue({ provider_configured: true, tools: [] })
    api.listAiSessions.mockResolvedValue([{ id: 'session-run', title: '续跑', status: 'running' }])
    api.getAiSession.mockImplementation(async () => ({
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
    api.getAiRun.mockResolvedValue({ id: 'run-resume', session_id: 'session-run', status: 'done' })
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

  it('maps cancel responses that still report waiting_user to cancelled', async () => {
    api.getAiTools.mockResolvedValue({ provider_configured: true, tools: [] })
    api.listAiSessions.mockResolvedValue([])
    api.createAiSession.mockResolvedValue({ id: 'session-1', title: '运行', status: 'idle', messages: [] })
    api.sendAiMessage.mockResolvedValue({ run_id: 'run-1' })
    api.streamAiRunEvents.mockImplementation((_id, _after, onEvent) => {
      onEvent({ type: 'waiting_user', data: { prompt: '确认？' } })
      return Promise.resolve(false)
    })
    api.cancelAiRun.mockResolvedValue({ id: 'run-1', session_id: 'session-1', status: 'waiting_user' })
    api.getAiSession.mockResolvedValue({
      id: 'session-1',
      title: '运行',
      status: 'cancelled',
      messages: [
        { id: 'u1', role: 'user', content: '测试', status: 'done' },
        { id: 'a1', role: 'assistant', content: '确认？', status: 'cancelled' },
      ],
    })
    const wrapper = mountAssistantHost({
      AssistantPanel: {
        props: ['messages', 'waitingUser'],
        emits: ['send', 'cancel'],
        template: '<div data-panel>waiting={{ waitingUser }} {{ messages.map((message) => `${message.content}:${message.status}`).join("|") }}<button data-send @click="$emit(\'send\', \'测试\')" /><button data-cancel @click="$emit(\'cancel\')" /></div>',
      },
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

  it('clears sticky send errors on the next successful send', async () => {
    api.getAiTools.mockResolvedValue({ provider_configured: true, tools: [] })
    api.listAiSessions.mockResolvedValue([])
    api.createAiSession.mockResolvedValue({ id: 'session-1', title: '运行', status: 'idle', messages: [] })
    api.sendAiMessage
      .mockRejectedValueOnce(new Error('network down'))
      .mockResolvedValueOnce({ run_id: 'run-2' })
    api.streamAiRunEvents.mockImplementation((_id, _after, onEvent) => {
      onEvent({ type: 'token', data: { delta: '补记成功' } })
      onEvent({ type: 'done', data: {} })
      return Promise.resolve(true)
    })
    api.getAiRun.mockResolvedValue({ id: 'run-2', session_id: 'session-1', status: 'done' })
    api.getAiSession.mockResolvedValue({
      id: 'session-1',
      title: '运行',
      status: 'done',
      messages: [
        { id: 'u2', role: 'user', content: '补交割', status: 'done' },
        { id: 'a2', role: 'assistant', content: '补记成功', status: 'done' },
      ],
    })

    const wrapper = mountAssistantHost({
      AssistantPanel: {
        props: ['messages', 'error'],
        emits: ['send'],
        template: '<div data-panel>error={{ error }} {{ messages.map((message) => `${message.content}:${message.status}`).join("|") }}<button data-send @click="$emit(\'send\', \'补交割\')" /></div>',
      },
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

  it('force-finishes locally when cancel API fails so the next send is not blocked', async () => {
    api.getAiTools.mockResolvedValue({ provider_configured: true, tools: [] })
    api.listAiSessions.mockResolvedValue([])
    api.createAiSession.mockResolvedValue({ id: 'session-1', title: '运行', status: 'idle', messages: [] })
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
    api.getAiRun.mockResolvedValue({ id: 'run-2', session_id: 'session-1', status: 'done' })
    api.getAiSession.mockImplementation(async () => ({
      id: 'session-1',
      title: '运行',
      status: 'idle',
      messages: [
        { id: 'u1', role: 'user', content: '继续', status: 'done' },
        { id: 'a1', role: 'assistant', content: '已中止', status: 'cancelled' },
      ],
    }))

    const wrapper = mountAssistantHost({
      AssistantPanel: {
        props: ['messages', 'error', 'busy'],
        emits: ['send', 'cancel'],
        template: '<div data-panel>busy={{ busy }} error={{ error }} {{ messages.map((message) => `${message.content}:${message.status}`).join("|") }}<button data-send @click="$emit(\'send\', \'继续\')" /><button data-cancel @click="$emit(\'cancel\')" /></div>',
      },
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

    api.getAiSession.mockResolvedValue({
      id: 'session-1',
      title: '运行',
      status: 'done',
      messages: [
        { id: 'u2', role: 'user', content: '继续', status: 'done' },
        { id: 'a2', role: 'assistant', content: '继续记账', status: 'done' },
      ],
    })
    await wrapper.get('[data-send]').trigger('click')
    await flushPromises()
    expect(wrapper.get('[data-panel]').text()).toContain('继续记账')
    expect(api.sendAiMessage).toHaveBeenCalledTimes(2)
    wrapper.unmount()
  })

  it('falls back to polling when the SSE stream ends while the run is still running', async () => {
    vi.useFakeTimers()
    api.getAiTools.mockResolvedValue({ provider_configured: true, tools: [] })
    api.listAiSessions.mockResolvedValue([])
    api.createAiSession.mockResolvedValue({ id: 'session-1', title: '运行', status: 'idle', messages: [] })
    api.sendAiMessage.mockResolvedValue({ run_id: 'run-1' })
    api.streamAiRunEvents.mockImplementation(async (_id, _after, onEvent) => {
      onEvent({ id: '1', type: 'tool_end', data: { call_id: 't1', name: 'ledger_positions', ok: true } })
      // 模拟 WebView/代理断流：连接结束但 run 仍在跑、done 未到
      return true
    })
    api.getAiRun
      .mockResolvedValueOnce({ id: 'run-1', session_id: 'session-1', status: 'running' })
      .mockResolvedValue({ id: 'run-1', session_id: 'session-1', status: 'done' })
    api.getAiRunEvents.mockResolvedValue({
      events: [{ id: '2', type: 'done', data: { text: '断流后续上了', content: '断流后续上了' } }],
      after: '2',
    })
    api.getAiSession.mockResolvedValue({
      id: 'session-1',
      title: '运行',
      status: 'done',
      messages: [
        { id: 'u1', role: 'user', content: '测试', status: 'done' },
        { id: 'a1', role: 'assistant', content: '断流后续上了', status: 'done' },
      ],
    })
    const wrapper = mountAssistantHost({
      AssistantPanel: {
        props: ['messages'],
        emits: ['send'],
        template: '<div data-panel>{{ messages.map((message) => `${message.content}:${message.status}`).join("|") }}<button data-send @click="$emit(\'send\', \'测试\')" /></div>',
      },
    })

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

  it('refetches session messages after a done-only stream so empty bubbles get server content', async () => {
    api.getAiTools.mockResolvedValue({ provider_configured: true, tools: [] })
    api.listAiSessions.mockResolvedValue([])
    api.createAiSession.mockResolvedValue({ id: 'session-1', title: '运行', status: 'idle', messages: [] })
    api.sendAiMessage.mockResolvedValue({ run_id: 'run-1' })
    api.streamAiRunEvents.mockImplementation(async (_id, _after, onEvent) => {
      onEvent({ type: 'done', data: {} })
      return false
    })
    api.getAiSession.mockResolvedValue({
      id: 'session-1',
      title: '运行',
      status: 'done',
      messages: [
        { id: 'u1', role: 'user', content: '测试', status: 'done' },
        { id: 'a1', role: 'assistant', content: '服务端落盘的完整答复', status: 'done' },
      ],
    })
    const wrapper = mountAssistantHost({
      AssistantPanel: {
        props: ['messages'],
        emits: ['send'],
        template: '<div data-panel>{{ messages.map((message) => `${message.content}:${message.status}`).join("|") }}<button data-send @click="$emit(\'send\', \'测试\')" /></div>',
      },
    })

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
    api.getAiTools.mockResolvedValue({ provider_configured: true, tools: [] })
    api.listAiSessions.mockResolvedValue([])
    api.createAiSession.mockResolvedValue({ id: 'session-1', title: '运行', status: 'idle', messages: [] })
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
      return {
        id: 'session-1',
        title: '运行',
        status: 'running',
        messages: [
          { id: 'u1', role: 'user' as const, content: '第一问', status: 'done' },
          { id: 'a1', role: 'assistant' as const, content: '第一答', status: 'done' },
          { id: 'u2', role: 'user' as const, content: '第二问', status: 'done' },
        ],
      } as never
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
      AssistantPanel: {
        props: ['messages', 'busy'],
        emits: ['send'],
        template: '<div data-panel>{{ messages.map((message) => `${message.role}:${message.content}`).join("|") }}<button data-send @click="$emit(\'send\', messages.some((row) => row.content === \'第一问\') ? \'第二问\' : \'第一问\')" /></div>',
      },
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
