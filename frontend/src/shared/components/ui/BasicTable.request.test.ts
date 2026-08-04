import { mount } from '@vue/test-utils'
import { describe, expect, it, vi } from 'vitest'

import BasicTable from './BasicTable.vue'

function deferred<T>(): { promise: Promise<T>; resolve: (value: T) => void } {
  let resolve!: (value: T) => void
  const promise = new Promise<T>((done) => {
    resolve = done
  })
  return { promise, resolve }
}

describe('BasicTable request ordering', () => {
  it('does not let an older response replace a newer reload', async () => {
    const older = deferred<{ list: Record<string, unknown>[]; total: number }>()
    const newer = deferred<{ list: Record<string, unknown>[]; total: number }>()
    const request = vi
      .fn()
      .mockReturnValueOnce(older.promise)
      .mockReturnValueOnce(newer.promise)
    const wrapper = mount(BasicTable, {
      props: {
        request,
        hasDefaultRequest: false,
      },
    })

    const table = wrapper.vm as unknown as {
      reloadTable: () => Promise<void>
      getTableData: () => Record<string, unknown>[]
    }
    const first = table.reloadTable()
    const second = table.reloadTable()
    newer.resolve({ list: [{ code: 'new' }], total: 1 })
    await second
    older.resolve({ list: [{ code: 'old' }], total: 1 })
    await first

    expect(table.getTableData()).toEqual([{ code: 'new' }])
    wrapper.unmount()
  })
})
