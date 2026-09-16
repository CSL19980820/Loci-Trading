import { createPinia, setActivePinia } from 'pinia'
import { beforeEach, describe, expect, it, vi } from 'vitest'

import { getAuthSession } from '@/shared/api/auth'
import { useUserStore } from '@/shared/stores/user'

import router from './index'

vi.mock('@/shared/api/auth', () => ({
  getAuthSession: vi.fn(),
  getAuthMe: vi.fn(),
  getNotifications: vi.fn(),
  markNotificationsRead: vi.fn(),
  logout: vi.fn(),
  patchProfile: vi.fn(),
}))

/**
 * 这些用例会真正走懒加载路由，首次命中要把整棵页面组件树转译进来，
 * 在冷缓存的机器上稳定超过 vitest 默认的 5s，属于预算不够而非逻辑失败。
 */
const ROUTE_LOAD_TIMEOUT = 25_000

const TESTER = {
  id: 'u_test',
  username: 'tester',
  display_name: 'tester',
  avatar_url: '',
  bio: '',
  role: 'member' as const,
  created_at: '2026-01-01T00:00:00+08:00',
}

describe('router failure boundaries', () => {
  beforeEach(async () => {
    setActivePinia(createPinia())
    vi.mocked(getAuthSession).mockReset()
    /*
     * router 是模块单例，位置会跨用例带过来。若上一条用例正好停在下一条要 push 的
     * 路由上，那次 push 就是重复导航——守卫压根不跑，断言「探了几次会话」全部失真。
     * 复位到失败页（守卫对它直接放行、不碰会话）最省事。
     */
    await router.replace('/auth-unavailable')
    vi.mocked(getAuthSession).mockReset()
  })

  it('redirects an unknown path to the dashboard', { timeout: ROUTE_LOAD_TIMEOUT }, async () => {
    vi.mocked(getAuthSession).mockResolvedValue({
      authenticated: true,
      username: 'tester',
      user: TESTER,
    })
    await router.push('/not-a-route')
    expect(router.currentRoute.value.name).toBe('pulse')
  })

  it(
    'sends a failed session check to the failure route',
    { timeout: ROUTE_LOAD_TIMEOUT },
    async () => {
      vi.mocked(getAuthSession).mockRejectedValue(new Error('会话校验不可用'))
      await router.push('/pool')
      expect(router.currentRoute.value.name).toBe('auth-unavailable')
      expect(router.currentRoute.value.query.redirect).toBe('/pool')
    },
  )

  /*
   * 失败页的「重试」就是一次 router.replace。会话缓存**不能**吃这一档：
   * 上次探测压根没打通（available=false）时必须真探一次，否则后端起来了也回不去。
   */
  it('失败后重试会真的再探一次会话', { timeout: ROUTE_LOAD_TIMEOUT }, async () => {
    vi.mocked(getAuthSession).mockRejectedValueOnce(new Error('会话校验不可用'))
    await router.push('/pool')
    expect(router.currentRoute.value.name).toBe('auth-unavailable')

    vi.mocked(getAuthSession).mockResolvedValue({
      authenticated: true,
      username: 'tester',
      user: TESTER,
    })
    await router.replace('/pool')

    expect(getAuthSession).toHaveBeenCalledTimes(2)
    expect(router.currentRoute.value.name).toBe('pool')
  })

  /*
   * 「点菜单先卡一会儿」的根因回归：守卫过去每次导航都 `await userStore.load()`，
   * 而 load() 只有 inflight 去重、没有缓存短路 —— 于是每切一个页面都要等一次
   * GET /api/auth/session 的网络往返，页面停在旧页不动。
   */
  it('已水合后不再为每次导航打 /auth/session', { timeout: ROUTE_LOAD_TIMEOUT }, async () => {
    vi.mocked(getAuthSession).mockResolvedValue({
      authenticated: true,
      username: 'tester',
      user: TESTER,
    })

    await router.push('/pool')
    expect(getAuthSession).toHaveBeenCalledTimes(1)

    await router.push('/winrate')
    await router.push('/insights')

    // 三次导航、一次请求：后两次全走 ensureLoaded() 的内存缓存
    expect(getAuthSession).toHaveBeenCalledTimes(1)
    expect(router.currentRoute.value.name).toBe('winrate')
  })

  it('缓存过期后在后台补一次，但导航不等它', { timeout: ROUTE_LOAD_TIMEOUT }, async () => {
    vi.mocked(getAuthSession).mockResolvedValue({
      authenticated: true,
      username: 'tester',
      user: TESTER,
    })
    await router.push('/pool')
    expect(getAuthSession).toHaveBeenCalledTimes(1)

    // 把时钟推过 60s 的新鲜期
    const realNow = Date.now
    const stale = realNow() + 61_000
    vi.spyOn(Date, 'now').mockImplementation(() => stale)
    try {
      await router.push('/winrate')
    } finally {
      vi.mocked(Date.now).mockRestore()
    }

    // 重验发生了，但它是 fire-and-forget：导航照样落地在目标页
    expect(getAuthSession).toHaveBeenCalledTimes(2)
    expect(router.currentRoute.value.name).toBe('winrate')
  })

  it(
    'hydrates the user store so a refresh keeps the avatar and admin entry',
    { timeout: ROUTE_LOAD_TIMEOUT },
    async () => {
      vi.mocked(getAuthSession).mockResolvedValue({
        authenticated: true,
        username: 'lociAdmin',
        user: { ...TESTER, username: 'lociAdmin', role: 'admin', must_change_password: true },
      })

      await router.push('/pool')

      // 守卫水合失败时这三条会全灭：头像显示未登录、管理后台入口消失、
      // 强制改密提示条不出现。这正是「刷新即失忆」的三个可观测症状。
      const store = useUserStore()
      expect(store.authenticated).toBe(true)
      expect(store.isAdmin).toBe(true)
      expect(store.mustChangePassword).toBe(true)
    },
  )

  it(
    'separates "not logged in" from "backend is down"',
    { timeout: ROUTE_LOAD_TIMEOUT },
    async () => {
      vi.mocked(getAuthSession).mockResolvedValue({
        authenticated: false,
        username: '',
        user: null,
      })

      await router.push('/winrate')

      // 后端答得上话、只是没登录 —— 去登录页，而不是「服务不可用」。
      expect(router.currentRoute.value.name).toBe('login')
      expect(router.currentRoute.value.query.redirect).toBe('/winrate')
    },
  )

  it('does not probe the session again on the failure route', async () => {
    vi.mocked(getAuthSession).mockRejectedValue(new Error('会话校验不可用'))

    await router.push('/auth-unavailable')

    expect(router.currentRoute.value.name).toBe('auth-unavailable')
    expect(getAuthSession).not.toHaveBeenCalled()
  })

  it(
    'opens peek without waiting on session (avoids blank quote window)',
    { timeout: ROUTE_LOAD_TIMEOUT },
    async () => {
      const pending = new Promise<never>(() => {
        /* never resolves — would white-screen Peek if awaited */
      })
      vi.mocked(getAuthSession).mockReturnValue(pending as never)

      await router.push('/peek')

      expect(router.currentRoute.value.name).toBe('peek')
      expect(getAuthSession).not.toHaveBeenCalled()
    },
  )

  it(
    'keeps peek open even when session probe would fail',
    { timeout: ROUTE_LOAD_TIMEOUT },
    async () => {
      vi.mocked(getAuthSession).mockRejectedValue(new Error('会话校验不可用'))

      await router.push('/peek')

      expect(router.currentRoute.value.name).toBe('peek')
      expect(getAuthSession).not.toHaveBeenCalled()
    },
  )
})
