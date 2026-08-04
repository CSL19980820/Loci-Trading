import { mount } from '@vue/test-utils'
import { defineComponent, h } from 'vue'
import { afterEach, describe, expect, it, vi } from 'vitest'

import { createOpsFeedback, useOpsFeedback } from './useOpsFeedback'

function deferred<T>() {
  let resolve!: (value: T) => void
  const promise = new Promise<T>((done) => {
    resolve = done
  })
  return { promise, resolve }
}

describe('useOpsFeedback', () => {
  afterEach(() => {
    vi.restoreAllMocks()
  })

  it('creates a local fallback without an injection warning', () => {
    let feedback: ReturnType<typeof useOpsFeedback> | undefined
    const Probe = defineComponent({
      setup() {
        feedback = useOpsFeedback()
        return () => h('div')
      },
    })
    const warning = vi.spyOn(console, 'warn').mockImplementation(() => undefined)
    const wrapper = mount(Probe)

    expect(feedback?.busy.value).toBe(false)
    expect(warning).not.toHaveBeenCalledWith(expect.stringContaining('ops-feedback'))
    wrapper.unmount()
  })

  it('keeps busy until all concurrent guarded tasks settle', async () => {
    const feedback = createOpsFeedback()
    const first = deferred<void>()
    const second = deferred<void>()

    const firstRun = feedback.guard(() => first.promise)
    const secondRun = feedback.guard(() => second.promise)
    expect(feedback.busy.value).toBe(true)

    first.resolve()
    await firstRun
    expect(feedback.busy.value).toBe(true)

    second.resolve()
    await secondRun
    expect(feedback.busy.value).toBe(false)
  })
})
