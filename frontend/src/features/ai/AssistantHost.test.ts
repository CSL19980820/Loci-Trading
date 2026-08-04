import { flushPromises, mount } from '@vue/test-utils'
import { afterEach, describe, expect, it, vi } from 'vitest'

const api = vi.hoisted(() => ({
  cancelAiRun: vi.fn(), createAiSession: vi.fn(), deleteAiSession: vi.fn(), getAiRun: vi.fn(), getAiRunEvents: vi.fn(),
  getAiSession: vi.fn(), getAiTools: vi.fn(), listAiSessions: vi.fn(), sendAiMessage: vi.fn(), streamAiRunEvents: vi.fn(),
}))
const router = vi.hoisted(() => ({ push: vi.fn() }))
vi.mock('@/shared/api/ai_assistant', () => api)
vi.mock('vue-router', () => ({ useRouter: () => router }))

import AssistantHost from './AssistantHost.vue'

function deferred<T>(): { promise: Promise<T>; resolve: (value: T) => void } {
  let resolve!: (value: T) => void
  return { promise: new Promise<T>((done) => { resolve = done }), resolve }
}

describe('AssistantHost', () => {
  afterEach(() => {
    vi.useRealTimers()
    vi.clearAllMocks()
  })

  it('ignores an older session response after a newer selection wins', async () => {
    const older = deferred<{ id: string; title: string; status: 'idle'; messages: [] }>()
    const newer = deferred<{ id: string; title: string; status: 'idle'; messages: [] }>()
    api.getAiTools.mockResolvedValue({ provider_configured: true, tools: [] })
    api.listAiSessions.mockResolvedValue([])
    api.getAiSession.mockReturnValueOnce(older.promise).mockReturnValueOnce(newer.promise)
    const wrapper = mount(AssistantHost, {
      global: {
        stubs: {
          AssistantFloatBall: { emits: ['toggle'], template: '<button data-open @click="$emit(\'toggle\')" />' },
          AssistantPanel: {
            props: ['messages', 'title', 'error'], emits: ['select', 'send'],
            template: '<div data-panel>{{ title }} {{ error }} {{ messages.map((message) => message.content).join("|") }}<button data-old @click="$emit(\'select\', \'old\')" /><button data-new @click="$emit(\'select\', \'new\')" /><button data-send @click="$emit(\'send\', \'测试\')" /></div>',
          },
        },
      },
    })

    await wrapper.get('[data-open]').trigger('click')
    await flushPromises()
    await wrapper.get('[data-old]').trigger('click')
    await wrapper.get('[data-new]').trigger('click')
    newer.resolve({ id: 'new', title: '新会话', status: 'idle', messages: [] })
    await flushPromises()
    older.resolve({ id: 'old', title: '旧会话', status: 'idle', messages: [] })
    await flushPromises()

    expect(wrapper.find('[data-panel]').text()).toContain('新会话')
    expect(wrapper.find('[data-panel]').text()).not.toContain('旧会话')
    expect(api.getAiSession).toHaveBeenCalledWith('new')
    wrapper.unmount()
  })

  it('refreshes the provider catalog when reopening an existing session', async () => {
    api.getAiTools
      .mockResolvedValueOnce({
        provider_configured: true,
        providers: [{ name: 'old-provider', models: ['old-model'], default_model: 'old-model', is_active: true, is_default: true }],
        tools: [],
      })
      .mockResolvedValueOnce({
        provider_configured: true,
        providers: [{ name: 'new-provider', models: ['new-model'], default_model: 'new-model', is_active: true, is_default: true }],
        tools: [],
      })
    api.listAiSessions.mockResolvedValue([{ id: 'session-1', title: '已有会话', status: 'idle' }])
    api.getAiSession.mockResolvedValue({ id: 'session-1', title: '已有会话', status: 'idle', messages: [] })
    const wrapper = mount(AssistantHost, {
      global: {
        stubs: {
          AssistantFloatBall: { emits: ['toggle'], template: '<button data-open @click="$emit(\'toggle\')" />' },
          AssistantPanel: { template: '<div />' },
        },
      },
    })

    await wrapper.get('[data-open]').trigger('click')
    await flushPromises()
    await wrapper.get('[data-open]').trigger('click')
    await wrapper.get('[data-open]').trigger('click')
    await flushPromises()

    expect(api.getAiTools).toHaveBeenCalledTimes(2)
    expect(api.listAiSessions).toHaveBeenCalledTimes(2)
    wrapper.unmount()
  })

  it('does not report an error when a completed SSE run aborts its reader', async () => {
    api.getAiTools.mockResolvedValue({ provider_configured: true, tools: [] })
    api.listAiSessions.mockResolvedValue([])
    api.createAiSession.mockResolvedValue({ id: 'session-1', title: '运行', status: 'idle', messages: [] })
    api.sendAiMessage.mockResolvedValue({ run_id: 'run-1' })
    api.streamAiRunEvents.mockImplementation(async (_id, _after, onEvent) => {
      onEvent({ type: 'done', data: {} })
      throw new DOMException('The operation was aborted.', 'AbortError')
    })
    const wrapper = mount(AssistantHost, {
      global: {
        stubs: {
          AssistantFloatBall: { emits: ['toggle'], template: '<button data-open @click="$emit(\'toggle\')" />' },
          AssistantPanel: {
            props: ['error'], emits: ['send'],
            template: '<div data-panel>{{ error }}<button data-send @click="$emit(\'send\', \'测试\')" /></div>',
          },
        },
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
    const wrapper = mount(AssistantHost, {
      global: {
        stubs: {
          AssistantFloatBall: { emits: ['toggle'], template: '<button data-open @click="$emit(\'toggle\')" />' },
          AssistantPanel: {
            emits: ['send', 'close'],
            template: '<div><button data-send @click="$emit(\'send\', \'测试\')" /><button data-close @click="$emit(\'close\')" /></div>',
          },
        },
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
    const wrapper = mount(AssistantHost, {
      global: {
        stubs: {
          AssistantFloatBall: { emits: ['toggle'], template: '<button data-open @click="$emit(\'toggle\')" />' },
          AssistantPanel: {
            emits: ['send'],
            template: '<div><button data-send @click="$emit(\'send\', \'测试\')" /></div>',
          },
        },
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

  it('does not revive a deleted session after its slow selection response arrives', async () => {
    const selected = deferred<{ id: string; title: string; status: 'idle'; messages: [] }>()
    api.getAiTools.mockResolvedValue({ provider_configured: true, tools: [] })
    api.listAiSessions.mockResolvedValue([])
    api.getAiSession.mockReturnValue(selected.promise)
    api.deleteAiSession.mockResolvedValue(undefined)
    const wrapper = mount(AssistantHost, {
      global: {
        stubs: {
          AssistantFloatBall: { emits: ['toggle'], template: '<button data-open @click="$emit(\'toggle\')" />' },
          AssistantPanel: {
            props: ['title'], emits: ['select', 'remove'],
            template: '<div data-panel>{{ title }}<button data-select @click="$emit(\'select\', \'old\')" /><button data-remove @click="$emit(\'remove\', \'old\')" /></div>',
          },
        },
      },
    })

    await wrapper.get('[data-open]').trigger('click')
    await flushPromises()
    await wrapper.get('[data-select]').trigger('click')
    await wrapper.get('[data-remove]').trigger('click')
    await flushPromises()
    selected.resolve({ id: 'old', title: '已删除会话', status: 'idle', messages: [] })
    await flushPromises()

    expect(wrapper.get('[data-panel]').text()).not.toContain('已删除会话')
    wrapper.unmount()
  })

  it('keeps an active selection valid when removing another session', async () => {
    const selected = deferred<{ id: string; title: string; status: 'idle'; messages: [] }>()
    api.getAiTools.mockResolvedValue({ provider_configured: true, tools: [] })
    api.listAiSessions.mockResolvedValue([
      { id: 'active', title: '活动会话', status: 'idle' },
      { id: 'remove', title: '待删除会话', status: 'idle' },
    ])
    api.getAiSession.mockReturnValue(selected.promise)
    api.deleteAiSession.mockResolvedValue(undefined)
    const wrapper = mount(AssistantHost, {
      global: {
        stubs: {
          AssistantFloatBall: { emits: ['toggle'], template: '<button data-open @click="$emit(\'toggle\')" />' },
          AssistantPanel: {
            props: ['title'], emits: ['select', 'remove'],
            template: '<div data-panel>{{ title }}<button data-select @click="$emit(\'select\', \'active\')" /><button data-remove @click="$emit(\'remove\', \'remove\')" /></div>',
          },
        },
      },
    })

    await wrapper.get('[data-open]').trigger('click')
    await flushPromises()
    await wrapper.get('[data-select]').trigger('click')
    await wrapper.get('[data-remove]').trigger('click')
    await flushPromises()
    selected.resolve({ id: 'active', title: '活动会话', status: 'idle', messages: [] })
    await flushPromises()

    expect(wrapper.get('[data-panel]').text()).toContain('活动会话')
    wrapper.unmount()
  })

  it('does not let an old cancellation response finish a newer run', async () => {
    const cancelled = deferred<{ status: 'cancelled' }>()
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
    const wrapper = mount(AssistantHost, {
      global: {
        stubs: {
          AssistantFloatBall: { emits: ['toggle'], template: '<button data-open @click="$emit(\'toggle\')" />' },
          AssistantPanel: {
            props: ['messages'], emits: ['send', 'cancel'],
            template: '<div data-panel>{{ messages.map((message) => `${message.content}:${message.status}`).join("|") }}<button data-send @click="$emit(\'send\', \'测试\')" /><button data-cancel @click="$emit(\'cancel\')" /></div>',
          },
        },
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
    cancelled.resolve({ status: 'cancelled' })
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
    const wrapper = mount(AssistantHost, {
      global: {
        stubs: {
          AssistantFloatBall: { emits: ['toggle'], template: '<button data-open @click="$emit(\'toggle\')" />' },
          AssistantPanel: {
            props: ['messages', 'error'], emits: ['send'],
            template: '<div data-panel>{{ error }} {{ messages.map((message) => `${message.content}:${message.status}`).join("|") }}<button data-send @click="$emit(\'send\', \'测试\')" /></div>',
          },
        },
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
    const wrapper = mount(AssistantHost, {
      global: {
        stubs: {
          AssistantFloatBall: { emits: ['toggle'], template: '<button data-open @click="$emit(\'toggle\')" />' },
          AssistantPanel: {
            props: ['messages', 'error'], emits: ['send'],
            template: '<div data-panel>{{ error }} {{ messages.map((message) => `${message.content}:${message.status}`).join("|") }}<button data-send @click="$emit(\'send\', \'测试\')" /></div>',
          },
        },
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

  it('routes an unavailable provider to the LLM settings tab', async () => {
    api.getAiTools.mockResolvedValue({ provider_configured: false, providers: [], tools: [] })
    api.listAiSessions.mockResolvedValue([])
    const wrapper = mount(AssistantHost, {
      global: {
        stubs: {
          AssistantFloatBall: { emits: ['toggle'], template: '<button data-open @click="$emit(\'toggle\')" />' },
          AssistantPanel: { emits: ['configure'], template: '<button data-configure @click="$emit(\'configure\')" />' },
        },
      },
    })

    await wrapper.get('[data-open]').trigger('click')
    await flushPromises()
    await wrapper.get('[data-configure]').trigger('click')

    expect(router.push).toHaveBeenCalledWith({ path: '/ops', query: { tab: 'llm' } })
    wrapper.unmount()
  })

  it('does not start event consumption after the host unmounts during send', async () => {
    const response = deferred<{ run_id: string }>()
    api.getAiTools.mockResolvedValue({ provider_configured: true, tools: [] })
    api.listAiSessions.mockResolvedValue([])
    api.createAiSession.mockResolvedValue({ id: 'session-1', title: '运行', status: 'idle', messages: [] })
    api.sendAiMessage.mockReturnValue(response.promise)
    const wrapper = mount(AssistantHost, {
      global: {
        stubs: {
          AssistantFloatBall: { emits: ['toggle'], template: '<button data-open @click="$emit(\'toggle\')" />' },
          AssistantPanel: { emits: ['send'], template: '<button data-send @click="$emit(\'send\', \'测试\')" />' },
        },
      },
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
      active_run: { id: 'run-wait', session_id: 'session-wait', status: 'waiting_user' },
    })
    const wrapper = mount(AssistantHost, {
      global: {
        stubs: {
          AssistantFloatBall: { emits: ['toggle'], template: '<button data-open @click="$emit(\'toggle\')" />' },
          AssistantPanel: {
            props: ['waitingUser', 'busy'],
            template: '<div data-panel>waiting={{ waitingUser }} busy={{ busy }}</div>',
          },
        },
      },
    })

    await wrapper.get('[data-open]').trigger('click')
    await flushPromises()

    expect(wrapper.get('[data-panel]').text()).toContain('waiting=true')
    expect(wrapper.get('[data-panel]').text()).toContain('busy=false')
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
    const wrapper = mount(AssistantHost, {
      global: {
        stubs: {
          AssistantFloatBall: { emits: ['toggle'], template: '<button data-open @click="$emit(\'toggle\')" />' },
          AssistantPanel: {
            props: ['messages', 'waitingUser', 'error'],
            emits: ['send'],
            template: '<div data-panel>waiting={{ waitingUser }} {{ error }} {{ messages.map((message) => `${message.content}:${message.status}`).join("|") }}<button data-send @click="$emit(\'send\', \'测试\')" /></div>',
          },
        },
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
    const wrapper = mount(AssistantHost, {
      global: {
        stubs: {
          AssistantFloatBall: { emits: ['toggle'], template: '<button data-open @click="$emit(\'toggle\')" />' },
          AssistantPanel: {
            props: ['messages'],
            template: '<div data-panel>{{ messages.map((message) => message.content).join("|") }}</div>',
          },
        },
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
    const wrapper = mount(AssistantHost, {
      global: {
        stubs: {
          AssistantFloatBall: { emits: ['toggle'], template: '<button data-open @click="$emit(\'toggle\')" />' },
          AssistantPanel: {
            props: ['messages', 'waitingUser'],
            emits: ['send', 'cancel'],
            template: '<div data-panel>waiting={{ waitingUser }} {{ messages.map((message) => `${message.content}:${message.status}`).join("|") }}<button data-send @click="$emit(\'send\', \'测试\')" /><button data-cancel @click="$emit(\'cancel\')" /></div>',
          },
        },
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
    const wrapper = mount(AssistantHost, {
      global: {
        stubs: {
          AssistantFloatBall: { emits: ['toggle'], template: '<button data-open @click="$emit(\'toggle\')" />' },
          AssistantPanel: {
            props: ['messages'],
            emits: ['send'],
            template: '<div data-panel>{{ messages.map((message) => `${message.content}:${message.status}`).join("|") }}<button data-send @click="$emit(\'send\', \'测试\')" /></div>',
          },
        },
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
})
