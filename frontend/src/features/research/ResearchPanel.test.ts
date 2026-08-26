import { mount } from '@vue/test-utils'
import { defineComponent, ref } from 'vue'
import { describe, expect, it, vi } from 'vitest'

const useResearchProfileMock = vi.hoisted(() => vi.fn())

vi.mock('./composables/useResearchProfile', () => ({
  useResearchProfile: useResearchProfileMock,
}))

import ResearchPanel from './ResearchPanel.vue'

const BacktestStub = defineComponent({
  setup(_, { expose }) {
    expose({ load: vi.fn(), setHistoricalUniverse: vi.fn() })
  },
  template: '<div />',
})

const HypothesisStub = defineComponent({
  setup(_, { expose }) {
    expose({ load: vi.fn() })
  },
  template: '<div />',
})

function profileWithUnobservedTelemetry() {
  return {
    code: '600519',
    subject: { name: '测试标的' },
    budget: 'standard' as const,
    generated_at: '',
    market_snapshot: {
      source_evidence: {
        attempts_not_observed: true,
        attempts_not_observed_codes: ['600519'],
        unresolved_codes: ['600519'],
        receipts: [{ code: '600519', fallback_used: true }],
      },
    },
    dimensions: [],
    quality: {
      overall: 'partial' as const, blocked: false, completeness_ratio: 0,
      market_revision: '', generated_at: '', findings: [], market_health: {},
    },
    requested_as_of: '',
    source_attempts: [{
      source_id: 'market.db', state: 'selected' as const, checked_at: '', rtt_ms: null,
      row_sources: [], fields: [], error: '',
    }],
    artifact_id: '', artifact_status: 'transient' as const,
    contract: { quality_values: [], evidence_required: true, production_signal: false },
  }
}

describe('ResearchPanel source telemetry', () => {
  it('does not label legacy rows as selected when receipt attempts were not observed', () => {
    useResearchProfileMock.mockReturnValue({
      catalog: ref(null), profile: ref(profileWithUnobservedTelemetry()), loading: ref(false),
      archiveLoading: ref(false), runLoading: ref(false), catalogLoading: ref(false), error: ref(''),
      archivedRun: ref(null), activeRun: ref(null), runs: ref([]), dimensionsCount: ref(0),
      loadCatalog: vi.fn(), loadProfile: vi.fn(), archiveProfile: vi.fn(), loadRun: vi.fn(), resumeRun: vi.fn(),
    })
    const wrapper = mount(ResearchPanel, {
      global: {
        stubs: {
          PageBusy: true, EmptyState: true, ResearchDimensionDetail: true, ResearchDimensionRail: true,
          ResearchEvidencePanel: true, ResearchBacktestPanel: BacktestStub, ResearchFactorPanel: true,
          ResearchHypothesisPanel: HypothesisStub, ResearchRunPanel: true, ResearchTemporalDataPanel: true,
          'el-alert': { props: ['title', 'description'], template: '<div>{{ title }} {{ description }}</div>' },
          'el-tag': { template: '<span><slot /></span>' },
        },
      },
    })

    expect(wrapper.text()).toContain('market.db · 未观测回执')
    expect(wrapper.text()).toContain('行情来源 telemetry 不完整或已降级')
    expect(wrapper.text()).toContain('未解析代码：600519')
    expect(wrapper.text()).toContain('已发生来源回退：600519')
    wrapper.unmount()
  })
})
