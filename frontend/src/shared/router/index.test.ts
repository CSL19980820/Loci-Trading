import { beforeEach, describe, expect, it, vi } from 'vitest'

import { getSession } from '@/shared/api/palace'

import router from './index'

vi.mock('@/shared/api/palace', () => ({
  getSession: vi.fn(),
}))

describe('router failure boundaries', () => {
  beforeEach(() => {
    vi.mocked(getSession).mockReset()
  })

  it('redirects an unknown path and renders a session-check failure route', async () => {
    vi.mocked(getSession).mockResolvedValue({ authenticated: true, username: 'tester' })
    await router.push('/not-a-route')
    expect(router.currentRoute.value.name).toBe('pulse')

    vi.mocked(getSession).mockRejectedValue(new Error('会话校验不可用'))
    await router.push('/ledger')
    expect(router.currentRoute.value.name).toBe('auth-unavailable')
    expect(router.currentRoute.value.query.redirect).toBe('/ledger')
  })

  it('does not probe the session again on the failure route', async () => {
    vi.mocked(getSession).mockRejectedValue(new Error('会话校验不可用'))

    await router.push('/auth-unavailable')

    expect(router.currentRoute.value.name).toBe('auth-unavailable')
    expect(getSession).not.toHaveBeenCalled()
  })

  it('opens peek without waiting on session (avoids blank quote window)', async () => {
    const pending = new Promise<never>(() => {
      /* never resolves — would white-screen Peek if awaited */
    })
    vi.mocked(getSession).mockReturnValue(pending as never)

    await router.push('/peek')

    expect(router.currentRoute.value.name).toBe('peek')
    expect(getSession).not.toHaveBeenCalled()
  })

  it('keeps peek open even when session probe would fail', async () => {
    vi.mocked(getSession).mockRejectedValue(new Error('会话校验不可用'))

    await router.push('/peek')

    expect(router.currentRoute.value.name).toBe('peek')
    expect(getSession).not.toHaveBeenCalled()
  })
})
