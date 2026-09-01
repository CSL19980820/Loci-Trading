import { beforeEach, describe, expect, it, vi } from 'vitest'
import { createPinia, setActivePinia } from 'pinia'

import { useUserStore } from '@/shared/stores/user'
import * as authApi from '@/shared/api/auth'
import type { AuthMeResponse, AuthSessionResponse, UserProfile } from '@/shared/types/auth'

vi.mock('@/shared/api/auth', () => ({
  getAuthSession: vi.fn(),
  getAuthMe: vi.fn(),
  getNotifications: vi.fn(),
  markNotificationsRead: vi.fn(),
  logout: vi.fn(),
  patchProfile: vi.fn(),
}))

describe('useUserStore', () => {
  const mockUser: UserProfile = {
    id: 'u_123',
    username: 'testuser',
    display_name: 'Test User',
    avatar_url: '',
    bio: 'hello',
    role: 'member',
    created_at: '2026-08-01T00:00:00Z',
    must_change_password: true,
  }

  beforeEach(() => {
    setActivePinia(createPinia())
    vi.clearAllMocks()
  })

  it('loads authenticated user session correctly', async () => {
    const sessionRes: AuthSessionResponse = {
      authenticated: true,
      username: 'testuser',
      user: mockUser,
    }
    vi.mocked(authApi.getAuthSession).mockResolvedValue(sessionRes)

    const store = useUserStore()
    expect(store.authenticated).toBe(false)

    const ok = await store.load()
    expect(ok).toBe(true)
    expect(store.authenticated).toBe(true)
    expect(store.user?.username).toBe('testuser')
    expect(store.isAdmin).toBe(false)
    expect(store.mustChangePassword).toBe(true)
  })

  it('handles unauthenticated session gracefully', async () => {
    const sessionRes: AuthSessionResponse = {
      authenticated: false,
      username: '',
      user: null,
    }
    vi.mocked(authApi.getAuthSession).mockResolvedValue(sessionRes)

    const store = useUserStore()
    const ok = await store.load()
    expect(ok).toBe(false)
    expect(store.authenticated).toBe(false)
    expect(store.user).toBeNull()
  })

  it('refreshes full profile, quota, and unread count', async () => {
    const meRes: AuthMeResponse = {
      user: { ...mockUser, role: 'admin' },
      identities: [],
      quota: {
        llm_monthly_tokens: 300000,
        llm_daily_calls: 200,
        strategy_slots: 20,
  publish_slots: 5,
        job_slots: 5,
     storage_mb: 2048,
      },
      sessions: [],
      unread: 3,
    }
    vi.mocked(authApi.getAuthMe).mockResolvedValue(meRes)

    const store = useUserStore()
    store.setUser(mockUser)

    await store.refresh()
    expect(store.isAdmin).toBe(true)
    expect(store.unread).toBe(3)
    expect(store.quota?.llm_monthly_tokens).toBe(300000)
  })

  it('clears state on logout', async () => {
    vi.mocked(authApi.logout).mockResolvedValue({ authenticated: false })

    const store = useUserStore()
    store.setUser(mockUser)
    expect(store.authenticated).toBe(true)

    await store.logout()
    expect(store.authenticated).toBe(false)
    expect(store.user).toBeNull()
    expect(store.quota).toBeNull()
    expect(store.unread).toBe(0)
  })

  it('updates profile via patchProfile', async () => {
    const updatedUser: UserProfile = { ...mockUser, display_name: 'Updated Name' }
    vi.mocked(authApi.patchProfile).mockResolvedValue(updatedUser)

    const store = useUserStore()
    store.setUser(mockUser)

    const res = await store.patchProfile({ display_name: 'Updated Name' })
    expect(res.display_name).toBe('Updated Name')
    expect(store.user?.display_name).toBe('Updated Name')
  })

  it('keeps the last known user when the backend is unreachable', async () => {
    vi.mocked(authApi.getAuthSession).mockRejectedValue(new Error('connect ECONNREFUSED'))

    const store = useUserStore()
    store.setUser(mockUser)

    const ok = await store.load()

    // 打不通 ≠ 已登出：清空会让网络抖一下就把整个界面降级成未登录。
    expect(ok).toBe(false)
    expect(store.available).toBe(false)
    expect(store.user?.username).toBe('testuser')
  })

  it('coalesces concurrent session loads into one request', async () => {
    vi.mocked(authApi.getAuthSession).mockResolvedValue({
      authenticated: true,
      username: 'testuser',
      user: mockUser,
    })

    const store = useUserStore()
    await Promise.all([store.load(), store.load(), store.load()])

  expect(authApi.getAuthSession).toHaveBeenCalledTimes(1)
  })

  it('loads notifications and announcements, then marks them read', async () => {
    vi.mocked(authApi.getNotifications).mockResolvedValue({
      items: [
      {
          id: 'n1',
     user_id: 'u_123',
     title: '战法被克隆',
      body: '有人克隆了你的战法',
       created_at: '2026-08-27T09:00:00+08:00',
        },
  ],
      unread: 1,
      announcements: [
      { id: 'a1', title: '本周维护', body: '周日 02:00 重启', level: 'info' },
      ],
    })
    vi.mocked(authApi.markNotificationsRead).mockResolvedValue({ marked: 1 })

    const store = useUserStore()
    store.setUser(mockUser)

    await store.loadNotifications()
    expect(store.unread).toBe(1)
    expect(store.announcements).toHaveLength(1)

    await store.markRead()
    expect(store.unread).toBe(0)
    expect(store.notifications[0]?.read_at).toBeTruthy()
  })
})
