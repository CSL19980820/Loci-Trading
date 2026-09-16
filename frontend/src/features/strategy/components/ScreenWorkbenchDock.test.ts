import { mount } from '@vue/test-utils'
import { describe, expect, it } from 'vitest'
import ScreenWorkbenchDock from './ScreenWorkbenchDock.vue'

// Mount the real EmptyState: an undeclared template component silently renders no text.
describe('ScreenWorkbenchDock', () => {
  it('renders the diagnostic empty state and emits the close action', async () => {
    const wrapper = mount(ScreenWorkbenchDock, {
      props: { open: true, activeTab: 'diag', preview: null, screenResult: null, backtestSlot: true },
      global: { stubs: { ScreenSkillTestReport: true } },
    })
    expect(wrapper.findAll('.empty-state__title').some(title => title.text() === '无诊断')).toBe(true)
    await wrapper.get('[aria-label="收起结果面板"]').trigger('click')
    expect(wrapper.emitted('close')).toEqual([[]])
    wrapper.unmount()
  })
})
