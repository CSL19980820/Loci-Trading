import { flushPromises, shallowMount, type VueWrapper } from '@vue/test-utils'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { defineComponent, ref } from 'vue'
import type { AdminUserItem, AdminUsersResponse } from '@/shared/types/admin'
import UsersTab from './UsersTab.vue'

const mocks = vi.hoisted(() => ({ list: vi.fn(), error: vi.fn() }))
vi.mock('@/shared/api/admin', () => ({
  listAdminUsers: mocks.list, setUserRole: vi.fn(), setUserStatus: vi.fn(),
}))
vi.mock('@/shared/stores/user', () => ({ useUserStore: () => ({ user: { id: 'self' } }) }))
vi.mock('vue-sonner', () => ({ toast: { error: mocks.error, success: vi.fn(), warning: vi.fn() } }))
vi.mock('@vueuse/core', async (importOriginal) => ({
  ...await importOriginal<typeof import('@vueuse/core')>(),
  useMediaQuery: () => ref(true),
}))

function user(index: number): AdminUserItem {
  return { id: String(index), username: `user${index}`, display_name: `User ${index}`,
    role: 'visitor', status: 'active', usage: {} } as AdminUserItem
}
function deferred() {
  let resolve!: (page: AdminUsersResponse) => void
  let reject!: (reason: Error) => void
  const promise = new Promise<AdminUsersResponse>((done, fail) => { resolve = done; reject = fail })
  return { promise, resolve, reject }
}
const wrappers: VueWrapper[] = []
function mountUsers() {
  const wrapper = shallowMount(UsersTab, { global: { stubs: {
    Select: defineComponent({ name: 'Select', props: ['modelValue'], emits: ['update:modelValue'], template: '<div><slot /></div>' }),
    Button: defineComponent({ name: 'Button', template: '<button><slot /></button>' }),
  } } })
  wrappers.push(wrapper)
  return wrapper
}
function more(wrapper: ReturnType<typeof mountUsers>) {
  return wrapper.get('button.users__more')
}

beforeEach(() => vi.clearAllMocks())
afterEach(() => { wrappers.splice(0).forEach(wrapper => wrapper.unmount()) })

describe('mobile admin users', () => {
  it('passes role to the server and visits three pages without repeated offsets or duplicate rows', async () => {
    const all = Array.from({ length: 65 }, (_, i) => user(i))
    mocks.list.mockImplementation(async (params) => ({ items: all.slice(params.offset, params.offset + params.limit), total: all.length }))
    const wrapper = mountUsers()
    await flushPromises()
    wrapper.findAllComponents({ name: 'Select' })[1]!.vm.$emit('update:modelValue', 'visitor')
    await flushPromises()
    mocks.list.mockClear()
    await more(wrapper).trigger('click')
    await flushPromises()
    await more(wrapper).trigger('click')
    await flushPromises()
    expect(mocks.list.mock.calls.map(call => call[0].offset)).toEqual([30, 60])
    expect(mocks.list.mock.calls.every(call => call[0].role === 'visitor')).toBe(true)
    const names = wrapper.findAll('.user-card__name').map(node => node.text())
    expect(names).toHaveLength(65)
    expect(new Set(names).size).toBe(65)
    expect(wrapper.find('button.users__more').exists()).toBe(false)
  })

  it('discards an old response when filters change, and aborts it', async () => {
    const old = deferred()
    const current = deferred()
    mocks.list.mockReturnValueOnce(old.promise).mockReturnValueOnce(current.promise)
    const wrapper = mountUsers()
    const oldSignal = mocks.list.mock.calls[0]![1] as AbortSignal
    wrapper.findAllComponents({ name: 'Select' })[1]!.vm.$emit('update:modelValue', 'admin')
    await flushPromises()
    expect(oldSignal.aborted).toBe(true)
    current.resolve({ items: [user(9)], total: 1 })
    await flushPromises()
    old.resolve({ items: [user(1)], total: 100 })
    await flushPromises()
    expect(wrapper.findAll('.user-card__name').map(node => node.text())).toEqual(['User 9'])
    expect(wrapper.find('button.users__more').exists()).toBe(false)
  })

  it('ignores duplicate append clicks, preserves rows on failure, and retries the same offset', async () => {
    const next = deferred()
    mocks.list.mockResolvedValueOnce({ items: Array.from({ length: 30 }, (_, i) => user(i)), total: 31 })
      .mockReturnValueOnce(next.promise)
      .mockResolvedValueOnce({ items: [user(30)], total: 31 })
    const wrapper = mountUsers()
    await flushPromises()
    void more(wrapper).trigger('click')
    void more(wrapper).trigger('click')
    await flushPromises()
    expect(mocks.list).toHaveBeenCalledTimes(2)
    next.reject(new Error('offline'))
    await flushPromises()
    expect(wrapper.findAll('.user-card')).toHaveLength(30)
    expect(mocks.error).toHaveBeenCalledOnce()
    await more(wrapper).trigger('click')
    await flushPromises()
    expect(mocks.list.mock.calls.map(call => call[0].offset)).toEqual([0, 30, 30])
    expect(wrapper.findAll('.user-card')).toHaveLength(31)
  })

  it('aborts on unmount without displaying an error from a late rejection', async () => {
    const pending = deferred()
    mocks.list.mockReturnValueOnce(pending.promise)
    const wrapper = mountUsers()
    const signal = mocks.list.mock.calls[0]![1] as AbortSignal
    wrapper.unmount()
    expect(signal.aborted).toBe(true)
    pending.reject(new Error('cancelled'))
    await flushPromises()
    expect(mocks.error).not.toHaveBeenCalled()
  })
})
