import { beforeEach, describe, expect, it, vi } from 'vitest'

import { getSession } from '@/shared/api/palace'

import router from './index'

vi.mock('@/shared/api/palace', () => ({
  getSession: vi.fn(),
}))

/**
 * 这些用例会真正走懒加载路由，首次命中要把整棵页面组件树转译进来，
 * 在冷缓存的机器上稳定超过 vitest 默认的 5s，属于预算不够而非逻辑失败。
 */
const ROUTE_LOAD_TIMEOUT = 25_000

describe('router failure boundaries', () => {
  beforeEach(() => {
    vi.mocked(getSession).mockReset()
  })

  it('redirects an unknown path and renders a session-check failure route', { timeout: ROUTE_LOAD_TIMEOUT }, async () => {
    vi.mocked(getSession).mockResolvedValue({ authenticated: true, username: 'tester' })
    await router.push('/not-a-route')
    expect(router.currentRoute.value.name).toBe('pulse')

    vi.mocked(getSession).mockRejectedValue(new Error('会话校验不可用'))
    await router.push('/pool')
    expect(router.currentRoute.value.name).toBe('auth-unavailable')
    expect(router.currentRoute.value.query.redirect).toBe('/pool')
  })

  it('does not probe the session again on the failure route', async () => {
    vi.mocked(getSession).mockRejectedValue(new Error('会话校验不可用'))

    await router.push('/auth-unavailable')

    expect(router.currentRoute.value.name).toBe('auth-unavailable')
    expect(getSession).not.toHaveBeenCalled()
  })

  it('opens peek without waiting on session (avoids blank quote window)', { timeout: ROUTE_LOAD_TIMEOUT }, async () => {
    const pending = new Promise<never>(() => {
      /* never resolves — would white-screen Peek if awaited */
    })
    vi.mocked(getSession).mockReturnValue(pending as never)

    await router.push('/peek')

    expect(router.currentRoute.value.name).toBe('peek')
    expect(getSession).not.toHaveBeenCalled()
  })

  it('keeps peek open even when session probe would fail', { timeout: ROUTE_LOAD_TIMEOUT }, async () => {
    vi.mocked(getSession).mockRejectedValue(new Error('会话校验不可用'))

    await router.push('/peek')

    expect(router.currentRoute.value.name).toBe('peek')
    expect(getSession).not.toHaveBeenCalled()
  })
})
