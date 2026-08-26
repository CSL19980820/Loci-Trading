import { flushPromises, mount } from '@vue/test-utils'
import { afterEach, describe, expect, it, vi } from 'vitest'

import type { ResearchBacktestJob } from '@/shared/types/quant-research'

const api = vi.hoisted(() => ({
  submitPth252FactorJob: vi.fn(),
  getResearchFactorJob: vi.fn(),
  getResearchBacktestRun: vi.fn(),
  researchArtifactUrl: vi.fn(),
}))

vi.mock('@/shared/api/quant_research', () => api)

import ResearchFactorPanel from './ResearchFactorPanel.vue'

function job(id: string, status: ResearchBacktestJob['status'], runId = ''): ResearchBacktestJob {
  return { id, status, request: {}, run_id: runId, error: '', created_at: '', updated_at: '' }
}

function mountPanel() {
  return mount(ResearchFactorPanel, {
    global: {
      stubs: {
        'el-form': { template: '<form><slot /></form>' },
        'el-form-item': { template: '<div><slot /></div>' },
        'el-date-picker': true,
        'el-input': {
          props: ['modelValue'],
          emits: ['update:modelValue'],
          template: '<input :value="modelValue" @input="$emit(\'update:modelValue\', $event.target.value)" />',
        },
        'el-alert': { props: ['title'], template: '<div>{{ title }}</div>' },
        'el-tag': { template: '<span><slot /></span>' },
        'el-button': { emits: ['click'], template: '<button type="button" @click="$emit(\'click\')"><slot /></button>' },
        'el-descriptions': { template: '<div><slot /></div>' },
        'el-descriptions-item': { template: '<div><slot /></div>' },
        'el-table': { template: '<div><slot /></div>' },
        'el-table-column': true,
        'el-link': true,
      },
    },
  })
}

describe('ResearchFactorPanel', () => {
  afterEach(() => {
    vi.clearAllMocks()
    vi.useRealTimers()
  })

  it('submits the fixed PTH252 contract', async () => {
    api.submitPth252FactorJob.mockResolvedValue({ job: job('factor-1', 'queued') })
    api.getResearchFactorJob.mockResolvedValue({ job: job('factor-1', 'queued') })
    const wrapper = mountPanel()

    await wrapper.get('input').setValue('a-share-pit')
    await wrapper.get('button').trigger('click')
    await flushPromises()

    expect(api.submitPth252FactorJob).toHaveBeenCalledWith(expect.objectContaining({
      factor_id: 'pth252',
      top_quantile: 0.9,
      rebalance_every: 20,
      initial_capital: 200000,
      max_positions: 20,
      strict_pit: true,
      historical_universe_id: 'a-share-pit',
      backtest_config: expect.objectContaining({
        hold_days: 20,
        commission_bps: 3,
        stamp_duty_bps: 10,
        slippage_bps: 5,
        allow_limit_up_entry: false,
        benchmark: '000300',
      }),
    }))
    wrapper.unmount()
  })

  it('ignores an old polling response after a new submission', async () => {
    let resolveOld!: (value: { job: ResearchBacktestJob }) => void
    const oldPoll = new Promise<{ job: ResearchBacktestJob }>((resolve) => { resolveOld = resolve })
    api.submitPth252FactorJob
      .mockResolvedValueOnce({ job: job('old', 'queued') })
      .mockResolvedValueOnce({ job: job('new', 'queued') })
    api.getResearchFactorJob
      .mockReturnValueOnce(oldPoll)
      .mockResolvedValueOnce({ job: job('new', 'queued') })
    const wrapper = mountPanel()

    await wrapper.get('input').setValue('a-share-pit')
    await wrapper.get('button').trigger('click')
    await flushPromises()
    await wrapper.get('button').trigger('click')
    await flushPromises()
    resolveOld({ job: job('old', 'completed', 'run-old') })
    await flushPromises()

    expect(wrapper.text()).toContain('new')
    expect(wrapper.text()).not.toContain('run-old')
    expect(api.getResearchBacktestRun).not.toHaveBeenCalled()
    wrapper.unmount()
  })

  it('loads the rejected run when strict PIT returns a diagnostic run id', async () => {
    api.submitPth252FactorJob.mockResolvedValue({ job: job('pit', 'queued') })
    api.getResearchFactorJob.mockResolvedValue({
      job: { ...job('pit', 'failed', 'run-pit'), error: '历史股票池快照不完整' },
    })
    api.getResearchBacktestRun.mockResolvedValue({
      run_id: 'run-pit', status: 'rejected', metrics: {}, validation: {}, artifact_manifest: [],
    })
    const wrapper = mountPanel()

    await wrapper.get('input').setValue('a-share-pit')
    await wrapper.get('button').trigger('click')
    await flushPromises()

    expect(api.getResearchBacktestRun).toHaveBeenCalledWith('run-pit')
    expect(wrapper.text()).toContain('run-pit')
    wrapper.unmount()
  })
})
