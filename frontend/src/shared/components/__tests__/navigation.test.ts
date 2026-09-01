import { mount } from '@vue/test-utils'
import { createPinia, setActivePinia } from 'pinia'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { defineComponent, h, nextTick, ref } from 'vue'

import App from '@/App.vue'
import AppSidebar from '@/shared/components/layout/AppSidebar.vue'
import UserAvatarMenu from '@/features/auth/UserAvatarMenu.vue'
import { useMarketSyncGate } from '@/shared/composables/useMarketSyncGate'
import { usePalaceStore } from '@/shared/stores/palace'
import { useUserStore } from '@/shared/stores/user'

const mockRoute = ref({
  name: 'pulse',
  fullPath: '/',
  path: '/',
  params: {},
  query: {},
  meta: {},
})

vi.mock('vue-router', () => ({
  useRoute: () => mockRoute.value,
  useRouter: () => ({
    push: vi.fn(),
    replace: vi.fn(),
    // 侧栏悬停预取会调它；mock 回一条空 matched，预取就是个空转。
    resolve: vi.fn(() => ({ matched: [] })),
  }),
  RouterLink: defineComponent({
    name: 'RouterLink',
    props: ['to'],
    setup(props, { slots }) {
      return () => {
        const href = typeof props.to === 'string' ? props.to : props.to?.path
        return h('a', { href }, slots.default?.())
      }
    },
  }),
  RouterView: defineComponent({
    name: 'RouterView',
    setup(_, { slots }) {
      return () => {
        const stub = h('div', { class: 'router-view-stub' })
        if (!slots.default) return stub
        return slots.default({ Component: stub, route: mockRoute.value })
      }
    },
  }),
}))

vi.mock('@/shared/api/quant', () => ({
  createDesktopShortcut: vi.fn(),
  getDataLocation: vi.fn().mockResolvedValue({ data_dir: '/test/data' }),
}))

// 补行情网关：mock 固定返回同一组 ref，测试里改 `.value` 就能驱动状态轨
vi.mock('@/shared/composables/useMarketSyncGate', async () => {
  const { ref: vueRef } = await import('vue')
  const syncing = vueRef(false)
  const busyLabel = vueRef('')
  const syncPercent = vueRef(0)
  return { useMarketSyncGate: () => ({ syncing, busyLabel, syncPercent }) }
})

// 壳一挂载就 loadRoute()，真 store 会去打接口（测试里只剩一串连接错误）。
// 换成可直接写字段的假 store，顺带让「加载中 / 加载失败」两条轨状态可控。
vi.mock('@/shared/stores/palace', async () => {
  const { reactive } = await import('vue')
  const store = reactive({
    loading: false,
    error: '',
    loadRoute: vi.fn(),
    invalidateArchive: vi.fn(),
    clearError: vi.fn(() => {
      store.error = ''
    }),
  })
  return { usePalaceStore: () => store }
})

const appStubs = {
  RouterView: defineComponent({
    setup(_, { slots }) {
      return () => {
        const stub = h('div', { class: 'router-view-stub' })
        if (!slots.default) return stub
        return slots.default({ Component: stub, route: mockRoute.value })
      }
    },
  }),
  PageHost: true,
  ScreenRunChip: true,
  NotificationCenter: true,
  MarketBootstrapDialog: true,
  RecordDialog: true,
  AssistantHost: true,
  'el-config-provider': {
    template: '<div><slot /></div>',
  },
  'el-tooltip': {
    template: '<div class="tooltip-stub"><slot /></div>',
  },
  'el-dropdown': true,
  'el-dropdown-menu': true,
  'el-dropdown-item': true,
  'el-button': {
    template: '<button><slot /></button>',
  },
  'el-icon': {
    template: '<i class="el-icon"><slot /></i>',
  },
}

function mountApp(extraStubs: Record<string, unknown> = {}) {
  return mount(App, { global: { stubs: { ...appStubs, ...extraStubs } } })
}

function member(overrides: Record<string, unknown> = {}) {
  return {
    id: 'u1',
    username: 'member1',
    display_name: 'Regular Member',
    avatar_url: '',
    role: 'member' as const,
    bio: '',
    created_at: '',
    ...overrides,
  }
}

