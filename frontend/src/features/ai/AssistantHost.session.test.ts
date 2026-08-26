import { describe, expect, it } from 'vitest'
import { flushPromises } from '@vue/test-utils'

import {
  api,
  deferred,
  router,
  mountAssistantHost,
  setupAfterEach,
} from './AssistantHost.test.helpers'

describe('AssistantHost session', () => {
  setupAfterEach()

  it('ignores an older session response after a newer selection wins', async () => {
    const older = deferred<{ id: string; title: string; status: 'idle'; messages: [] }>()
    const newer = deferred<{ id: string; title: string; status: 'idle'; messages: [] }>()
    api.getAiTools.mockResolvedValue({ provider_configured: true, tools: [] })
    api.listAiSessions.mockResolvedValue([])
    api.getAiSession.mockReturnValueOnce(older.promise).mockReturnValueOnce(newer.promise)
    const wrapper = mountAssistantHost({
      AssistantPanel: {
        props: ['messages', 'title', 'error'], emits: ['select', 'send'],
        template: '<div data-panel>{{ title }} {{ error }} {{ messages.map((message) => message.content).join("|") }}<button data-old @click="$emit(\'select\', \'old\')" /><button data-new @click="$emit(\'select\', \'new\')" /><button data-send @click="$emit(\'send\', \'测试\')" /></div>',
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
    const wrapper = mountAssistantHost({
      AssistantPanel: { template: '<div />' },
    })

    await wrapper.get('[data-open]').trigger('click')
    await flushPromises()
    await wrapper.get('[data-open]').trigger('click')
    await wrapper.get('[data-open]').trigger('click')
    await flushPromises()

    expect(api.getAiTools).toHaveBeenCalledTimes(2)
    expect(api.listAiSessions).toHaveBeenCalledTimes(4)
    wrapper.unmount()
  })

  it('does not revive a deleted session after its slow selection response arrives', async () => {
    const selected = deferred<{ id: string; title: string; status: 'idle'; messages: [] }>()
    api.getAiTools.mockResolvedValue({ provider_configured: true, tools: [] })
    api.listAiSessions.mockResolvedValue([])
    api.getAiSession.mockReturnValue(selected.promise)
    api.deleteAiSession.mockResolvedValue(undefined)
    const wrapper = mountAssistantHost({
      AssistantPanel: {
        props: ['title'], emits: ['select', 'remove'],
        template: '<div data-panel>{{ title }}<button data-select @click="$emit(\'select\', \'old\')" /><button data-remove @click="$emit(\'remove\', \'old\')" /></div>',
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
    const wrapper = mountAssistantHost({
      AssistantPanel: {
        props: ['title'], emits: ['select', 'remove'],
        template: '<div data-panel>{{ title }}<button data-select @click="$emit(\'select\', \'active\')" /><button data-remove @click="$emit(\'remove\', \'remove\')" /></div>',
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

  it('routes an unavailable provider to the LLM settings tab', async () => {
    api.getAiTools.mockResolvedValue({ provider_configured: false, providers: [], tools: [] })
    api.listAiSessions.mockResolvedValue([])
    const wrapper = mountAssistantHost({
      AssistantPanel: { emits: ['configure'], template: '<button data-configure @click="$emit(\'configure\')" />' },
    })

    await wrapper.get('[data-open]').trigger('click')
    await flushPromises()
    await wrapper.get('[data-configure]').trigger('click')

    expect(router.push).toHaveBeenCalledWith({ path: '/ops', query: { tab: 'llm' } })
    wrapper.unmount()
  })

  it('reuses an empty draft instead of creating another 新对话', async () => {
    api.getAiTools.mockResolvedValue({ provider_configured: true, tools: [] })
    api.listAiSessions.mockResolvedValue([{ id: 'draft-1', title: '新对话', status: 'idle' }])
    api.getAiSession.mockResolvedValue({ id: 'draft-1', title: '新对话', status: 'idle', messages: [] })
    const wrapper = mountAssistantHost({
      AssistantPanel: {
        props: ['activeId', 'title'],
        emits: ['create'],
        template: '<div data-panel>{{ title }}<button data-create @click="$emit(\'create\')" /></div>',
      },
    })

    await wrapper.get('[data-open]').trigger('click')
    await flushPromises()
    await wrapper.get('[data-create]').trigger('click')
    await flushPromises()

    expect(api.createAiSession).not.toHaveBeenCalled()
    expect(wrapper.get('[data-panel]').text()).toContain('新对话')
    wrapper.unmount()
  })

  it('silently deletes an empty draft when leaving the assistant', async () => {
    api.getAiTools.mockResolvedValue({ provider_configured: true, tools: [] })
    api.listAiSessions.mockResolvedValue([{ id: 'draft-1', title: '新对话', status: 'idle' }])
    api.getAiSession.mockResolvedValue({ id: 'draft-1', title: '新对话', status: 'idle', messages: [] })
    api.deleteAiSession.mockResolvedValue(undefined)
    const wrapper = mountAssistantHost({
      AssistantFloatBall: {
        props: ['open'],
        emits: ['toggle'],
        template: '<button data-toggle @click="$emit(\'toggle\')">{{ open ? "open" : "closed" }}</button>',
      },
      AssistantPanel: {
        props: ['open', 'title'],
        emits: ['close'],
        template: '<div data-panel v-if="open">{{ title }}<button data-close @click="$emit(\'close\')" /></div>',
      },
    })

    await wrapper.get('[data-toggle]').trigger('click')
    await flushPromises()
    await wrapper.get('[data-close]').trigger('click')
    await flushPromises()

    expect(api.deleteAiSession).toHaveBeenCalledWith('draft-1')
    wrapper.unmount()
  })
})
