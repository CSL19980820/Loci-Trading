import { flushPromises, mount } from '@vue/test-utils'
import { defineComponent, h, ref } from 'vue'
import { createMemoryHistory, createRouter } from 'vue-router'
import { beforeEach, describe, expect, it, vi } from 'vitest'

import { getScheduleStatus, runJob } from '@/shared/api/quant'

import JobsTab from './JobsTab.vue'

const jobsError = ref<Error | null>(null)
const jobs = ref<Array<Record<string, unknown>>>([])
const emptySchedule = { running: false, jobs: [] } satisfies Awaited<ReturnType<typeof getScheduleStatus>>

vi.mock('@/features/ops/composables/useJobsQuery', () => ({
  useJobsQuery: () => ({
    jobs,
    isPending: ref(false),
    error: jobsError,
    refetch: vi.fn().mockResolvedValue(undefined),
  }),
}))

vi.mock('@/shared/api/quant', () => ({
  getScheduleStatus: vi.fn().mockResolvedValue(null),
  getStrategies: vi.fn().mockResolvedValue([]),
  getSkills: vi.fn().mockResolvedValue([]),
  getProviders: vi.fn().mockResolvedValue([]),
  getJobQuota: vi.fn().mockResolvedValue({ used: 2, limit: 5, unlimited: false, managed: 7 }),
  createJob: vi.fn(),
  deleteJob: vi.fn(),
  runJob: vi.fn(),
  updateJob: vi.fn(),
}))

function mountJobs() {
  const router = createRouter({
    history: createMemoryHistory(),
    routes: [{ path: '/', component: JobsTab }],
  })
  return router.push('/').then(async () => {
    await router.isReady()
    return mount(JobsTab, {
      global: {
        plugins: [router],
        stubs: {
          SettingsPanel: { template: '<section><slot name="action" /><slot /></section>' },
          EmptyState: { template: '<div><slot /></div>' },
          JobDetailPane: defineComponent({
            emits: ['fire'],
            setup(_props, { emit, expose }) {
              expose({ reloadRuns: async () => undefined })
              return () => h('button', { 'data-testid': 'fire-job', onClick: () => emit('fire') }, '执行')
            },
          }),
          JobEditorDialog: true,
          JobRunsDialog: true,
          'el-alert': { props: ['title'], template: '<div role="alert">{{ title }}</div>' },
          'el-button': { template: '<button><slot /></button>' },
          'el-select': { template: '<select><slot /></select>' },
          'el-option': true,
          'el-scrollbar': { template: '<div><slot /></div>' },
          'el-tag': { template: '<span><slot /></span>' },
        },
      },
    })
  })
}

describe('JobsTab failure state', () => {
  beforeEach(() => {
    jobsError.value = null
    jobs.value = []
    vi.mocked(getScheduleStatus).mockReset()
    vi.mocked(getScheduleStatus).mockResolvedValue(emptySchedule)
    vi.mocked(runJob).mockReset()
  })

  it('shows the jobs query failure instead of the empty jobs state', async () => {
    jobsError.value = new Error('任务服务不可用')
    const wrapper = await mountJobs()
    await flushPromises()

    expect(wrapper.text()).toContain('任务服务不可用')
    expect(wrapper.text()).not.toContain('还没有定时任务')
  })

  it('shows a schedule failure instead of the empty jobs state', async () => {
    vi.mocked(getScheduleStatus).mockRejectedValue(new Error('调度状态不可用'))
    const wrapper = await mountJobs()
    await flushPromises()

    expect(wrapper.text()).toContain('调度状态不可用')
    expect(wrapper.text()).not.toContain('还没有定时任务')
  })

  it('shows the skip reason instead of reporting success', async () => {
    jobs.value = [
      {
        id: 'job-1',
        name: '收盘同步',
        kind: 'sync',
        cron: '',
        config: {},
        enabled: true,
        last_run_at: '',
        last_status: '',
        created_at: '',
        updated_at: '',
      },
    ]
    vi.mocked(runJob).mockResolvedValue({
      run_id: 'run-1',
      status: 'skipped',
      error: '当前不是交易时段',
    })
    const wrapper = await mountJobs()
    await flushPromises()

    await wrapper.get('[data-testid="fire-job"]').trigger('click')
    await flushPromises()

    expect(wrapper.text()).toContain('已跳过：当前不是交易时段')
    expect(wrapper.text()).not.toContain('已跑完')
  })
})
