import { expect, it, vi } from 'vitest'
import { listAdminUsers } from './admin'

const request = vi.hoisted(() => vi.fn().mockResolvedValue({ items: [], total: 0 }))
vi.mock('@/shared/api/palace', () => ({ apiRequest: request }))

it('sends role and all page filters together, forwarding caller cancellation', async () => {
  const controller = new AbortController()
  await listAdminUsers({ role: 'visitor', status: 'active', keyword: 'A & B', limit: 30, offset: 60 }, controller.signal)
  const [path, options] = request.mock.calls[0]!
  const query = new URL(path, 'https://example.test').searchParams
  expect(Object.fromEntries(query)).toEqual({ role: 'visitor', status: 'active', keyword: 'A & B', limit: '30', offset: '60' })
  expect(options.signal).toBe(controller.signal)
})
