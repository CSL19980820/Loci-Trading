import { shallowMount } from '@vue/test-utils'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { nextTick } from 'vue'

import AssistantPanel from './AssistantPanel.vue'

const baseProps = {
  open: true,
  sessions: [],
  archivedSessions: [],
  railTab: 'active' as const,
  messages: [],
  agents: [] as [],
  providerReady: false,
  providers: [],
  provider: '',
  model: '',
  thinking: 'off' as const,
}

const buttonStub = {
  emits: ['click'],
  template: '<button v-bind="$attrs" @click="$emit(\'click\')"><slot /></button>',
}

const dialogStub = {
  props: ['width', 'alignCenter', 'showClose'],
  template:
    '<div data-testid="assistant-dialog" :data-width="width" :data-align-center="alignCenter" :data-show-close="showClose"><slot /></div>',
}

describe('AssistantPanel', () => {
  afterEach(() => {
    localStorage.clear()
    vi.unstubAllGlobals()
  })

  /** 侧栏折叠态只从 collapsed / open 两个 prop 看得出来，stub 把它们透出成属性 */
  function mountWithSidebarProbes() {
    return shallowMount(AssistantPanel, {
      props: { ...baseProps, providerReady: true },
      global: {
        stubs: {
          'el-dialog': { template: '<div><slot /></div>' },
          'el-button': buttonStub,
          AssistantEmptyState: { template: '<div />' },
          AssistantSenderDock: { template: '<div />' },
          AssistantSessionRail: {
            props: ['collapsed'],
            template: '<aside data-testid="session-rail" :data-collapsed="collapsed" />',
          },
          AssistantTaskSidebar: {
            props: ['open'],
            template: '<aside data-testid="task-sidebar" :data-open="open" />',
          },
        },
      },
    })
  }

  it('opens as a dialog at 90% of the viewport', () => {
    const wrapper = shallowMount(AssistantPanel, {
      props: baseProps,
      global: {
        stubs: {
          'el-dialog': dialogStub,
          'el-button': buttonStub,
        },
      },
    })

    const dialog = wrapper.get('[data-testid="assistant-dialog"]')
    expect(dialog.attributes('data-width')).toBe('90%')
    expect(dialog.attributes('data-align-center')).toBe('false')
    expect(dialog.attributes('data-show-close')).toBe('false')
  })

  it('has no chrome header; keeps history and task sidebars', () => {
    localStorage.setItem('loci.assistant.historyOpen', '1')
    localStorage.setItem('loci.assistant.taskSidebarOpen', '1')
    const wrapper = shallowMount(AssistantPanel, {
      props: { ...baseProps, providerReady: true },
      global: {
        stubs: {
          'el-dialog': { template: '<div><slot /></div>' },
          'el-button': buttonStub,
          AssistantEmptyState: { template: '<div />' },
          AssistantSenderDock: { template: '<div />' },
          AssistantSessionRail: { template: '<aside data-testid="session-rail" />' },
          AssistantTaskSidebar: { template: '<aside data-testid="task-sidebar" />' },
        },
      },
    })

    expect(wrapper.find('.assistant-panel__header').exists()).toBe(false)
    expect(wrapper.find('[data-testid="session-rail"]').exists()).toBe(true)
    expect(wrapper.find('[data-testid="task-sidebar"]').exists()).toBe(true)
  })

  it('shows the instrument empty stage with prompt cards when ready and empty', () => {
    const wrapper = shallowMount(AssistantPanel, {
      props: { ...baseProps, providerReady: true },
      global: {
        stubs: {
          'el-dialog': { template: '<div><slot /></div>' },
          'el-button': buttonStub,
          AssistantEmptyState: {
            props: ['prompts'],
            emits: ['pick'],
            template: '<div data-testid="assistant-empty" :data-count="prompts.length" />',
          },
        },
      },
    })

    expect(wrapper.get('[data-testid="assistant-empty"]').attributes('data-count')).toBe('6')
  })

  it('emits a configuration request when no provider is available', async () => {
    const wrapper = shallowMount(AssistantPanel, {
      props: baseProps,
      global: {
        stubs: {
          'el-dialog': { template: '<div><slot /></div>' },
          'el-button': buttonStub,
        },
      },
    })

    await wrapper.get('[data-testid="assistant-configure-provider"]').trigger('click')
    expect(wrapper.emitted('configure')).toEqual([[]])
  })

  it('locks session rail while waiting for the user', async () => {
    localStorage.setItem('loci.assistant.historyOpen', '1')
    const wrapper = shallowMount(AssistantPanel, {
      props: { ...baseProps, providerReady: true, waitingUser: true },
      global: {
        stubs: {
          'el-dialog': { template: '<div><slot /></div>' },
          'el-button': buttonStub,
          'el-tooltip': { template: '<div><slot /></div>' },
          AssistantEmptyState: { template: '<div />' },
          AssistantSenderDock: { template: '<div data-testid="assistant-sender" />' },
          AssistantSessionRail: {
            props: ['disabled'],
            template: '<aside data-testid="session-rail" :data-disabled="disabled" />',
          },
          AssistantTaskSidebar: { template: '<aside />' },
        },
      },
    })

    expect(wrapper.get('[data-testid="session-rail"]').attributes('data-disabled')).toBe('true')
  })

  it('窄屏挂载时把两侧栏折成 rail，且不改写记住的偏好', async () => {
    localStorage.setItem('loci.assistant.historyOpen', '1')
    localStorage.setItem('loci.assistant.taskSidebarOpen', '1')
    vi.stubGlobal('matchMedia', () => ({ matches: false }))

    const wrapper = mountWithSidebarProbes()
    // 折叠发生在 onMounted 里，属性要等一次 flush 才落到 DOM
    await nextTick()

    expect(wrapper.get('[data-testid="session-rail"]').attributes('data-collapsed')).toBe('true')
    expect(wrapper.get('[data-testid="task-sidebar"]').attributes('data-open')).toBe('false')
    // 断点折叠不落盘：否则一次窄屏访问就把用户的展开偏好永久改掉
    expect(localStorage.getItem('loci.assistant.historyOpen')).toBe('1')
    expect(localStorage.getItem('loci.assistant.taskSidebarOpen')).toBe('1')
  })

  it('够宽时保留记住的展开态', async () => {
    localStorage.setItem('loci.assistant.historyOpen', '1')
    localStorage.setItem('loci.assistant.taskSidebarOpen', '1')
    vi.stubGlobal('matchMedia', () => ({ matches: true }))

    const wrapper = mountWithSidebarProbes()
    // 折叠发生在 onMounted 里，属性要等一次 flush 才落到 DOM
    await nextTick()

    expect(wrapper.get('[data-testid="session-rail"]').attributes('data-collapsed')).toBe('false')
    expect(wrapper.get('[data-testid="task-sidebar"]').attributes('data-open')).toBe('true')
  })
})
