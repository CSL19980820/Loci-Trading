import { flushPromises, mount } from '@vue/test-utils'
import { createPinia, setActivePinia } from 'pinia'
import { beforeEach, describe, expect, it, vi } from 'vitest'

import { useUserStore } from '@/shared/stores/user'
import AdminView from '../AdminView.vue'

const api = vi.hoisted(() => ({
  getAdminOverview: vi.fn().mockResolvedValue({
    users: 5,
    admins: 1,
    top_llm_usage: [],
    recent_audit: [],
    announcements: [],
    tenants: ['tenant-1'],
  }),
  listAdminUsers: vi.fn().mockResolvedValue({ items: [], total: 0 }),
  listAdminAudit: vi.fn().mockResolvedValue({ items: [], total: 0 }),
  listAdminLogins: vi.fn().mockResolvedValue({ items: [], total: 0 }),
  listAdminAnnouncements: vi.fn().mockResolvedValue({ items: [] }),
}))

vi.mock('@/shared/api/admin', () => api)

// AdminView 的「返回首页」已从手抄 EP class 的 RouterLink 换成 el-button + router.push
const push = vi.hoisted(() => vi.fn())
vi.mock('vue-router', () => ({ useRouter: () => ({ push }) }))

const stubs = {
  'el-empty': { props: ['description'], template: '<div class="el-empty">{{ description }}<slot name="description" /><slot /></div>' },
  'el-button': { template: '<button><slot /></button>' },
  'el-icon': { template: '<i><slot /></i>' },
}

describe('AdminView 权限控制与空态', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
  })

  it('非管理员访问时显示「仅管理员可访问」空态及返回首页按钮', async () => {
    const userStore = useUserStore()
    userStore.setUser({
      id: 'u1',
      username: 'memberUser',
      display_name: '普通成员',
      avatar_url: '',
      bio: '',
      role: 'member',
      created_at: '2026-08-27T00:00:00Z',
    })

    const wrapper = mount(AdminView, {
      global: {
        stubs,
      },
    })

    await flushPromises()

    expect(wrapper.find('.admin-forbidden').exists()).toBe(true)
    expect(wrapper.text()).toContain('仅管理员可访问')
    expect(wrapper.text()).toContain('返回首页')
    expect(wrapper.find('.admin-layout').exists()).toBe(false)
  })

  it('管理员访问时正常渲染管理后台布局', async () => {
    const userStore = useUserStore()
    userStore.setUser({
      id: 'admin-1',
      username: 'lociAdmin',
      display_name: '管理员',
      avatar_url: '',
      bio: '',
      role: 'admin',
      created_at: '2026-08-27T00:00:00Z',
    })

    const wrapper = mount(AdminView, {
      global: {
        stubs: {
          ...stubs,
          OverviewTab: { template: '<div class="overview-tab-stub">总览</div>' },
        },
      },
    })

    await flushPromises()

    expect(wrapper.find('.admin-forbidden').exists()).toBe(false)
    expect(wrapper.find('.admin-layout').exists()).toBe(true)
    expect(wrapper.find('.rail-title').text()).toBe('平台治理')
    // 左栏必须是真 el-menu，不再是一排裸 <button class="rail-item">
    expect(wrapper.find('button.rail-item').exists()).toBe(false)
    expect(wrapper.findAll('.rail-nav .el-menu-item')).toHaveLength(6)
  })
})
