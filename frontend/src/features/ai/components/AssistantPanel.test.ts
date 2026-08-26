import { shallowMount } from '@vue/test-utils'
import { afterEach, describe, expect, it } from 'vitest'

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
  })

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
})
