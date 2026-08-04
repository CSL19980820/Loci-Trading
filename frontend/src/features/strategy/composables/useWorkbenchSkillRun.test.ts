import { flushPromises, mount } from '@vue/test-utils'
import { defineComponent, h } from 'vue'
import { afterEach, describe, expect, it, vi } from 'vitest'

const api = vi.hoisted(() => ({
  getSkillRun: vi.fn(),
  getSkillRunEvents: vi.fn(),
  replySkillRun: vi.fn(),
  startSkillRun: vi.fn(),
}))

vi.mock('@/shared/api/quant', () => api)

import { useWorkbenchSkillRun } from './useWorkbenchSkillRun'

function deferred<T>(): { promise: Promise<T>; resolve: (value: T) => void } {
  let resolve!: (value: T) => void
  const promise = new Promise<T>((done) => {
    resolve = done
  })
  return { promise, resolve }
}

describe('useWorkbenchSkillRun lifecycle', () => {
  afterEach(() => {
    vi.useRealTimers()
    vi.restoreAllMocks()
    vi.clearAllMocks()
  })

  it('does not start polling after the composable is unmounted during start', async () => {
    vi.useFakeTimers()
    const setIntervalSpy = vi.spyOn(globalThis, 'setInterval')
    const started = deferred<{ run: { id: string; status: string } }>()
    api.startSkillRun.mockReturnValue(started.promise)

    let run!: ReturnType<typeof useWorkbenchSkillRun>
    const Probe = defineComponent({
      setup() {
        run = useWorkbenchSkillRun()
        return () => h('div')
      },
    })
    const wrapper = mount(Probe)

    const pendingStart = run.start({ slug: 'demo', name: '演示', provider: 'local' })
    wrapper.unmount()
    started.resolve({ run: { id: 'SR-1', status: 'running' } })
    await flushPromises()

    expect(await pendingStart).toBe(false)
    expect(api.getSkillRunEvents).not.toHaveBeenCalled()
    expect(setIntervalSpy).not.toHaveBeenCalled()
  })
})
