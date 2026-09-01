import { flushPromises, mount } from '@vue/test-utils'
import { defineComponent, nextTick } from 'vue'
import { afterEach, describe, expect, it, vi } from 'vitest'

import type { ResearchBacktestJob } from '@/shared/types/quant-research'

const api = vi.hoisted(() => ({
  getResearchBacktestRun: vi.fn(),
  getResearchBacktestJob: vi.fn(),
  getResearchWorkflow: vi.fn(),
  listResearchBacktestRuns: vi.fn(),
  publishResearchBacktestRun: vi.fn(),
  rejectResearchBacktestRun: vi.fn(),
  replayResearchBacktestRun: vi.fn(),
  researchArtifactUrl: vi.fn(),
  submitResearchBacktestJob: vi.fn(),
}))

vi.mock('@/shared/api/quant_research', () => api)

import ResearchBacktestPanel from './ResearchBacktestPanel.vue'

const InputStub = defineComponent({
  props: { modelValue: { type: String, default: '' } },
  emits: ['update:modelValue'],
  template: '<input :value="modelValue" @input="$emit(\'update:modelValue\', $event.target.value)">',
})

const DatePickerStub = defineComponent({
  props: { modelValue: { type: Array, default: () => [] } },
  emits: ['update:modelValue'],
  template: '<button class="date-picker" type="button"></button>',
})

const SwitchStub = defineComponent({
  props: { modelValue: Boolean },
  emits: ['update:modelValue'],
  template: '<input class="strict-switch" type="checkbox" :checked="modelValue" @change="$emit(\'update:modelValue\', $event.target.checked)">',
})

/** 战法字段已从 el-input 换成 el-select（选项文案中文、value 仍是 slug），stub 成同形输入 */
const SelectStub = defineComponent({
  props: { modelValue: { type: String, default: '' } },
  emits: ['update:modelValue'],
  template: '<input :value="modelValue" @input="$emit(\'update:modelValue\', $event.target.value)">',
})

const FormStub = defineComponent({
  template: '<form><slot /></form>',
})

function job(status: ResearchBacktestJob['status']): ResearchBacktestJob {
  return {
    id: 'job-1',
    status,
    request: {},
    run_id: '',
    error: '',
    created_at: '',
    updated_at: '',
  }
}

function mountPanel() {
  return mount(ResearchBacktestPanel, {
    global: {
      stubs: {
        ResearchPublicationDialog: true,
        ResearchRejectionDialog: true,
        'el-form': FormStub,
        'el-form-item': { template: '<div><slot /></div>' },
        'el-input': InputStub,
        'el-select': SelectStub,
        'el-option': true,
        'el-input-number': true,
        'el-date-picker': DatePickerStub,
        'el-switch': SwitchStub,
        'el-alert': { props: ['title'], template: '<div>{{ title }}<slot /></div>' },
        'el-button': { emits: ['click'], template: '<button type="button" @click="$emit(\'click\')"><slot /></button>' },
        'el-tag': { template: '<span><slot /></span>' },
        'el-table': { template: '<div><slot /></div>' },
        'el-table-column': true,
        'el-empty': true,
        'el-descriptions': { template: '<div><slot /></div>' },
        'el-descriptions-item': { template: '<div><slot /></div>' },
        'el-link': true,
      },
    },
  })
}

async function fillStrictPitInput(wrapper: ReturnType<typeof mountPanel>): Promise<void> {
  const inputs = wrapper.findAll('input').filter((input) => input.classes().indexOf('strict-switch') < 0)
  await inputs[0].setValue('sanyuan-tail-v1')
  await inputs[1].setValue('ashare-2024-2025')
  const pickers = wrapper.findAllComponents(DatePickerStub)
  pickers[0].vm.$emit('update:modelValue', ['2024-01-02', '2025-12-31'])
  pickers[1].vm.$emit('update:modelValue', ['2024-01-02', '2024-12-31'])
  pickers[2].vm.$emit('update:modelValue', ['2025-01-01', '2025-12-31'])
  await wrapper.get('.strict-switch').setValue(true)
  await nextTick()
}

async function submitBacktest(wrapper: ReturnType<typeof mountPanel>): Promise<void> {
  const submitButton = wrapper.findAll('button').find((button) => button.text().includes('提交回测'))
  if (!submitButton) throw new Error('未找到提交回测按钮')
  await submitButton.trigger('click')
}

describe('ResearchBacktestPanel', () => {
  afterEach(() => vi.clearAllMocks())

  it('blocks strict PIT before submitting when train/OOS and universe evidence are absent', async () => {
    const wrapper = mountPanel()
    const inputs = wrapper.findAll('input').filter((input) => input.classes().indexOf('strict-switch') < 0)
    await inputs[0].setValue('sanyuan-tail-v1')
    wrapper.findAllComponents(DatePickerStub)[0].vm.$emit('update:modelValue', ['2024-01-02', '2025-12-31'])
    await wrapper.get('.strict-switch').setValue(true)
    await submitBacktest(wrapper)

    expect(api.submitResearchBacktestJob).not.toHaveBeenCalled()
    expect(wrapper.text()).toContain('严格 PIT 模式要求')
    wrapper.unmount()
  })

  it('submits one complete strict PIT request and starts polling its persistent job', async () => {
    api.submitResearchBacktestJob.mockResolvedValue({ job: job('queued') })
    api.getResearchBacktestJob.mockResolvedValue({ job: job('queued') })
    const wrapper = mountPanel()
    await fillStrictPitInput(wrapper)
    await submitBacktest(wrapper)
    await flushPromises()

    expect(api.submitResearchBacktestJob).toHaveBeenCalledWith(expect.objectContaining({
      strategy: 'sanyuan-tail-v1',
      start: '2024-01-02',
      end: '2025-12-31',
      split: {
        train_start: '2024-01-02', train_end: '2024-12-31',
        oos_start: '2025-01-01', oos_end: '2025-12-31',
      },
      historical_universe_id: 'ashare-2024-2025',
      strict_pit: true,
    }))
    expect(api.getResearchBacktestJob).toHaveBeenCalledWith('job-1')
    expect(wrapper.text()).toContain('job-1')
    expect(wrapper.text()).toContain('排队中')
    wrapper.unmount()
  })

  it('lets the user reattach polling after a transient job-status read failure', async () => {
    api.submitResearchBacktestJob.mockResolvedValue({ job: job('queued') })
    api.getResearchBacktestJob
      .mockRejectedValueOnce(new Error('temporary network failure'))
      .mockResolvedValueOnce({ job: job('failed') })
    const wrapper = mountPanel()
    await fillStrictPitInput(wrapper)
    await submitBacktest(wrapper)
    await flushPromises()

    expect(wrapper.text()).toContain('temporary network failure')
    const retry = wrapper.findAll('button').find((button) => button.text().includes('重试读取任务状态'))
    await retry!.trigger('click')
    await flushPromises()

    expect(api.getResearchBacktestJob).toHaveBeenCalledTimes(2)
    expect(wrapper.text()).toContain('研究回测任务失败')
    wrapper.unmount()
  })
})