describe('Navigation wiring and App layout', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
    mockRoute.value = {
      name: 'pulse',
      fullPath: '/',
      path: '/',
      params: {},
      query: {},
      meta: {},
    }
    const gate = useMarketSyncGate()
    gate.syncing.value = false
    gate.syncPercent.value = 0
    const palace = usePalaceStore()
    palace.loading = false
    palace.error = ''
  })

  it('renders both nav groups in AppSidebar (市场, 我的)', () => {
    const wrapper = mount(AppSidebar, {
      global: {
        stubs: {
          RouterLink: defineComponent({
            props: ['to'],
            setup(props, { slots }) {
              return () => {
                const href = typeof props.to === 'string' ? props.to : props.to?.path
                return h('a', { href }, slots.default?.())
              }
            },
          }),
          ThemeDialog: true,
          UserAvatarMenu: true,
          NotificationCenter: true,
          'el-tooltip': {
            template: '<div class="tooltip-stub"><slot /></div>',
          },
          'el-menu': {
            template: '<div class="el-menu-stub"><slot /></div>',
          },
          'el-sub-menu': {
            props: ['index'],
            template:
              '<div class="el-sub-menu-stub" :data-index="index"><slot name="title" /><slot /></div>',
          },
          'el-menu-item': {
            props: ['index'],
            template:
              '<div class="el-menu-item-stub" :data-index="index"><slot /><slot name="title" /></div>',
          },
          'el-dropdown': {
            template: '<div class="el-dropdown-stub"><slot /><slot name="dropdown" /></div>',
          },
          'el-dropdown-menu': {
            template: '<div><slot /></div>',
          },
          'el-dropdown-item': {
            template: '<div><slot /></div>',
          },
          'el-button': {
            template: '<button><slot /></button>',
          },
          'el-icon': {
            template: '<i class="el-icon"><slot /></i>',
          },
        },
      },
    })

    const groupTitles = wrapper.findAll('.nav-group-title').map((el) => el.text())
    expect(groupTitles).toEqual(['市场', '我的'])

    // 检查市场组项：盘面 / live / data
    const items = wrapper.findAll('.el-menu-item-stub').map((el) => el.attributes('data-index'))
    expect(items).toContain('/')
    expect(items).toContain('/live')
    expect(items).toContain('/data')

    // 检查我的组项：候选池 / 选股 / 工坊 / 策稿 / 复盘 / 胜率 / 体检
    expect(items).toContain('/pool')
    expect(items).toContain('/screen-history')
    expect(items).toContain('/quant')
    expect(items).toContain('/strategy-converter')
    expect(items).toContain('/reviews')
    expect(items).toContain('/winrate')
    expect(items).toContain('/insights')

    // 社区整体下线：这几条路由与菜单项都不该再存在
    expect(items).not.toContain('/square')
    expect(items).not.toContain('/leaderboard')
    expect(items).not.toContain('/my/community')

    // 消息 / 主题 / 设置 是钉在左下角的**同款菜单项**，不再是图标按钮条
    const foot = wrapper.findAll('.foot-menu-item')
    expect(foot.map((el) => el.text())).toEqual(['消息', '主题', '设置'])
    expect(wrapper.find('.foot-menu-item--ops').attributes('data-index')).toBe('/ops')
    // 管理后台只对管理员出现（此处未登录）
    expect(wrapper.find('.foot-menu-item--admin').exists()).toBe(false)
  })

  it('drops group titles when the sidebar collapses', async () => {
    const wrapper = mount(AppSidebar, {
      global: {
        stubs: {
          RouterLink: defineComponent({
            props: ['to'],
            setup(props, { slots }) {
              return () => {
                const href = typeof props.to === 'string' ? props.to : props.to?.path
                return h('a', { href }, slots.default?.())
              }
            },
          }),
          ThemeDialog: true,
          UserAvatarMenu: true,
          NotificationCenter: true,
          'el-tooltip': {
            template: '<div class="tooltip-stub"><slot /></div>',
          },
          'el-menu': {
            template: '<div class="el-menu-stub"><slot /></div>',
          },
          'el-sub-menu': {
            props: ['index'],
            template:
              '<div class="el-sub-menu-stub" :data-index="index"><slot name="title" /><slot /></div>',
          },
          'el-menu-item': {
            props: ['index'],
            template: '<div class="el-menu-item-stub" :data-index="index"><slot /></div>',
          },
          'el-dropdown': {
            template: '<div><slot /><slot name="dropdown" /></div>',
          },
          'el-dropdown-menu': true,
          'el-dropdown-item': true,
          'el-button': {
            template: '<button><slot /></button>',
          },
          'el-icon': {
            template: '<i class="el-icon"><slot /></i>',
          },
        },
      },
    })

    expect(wrapper.findAll('.nav-group-title')).toHaveLength(2)
    expect(wrapper.find('.brand-name').exists()).toBe(true)

    await wrapper.find('.brand-toggle').trigger('click')
    await nextTick()

    expect(wrapper.find('.app-sidebar').classes()).toContain('collapsed')
    expect(wrapper.findAll('.nav-group-title')).toHaveLength(0)
    expect(wrapper.find('.brand-name').exists()).toBe(false)
    // 收起后菜单项还在，只是没有分组标题；两组之间仍有一条分隔线
    expect(wrapper.findAll('.el-menu-item-stub').length).toBeGreaterThan(0)
    expect(wrapper.findAll('.nav-group-divider')).toHaveLength(1)
  })

  it('shows AppSidebar and MobileBottomNav under /live route in App.vue', async () => {
    mockRoute.value = {
      name: 'live',
      fullPath: '/live',
      path: '/live',
      params: {},
      query: {},
      meta: {},
    }

    const wrapper = mountApp({
      AppSidebar: { template: '<aside class="sidebar-stub"></aside>' },
      MobileBottomNav: { template: '<nav class="bottom-nav-stub"></nav>' },
    })

    await nextTick()
    expect(wrapper.find('.sidebar-stub').exists()).toBe(true)
    expect(wrapper.find('.bottom-nav-stub').exists()).toBe(true)
  })
  it('shows AppSidebar and MobileBottomNav for standard routes in App.vue', async () => {
    mockRoute.value = {
      name: 'pulse',
      fullPath: '/',
      path: '/',
      params: {},
      query: {},
      meta: {},
    }

    const wrapper = mountApp({
      AppSidebar: { template: '<aside class="sidebar-stub"></aside>' },
      MobileBottomNav: { template: '<nav class="bottom-nav-stub"></nav>' },
    })

    await nextTick()
    expect(wrapper.find('.sidebar-stub').exists()).toBe(true)
    expect(wrapper.find('.bottom-nav-stub').exists()).toBe(true)
  })

  it('keeps the status rail out of the DOM when nothing is happening', async () => {
    const wrapper = mountApp({ AppSidebar: true, MobileBottomNav: true })
    await nextTick()

    expect(wrapper.find('.status-rail').exists()).toBe(false)
    expect(wrapper.find('.load-line').exists()).toBe(false)
    expect(wrapper.find('.workspace').classes()).not.toContain('workspace--railed')
  })

  it('orders status chips by 阻塞 > 错误 > 进行中', async () => {
    const userStore = useUserStore()
    userStore.setUser(member({ must_change_password: true }))
    const palace = usePalaceStore()
    palace.error = '候选池接口 500'
    const gate = useMarketSyncGate()
    gate.syncing.value = true
    gate.syncPercent.value = 62

    const wrapper = mountApp({ AppSidebar: true, MobileBottomNav: true })
    await nextTick()

    expect(wrapper.find('.workspace').classes()).toContain('workspace--railed')
    const chips = wrapper.findAll('.rail-chip')
    expect(chips).toHaveLength(3)
    expect(chips[0].classes()).toContain('rail-chip--block')
    expect(chips[1].classes()).toContain('rail-chip--error')
    expect(chips[2].classes()).toContain('rail-chip--busy')
    expect(chips[2].text()).toContain('62%')
    // 阻塞档的长文案不进轨，只留 ≤12 字 + 一颗动作按钮
    expect(chips[0].find('.rail-chip__text').text()).toBe('初始密码')
  })

  it('shows the 2px load line instead of a full-width progress bar', async () => {
    const palace = usePalaceStore()
    palace.loading = true

    const wrapper = mountApp({ AppSidebar: true, MobileBottomNav: true })
    await nextTick()

    expect(wrapper.find('.load-line').exists()).toBe(true)
    // 纯加载不值得占一条轨：轨不渲染，进度线吸在主区顶边
    expect(wrapper.find('.status-rail').exists()).toBe(false)
  })

  it('brings up the rail for unread notifications alone', async () => {
    const userStore = useUserStore()
    userStore.setUser(member())
    userStore.unread = 3

    const wrapper = mountApp({ AppSidebar: true, MobileBottomNav: true })
    await nextTick()

    expect(wrapper.find('.status-rail').exists()).toBe(true)
    expect(wrapper.findAll('.rail-chip')).toHaveLength(0)
    expect(wrapper.find('notification-center-stub').exists()).toBe(true)
  })

  it('controls admin menu visibility based on user role in UserAvatarMenu', async () => {
    const userStore = useUserStore()
    userStore.setUser({
      id: 'u1',
      username: 'member1',
      display_name: 'Regular Member',
      avatar_url: '',
      role: 'member',
      bio: '',
      created_at: '',
    })

    const wrapper = mount(UserAvatarMenu, {
      global: {
        stubs: {
          'el-dropdown': {
            template: '<div class="dropdown-stub"><slot /><slot name="dropdown" /></div>',
          },
          'el-dropdown-menu': {
            template: '<div class="dropdown-menu-stub"><slot /></div>',
          },
          'el-dropdown-item': {
            props: ['command'],
            template: '<div class="dropdown-item-stub" :data-command="command"><slot /></div>',
          },
          'el-badge': {
            template: '<div><slot /></div>',
          },
          'el-avatar': {
            template: '<div><slot /></div>',
          },
          'el-tag': {
            template: '<div><slot /></div>',
          },
        },
      },
    })

    // 非管理员：看不到 command="admin" 的菜单项
    let adminItem = wrapper
      .findAll('.dropdown-item-stub')
      .find((el) => el.attributes('data-command') === 'admin')
    expect(adminItem).toBeUndefined()

    // 切换为管理员
    userStore.setUser({
      id: 'u2',
      username: 'admin1',
      display_name: 'Admin User',
      avatar_url: '',
      role: 'admin',
      bio: '',
      created_at: '',
    })
    await nextTick()

    adminItem = wrapper
      .findAll('.dropdown-item-stub')
      .find((el) => el.attributes('data-command') === 'admin')
    expect(adminItem).toBeDefined()
    expect(adminItem?.text()).toContain('管理后台')
  })
})
