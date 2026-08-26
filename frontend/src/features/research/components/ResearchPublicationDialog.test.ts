import { flushPromises, mount } from '@vue/test-utils'
import { defineComponent } from 'vue'
import { afterEach, describe, expect, it, vi } from 'vitest'

import type {
  ResearchBacktestPublicationResult,
  ResearchBacktestRun,
} from '@/shared/types/quant-research'

const api = vi.hoisted(() => ({ publishResearchBacktestRun: vi.fn() }))

vi.mock('@/shared/api/quant_research', () => api)

import ResearchPublicationDialog from './ResearchPublicationDialog.vue'

const manifestSha256 = 'a'.repeat(64)

const InputStub = defineComponent({
  props: { modelValue: { type: String, default: '' } },
  emits: ['update:modelValue'],
  template: '<input :value="modelValue" @input="$emit(\'update:modelValue\', $event.target.value)">',
})

const ButtonStub = defineComponent({
  props: { disabled: Boolean, loading: Boolean },
  emits: ['click'],
  template: '<button :disabled="disabled || loading" @click="$emit(\'click\')"><slot /></button>',
})

const DialogStub = defineComponent({
  props: { modelValue: Boolean },
  emits: ['update:modelValue', 'closed'],
  template: '<div v-if="modelValue"><slot /><slot name="footer" /></div>',
})

function waitingRun(): ResearchBacktestRun {
  return {
    contract_version: 'research-run-card-v1',
    run_id: 'run-1',
    strategy_slug: 'sanyuan-tail-v1',
    strategy_revision: 'r1',
    version: 'v1',
    hypothesis_id: null,
    hypothesis_revision: null,
    requested_as_of: '2025-12-31',
    actual_as_of: '2025-12-31',
    market_revision: 'market-r1',
    universe: {},
    universe_funnel: {},
    params: {},
    backtest_config: {},
    data_snapshot: {},
    source_evidence: [],
    metrics: {},
    validation: { status: 'passed' },
    risk_xray: {},
    conclusion: null,
    artifact_manifest: [],
    status: 'awaiting_human_review',
    created_at: '2026-08-04T00:00:00Z',
    updated_at: '2026-08-04T00:00:00Z',
    input_sha256: 'input',
    artifact_manifest_sha256: manifestSha256,
    manifest_sha256: manifestSha256,
    error: '',
  }
}

function publicationResult(): ResearchBacktestPublicationResult {
  return {
    run_card: { ...waitingRun(), status: 'completed' },
    workflow: {
      contract_version: 'research-workflow-v1',
      workflow_id: 'workflow-1',
      run_id: 'run-1',
      max_retries: 1,
      status: 'completed',
      stages: {},
      events: [],
    },
    reused: false,
  }
}

function mountDialog() {
  return mount(ResearchPublicationDialog, {
    props: { visible: true, run: waitingRun() },
    global: {
      stubs: {
        'el-dialog': DialogStub,
        'el-alert': { props: ['title'], template: '<div>{{ title }}<slot /></div>' },
        'el-descriptions': { template: '<div><slot /></div>' },
        'el-descriptions-item': { template: '<div><slot /></div>' },
        'el-form': { template: '<form><slot /></form>' },
        'el-form-item': { template: '<div><slot /></div>' },
        'el-input': InputStub,
        'el-button': ButtonStub,
      },
    },
  })
}

describe('ResearchPublicationDialog', () => {
  afterEach(() => vi.clearAllMocks())

  it('returns the manifest digest supplied by the run card without computing a browser hash', async () => {
    const result = publicationResult()
    api.publishResearchBacktestRun.mockResolvedValue(result)
    const wrapper = mountDialog()

    expect(wrapper.text()).toContain(manifestSha256)
    const inputs = wrapper.findAll('input')
    await inputs[0].setValue('reviewer-a')
    await inputs[1].setValue('验证通过且人工复核完毕')
    const publishButton = wrapper.findAll('button').find((button) => button.text().includes('人工签署发布'))
    await publishButton!.trigger('click')
    await flushPromises()

    expect(api.publishResearchBacktestRun).toHaveBeenCalledWith('run-1', {
      manifest_sha256: manifestSha256,
      reviewer: 'reviewer-a',
      reason: '验证通过且人工复核完毕',
    })
    expect(wrapper.emitted('published')?.[0]).toEqual([result])
    wrapper.unmount()
  })
})
