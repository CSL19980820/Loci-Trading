import { mount } from '@vue/test-utils'
import { describe, expect, it } from 'vitest'

import AssistantAgentsRail from './AssistantAgentsRail.vue'

const stubs = {
  ElCollapse: { template: '<div><slot /></div>' },
  ElCollapseItem: { template: '<section><slot name="title" /><slot /></section>' },
  ElTag: { template: '<span><slot /></span>' },
  ElProgress: { props: ['percentage'], template: '<span>{{ percentage }}%</span>' },
  ElTimeline: { template: '<ol><slot /></ol>' },
  ElTimelineItem: { template: '<li><slot /></li>' },
}

describe('AssistantAgentsRail', () => {
  it('shows normalized Agent progress, completion detail, and timeline', () => {
    const wrapper = mount(AssistantAgentsRail, {
      props: {
        agents: [{
          id: 'evidence', name: '证据核查', status: 'done', progress: 100,
          detail: '已完成证据整理', timeline: ['已启动', '正在读取行情'],
        }],
      },
      global: { stubs },
    })

    expect(wrapper.text()).toContain('证据核查')
    expect(wrapper.text()).toContain('完成')
    expect(wrapper.text()).toContain('100%')
    expect(wrapper.text()).toContain('已完成证据整理')
    expect(wrapper.text()).toContain('正在读取行情')
    expect(wrapper.find('button').exists()).toBe(false)
  })

  it('dismisses the overlay rail via backdrop until agents change', async () => {
    const agents = [{
      id: 'evidence', name: '证据核查', status: 'running' as const, progress: 40,
    }]
    const wrapper = mount(AssistantAgentsRail, {
      props: { agents, overlay: true },
      global: { stubs },
    })

    expect(wrapper.find('[data-testid="assistant-agents-backdrop"]').exists()).toBe(true)
    await wrapper.get('[data-testid="assistant-agents-backdrop"]').trigger('click')
    expect(wrapper.find('.assistant-agents').exists()).toBe(false)

    await wrapper.setProps({
      agents: [{ id: 'writer', name: '写手', status: 'queued' as const }],
    })
    expect(wrapper.find('.assistant-agents').exists()).toBe(true)
    expect(wrapper.find('[data-testid="assistant-agents-backdrop"]').exists()).toBe(true)
  })
})
