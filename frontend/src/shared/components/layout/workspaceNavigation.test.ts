import { shallowMount } from '@vue/test-utils'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { reactive } from 'vue'
import MobileBottomNav from './MobileBottomNav.vue'
import { useSidebarNav } from './composables/useSidebarNav'
import { navRoute } from '@/shared/lib/navLabels'

const state = vi.hoisted(() => ({ route: { path: '/pool' }, user: { isAdmin: false } }))
vi.mock('vue-router', () => ({
  useRoute: () => state.route,
  useRouter: () => ({ push: vi.fn() }),
}))
vi.mock('@/shared/stores/user', () => ({ useUserStore: () => state.user }))

const corePaths = ['/', '/screen-history', '/pool', '/quant', '/agents', '/winrate']

beforeEach(() => {
  state.route = reactive({ path: '/pool' })
  state.user.isAdmin = false
})

describe('core stock screening remains directly navigable', () => {
  it.each([false, true])('keeps screening in the expanded workspace for admin=%s', (isAdmin) => {
    state.user.isAdmin = isAdmin
    const { navGroups, defaultOpeneds } = useSidebarNav()
    const workspace = navGroups.find(group => group.id === 'workspace')!
    expect(defaultOpeneds.value).toContain(workspace.id)
    expect(workspace.items.map(item => item.path)).toEqual(corePaths)
    expect(workspace.items.find(item => item.path === '/screen-history')?.label).toBe('选股')
  })

  it('selects the screening entry itself instead of strategies or candidates', () => {
    const { active } = useSidebarNav()
    state.route.path = '/screen-history'
    expect(active.value).toBe('/screen-history')
    expect(navRoute('screen-history')).toEqual({
      path: '/screen-history', name: 'screen-history', meta: { title: '选股' },
    })
  })

  it('puts screening directly in the mobile primary navigation and highlights only that tab', async () => {
    const wrapper = shallowMount(MobileBottomNav, {
      global: {
        stubs: {
          RouterLink: { props: ['to'], template: '<a :href="to"><slot /></a>' },
          Button: { template: '<button><slot /></button>' },
          ThemeDialog: true, Drawer: true, UserAvatarMenu: true,
        },
      },
    })
    try {
      const nav = wrapper.get('nav[aria-label="主导航"]')
      expect(nav.findAll('a').map(link => link.attributes('href'))).toEqual(corePaths)
      expect(nav.get('a[href="/screen-history"]').text()).toBe('选股')
      state.route.path = '/screen-history'
      await wrapper.vm.$nextTick()
      expect(nav.get('a[href="/screen-history"]').attributes('aria-current')).toBe('page')
      expect(nav.findAll('[aria-current="page"]')).toHaveLength(1)
      expect(nav.get('button[aria-label="更多导航"]').classes()).not.toContain('active')
    } finally { wrapper.unmount() }
  })
})
