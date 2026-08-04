import { mount } from '@vue/test-utils'
import { defineComponent, h, nextTick } from 'vue'
import { describe, expect, it } from 'vitest'
import type { RouteLocationNormalizedLoaded } from 'vue-router'

import PageHost from './PageHost.vue'

const PulseStub = defineComponent({
  name: 'PulseStub',
  setup() {
    return () => h('div', { class: 'pulse-stub' }, 'pulse')
  },
})

const ArchiveStub = defineComponent({
  name: 'ArchiveStub',
  setup() {
    return () => h('div', { class: 'archive-stub' }, 'archive')
  },
})

function fakeRoute(name: string, fullPath: string): RouteLocationNormalizedLoaded {
  return {
    name,
    fullPath,
    path: fullPath,
    hash: '',
    query: {},
    params: {},
    matched: [],
    meta: {},
    redirectedFrom: undefined,
  } as RouteLocationNormalizedLoaded
}

describe('PageHost archive overlay', () => {
  it('keeps non-archive pages in host and skips overlay', async () => {
    const wrapper = mount(PageHost, {
      props: {
        component: PulseStub,
        route: fakeRoute('pulse', '/'),
      },
      attachTo: document.body,
    })
    await nextTick()
    expect(wrapper.find('.pulse-stub').exists()).toBe(true)
    expect(document.body.querySelector('.archive-overlay')).toBeNull()
    wrapper.unmount()
  })

  it('teleports archive into full-screen overlay and hides host page', async () => {
    const wrapper = mount(PageHost, {
      props: {
        component: ArchiveStub,
        route: fakeRoute('archive', '/archive/301201'),
      },
      attachTo: document.body,
    })
    await nextTick()
    expect(wrapper.find('.archive-stub').exists()).toBe(false)
    const overlay = document.body.querySelector('.archive-overlay')
    expect(overlay).not.toBeNull()
    expect(overlay?.querySelector('.archive-stub')?.textContent).toBe('archive')
    expect(overlay?.getAttribute('role')).toBe('dialog')
    expect(overlay?.getAttribute('aria-modal')).toBe('true')
    wrapper.unmount()
  })
})
