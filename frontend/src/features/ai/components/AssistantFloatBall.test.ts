import { mount } from '@vue/test-utils'
import { afterEach, describe, expect, it } from 'vitest'
import { ChatDotRound, Close } from '@element-plus/icons-vue'

import AssistantFloatBall from './AssistantFloatBall.vue'

const stubs = {
  ElTooltip: { template: '<div><slot /></div>' },
  ElButton: { inheritAttrs: false, template: '<button v-bind="$attrs"><slot /></button>' },
}

describe('AssistantFloatBall', () => {
  afterEach(() => {
    localStorage.clear()
  })

  it('binds its persisted viewport position to the Element Plus button', () => {
    const wrapper = mount(AssistantFloatBall, {
      props: { open: false },
      global: { stubs },
    })

    expect(wrapper.get('button').attributes('style')).toContain('right: 24px')
    expect(wrapper.get('button').attributes('style')).toContain('bottom: 88px')
  })

  it('opens from a native click so keyboard activation works', async () => {
    const wrapper = mount(AssistantFloatBall, {
      props: { open: false },
      global: { stubs },
    })

    await wrapper.get('button').trigger('click')
    expect(wrapper.emitted('toggle')).toHaveLength(1)
  })

  it('switches the conversation icon and accessible action when opening', async () => {
    const wrapper = mount(AssistantFloatBall, {
      props: { open: false },
      global: { stubs },
    })

    expect(wrapper.findComponent(ChatDotRound).exists()).toBe(true)
    expect(wrapper.findComponent(Close).exists()).toBe(false)
    expect(wrapper.get('button').attributes('aria-label')).toBe('打开 Loci 助手')
    expect(wrapper.get('button').attributes('aria-expanded')).toBe('false')

    await wrapper.setProps({ open: true })
    expect(wrapper.findComponent(ChatDotRound).exists()).toBe(false)
    expect(wrapper.findComponent(Close).exists()).toBe(true)
    expect(wrapper.get('button').classes()).toContain('is-open')
    expect(wrapper.get('button').attributes('aria-label')).toBe('关闭 Loci 助手')
    expect(wrapper.get('button').attributes('aria-expanded')).toBe('true')
    wrapper.unmount()
  })

  it('marks busy and unavailable states on the launcher', async () => {
    const wrapper = mount(AssistantFloatBall, {
      props: { open: false, busy: true, unavailable: true },
      global: { stubs },
    })
    const ball = wrapper.get('button')
    expect(ball.classes()).toContain('is-busy')
    expect(ball.classes()).toContain('is-unavailable')
  })

  it('applies dragged inline bottom without CSS !important override', async () => {
    const wrapper = mount(AssistantFloatBall, {
      props: { open: false },
      global: { stubs },
    })
    const ball = wrapper.get('button')

    await ball.trigger('pointerdown', { clientX: 200, clientY: 400, pointerId: 1 })
    await ball.trigger('pointermove', { clientX: 180, clientY: 320, pointerId: 1 })
    await ball.trigger('pointerup', { pointerId: 1 })

    const style = ball.attributes('style') ?? ''
    expect(style).toMatch(/bottom:\s*\d+px/)
    expect(style).toMatch(/right:\s*\d+px/)
    // Drag moved up (clientY decreased) → bottom increases; must keep inline bottom (not wiped by CSS).
    const bottom = Number(/bottom:\s*(\d+)px/.exec(style)?.[1] ?? 0)
    expect(bottom).toBeGreaterThan(88)
  })
})
