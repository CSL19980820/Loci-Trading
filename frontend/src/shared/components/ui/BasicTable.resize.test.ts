import { mount } from '@vue/test-utils'
import { afterEach, describe, expect, it, vi } from 'vitest'

import BasicTable from './BasicTable.vue'

/** 只关心 spy 记到的参数，不耦合 vitest 的 mock 实现类型。 */
type ListenerSpy = { mock: { calls: unknown[][] } }

/**
 * 只挑 BasicTable 自己那一个 resize 监听器。
 * window 上还有 el-table / el-table-v2 内部注册的 `update`，
 * 混在一起数会把断言变成在测 Element Plus。
 */
function ownResizeHandlers(spy: ListenerSpy): unknown[] {
  return spy.mock.calls
    .filter(([type]) => type === 'resize')
    .map(([, handler]) => handler)
    .filter((handler) => typeof handler === 'function' && handler.name === 'calcOffsetHeight')
}

describe('BasicTable resize listener', () => {
  afterEach(() => vi.restoreAllMocks())

  it('removes the resize listener even after offsetHeight changes', async () => {
    const add = vi.spyOn(window, 'addEventListener')
    const remove = vi.spyOn(window, 'removeEventListener')

    const wrapper = mount(BasicTable, { props: { offsetHeight: 240 } })
    expect(ownResizeHandlers(add)).toHaveLength(1)

    // 泄漏的触发条件：注册时 offsetHeight 为真、卸载时为假。
    // 旧实现两端都包在 `if (props.offsetHeight)` 里，这里就漏掉了 remove。
    await wrapper.setProps({ offsetHeight: 0 })
    wrapper.unmount()

    expect(ownResizeHandlers(remove)).toEqual(ownResizeHandlers(add))
  })

  it('registers and unregisters symmetrically when offsetHeight starts at 0', () => {
    const add = vi.spyOn(window, 'addEventListener')
    const remove = vi.spyOn(window, 'removeEventListener')

    const wrapper = mount(BasicTable, { props: { offsetHeight: 0 } })
    wrapper.unmount()

    expect(ownResizeHandlers(add)).toHaveLength(1)
    expect(ownResizeHandlers(remove)).toEqual(ownResizeHandlers(add))
  })

  it('recomputes the table height when offsetHeight changes at runtime', async () => {
    const wrapper = mount(BasicTable, { props: { offsetHeight: 0 } })
    const table = () => wrapper.findComponent({ name: 'ElTable' })
    expect(table().props('height')).toBeUndefined()

    await wrapper.setProps({ offsetHeight: 200 })
    expect(table().props('height')).toBe(Math.max(120, window.innerHeight - 200))

    wrapper.unmount()
  })

  it('feeds the body clientHeight to el-table when height is 100%', async () => {
    const wrapper = mount(BasicTable, {
      props: { height: '100%' },
      attachTo: document.body,
    })
    const bodyEl = wrapper.find('.basic-table__body').element as HTMLElement
    Object.defineProperty(bodyEl, 'clientHeight', { configurable: true, get: () => 640 })
    window.dispatchEvent(new Event('resize'))
    await wrapper.vm.$nextTick()
    const { promise, resolve } = Promise.withResolvers<void>()
    requestAnimationFrame(() => resolve())
    await promise
    const table = wrapper.findComponent({ name: 'ElTable' })
    expect(wrapper.classes()).toContain('basic-table--fill')
    expect(table.props('height')).toBe(640)
    wrapper.unmount()
  })
})
