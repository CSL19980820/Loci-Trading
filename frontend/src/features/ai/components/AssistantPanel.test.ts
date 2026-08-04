import { shallowMount } from '@vue/test-utils'
import { describe, expect, it } from 'vitest'

import AssistantPanel from './AssistantPanel.vue'

const baseProps = {
  open: true,
  sessions: [],
  messages: [],
  agents: [] as [],
  providerReady: false,
  providers: [],
  provider: '',
  model: '',
  models: [],
}

const buttonStub = {
  emits: ['click'],
  template: '<button v-bind="$attrs" @click="$emit(\'click\')"><slot /></button>',
}

describe('AssistantPanel', () => {
  it('constrains the drawer to the dynamic viewport width', () => {
    const wrapper = shallowMount(AssistantPanel, {
      props: baseProps,
      global: {
        stubs: {
          'el-drawer': {
            props: ['size'],
            template: '<aside data-testid="assistant-drawer" :data-size="size"><slot /></aside>',
          },
          'el-button': buttonStub,
        },
      },
    })

    expect(wrapper.get('[data-testid="assistant-drawer"]').attributes('data-size')).toBe(
      'min(560px, 100dvw)',
    )
  })

  it('emits a configuration request when no provider is available', async () => {
    const wrapper = shallowMount(AssistantPanel, {
      props: baseProps,
      global: {
        stubs: {
          'el-drawer': { template: '<aside><slot /></aside>' },
          'el-button': buttonStub,
        },
      },
    })

    await wrapper.get('[data-testid="assistant-configure-provider"]').trigger('click')
    expect(wrapper.emitted('configure')).toEqual([[]])
  })

  it('locks create and session rail while waiting for the user', async () => {
    const wrapper = shallowMount(AssistantPanel, {
      props: { ...baseProps, providerReady: true, waitingUser: true },
      global: {
        stubs: {
          'el-drawer': { template: '<aside><slot /></aside>' },
          'el-button': buttonStub,
          'el-tooltip': { template: '<div><slot /></div>' },
          AssistantSessionRail: {
            props: ['disabled'],
            template: '<aside data-testid="session-rail" :data-disabled="disabled" />',
          },
        },
      },
    })

    expect(wrapper.get('button[aria-label="新建对话"]').attributes('disabled')).toBeDefined()
    await wrapper.get('button[aria-label="历史对话"]').trigger('click')
    expect(wrapper.get('[data-testid="session-rail"]').attributes('data-disabled')).toBe('true')
  })
})
