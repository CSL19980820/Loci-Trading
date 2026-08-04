import { flushPromises, mount } from '@vue/test-utils'
import { afterEach, describe, expect, it, vi } from 'vitest'

const api = vi.hoisted(() => ({
  getProviders: vi.fn(),
  getSkillJob: vi.fn(),
  upsertSkillJob: vi.fn(),
}))

vi.mock('@/shared/api/quant', () => ({ getProviders: api.getProviders }))
vi.mock('@/shared/api/quant_ops', () => ({
  getSkillJob: api.getSkillJob,
  upsertSkillJob: api.upsertSkillJob,
}))

import SkillJobConfigPanel from './SkillJobConfigPanel.vue'

function deferred<T>(): { promise: Promise<T>; resolve: (value: T) => void } {
  let resolve!: (value: T) => void
  const promise = new Promise<T>((done) => {
    resolve = done
  })
  return { promise, resolve }
}

function job(slug: string, run: string): Record<string, unknown> {
  return {
    id: `JOB-${slug}`,
    name: `skill:${slug}`,
    kind: 'skill',
    cron: '30 15 * * 1-5',
    enabled: true,
    bound: true,
    slug,
    next_runs: [run],
    config: {
      provider: `${slug}-provider`,
      push_wecom: true,
      schedule: { mode: 'once', run_hour: 15, run_minute: 30 },
    },
  }
}

function mountPanel(slug: string) {
  return mount(SkillJobConfigPanel, {
    props: { slug },
    global: {
      stubs: {
        'el-form': { template: '<div><slot /></div>' },
        'el-form-item': { template: '<div><slot /></div>' },
        'el-switch': true,
        'el-select': { template: '<div><slot /></div>' },
        'el-option': { props: ['label'], template: '<span>{{ label }}</span>' },
        'el-input': true,
        'el-radio-group': { template: '<div><slot /></div>' },
        'el-radio-button': { template: '<span><slot /></span>' },
        'el-button': { template: '<button><slot /></button>' },
      },
    },
  })
}

describe('SkillJobConfigPanel request ordering', () => {
  afterEach(() => vi.clearAllMocks())

  it('keeps the newest slug when an older job response arrives later', async () => {
    const oldJob = deferred<Record<string, unknown>>()
    const newJob = deferred<Record<string, unknown>>()
    api.getProviders.mockResolvedValue([])
    api.getSkillJob.mockImplementation((slug: string) =>
      slug === 'old-skill' ? oldJob.promise : newJob.promise,
    )

    const wrapper = mountPanel('old-skill')
    await wrapper.setProps({ slug: 'new-skill' })
    newJob.resolve(job('new-skill', 'new-run'))
    await flushPromises()
    oldJob.resolve(job('old-skill', 'old-run'))
    await flushPromises()

    expect(wrapper.text()).toContain('new-run')
    expect(wrapper.text()).not.toContain('old-run')
    wrapper.unmount()
  })
})
