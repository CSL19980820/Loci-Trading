import { flushPromises, mount } from '@vue/test-utils'
import { createPinia, setActivePinia } from 'pinia'
import { beforeEach, describe, expect, it, vi } from 'vitest'

import * as confirmLib from '@/shared/lib/confirm'
import { useUserStore } from '@/shared/stores/user'
import UsersTab from '../components/UsersTab.vue'

const api = vi.hoisted(() => ({
  listAdminUsers: vi.fn(),
  createAdminUser: vi.fn(),
  setUserRole: vi.fn(),
  setUserStatus: vi.fn(),
  setUserQuota: vi.fn(),
  resetUserPassword: vi.fn(),
  notifyUser: vi.fn(),
}))

vi.mock('@/shared/api/admin', () => api)

const confirmSpy = vi.spyOn(confirmLib, 'confirmDangerous')

function makeUser(overrides: Record<string, unknown>) {
  return {
    id: 'u-member',
    username: 'member1',
    display_name: '普通成员',
    email: 'member@example.com',
    role: 'member' as const,
    status: 'active' as const,
    tenant_id: 'tenant-3',
    avatar_url: '',
    bio: '',
    email_verified_at: null,
    created_at: '2026-08-27T00:00:00Z',
    updated_at: '2026-08-27T00:00:00Z',
    last_login_at: null,
    must_change_password: false,
    quota: {
      llm_monthly_tokens: 300000,
      llm_daily_calls: 200,
      strategy_slots: 20,
      publish_slots: 5,
      job_slots: 5,
      storage_mb: 2048,
    },
    usage: { llm_tokens: 50 },
    ...overrides,
  }
}

const mockUsers = [
  makeUser({
    id: 'u-other-admin',
    username: 'otherAdmin',
    display_name: '另一个管理员',
    email: 'other@example.com',
    role: 'admin' as const,
    email_verified_at: '2026-08-27T00:00:00Z',
    tenant_id: 'tenant-2',
    usage: { llm_tokens: 100 },
  }),
  makeUser({}),
]

/**
 * 表体/表单换成公共组件后不需要在这里复刻它们的内部结构：
 * 本用例守的是「危险操作必须二次确认」这条业务纪律，不是渲染细节。
 */
const stubs = {
  PageContainer: {
    template: '<div><slot name="search" /><slot name="main" /></div>',
  },
  BasicForm: true,
  BasicTable: true,
  ListToolbar: true,
  RowActions: true,
  CreateUserDialog: true,
  UserQuotaDialog: true,
  ResetPasswordDialog: true,
  NotifyUserDialog: true,
  'el-button': {
    template: '<button :disabled="$attrs.disabled" @click="$emit(\'click\')"><slot /></button>',
  },
}

describe('UsersTab 危险操作二次确认', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
    vi.clearAllMocks()
    api.listAdminUsers.mockResolvedValue({ items: mockUsers, total: 2 })

    const userStore = useUserStore()
    userStore.setUser({
      id: 'admin-me',
      username: 'lociAdmin',
      display_name: '我（管理员）',
      avatar_url: '',
      bio: '',
      role: 'admin',
      created_at: '2026-08-27T00:00:00Z',
    })
  })

  it('管理员降级、停用用户时必须触发 confirmDangerous', async () => {
    const wrapper = mount(UsersTab, { global: { stubs } })
    await flushPromises()

    const vm = wrapper.vm as unknown as {
      handleToggleRole: (row: (typeof mockUsers)[number]) => Promise<void>
      handleToggleStatus: (row: (typeof mockUsers)[number]) => Promise<void>
    }

    confirmSpy.mockResolvedValueOnce(true)
    api.setUserRole.mockResolvedValueOnce({ ...mockUsers[0], role: 'member' })
    await vm.handleToggleRole(mockUsers[0])

    expect(confirmSpy).toHaveBeenCalledWith(
      expect.stringContaining('降级'),
      expect.any(String),
      expect.any(String),
    )
    expect(api.setUserRole).toHaveBeenCalledWith('u-other-admin', 'member')

    confirmSpy.mockResolvedValueOnce(true)
    api.setUserStatus.mockResolvedValueOnce({ ...mockUsers[1], status: 'disabled' })
    await vm.handleToggleStatus(mockUsers[1])

    expect(confirmSpy).toHaveBeenCalledWith(
      expect.stringContaining('停用'),
      expect.any(String),
      expect.any(String),
    )
    expect(api.setUserStatus).toHaveBeenCalledWith('u-member', 'disabled')
  })

  it('取消确认时不发请求', async () => {
    const wrapper = mount(UsersTab, { global: { stubs } })
    await flushPromises()

    const vm = wrapper.vm as unknown as {
      handleToggleStatus: (row: (typeof mockUsers)[number]) => Promise<void>
    }

    confirmSpy.mockResolvedValueOnce(false)
    await vm.handleToggleStatus(mockUsers[1])

    expect(api.setUserStatus).not.toHaveBeenCalled()
  })
})
